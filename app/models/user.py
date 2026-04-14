"""User model with password hashing and invite token support."""

import secrets
from datetime import UTC, datetime, timedelta

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db, login_manager


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=True)  # null until registered
    display_name = db.Column(db.String(128))
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_active_user = db.Column(db.Boolean, default=True, nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    # Invite / reset tokens
    invite_token = db.Column(db.String(128), unique=True, nullable=True)
    invite_expires = db.Column(db.DateTime, nullable=True)
    reset_token = db.Column(db.String(128), unique=True, nullable=True)
    reset_expires = db.Column(db.DateTime, nullable=True)

    # Relationships
    client = db.relationship('Client', back_populates='users')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def generate_invite_token(self, expires_hours=72):
        self.invite_token = secrets.token_urlsafe(32)
        self.invite_expires = datetime.now(UTC) + timedelta(hours=expires_hours)
        return self.invite_token

    def generate_reset_token(self, expires_hours=24):
        self.reset_token = secrets.token_urlsafe(32)
        self.reset_expires = datetime.now(UTC) + timedelta(hours=expires_hours)
        return self.reset_token

    @property
    def is_registered(self):
        return self.password_hash is not None

    @property
    def is_invite_valid(self):
        if not self.invite_token or not self.invite_expires:
            return False
        return datetime.now(UTC) < self.invite_expires

    @property
    def is_reset_valid(self):
        if not self.reset_token or not self.reset_expires:
            return False
        return datetime.now(UTC) < self.reset_expires

    def __repr__(self):
        return f'<User {self.email}>'


@login_manager.user_loader
def load_user(user_id: str):
    return User.query.get(int(user_id))
