"""Client portal dashboard — authenticated, per-client resource view."""

import os

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_login import current_user, login_required

from app.extensions import db
from app.models.client import Client, ClientResource
from app.models.user import User

portal_bp = Blueprint('portal', __name__)


# ---------- Legacy redirects (old Bluehost URLs) ---------- #

@portal_bp.get('/clients/ctai/truview-guide')
@portal_bp.get('/clients/ctai/trueview-guide')
def legacy_truview_guide():
    """Redirect old Bluehost URL to portal-hosted guide."""
    return redirect('/guides/ctai/truview/', code=301)


# ---------- Client guide serving ---------- #

@portal_bp.get('/guides/<slug>/<guide>/')
@portal_bp.get('/guides/<slug>/<guide>/<path:path>')
def serve_guide(slug, guide, path='index.html'):
    """Serve static MkDocs guide content from client-content directory."""
    if not path or path.endswith('/'):
        path = path + 'index.html'
    guide_dir = os.path.join(
        current_app.static_folder,
        'client-content', slug, guide,
    )
    guide_dir = os.path.realpath(guide_dir)

    # If path is a directory, redirect to add trailing slash
    # so relative links resolve correctly.
    full = os.path.join(guide_dir, path)
    if os.path.isdir(full):
        return redirect(request.path + '/', code=301)

    # If file doesn't exist but path/index.html does, serve it.
    if not os.path.isfile(full):
        index_candidate = os.path.join(full + '/', 'index.html')
        if os.path.isfile(index_candidate):
            return redirect(request.path + '/', code=301)

    return send_from_directory(guide_dir, path)


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


# ---------- Drift & Anchor (per-client landing page) ----------

@portal_bp.get('/p/drift-and-anchor/')
@login_required
def drift_and_anchor_overview():
    """Drift & Anchor landing — brand story + services split + engagement hub.

    Sister route to ``client_dashboard`` but richer: the dashboard is
    the standard 5-column resource grid; this landing is the
    brand-story-driven entry pad that the rest of the portal hangs off.
    R1 ships the route + template + theming; R2 layers in the live
    engagement timeline and the OpenProject embed (see the engagement
    card in ``portal/drift_and_anchor.html`` for the R2/R3 plan).

    Access mirrors ``client_dashboard``: the user must belong to the
    Drift & Anchor client OR be a site admin. The slug is hard-coded
    to ``drift-and-anchor`` by the route literal (matches the
    BRANDING_PROFILES key) — so an inactive or missing client row
    404s cleanly via ``first_or_404``.
    """
    client = Client.query.filter_by(
        slug='drift-and-anchor', is_active=True,
    ).first_or_404()

    if not current_user.is_admin and (
        not current_user.client or current_user.client.id != client.id
    ):
        abort(403)

    return render_template(
        'portal/drift_and_anchor.html',
        client=client,
        user=current_user,
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
