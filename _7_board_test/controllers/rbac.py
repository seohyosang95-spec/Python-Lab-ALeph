"""등급별 접근제어(RBAC) 공용 규칙 — 한 곳에서만 판정한다.

등급은 계단식이다.  user(1) < gold(2) < admin(3)
  · 필요 등급보다 내 등급이 같거나 높으면 통과
  · 그래서 admin 은 골드 화면도 볼 수 있다(등급마다 계정을 새로 만들 필요가 없다)

인증(authentication) 과 인가(authorization) 는 다른 문제라 응답 코드도 다르다.
  401 = 네가 누구인지 모른다(로그인 안 함)
  403 = 누구인지는 알지만 등급이 모자라다
"""
from functools import wraps

from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from extensions import db
from models import User
# 등급 정의는 모델(models/user.py)이 갖는다 — 새 등급은 거기 한 곳에만 추가한다.
from models.user import ROLE_LABEL, ROLE_LEVEL, VALID_ROLES, role_level  # noqa: F401


def current_user():
  """JWT 가 유효하면 그 User, 아니면 None. 토큰이 없거나 깨져도 예외를 내지 않는다."""
  try:
    verify_jwt_in_request(optional=True)
  except Exception:
    return None
  uid = get_jwt_identity()
  if not uid:
    return None
  try:
    return db.session.get(User, int(uid))
  except (TypeError, ValueError):
    return None


def role_required(required):
  """required 등급 이상만 통과. 미로그인 401, 등급 부족 403.

  403 응답에 required_role·current_role 을 함께 넘긴다 —
  화면이 "골드 등급이 필요합니다(현재: 일반)" 예외 화면을 그릴 때 쓴다.
  """
  def decorator(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
      user = current_user()
      if user is None:
        return jsonify({
            'msg': '로그인이 필요합니다.',
            'required_role': required,
            'current_role': None,
        }), 401
      if role_level(user.role) < role_level(required):
        return jsonify({
            'msg': f'{ROLE_LABEL.get(required, required)} 등급 이상만 이용할 수 있습니다.',
            'required_role': required,
            'current_role': user.role,
        }), 403
      request.current_user = user
      return fn(*args, **kwargs)
    return wrapper
  return decorator