"""Auth routes — login, register (via invite), password reset, logout."""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_user, logout_user

from app.extensions import db
from app.models.user import User

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/p/login', methods=['GET', 'POST'])
def login():
    """Client portal login page — also serves register and reset tabs."""
    mode = request.args.get('mode', 'login')
    token = request.args.get('token', '')

    # If an invite token is provided, switch to register mode
    if token and mode != 'reset':
        mode = 'register'

    if request.method == 'POST':
        action = request.form.get('action', 'login')

        if action == 'login':
            return _handle_login()
        elif action == 'register':
            return _handle_register()
        elif action == 'reset-request':
            return _handle_reset_request()
        elif action == 'reset-confirm':
            return _handle_reset_confirm()

    return render_template('auth/login.html', mode=mode, token=token)


def _handle_login():
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')

    user = User.query.filter_by(email=email).first()
    if user and user.is_active_user and user.check_password(password):
        login_user(user)
        return redirect(url_for('portal.dashboard'))

    flash('Invalid email or password.', 'error')
    return redirect(url_for('auth.login', mode='login'))


def _handle_register():
    token = request.form.get('token', '')
    display_name = request.form.get('display_name', '').strip()
    password = request.form.get('password', '')
    password_confirm = request.form.get('password_confirm', '')

    if not token:
        flash('An invite token is required to register.', 'error')
        return redirect(url_for('auth.login', mode='register'))

    user = User.query.filter_by(invite_token=token).first()
    if not user or not user.is_invite_valid:
        flash('This invite link has expired or is invalid.', 'error')
        return redirect(url_for('auth.login', mode='login'))

    if user.is_registered:
        flash('This account is already registered. Please sign in.', 'error')
        return redirect(url_for('auth.login', mode='login'))

    if not password or len(password) < 8:
        flash('Password must be at least 8 characters.', 'error')
        return redirect(url_for('auth.login', mode='register', token=token))

    if password != password_confirm:
        flash('Passwords do not match.', 'error')
        return redirect(url_for('auth.login', mode='register', token=token))

    user.display_name = display_name or user.email.split('@')[0]
    user.set_password(password)
    user.invite_token = None
    user.invite_expires = None
    db.session.commit()

    login_user(user)
    flash('Welcome! Your account is ready.', 'success')
    return redirect(url_for('portal.dashboard'))


def _handle_reset_request():
    email = request.form.get('email', '').strip().lower()

    # Always show the same message to avoid email enumeration
    flash('If that email is registered, you will receive a reset link.', 'info')

    user = User.query.filter_by(email=email, is_active_user=True).first()
    if user and user.is_registered:
        token = user.generate_reset_token()
        db.session.commit()
        # TODO: Send reset email via AgentMail
        # For now, token is generated and stored — email integration next

    return redirect(url_for('auth.login', mode='login'))


def _handle_reset_confirm():
    token = request.form.get('token', '')
    password = request.form.get('password', '')
    password_confirm = request.form.get('password_confirm', '')

    user = User.query.filter_by(reset_token=token).first()
    if not user or not user.is_reset_valid:
        flash('This reset link has expired or is invalid.', 'error')
        return redirect(url_for('auth.login', mode='reset'))

    if not password or len(password) < 8:
        flash('Password must be at least 8 characters.', 'error')
        return redirect(url_for('auth.login', mode='reset', token=token))

    if password != password_confirm:
        flash('Passwords do not match.', 'error')
        return redirect(url_for('auth.login', mode='reset', token=token))

    user.set_password(password)
    user.reset_token = None
    user.reset_expires = None
    db.session.commit()

    flash('Password updated. Please sign in.', 'success')
    return redirect(url_for('auth.login', mode='login'))


@auth_bp.get('/p/logout')
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
