"""등급 접근 제어 제출 증거 화면을 PC 해상도로 자동 캡처한다.

    python app.py                          # 다른 터미널에서 먼저 실행
    python capture_role_evidence.py

images/role-access/ 아래에 01~15번 PNG 를 만든다. 1440x900 뷰포트에 2배
스케일이라 글자가 또렷하다.

캡처 전에 데모 계정과 게시글을 심고, 끝나면 처음 상태로 되돌린다.
그래서 몇 번을 돌려도 같은 결과가 나온다.

준비물)
    pip install playwright
    python -m playwright install chromium
"""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright
from werkzeug.security import generate_password_hash

from app import ROLE_ADMIN, ROLE_GOLD, ROLE_USER, Post, User, app, db

BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / 'images' / 'role-access'
PORT = os.environ.get('PORT', '5000')
BASE_URL = f'http://127.0.0.1:{PORT}'
PASSWORD = 'pw1234'
VIEWPORT = {'width': 1440, 'height': 900}

ACCOUNTS = [('normal01', ROLE_USER), ('gold01', ROLE_GOLD), ('admin01', ROLE_ADMIN)]


def seed():
  """캡처가 항상 같은 화면을 찍도록 데모 데이터를 다시 심는다."""
  with app.app_context():
    Post.query.delete()
    User.query.delete()
    db.session.commit()
    for username, role in ACCOUNTS:
      db.session.add(User(
          username=username,
          password=generate_password_hash(PASSWORD),
          role=role,
      ))
    db.session.commit()
    normal = User.query.filter_by(username='normal01').first()
    gold = User.query.filter_by(username='gold01').first()
    db.session.add(Post(
        title='일반 유저가 쓴 합성 글',
        content='관리자 삭제 대상이 되는 합성 내용입니다.',
        category='일반',
        author_id=normal.id,
    ))
    db.session.add(Post(
        title='골드 유저가 쓴 합성 글',
        content='등급별 노출 확인용 합성 내용입니다.',
        category='질문',
        author_id=gold.id,
    ))
    db.session.commit()
  print('데모 계정 3개와 게시글 2건을 심었습니다.')


class Shooter:
  def __init__(self, browser):
    self.browser = browser
    self.index = 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)

  def context(self, username=None):
    """계정마다 새 컨텍스트를 써서 쿠키가 섞이지 않게 한다."""
    context = self.browser.new_context(
        viewport=VIEWPORT, device_scale_factor=2, locale='ko-KR'
    )
    if username:
      response = context.request.post(
          f'{BASE_URL}/api/auth/login',
          data={'username': username, 'password': PASSWORD},
      )
      assert response.ok, f'{username} 로그인 실패: {response.status}'
    return context

  def shot(self, page, name, full_page=False):
    self.index += 1
    path = OUT_DIR / f'{self.index:02d}-{name}.png'
    page.screenshot(path=str(path), full_page=full_page)
    print(f'  {path.name}')

  def visit(self, page, path):
    response = page.goto(f'{BASE_URL}{path}', wait_until='networkidle')
    return response.status if response else None


def capture():
  with sync_playwright() as pw:
    browser = pw.chromium.launch()
    shooter = Shooter(browser)

    # ── 비로그인 ──────────────────────────────────────────
    print('비로그인')
    context = shooter.context()
    page = context.new_page()
    shooter.visit(page, '/')
    shooter.shot(page, 'anonymous-board')
    status = shooter.visit(page, '/admin')
    assert status == 401, f'기대 401, 실제 {status}'
    shooter.shot(page, 'anonymous-admin-401')
    context.close()

    # ── 일반(0) ──────────────────────────────────────────
    print('normal01 · 일반(0)')
    context = shooter.context('normal01')
    page = context.new_page()
    shooter.visit(page, '/')
    shooter.shot(page, 'normal-board-header')
    status = shooter.visit(page, '/gold')
    assert status == 403, f'기대 403, 실제 {status}'
    shooter.shot(page, 'normal-gold-403')
    status = shooter.visit(page, '/admin')
    assert status == 403, f'기대 403, 실제 {status}'
    shooter.shot(page, 'normal-admin-403')
    context.close()

    # ── 골드(1) ──────────────────────────────────────────
    print('gold01 · 골드(1)')
    context = shooter.context('gold01')
    page = context.new_page()
    shooter.visit(page, '/')
    shooter.shot(page, 'gold-board-header')
    status = shooter.visit(page, '/gold')
    assert status == 200, f'기대 200, 실제 {status}'
    shooter.shot(page, 'gold-lounge')
    status = shooter.visit(page, '/admin')
    assert status == 403, f'기대 403, 실제 {status}'
    shooter.shot(page, 'gold-admin-403')
    context.close()

    # ── 관리자(2) ────────────────────────────────────────
    print('admin01 · 관리자(2)')
    admin_ctx = shooter.context('admin01')
    page = admin_ctx.new_page()
    shooter.visit(page, '/')
    page.wait_for_selector('text=관리자 삭제')
    shooter.shot(page, 'admin-board-header')
    shooter.visit(page, '/gold')
    shooter.shot(page, 'admin-gold-allowed')

    shooter.visit(page, '/admin')
    page.wait_for_selector('#user-rows tr td')
    shooter.shot(page, 'admin-console', full_page=True)

    # 등급 변경: normal01 → 골드(1)
    row = page.locator('#user-rows tr', has_text='normal01')
    row.locator('select').select_option('1')
    row.locator('button', has_text='저장').click()
    page.wait_for_selector('#flash:not(.hidden)')
    page.wait_for_timeout(400)
    shooter.shot(page, 'admin-role-changed', full_page=True)

    # 승급이 실제로 접근 권한을 바꾸는지 확인
    promoted = shooter.context('normal01')
    promoted_page = promoted.new_page()
    status = shooter.visit(promoted_page, '/gold')
    assert status == 200, f'승급 후 기대 200, 실제 {status}'
    shooter.shot(promoted_page, 'normal-promoted-gold-allowed')
    promoted.close()

    # 안전장치: 자기 자신 강등 거절
    page.reload(wait_until='networkidle')
    page.wait_for_selector('#user-rows tr td')
    row = page.locator('#user-rows tr', has_text='admin01')
    row.locator('select').select_option('0')
    row.locator('button', has_text='저장').click()
    page.wait_for_selector('#flash:not(.hidden)')
    page.wait_for_timeout(400)
    shooter.shot(page, 'admin-self-demote-blocked', full_page=True)

    # 관리자가 남의 글을 실제로 삭제한 결과
    shooter.visit(page, '/')
    page.wait_for_selector('text=관리자 삭제')
    page.on('dialog', lambda dialog: dialog.accept())
    target = page.locator('div', has_text='일반 유저가 쓴 합성 글').last
    target.locator('button', has_text='관리자 삭제').click()
    page.wait_for_selector('text=일반 유저가 쓴 합성 글', state='detached')
    page.wait_for_timeout(400)
    shooter.shot(page, 'admin-post-deleted')

    admin_ctx.close()
    browser.close()


def main():
  seed()
  print(f'\n캡처 시작 → {OUT_DIR}')
  try:
    capture()
  finally:
    seed()
    print('캡처 전 상태로 되돌렸습니다.')
  print('\n완료.')


if __name__ == '__main__':
  main()
