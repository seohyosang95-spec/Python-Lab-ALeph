import os
from datetime import timedelta
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, g, jsonify, render_template, request
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    get_jwt_identity,
    jwt_required,
    set_access_cookies,
    unset_jwt_cookies,
    verify_jwt_in_request,
)
from flask_jwt_extended.exceptions import JWTExtendedException
from flask_sqlalchemy import SQLAlchemy
from jwt import PyJWTError
import requests
from werkzeug.security import check_password_hash, generate_password_hash

# .env 를 먼저 읽어야 아래 config 에서 환경변수를 쓸 수 있다.
load_dotenv()

app = Flask(__name__)

# 접속 정보는 .env 로 뺀다. .env 가 없으면 기존 값 그대로 동작한다.
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL', 'mysql+pymysql://root:123456@localhost:3306/my_new_board_db'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = os.environ.get(
    'JWT_SECRET_KEY', 'super-secret-key-change-this'
)
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=2)

# 페이지 접근 제어를 서버에서 하려면 주소창 이동(GET)에도 토큰이 실려야 한다.
# 그래서 헤더와 쿠키를 모두 인정한다.
#   - 기존 fetch 호출: Authorization 헤더 그대로
#   - /gold, /admin 이동: 쿠키를 보고 서버가 등급을 판정
app.config['JWT_TOKEN_LOCATION'] = ['headers', 'cookies']
app.config['JWT_ACCESS_COOKIE_PATH'] = '/'
# CSRF 보호는 켜 둔다. 쿠키로 온 토큰의 POST/PUT/PATCH/DELETE 만 CSRF 토큰을
# 요구하므로 GET 페이지와 헤더 토큰을 쓰는 기존 API 에는 영향이 없다.
app.config['JWT_COOKIE_CSRF_PROTECT'] = True
app.config['JWT_COOKIE_SECURE'] = os.environ.get('JWT_COOKIE_SECURE', '0') == '1'
app.config['JWT_COOKIE_SAMESITE'] = 'Lax'

db = SQLAlchemy(app)
jwt = JWTManager(app)


# ----------------- 등급(권한) 정의 -----------------
# 숫자가 클수록 권한이 넓다. 그래서 검사는 user.role >= 요구등급 한 줄이면 되고,
# 관리자는 골드 페이지도 자동으로 볼 수 있다.
ROLE_USER = 0    # 일반 · 최초 가입
ROLE_GOLD = 1    # 골드 · 중간 관리자
ROLE_ADMIN = 2   # 관리자

ROLE_NAMES = {
    ROLE_USER: '일반',
    ROLE_GOLD: '골드',
    ROLE_ADMIN: '관리자',
}
VALID_ROLES = tuple(ROLE_NAMES)


def role_name(role):
  """등급 숫자를 사람이 읽는 이름으로 바꾼다."""
  return ROLE_NAMES.get(role, '알 수 없음')


# ----------------- Database Models -----------------
class User(db.Model):
  __tablename__ = 'users'
  id = db.Column(db.Integer, primary_key=True)
  username = db.Column(db.String(80), unique=True, nullable=False)
  password = db.Column(db.String(255), nullable=False)
  # 회원가입은 항상 일반(0)으로 시작하고, 승급은 관리자만 할 수 있다.
  role = db.Column(
      db.Integer, nullable=False, default=ROLE_USER, server_default='0'
  )

  @property
  def role_name(self):
    return role_name(self.role)

  def has_role(self, minimum_role):
    return self.role >= minimum_role

  def to_dict(self):
    return {
        'id': self.id,
        'username': self.username,
        'role': self.role,
        'role_name': self.role_name,
    }


class Post(db.Model):
  __tablename__ = 'posts'
  id = db.Column(db.Integer, primary_key=True)
  title = db.Column(db.String(200), nullable=False)
  content = db.Column(db.Text, nullable=False)
  category = db.Column(db.String(50), nullable=False, default='일반')
  author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
  author = db.relationship('User', backref=db.backref('posts', lazy=True))


with app.app_context():
  db.create_all()


# ----------------- 인가(권한 검사) -----------------
# 인증(로그인 여부)과 인가(등급 충족 여부)를 나눠서 다룬다.
#   인증 실패              -> 401
#   인증은 됐는데 등급 부족 -> 403
def load_current_user():
  """헤더 또는 쿠키의 토큰으로 현재 사용자를 찾는다. 없으면 None."""
  try:
    verify_jwt_in_request(optional=True)
  except (JWTExtendedException, PyJWTError):
    # 만료·위조 토큰은 비로그인과 똑같이 취급한다.
    return None
  identity = get_jwt_identity()
  if not identity:
    return None
  try:
    user_id = int(identity)
  except (TypeError, ValueError):
    return None
  return db.session.get(User, user_id)


@app.before_request
def reset_current_user_cache():
  """요청이 시작될 때마다 캐시를 비운다.

  g 는 요청이 아니라 '앱 컨텍스트'에 붙는다. 테스트처럼 앱 컨텍스트를 하나
  열어 두고 여러 요청을 보내면 캐시가 그대로 남아, 로그아웃한 뒤에도 이전
  사용자로 인가가 통과해 버린다. 그래서 요청마다 명시적으로 지운다.
  """
  g.pop('current_user', None)


def current_user():
  """요청 한 번 안에서는 조회 결과를 재사용한다."""
  if 'current_user' not in g:
    g.current_user = load_current_user()
  return g.current_user


def denial_reason(user, required_role):
  """거절 사유를 한 곳에서 만든다. (상태코드, 사유, 안내문)"""
  if user is None:
    return 401, 'unauthenticated', '로그인이 필요한 페이지입니다.'
  return (
      403,
      'insufficient_role',
      f'{role_name(required_role)} 등급 이상만 접근할 수 있습니다. '
      f'현재 등급은 {user.role_name}입니다.',
  )


def api_role_required(required_role):
  """JSON API 용 등급 검사. 거절하면 사유를 JSON 으로 돌려준다."""
  def decorator(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
      user = current_user()
      if user is None or not user.has_role(required_role):
        status, reason, message = denial_reason(user, required_role)
        return jsonify({
            'msg': message,
            'reason': reason,
            'required_role': required_role,
            'required_role_name': role_name(required_role),
            'current_role': user.role if user else None,
        }), status
      return view(*args, **kwargs)
    return wrapper
  return decorator


def page_role_required(required_role):
  """페이지 용 등급 검사. 거절하면 예외 화면을 그대로 그린다."""
  def decorator(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
      user = current_user()
      if user is None or not user.has_role(required_role):
        status, reason, message = denial_reason(user, required_role)
        return render_template(
            '403.html',
            status=status,
            reason=reason,
            message=message,
            required_role=required_role,
            required_role_name=role_name(required_role),
            user=user,
        ), status
      return view(*args, **kwargs)
    return wrapper
  return decorator


@app.context_processor
def inject_current_user():
  """모든 템플릿에서 로그인 사용자와 등급 상수를 쓸 수 있게 한다."""
  return {
      'current_user': current_user(),
      'ROLE_GOLD': ROLE_GOLD,
      'ROLE_ADMIN': ROLE_ADMIN,
  }


# ----------------- Auth Endpoints -----------------
@app.route('/api/auth/register', methods=['POST'])
def register():
  data = request.get_json()
  if User.query.filter_by(username=data['username']).first():
    return jsonify({'msg': '이미 존재하는 사용자입니다.'}), 400

  hashed_password = generate_password_hash(data['password'])
  # 가입은 언제나 일반(0) 등급이다. 요청 본문에 role 이 와도 무시한다.
  new_user = User(
      username=data['username'], password=hashed_password, role=ROLE_USER
  )
  db.session.add(new_user)
  db.session.commit()
  return jsonify({
      'msg': '회원가입 성공',
      'role': new_user.role,
      'role_name': new_user.role_name,
  }), 201


@app.route('/api/auth/login', methods=['POST'])
def login():
  data = request.get_json()
  user = User.query.filter_by(username=data['username']).first()
  if not user or not check_password_hash(user.password, data['password']):
    return jsonify({'msg': '아이디 또는 비밀번호가 잘못되었습니다.'}), 401

  access_token = create_access_token(identity=str(user.id))
  response = jsonify(
      access_token=access_token,
      username=user.username,
      role=user.role,
      role_name=user.role_name,
  )
  # 페이지 이동(GET)에서도 서버가 등급을 확인할 수 있도록 쿠키에도 실어 보낸다.
  set_access_cookies(response, access_token)
  return response


@app.route('/api/auth/logout', methods=['POST'])
def logout():
  response = jsonify({'msg': '로그아웃되었습니다.'})
  unset_jwt_cookies(response)
  return response


@app.route('/api/auth/me', methods=['GET'])
def me():
  """현재 로그인 상태와 등급을 알려준다. 비로그인도 200 으로 답한다."""
  user = current_user()
  if user is None:
    return jsonify({'authenticated': False, 'user': None})
  return jsonify({'authenticated': True, 'user': user.to_dict()})


# ----------------- Post Endpoints (RESTful) -----------------
@app.route('/')
def index():
  return render_template('index.html')


# ----------------- 등급별 페이지 -----------------
@app.route('/gold')
@page_role_required(ROLE_GOLD)
def gold_lounge():
  """골드(1) 이상만 볼 수 있는 라운지."""
  return render_template('gold.html')


@app.route('/admin')
@page_role_required(ROLE_ADMIN)
def admin_console():
  """관리자(2)만 볼 수 있는 회원 관리 화면."""
  return render_template('admin.html')


# ----------------- 관리자 전용 회원 관리 API -----------------
def count_admins(exclude_user_id=None):
  query = User.query.filter(User.role >= ROLE_ADMIN)
  if exclude_user_id is not None:
    query = query.filter(User.id != exclude_user_id)
  return query.count()


@app.route('/api/admin/users', methods=['GET'])
@api_role_required(ROLE_ADMIN)
def list_users():
  """회원 목록을 등급 높은 순으로 불러온다."""
  users = User.query.order_by(User.role.desc(), User.id.asc()).all()
  post_counts = dict(
      db.session.query(Post.author_id, db.func.count(Post.id))
      .group_by(Post.author_id)
      .all()
  )
  me_user = current_user()
  return jsonify({
      'users': [
          dict(
              u.to_dict(),
              post_count=post_counts.get(u.id, 0),
              is_me=(u.id == me_user.id),
          )
          for u in users
      ],
      'roles': [{'value': v, 'name': role_name(v)} for v in VALID_ROLES],
      'me': me_user.to_dict(),
  })


@app.route('/api/admin/users/<int:user_id>', methods=['PATCH'])
@api_role_required(ROLE_ADMIN)
def update_user_role(user_id):
  """회원 등급을 수정한다."""
  me_user = current_user()
  target = db.session.get(User, user_id)
  if target is None:
    return jsonify({'msg': '존재하지 않는 회원입니다.'}), 404

  data = request.get_json(silent=True) or {}
  if 'role' not in data:
    return jsonify({'msg': 'role 값이 필요합니다.'}), 400
  try:
    new_role = int(data['role'])
  except (TypeError, ValueError):
    return jsonify({'msg': 'role 은 숫자여야 합니다.'}), 400
  if new_role not in VALID_ROLES:
    return jsonify({'msg': f'role 은 {list(VALID_ROLES)} 중 하나여야 합니다.'}), 400

  # 스스로 강등해 관리자 화면에서 잠기는 사고를 막는다.
  if target.id == me_user.id and new_role < ROLE_ADMIN:
    return jsonify({'msg': '자기 자신의 등급은 내릴 수 없습니다.'}), 400
  # 마지막 관리자가 사라지면 아무도 회원 관리를 할 수 없게 된다.
  if (target.role >= ROLE_ADMIN and new_role < ROLE_ADMIN
      and count_admins(target.id) == 0):
    return jsonify({'msg': '마지막 관리자는 강등할 수 없습니다.'}), 400

  previous = target.role_name
  target.role = new_role
  db.session.commit()
  return jsonify({
      'msg': f'{target.username}님의 등급을 {previous} → {target.role_name}(으)로 변경했습니다.',
      'user': target.to_dict(),
  })


@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@api_role_required(ROLE_ADMIN)
def delete_user(user_id):
  """회원을 삭제한다. 남은 게시글도 함께 정리한다."""
  me_user = current_user()
  target = db.session.get(User, user_id)
  if target is None:
    return jsonify({'msg': '존재하지 않는 회원입니다.'}), 404
  if target.id == me_user.id:
    return jsonify({'msg': '자기 자신은 삭제할 수 없습니다.'}), 400
  if target.role >= ROLE_ADMIN and count_admins(target.id) == 0:
    return jsonify({'msg': '마지막 관리자는 삭제할 수 없습니다.'}), 400

  # 게시글은 author_id 외래키로 묶여 있어 먼저 지워야 한다.
  removed_posts = Post.query.filter_by(author_id=target.id).delete()
  username = target.username
  db.session.delete(target)
  db.session.commit()
  return jsonify({
      'msg': f'{username}님을 삭제했습니다. (게시글 {removed_posts}건 함께 삭제)'
  })


@app.route('/api/posts', methods=['GET'])
def get_posts():
  cursor = request.args.get('cursor', type=int)
  limit = request.args.get('limit', default=5, type=int)
  search = request.args.get('search', default='', type=str)
  category = request.args.get('category', default='', type=str)

  query = Post.query
  if category and category != '전체':
    query = query.filter(Post.category == category)
  if search:
    query = query.filter(
        (Post.title.like(f'%{search}%')) | (Post.content.like(f'%{search}%'))
    )
  if cursor:
    query = query.filter(Post.id < cursor)

  posts = query.order_by(Post.id.desc()).limit(limit + 1).all()
  has_more = len(posts) > limit
  if has_more:
    posts = posts[:limit]
    next_cursor = posts[-1].id
  else:
    next_cursor = None

  results = []
  for p in posts:
    results.append({
        'id': p.id,
        'title': p.title,
        'content': p.content,
        'category': p.category,
        'author': p.author.username,
        'author_id': p.author_id,
    })

  return jsonify({
      'posts': results,
      'next_cursor': next_cursor,
      'has_more': has_more,
  })


@app.route('/api/posts', methods=['POST'])
@jwt_required()
def create_post():
  current_user_id = int(get_jwt_identity())
  data = request.get_json()
  new_post = Post(
      title=data['title'],
      content=data['content'],
      category=data.get('category', '일반'),
      author_id=current_user_id,
  )
  db.session.add(new_post)
  db.session.commit()
  return jsonify({'msg': '게시글이 등록되었습니다.'}), 201


@app.route('/api/posts/<int:id>', methods=['PUT'])
@jwt_required()
def update_post(id):
  current_user_id = int(get_jwt_identity())
  post = Post.query.get_or_404(id)
  if post.author_id != current_user_id:
    return jsonify({'msg': '권한이 없습니다.'}), 403

  data = request.get_json()
  post.title = data.get('title', post.title)
  post.content = data.get('content', post.content)
  post.category = data.get('category', post.category)
  db.session.commit()
  return jsonify({'msg': '수정되었습니다.'})


@app.route('/api/posts/<int:id>', methods=['DELETE'])
@jwt_required()
def delete_post(id):
  """작성자 본인, 그리고 관리자(2)가 삭제할 수 있다.

  수정은 여전히 본인만 가능하다. 관리자에게 준 것은 부적절한 글을 내리는
  삭제 권한이지, 남의 글 내용을 바꾸는 권한이 아니다.
  """
  user = current_user()
  if user is None:
    # 토큰은 살아 있는데 계정이 삭제된 경우
    return jsonify({'msg': '로그인이 필요합니다.'}), 401

  post = Post.query.get_or_404(id)
  is_owner = post.author_id == user.id
  is_moderator = user.role >= ROLE_ADMIN
  if not (is_owner or is_moderator):
    return jsonify({'msg': '권한이 없습니다.'}), 403

  author = post.author.username
  db.session.delete(post)
  db.session.commit()
  if is_owner:
    return jsonify({'msg': '삭제되었습니다.', 'moderated': False})
  return jsonify({
      'msg': f'관리자 권한으로 {author}님의 글을 삭제했습니다.',
      'moderated': True,
  })


# ----------------- 부산 테마여행 공공 데이터 연동 엔드포인트 -----------------
import requests  # 상단에 이미 없다면 추가

# ----------------- 공공 데이터 연동 설정 (부산테마여행) -----------------
import os
from dotenv import load_dotenv

# 같은 폴더의 .env 를 읽어 환경변수로 올려 준다 (이 한 줄이 핵심)
load_dotenv()

# .env 파일에 정의한 변수 이름으로 키를 가져온다
PUBLIC_API_KEY = os.environ.get("PUBLIC_API_KEY")

# 키 값 자체는 절대 출력하지 않고 안전하게 확인
if PUBLIC_API_KEY:
    print("키 로드됨 - 앞 4자리:", PUBLIC_API_KEY[:4] + "****")
    # 이후 불러온 key를 활용해 공공데이터 API 요청 로직 작성
else:
    print("키 없음 - 더미 실습 진행 또는 설정을 확인하세요.")

PUBLIC_API_URL = "http://apis.data.go.kr/6260000/RecommendedService/getRecommendedKr"

# 1) 외부 공공 API 목록 데이터를 클라이언트에 전달하는 API 라우트 (100건)
@app.route('/api/public/posts', methods=['GET'])
def get_public_posts():
    params = {
        'serviceKey': PUBLIC_API_KEY,
        'numOfRows': '100',
        'pageNo': '1',
        'resultType': 'json'
    }
    try:
        response = requests.get(PUBLIC_API_URL, params=params)
        if response.status_code == 200:
            return response.json()
        else:
            return jsonify({"msg": "공공 API 호출 실패", "status": response.status_code}), 500
    except Exception as e:
        return jsonify({"msg": "서버 통신 에러 발생", "error": str(e)}), 500

# 2) 공공데이터 목록 화면 페이지 라우트
@app.route('/public-posts')
def public_posts_page():
    return render_template('public_posts.html')

# 3) 공공데이터 상세 보기 화면 페이지 라우트 (UC_SEQ 식별자 이용)
@app.route('/public-posts/<int:uc_seq>')
def public_post_detail_page(uc_seq):
    return render_template('public_detail.html', uc_seq=uc_seq)

if __name__ == '__main__':
  # 다른 실습 서버와 포트가 겹칠 때만 .env 에 PORT 를 지정하면 된다.
  app.run(debug=True, port=int(os.environ.get('PORT', 5000)))