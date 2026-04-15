"""Client portal dashboard — authenticated, per-client resource view."""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models.client import Client, ClientResource
from app.models.user import User

portal_bp = Blueprint('portal', __name__)


@portal_bp.get('/p/dashboard')
@login_required
def dashboard():
    """Redirect to the slug-based client dashboard."""
    client = current_user.client
    if not client or not client.is_active:
        abort(403)
    return redirect(url_for('portal.client_dashboard', slug=client.slug))


@portal_bp.get('/p/admin')
@login_required
def admin_overview():
    """Admin overview — list all active clients with stats."""
    if not current_user.is_admin:
        abort(403)

    clients = (
        Client.query
        .filter_by(is_active=True)
        .order_by(Client.name)
        .all()
    )

    # Build stats for each client
    client_stats = []
    for c in clients:
        client_stats.append({
            'client': c,
            'user_count': c.users.count(),
            'resource_count': c.resources.filter_by(is_visible=True).count(),
        })

    return render_template(
        'portal/admin.html',
        client_stats=client_stats,
    )


@portal_bp.get('/p/<slug>')
@login_required
def client_dashboard(slug: str):
    """Client dashboard — shows resources grouped by category, themed per client."""
    client = Client.query.filter_by(slug=slug, is_active=True).first_or_404()

    # Check access: user must belong to this client or be an admin
    if not current_user.is_admin and (
        not current_user.client or current_user.client.id != client.id
    ):
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

    # Active registered users for this client
    client_users = (
        User.query
        .filter_by(client_id=client.id, is_active_user=True)
        .filter(User.password_hash.isnot(None))
        .all()
    )

    return render_template(
        'portal/dashboard.html',
        client=client,
        user=current_user,
        grouped_resources=grouped,
        resources_by_cat=grouped,
        categories=ClientResource.CATEGORIES,
        client_users=client_users,
    )


@portal_bp.get('/p/<slug>/invite')
@login_required
def invite_user(slug):
    """Show invite form for adding a user to this client portal."""
    client = Client.query.filter_by(slug=slug, is_active=True).first_or_404()
    if current_user.client_id != client.id and not current_user.is_admin:
        abort(403)
    return render_template('portal/invite.html', client=client)


@portal_bp.post('/p/<slug>/invite')
@login_required
def invite_user_submit(slug):
    """Process invite form submission."""
    client = Client.query.filter_by(slug=slug, is_active=True).first_or_404()
    if current_user.client_id != client.id and not current_user.is_admin:
        abort(403)

    email = request.form.get('email', '').strip().lower()
    if not email:
        flash('Email is required.', 'error')
        return redirect(url_for('portal.invite_user', slug=slug))

    existing = User.query.filter_by(email=email).first()
    if existing:
        flash('A user with that email already exists.', 'error')
        return redirect(url_for('portal.invite_user', slug=slug))

    user = User(email=email, client_id=client.id)
    db.session.add(user)
    user.generate_invite_token()
    db.session.commit()

    flash(f'Invite sent to {email}.', 'success')
    # TODO: Send invite email via AgentMail
    return redirect(url_for('portal.client_dashboard', slug=slug))
