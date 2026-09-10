"""테스트 공통 준비.

app.py 는 import 되는 순간 config 를 읽고 db.create_all() 까지 수행한다.
그래서 app 을 import 하기 전에 여기서 접속 정보를 메모리 sqlite 로 바꿔 둔다.
conftest.py 는 테스트 모듈보다 먼저 로드되므로 이 자리가 맞다.

setdefault 가 아니라 대입인 이유: 개발자 PC에 DATABASE_URL 이 이미 걸려 있으면
테스트가 실제 MySQL 데이터를 지워 버릴 수 있다. 테스트는 언제나 메모리 DB 를 쓴다.
"""
import os

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['JWT_SECRET_KEY'] = 'test-only-jwt-secret-at-least-32-bytes'
os.environ['PUBLIC_API_KEY'] = ''

import pytest  # noqa: E402

from app import Post, User, app as flask_app, db  # noqa: E402


@pytest.fixture
def app():
  flask_app.config['TESTING'] = True
  with flask_app.app_context():
    db.create_all()
    yield flask_app
    # 테스트끼리 데이터가 새지 않도록 매번 비운다.
    Post.query.delete()
    User.query.delete()
    db.session.commit()
