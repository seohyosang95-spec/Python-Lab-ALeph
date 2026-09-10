"""회원 등급 컬럼 추가와 최초 관리자 지정을 위한 도구.

db.create_all() 은 이미 존재하는 테이블에 컬럼을 추가하지 못한다.
그래서 기존 users 테이블에 role 컬럼을 직접 붙여 주는 단계가 필요하다.

사용 예)
    python manage_roles.py --ensure-column
    python manage_roles.py --list
    python manage_roles.py --promote admin01 --role 2
"""
import argparse
from unicodedata import east_asian_width

from sqlalchemy import inspect, text

from app import ROLE_NAMES, VALID_ROLES, User, app, db, role_name


def ensure_column():
  """users.role 컬럼이 없으면 추가한다. 이미 있으면 아무것도 하지 않는다."""
  columns = {c['name'] for c in inspect(db.engine).get_columns('users')}
  if 'role' in columns:
    print('users.role 컬럼이 이미 있습니다.')
    return False
  db.session.execute(
      text('ALTER TABLE users ADD COLUMN role INTEGER NOT NULL DEFAULT 0')
  )
  db.session.commit()
  print('users.role 컬럼을 추가했습니다. 기존 회원은 모두 일반(0) 등급입니다.')
  return True


def pad(text_value, width):
  """한글은 콘솔에서 두 칸을 차지하므로 표시 폭으로 맞춘다."""
  display = sum(2 if east_asian_width(ch) in 'WF' else 1 for ch in text_value)
  return text_value + ' ' * max(width - display, 0)


def list_users():
  users = User.query.order_by(User.role.desc(), User.id.asc()).all()
  if not users:
    print('등록된 회원이 없습니다.')
    return
  print(f"{'ID':>4}  {pad('등급', 14)}{'아이디'}")
  print('-' * 40)
  for user in users:
    print(f'{user.id:>4}  {pad(f"{user.role_name}({user.role})", 14)}{user.username}')
  print('-' * 40)
  print(f'총 {len(users)}명  ·  users 테이블의 role 컬럼 값')


def promote(username, role):
  user = User.query.filter_by(username=username).first()
  if user is None:
    print(f"'{username}' 회원을 찾을 수 없습니다.")
    return False
  previous = user.role_name
  user.role = role
  db.session.commit()
  print(f'{username}: {previous} → {user.role_name}({role})')
  return True


def main():
  parser = argparse.ArgumentParser(description='회원 등급 관리 도구')
  parser.add_argument(
      '--ensure-column', action='store_true', help='users.role 컬럼을 추가한다.'
  )
  parser.add_argument('--list', action='store_true', help='회원과 등급을 출력한다.')
  parser.add_argument('--promote', metavar='USERNAME', help='등급을 바꿀 아이디')
  parser.add_argument(
      '--role', type=int, choices=VALID_ROLES, help=f'등급 값 {dict(ROLE_NAMES)}'
  )
  args = parser.parse_args()

  if not (args.ensure_column or args.list or args.promote):
    parser.print_help()
    return

  with app.app_context():
    if args.ensure_column:
      ensure_column()
    if args.promote:
      if args.role is None:
        print('--promote 를 쓸 때는 --role 도 함께 지정하세요.')
        return
      print(f'대상 등급: {role_name(args.role)}({args.role})')
      promote(args.promote, args.role)
    if args.list:
      list_users()


if __name__ == '__main__':
  main()
