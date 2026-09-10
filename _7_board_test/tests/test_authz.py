"""등급(0 일반 / 1 골드 / 2 관리자) 접근 제어 테스트.

과제 요구사항 1~6 이 실제로 동작하는지 확인한다.
"""
import pytest

from app import ROLE_ADMIN, ROLE_GOLD, ROLE_USER, User, db

PASSWORD = 'pw1234'


@pytest.fixture
def client(app):
  return app.test_client()


# ----------------- 도우미 -----------------
def register(client, username):
  response = client.post(
      '/api/auth/register', json={'username': username, 'password': PASSWORD}
  )
  assert response.status_code == 201, response.get_data(as_text=True)
  return response.get_json()


def set_role(username, role):
  user = User.query.filter_by(username=username).first()
  user.role = role
  db.session.commit()
  return user.id


def login(client, username):
  """로그인하면 클라이언트에 쿠키가 심기고 헤더용 토큰을 돌려준다."""
  response = client.post(
      '/api/auth/login', json={'username': username, 'password': PASSWORD}
  )
  assert response.status_code == 200, response.get_data(as_text=True)
  return response.get_json()['access_token']


def sign_in_as(client, username, role):
  """가입 → 등급 지정 → 로그인. (user_id, token) 반환."""
  register(client, username)
  user_id = set_role(username, role)
  return user_id, login(client, username)


def bearer(token):
  return {'Authorization': f'Bearer {token}'}


# ----------------- 3·4) 가입 등급과 권한 값 -----------------
def test_register_always_starts_as_normal_user(client):
  body = register(client, 'newbie')
  assert body['role'] == ROLE_USER
  assert body['role_name'] == '일반'


def test_register_ignores_role_sent_by_client(client):
  response = client.post(
      '/api/auth/register',
      json={'username': 'sneaky', 'password': PASSWORD, 'role': ROLE_ADMIN},
  )
  assert response.status_code == 201
  assert User.query.filter_by(username='sneaky').first().role == ROLE_USER


def test_me_reports_role(client):
  sign_in_as(client, 'gold01', ROLE_GOLD)
  body = client.get('/api/auth/me').get_json()
  assert body['authenticated'] is True
  assert body['user']['role'] == ROLE_GOLD
  assert body['user']['role_name'] == '골드'


def test_me_allows_anonymous(client):
  body = client.get('/api/auth/me').get_json()
  assert body['authenticated'] is False
  assert body['user'] is None


# ----------------- 6) 페이지 접근 제어와 예외 화면 -----------------
@pytest.mark.parametrize('path', ['/gold', '/admin'])
def test_anonymous_is_blocked_with_401_exception_page(client, path):
  response = client.get(path)
  assert response.status_code == 401
  assert '로그인이 필요합니다' in response.get_data(as_text=True)


@pytest.mark.parametrize('path', ['/gold', '/admin'])
def test_normal_user_is_blocked_with_403(client, path):
  sign_in_as(client, 'normal01', ROLE_USER)
  response = client.get(path)
  assert response.status_code == 403
  html = response.get_data(as_text=True)
  assert '접근 권한이 없습니다' in html
  assert '현재 등급은 일반입니다' in html


def test_gold_user_opens_gold_but_not_admin(client):
  sign_in_as(client, 'gold01', ROLE_GOLD)
  assert client.get('/gold').status_code == 200
  response = client.get('/admin')
  assert response.status_code == 403
  assert '관리자 등급 이상만' in response.get_data(as_text=True)


def test_admin_opens_every_role_page(client):
  sign_in_as(client, 'admin01', ROLE_ADMIN)
  assert client.get('/gold').status_code == 200
  assert client.get('/admin').status_code == 200


def test_public_pages_stay_open_to_everyone(client):
  assert client.get('/').status_code == 200


# ----------------- 1) 헤더 링크와 유저명·권한 표기 -----------------
def test_nav_shows_role_links_only_to_qualified_users(client, app):
  anonymous = client.get('/').get_data(as_text=True)
  assert 'href="/gold"' not in anonymous
  assert 'href="/admin"' not in anonymous

  sign_in_as(client, 'gold01', ROLE_GOLD)
  gold_html = client.get('/').get_data(as_text=True)
  assert 'href="/gold"' in gold_html
  assert 'href="/admin"' not in gold_html

  admin_client = app.test_client()
  register(admin_client, 'admin01')
  set_role('admin01', ROLE_ADMIN)
  login(admin_client, 'admin01')
  admin_html = admin_client.get('/').get_data(as_text=True)
  assert 'href="/gold"' in admin_html
  assert 'href="/admin"' in admin_html


def test_header_shows_username_and_role(client, app):
  """제출 항목 1: 헤더에 로그인 유저명과 권한이 함께 찍히는지."""
  cases = [
      ('normal01', ROLE_USER, '일반 (0)', ['/']),
      ('gold01', ROLE_GOLD, '골드 (1)', ['/', '/gold']),
      ('admin01', ROLE_ADMIN, '관리자 (2)', ['/', '/gold', '/admin']),
  ]
  for username, role, label, paths in cases:
    fresh = app.test_client()
    register(fresh, username)
    set_role(username, role)
    login(fresh, username)
    for path in paths:
      html = fresh.get(path).get_data(as_text=True)
      assert username in html, f'{username} @ {path}'
      assert label in html, f'{username} @ {path}'


def test_hidden_link_is_not_the_actual_guard(client):
  """링크가 안 보여도 URL 을 직접 치면 서버가 막는지 확인한다."""
  sign_in_as(client, 'normal01', ROLE_USER)
  assert client.get('/admin').status_code == 403


# ----------------- 5) 관리자 회원 관리 API -----------------
def test_admin_api_rejects_anonymous_and_non_admin(client, app):
  assert client.get('/api/admin/users').status_code == 401

  _, token = sign_in_as(client, 'normal01', ROLE_USER)
  response = client.get('/api/admin/users', headers=bearer(token))
  assert response.status_code == 403
  assert response.get_json()['reason'] == 'insufficient_role'

  gold_client = app.test_client()
  _, gold_token = sign_in_as(gold_client, 'gold01', ROLE_GOLD)
  assert gold_client.get(
      '/api/admin/users', headers=bearer(gold_token)
  ).status_code == 403


def test_admin_lists_users_with_roles(client):
  register(client, 'normal01')
  register(client, 'gold01')
  set_role('gold01', ROLE_GOLD)
  _, token = sign_in_as(client, 'admin01', ROLE_ADMIN)

  body = client.get('/api/admin/users', headers=bearer(token)).get_json()
  by_name = {u['username']: u for u in body['users']}
  assert by_name['normal01']['role'] == ROLE_USER
  assert by_name['gold01']['role_name'] == '골드'
  assert by_name['admin01']['is_me'] is True
  assert len(body['roles']) == 3


def test_admin_can_change_role(client):
  register(client, 'normal01')
  target_id = set_role('normal01', ROLE_USER)
  _, token = sign_in_as(client, 'admin01', ROLE_ADMIN)

  response = client.patch(
      f'/api/admin/users/{target_id}', headers=bearer(token), json={'role': ROLE_GOLD}
  )
  assert response.status_code == 200
  assert response.get_json()['user']['role'] == ROLE_GOLD
  assert db.session.get(User, target_id).role == ROLE_GOLD


def test_promoted_user_gains_page_access(client, app):
  """승급 전 403 → 승급 후 200 으로 바뀌는지 끝까지 확인한다."""
  member = app.test_client()
  register(member, 'member')
  login(member, 'member')
  assert member.get('/gold').status_code == 403

  _, token = sign_in_as(client, 'admin01', ROLE_ADMIN)
  member_id = User.query.filter_by(username='member').first().id
  client.patch(
      f'/api/admin/users/{member_id}', headers=bearer(token), json={'role': ROLE_GOLD}
  )
  assert member.get('/gold').status_code == 200


@pytest.mark.parametrize('payload', [{'role': 9}, {'role': 'gold'}, {}])
def test_admin_rejects_invalid_role_values(client, payload):
  register(client, 'normal01')
  target_id = set_role('normal01', ROLE_USER)
  _, token = sign_in_as(client, 'admin01', ROLE_ADMIN)

  response = client.patch(
      f'/api/admin/users/{target_id}', headers=bearer(token), json=payload
  )
  assert response.status_code == 400


def test_admin_cannot_demote_self(client):
  admin_id, token = sign_in_as(client, 'admin01', ROLE_ADMIN)
  response = client.patch(
      f'/api/admin/users/{admin_id}', headers=bearer(token), json={'role': ROLE_USER}
  )
  assert response.status_code == 400
  assert '자기 자신' in response.get_json()['msg']


def test_admin_cannot_delete_self(client):
  admin_id, token = sign_in_as(client, 'admin01', ROLE_ADMIN)
  response = client.delete(f'/api/admin/users/{admin_id}', headers=bearer(token))
  assert response.status_code == 400
  assert '자기 자신' in response.get_json()['msg']


def test_admin_can_delete_user_and_their_posts(client, app):
  victim = app.test_client()
  register(victim, 'victim')
  victim_token = login(victim, 'victim')
  victim.post(
      '/api/posts',
      headers=bearer(victim_token),
      json={'title': '합성 글', 'content': '합성 내용'},
  )
  victim_id = User.query.filter_by(username='victim').first().id

  _, token = sign_in_as(client, 'admin01', ROLE_ADMIN)
  response = client.delete(f'/api/admin/users/{victim_id}', headers=bearer(token))
  assert response.status_code == 200
  assert '게시글 1건' in response.get_json()['msg']
  assert db.session.get(User, victim_id) is None
  assert client.get('/api/posts').get_json()['posts'] == []


def test_admin_delete_missing_user_returns_404(client):
  _, token = sign_in_as(client, 'admin01', ROLE_ADMIN)
  assert client.delete(
      '/api/admin/users/9999', headers=bearer(token)
  ).status_code == 404


# ----------------- +a) 관리자의 게시글 삭제 -----------------
def write_post(app, username, title='합성 제목'):
  writer = app.test_client()
  token = login(writer, username)
  response = writer.post(
      '/api/posts', headers=bearer(token), json={'title': title, 'content': '합성 내용'}
  )
  assert response.status_code == 201
  from app import Post
  return Post.query.order_by(Post.id.desc()).first().id


def test_admin_can_delete_someone_elses_post(client, app):
  register(client, 'writer')
  post_id = write_post(app, 'writer')

  _, admin_token = sign_in_as(client, 'admin01', ROLE_ADMIN)
  response = client.delete(f'/api/posts/{post_id}', headers=bearer(admin_token))
  assert response.status_code == 200
  body = response.get_json()
  assert body['moderated'] is True
  assert 'writer' in body['msg']
  assert client.get('/api/posts').get_json()['posts'] == []


def test_owner_delete_is_not_marked_as_moderation(client, app):
  register(client, 'writer')
  post_id = write_post(app, 'writer')
  own_token = login(client, 'writer')

  body = client.delete(
      f'/api/posts/{post_id}', headers=bearer(own_token)
  ).get_json()
  assert body['moderated'] is False


@pytest.mark.parametrize('role', [ROLE_USER, ROLE_GOLD])
def test_gold_and_normal_cannot_delete_others_post(client, app, role):
  register(client, 'writer')
  post_id = write_post(app, 'writer')

  _, token = sign_in_as(client, 'someone', role)
  response = client.delete(f'/api/posts/{post_id}', headers=bearer(token))
  assert response.status_code == 403
  assert len(client.get('/api/posts').get_json()['posts']) == 1


def test_admin_still_cannot_edit_someone_elses_post(client, app):
  """삭제만 열어 준다. 남의 글 내용을 고치는 건 여전히 막는다."""
  register(client, 'writer')
  post_id = write_post(app, 'writer')

  _, admin_token = sign_in_as(client, 'admin01', ROLE_ADMIN)
  response = client.put(
      f'/api/posts/{post_id}',
      headers=bearer(admin_token),
      json={'title': '관리자가 고친 제목'},
  )
  assert response.status_code == 403


# ----------------- 로그아웃 -----------------
def test_logout_closes_page_access(client):
  sign_in_as(client, 'admin01', ROLE_ADMIN)
  assert client.get('/admin').status_code == 200
  assert client.post('/api/auth/logout').status_code == 200
  assert client.get('/admin').status_code == 401
