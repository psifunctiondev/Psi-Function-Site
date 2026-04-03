from flask_login import UserMixin

from app.extensions import db, login_manager


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(128))
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=True)

    # Relationships
    client = db.relationship('Client', back_populates='users')

@login_manager.user_loader
def load_user(user_id: str):
    return User.query.get(int(user_id))
