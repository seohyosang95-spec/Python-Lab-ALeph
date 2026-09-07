from datetime import timedelta
from flask import Flask, jsonify, render_template, request
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    get_jwt_identity,
    jwt_required,
)
from flask_sqlalchemy import SQLAlchemy
import requests
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = (
    'mysql+pymysql://root:123456@localhost:3306/my_new_board_db'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = 'super-secret-key-change-this'
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=2)

db = SQLAlchemy(app)
jwt = JWTManager(app)


# ----------------- Database Models -----------------
class User(db.Model):
  __tablename__ = 'users'
  id = db.Column(db.Integer, primary_key=True)
  username = db.Column(db.String(80), unique=True, nullable=False)
  password = db.Column(db.String(255), nullable=False)


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


# ----------------- Auth Endpoints -----------------
@app.route('/api/auth/register', methods=['POST'])
def register():
  data = request.get_json()
  if User.query.filter_by(username=data['username']).first():
    return jsonify({'msg': '이미 존재하는 사용자입니다.'}), 400

  hashed_password = generate_password_hash(data['password'])
  new_user = User(username=data['username'], password=hashed_password)
  db.session.add(new_user)
  db.session.commit()
  return jsonify({'msg': '회원가입 성공'}), 201


@app.route('/api/auth/login', methods=['POST'])
def login():
  data = request.get_json()
  user = User.query.filter_by(username=data['username']).first()
  if not user or not check_password_hash(user.password, data['password']):
    return jsonify({'msg': '아이디 또는 비밀번호가 잘못되었습니다.'}), 401

  access_token = create_access_token(identity=str(user.id))
  return jsonify(access_token=access_token, username=user.username)


# ----------------- Post Endpoints (RESTful) -----------------
@app.route('/')
def index():
  return render_template('index.html')


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
  current_user_id = int(get_jwt_identity())
  post = Post.query.get_or_404(id)
  if post.author_id != current_user_id:
    return jsonify({'msg': '권한이 없습니다.'}), 403

  db.session.delete(post)
  db.session.commit()
  return jsonify({'msg': '삭제되었습니다.'})


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
    print("키 로드됨 — 앞 4자리:", PUBLIC_API_KEY[:4] + "****")
    # 이후 불러온 key를 활용해 공공데이터 API 요청 로직 작성
else:
    print("키 없음 — 더미 실습 진행 또는 설정을 확인하세요.")

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
  app.run(debug=True, port=5000)