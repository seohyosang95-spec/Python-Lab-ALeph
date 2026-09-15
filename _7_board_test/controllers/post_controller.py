"""게시글 CRUD (RESTful). 쓰기/수정/삭제는 JWT 로그인 필요."""
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from extensions import db
from models import Post

post_bp = Blueprint('post', __name__, url_prefix='/api/posts')


@post_bp.route('', methods=['GET'])
def get_posts():
  """커서 기반 목록. ?cursor=&limit=&search=&category="""
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

  return jsonify({
      'posts': [p.to_dict() for p in posts],
      'next_cursor': next_cursor,
      'has_more': has_more,
  })


@post_bp.route('', methods=['POST'])
@jwt_required()
def create_post():
  user_id = int(get_jwt_identity())
  data = request.get_json(silent=True) or {}
  if not data.get('title') or not data.get('content'):
    return jsonify({'msg': 'title, content 는 필수입니다.'}), 400

  post = Post(title=data['title'], content=data['content'],
              category=data.get('category', '일반'), author_id=user_id)
  db.session.add(post)
  db.session.commit()
  return jsonify({'msg': '게시글이 등록되었습니다.', 'id': post.id}), 201


@post_bp.route('/<int:id>', methods=['PUT'])
@jwt_required()
def update_post(id):
  user_id = int(get_jwt_identity())
  post = Post.query.get_or_404(id)
  if post.author_id != user_id:
    return jsonify({'msg': '권한이 없습니다.'}), 403

  data = request.get_json(silent=True) or {}
  post.title = data.get('title', post.title)
  post.content = data.get('content', post.content)
  post.category = data.get('category', post.category)
  db.session.commit()
  return jsonify({'msg': '수정되었습니다.'})


@post_bp.route('/<int:id>', methods=['DELETE'])
@jwt_required()
def delete_post(id):
  user_id = int(get_jwt_identity())
  post = Post.query.get_or_404(id)
  if post.author_id != user_id:
    return jsonify({'msg': '권한이 없습니다.'}), 403

  db.session.delete(post)
  db.session.commit()
  return jsonify({'msg': '삭제되었습니다.'})