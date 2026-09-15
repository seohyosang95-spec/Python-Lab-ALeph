from extensions import db


class Post(db.Model):
  __tablename__ = 'posts'

  id = db.Column(db.Integer, primary_key=True)
  title = db.Column(db.String(200), nullable=False)
  content = db.Column(db.Text, nullable=False)
  category = db.Column(db.String(50), nullable=False, default='일반')
  author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
  author = db.relationship('User', backref=db.backref('posts', lazy=True))

  def to_dict(self):
    return {
        'id': self.id,
        'title': self.title,
        'content': self.content,
        'category': self.category,
        'author': self.author.username,
        'author_id': self.author_id,
    }