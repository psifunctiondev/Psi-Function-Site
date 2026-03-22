from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_user, logout_user

from app.models.user import User

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '')
        user = User.query.filter_by(email=email).first()
        if user:
            login_user(user)
            return redirect(url_for('portal.dashboard'))
        flash('Invalid credentials', 'error')
    return render_template('auth/login.html')

@auth_bp.get('/logout')
def logout():
    logout_user()
    return redirect(url_for('public.home'))
