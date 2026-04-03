from flask import Blueprint, abort, render_template
from flask_login import current_user, login_required

from app.models.client import ClientResource

portal_bp = Blueprint('portal', __name__)


@portal_bp.get('/')
@login_required
def dashboard():
    """Client dashboard — shows resources grouped by category."""
    client = current_user.client
    if not client or not client.is_active:
        abort(403)

    resources = (
        ClientResource.query
        .filter_by(client_id=client.id, is_visible=True)
        .order_by(ClientResource.category, ClientResource.sort_order)
        .all()
    )

    # Group resources by category
    grouped = {}
    for r in resources:
        grouped.setdefault(r.category, []).append(r)

    return render_template(
        'portal/dashboard.html',
        client=client,
        grouped_resources=grouped,
        categories=ClientResource.CATEGORIES,
    )
