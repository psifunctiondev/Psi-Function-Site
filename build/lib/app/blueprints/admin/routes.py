from flask import Blueprint, render_template
from flask_login import current_user, login_required
from werkzeug.exceptions import Forbidden

admin_bp = Blueprint('admin', __name__)

@admin_bp.get('/')
@login_required
def index():
    if not current_user.is_admin:
        raise Forbidden()
    return render_template('public/about.html')
