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
from app.models.competitive_audit import CompetitiveAuditSubmission
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
    """Drift & Anchor landing — brand banner + tagline + engagement hub.

    Sister route to ``client_dashboard`` but richer: the dashboard is
    the eyebrow-row / 5-column resource grid; this landing adds a
    brand-story banner (storm/seascape from drift-and-anchor.com) and
    a single hero tagline above the same 5-card engagement hub that
    ACME and CTAI use.

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

    resources = (
        ClientResource.query
        .filter_by(client_id=client.id, is_visible=True)
        .order_by(ClientResource.category, ClientResource.sort_order)
        .all()
    )
    grouped = {}
    for r in resources:
        grouped.setdefault(r.category, []).append(r)

    client_users = (
        User.query
        .filter_by(client_id=client.id, is_active_user=True)
        .filter(User.password_hash.isnot(None))
        .all()
    )

    return render_template(
        'portal/drift_and_anchor.html',
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


# ---------- Drift & Anchor: Competitive Audit Requests (R1) ---------- #

# Empty form_data shape — used for both the GET empty-state render and
# POST failure re-render so the template always has a complete shape to
# iterate over (4 competitor sub-cards, social toggles default checked).
_EMPTY_FORM_DATA = {
    'client_name': '',
    'competitor_1': None,
    'competitor_2': None,
    'competitor_3': None,
    'competitor_4': None,
}


def _parse_competitive_audit_form(form):
    """Pull form_data + metadata out of a POSTed WTForms-ish form.

    Empty competitor sub-cards (no fields filled in) land as ``None``
    in the stored JSON, not as empty dicts — keeps the shape
    predictable for the R2 back-end pipeline.
    """
    form_data = dict(_EMPTY_FORM_DATA)
    form_data['client_name'] = (form.get('client_name') or '').strip()

    for i in range(1, 5):
        prefix = f'competitor_{i}_'
        brand_name = (form.get(f'{prefix}brand_name') or '').strip()
        home_url = (form.get(f'{prefix}home_url') or '').strip()

        # Sub-card is empty iff both fields are blank. Toggles default
        # to checked, so the absence of a checkbox submission is
        # itself a signal — but for the empty case we short-circuit
        # to None and ignore toggle data entirely.
        if not brand_name and not home_url:
            form_data[f'competitor_{i}'] = None
            continue

        form_data[f'competitor_{i}'] = {
            'brand_name': brand_name or None,
            'home_url': home_url,
            'include_socials': {
                'x': form.get(f'{prefix}include_x') == 'on',
                'facebook': form.get(f'{prefix}include_facebook') == 'on',
                'instagram': form.get(f'{prefix}include_instagram') == 'on',
                'youtube': form.get(f'{prefix}include_youtube') == 'on',
            },
        }
    return form_data


def _fetch_drift_and_anchor_submission(client_id, submission_id):
    """Look up a submission scoped to the D&A client, 404 otherwise.

    Spec: cross-client id access must 404, NOT 403, so existence
    isn't leaked through the status code.
    """
    sub = CompetitiveAuditSubmission.query.filter_by(
        id=submission_id, client_id=client_id,
    ).first()
    if sub is None:
        abort(404)
    return sub


@portal_bp.route(
    '/p/drift-and-anchor/competitive-audit/',
    methods=['GET', 'POST'],
)
@login_required
def drift_and_anchor_competitive_audit():
    """Drift & Anchor competitive-audit intake (R1).

    GET renders the form (empty, pre-filled via ``?edit=<id>`` or
    ``?fork=<id>``) plus a history list of past submissions for this
    client. POST validates ``client_name`` is non-empty, then either
    updates an existing row (if ``submission_id`` present in the form)
    or creates a new one (carrying ``forked_from_id`` when present).

    Access mirrors the Drift & Anchor landing: own-client user OR site
    admin. Cross-client ``?edit=<id>`` access returns 404 so the
    existence of other clients' audits is not leaked.
    """
    client = Client.query.filter_by(
        slug='drift-and-anchor', is_active=True,
    ).first_or_404()

    if not current_user.is_admin and (
        not current_user.client or current_user.client.id != client.id
    ):
        abort(403)

    history = (
        CompetitiveAuditSubmission.query
        .filter_by(client_id=client.id)
        .order_by(CompetitiveAuditSubmission.created_at.desc())
        .all()
    )

    edit_id = request.values.get('edit', type=int)
    fork_id = request.values.get('fork', type=int)

    edit_target = None
    fork_source = None
    if edit_id:
        edit_target = _fetch_drift_and_anchor_submission(client.id, edit_id)
    if fork_id:
        fork_source = _fetch_drift_and_anchor_submission(client.id, fork_id)

    if request.method == 'POST':
        form_data = _parse_competitive_audit_form(request.form)
        if not form_data['client_name']:
            flash('Client name is required.', 'error')
            return render_template(
                'portal/drift_and_anchor_competitive_audit.html',
                client=client,
                user=current_user,
                history=history,
                form_data=form_data,
                edit_target=None,
                fork_source=None,
                show_form=True,
            )

        submission_id = request.form.get('submission_id', type=int)
        forked_from_id = request.form.get('forked_from_id', type=int)

        if submission_id:
            # Update in place. Re-scope the lookup to this client so
            # the 404 leak-protection holds on POST as well as GET.
            sub = _fetch_drift_and_anchor_submission(
                client.id, submission_id,
            )
            sub.form_data = form_data
        else:
            sub = CompetitiveAuditSubmission(
                client_id=client.id,
                author_id=current_user.id,
                status=CompetitiveAuditSubmission.STATUS_SUBMITTED,
                form_data=form_data,
                forked_from_id=forked_from_id,
            )
            db.session.add(sub)

        db.session.commit()
        flash('Saved.', 'success')
        return redirect(url_for(
            'portal.drift_and_anchor_competitive_audit',
        ))

    # GET — choose the form's prefill source.
    if edit_target is not None:
        # ?edit: prefill from the row; no carry-forward of forked_from_id
        # because the user is editing in place.
        form_data = dict(edit_target.form_data)
        show_form = True
    elif fork_source is not None:
        # ?fork: copy the row's form_data; template renders the
        # hidden forked_from_id so submit creates a new linked row.
        form_data = dict(fork_source.form_data)
        show_form = True
    else:
        form_data = dict(_EMPTY_FORM_DATA)
        show_form = bool(request.values.get('new'))

    return render_template(
        'portal/drift_and_anchor_competitive_audit.html',
        client=client,
        user=current_user,
        history=history,
        form_data=form_data,
        edit_target=edit_target,
        fork_source=fork_source,
        show_form=show_form,
    )
