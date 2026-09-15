"""화면(HTML) 라우트만 모음. 데이터는 각 페이지의 JS 가 API 로 가져온다."""
from flask import Blueprint, render_template

page_bp = Blueprint('page', __name__)


@page_bp.route('/')
def index():
  return render_template('index.html')


@page_bp.route('/dashboard')
def dashboard():
  """보안 이벤트 대시보드 (n8n 이 저장한 허용/거부 기록)."""
  return render_template('dashboard.html')


@page_bp.route('/gold')
def gold_page():
  """골드 등급 전용 화면. 페이지 자체는 항상 렌더되고,
  등급 확인은 화면 JS 가 /api/auth/me 로 한다(모자라면 예외 화면).
  실제 데이터 차단은 서버(/api/gold/posts)가 담당한다."""
  return render_template('gold.html')


@page_bp.route('/admin')
def admin_page():
  """관리자 페이지 — 회원 역할(인가) 부여/회수. admin 계정 로그인 필요."""
  return render_template('admin.html')


@page_bp.route('/public-posts')
def public_posts_page():
  return render_template('public_posts.html')


@page_bp.route('/public-posts/<int:uc_seq>')
def public_post_detail_page(uc_seq):
  return render_template('public_detail.html', uc_seq=uc_seq)