"""Flask CLI commands for user and client management."""

import os
import secrets

import click
from flask import current_app
from flask.cli import with_appcontext

from app.extensions import db
from app.models.client import Client
from app.models.user import User


@click.group('user')
def user_cli():
    """Manage portal users."""
    pass


@user_cli.command('invite')
@click.option('--email', required=True, help='Email address to invite')
@click.option('--client', required=True, help='Client slug (created if missing)')
@click.option('--client-name', default=None, help='Client display name (if creating)')
@click.option('--hours', default=72, help='Invite expiry in hours (default: 72)')
@with_appcontext
def invite_user(email, client, client_name, hours):
    """Send a registration invite to a new portal user."""
    email = email.strip().lower()

    # Find or create client org
    client_org = Client.query.filter_by(slug=client).first()
    if not client_org:
        client_org = Client(
            name=client_name or client.replace('-', ' ').title(),
            slug=client,
        )
        db.session.add(client_org)
        db.session.flush()
        click.echo(f'Created client org: {client_org.name} ({client_org.slug})')

    # Check if user already exists
    existing = User.query.filter_by(email=email).first()
    if existing and existing.is_registered:
        click.echo(f'User {email} is already registered.')
        return

    if existing:
        user = existing
    else:
        user = User(email=email, client_id=client_org.id)
        db.session.add(user)

    token = user.generate_invite_token(expires_hours=hours)
    db.session.commit()

    base_url = current_app.config.get('SERVER_NAME', 'psifunction.com')
    scheme = 'https' if not current_app.debug else 'http'
    invite_url = f'{scheme}://{base_url}/p/login?mode=register&token={token}'

    click.echo(f'Invite created for {email}')
    click.echo(f'Client: {client_org.name}')
    click.echo(f'Expires: {hours} hours')
    click.echo(f'Invite URL: {invite_url}')
    click.echo('')
    click.echo('Send this URL to the user. They will set their name and password.')
    # TODO: Auto-send via AgentMail


@user_cli.command('list')
@with_appcontext
def list_users():
    """List all portal users."""
    users = User.query.order_by(User.client_id, User.email).all()
    if not users:
        click.echo('No users found.')
        return

    click.echo(f'{"Email":<35} {"Name":<20} {"Client":<20} {"Status":<12}')
    click.echo('-' * 90)
    for u in users:
        client_name = u.client.name if u.client else '(none)'
        status = 'active' if u.is_registered and u.is_active_user else \
                 'invited' if u.invite_token else 'inactive'
        name = u.display_name or ''
        click.echo(f'{u.email:<35} {name:<20} {client_name:<20} {status:<12}')


@user_cli.command('make-admin')
@click.option('--email', required=True, help='Email of user to promote')
@with_appcontext
def make_admin(email):
    """Grant admin privileges to a portal user."""
    user = User.query.filter_by(email=email.strip().lower()).first()
    if not user:
        click.echo(f'User {email} not found.')
        return

    if user.is_admin:
        click.echo(f'{email} is already an admin.')
        return

    user.is_admin = True
    db.session.commit()
    click.echo(f'Granted admin privileges to {email}.')


@user_cli.command('deactivate')
@click.option('--email', required=True, help='Email of user to deactivate')
@with_appcontext
def deactivate_user(email):
    """Deactivate a portal user (revoke access)."""
    user = User.query.filter_by(email=email.strip().lower()).first()
    if not user:
        click.echo(f'User {email} not found.')
        return

    user.is_active_user = False
    user.invite_token = None
    user.reset_token = None
    db.session.commit()
    click.echo(f'Deactivated {email}.')


@user_cli.command('reset-password')
@click.option('--email', required=True, help='Email of user')
@click.option('--hours', default=24, help='Reset token expiry in hours')
@with_appcontext
def reset_password(email, hours):
    """Generate a password reset link for a user."""
    user = User.query.filter_by(email=email.strip().lower()).first()
    if not user:
        click.echo(f'User {email} not found.')
        return

    token = user.generate_reset_token(expires_hours=hours)
    db.session.commit()

    base_url = current_app.config.get('SERVER_NAME', 'psifunction.com')
    scheme = 'https' if not current_app.debug else 'http'
    reset_url = f'{scheme}://{base_url}/p/login?mode=reset&token={token}'

    click.echo(f'Reset link for {email}:')
    click.echo(f'{reset_url}')
    click.echo(f'Expires: {hours} hours')


@click.group('client')
def client_cli():
    """Manage client organizations."""
    pass


@client_cli.command('create')
@click.option('--slug', required=True, help='URL slug (e.g. ctai)')
@click.option('--name', required=True, help='Display name')
@click.option('--primary', default=None, help='Primary hex color (e.g. #2B4C6F)')
@click.option('--accent', default=None, help='Accent hex color (e.g. #C4956A)')
@click.option('--logo', default=None, help='Logo URL')
@click.option('--banner', default=None, help='Banner image URL')
@click.option('--tagline', default=None, help='Short welcome tagline')
@click.option('--font-url', default=None, help='Google Fonts CSS URL')
@click.option('--font-display', default=None, help='Display font-family')
@with_appcontext
def create_client(slug, name, primary, accent, logo, banner, tagline, font_url, font_display):
    """Create a new client organization."""
    existing = Client.query.filter_by(slug=slug).first()
    if existing:
        click.echo(f'Client with slug "{slug}" already exists.')
        return

    client = Client(
        slug=slug,
        name=name,
        primary_color=primary,
        accent_color=accent,
        logo_url=logo,
        banner_url=banner,
        tagline=tagline,
        font_url=font_url,
        font_display=font_display,
    )
    db.session.add(client)
    db.session.commit()
    click.echo(f'Created client: {client.name} ({client.slug})')


@client_cli.command('list')
@with_appcontext
def list_clients():
    """List all client organizations."""
    clients = Client.query.order_by(Client.name).all()
    if not clients:
        click.echo('No clients found.')
        return

    click.echo(f'{"Name":<40} {"Slug":<16} {"Active":<8} {"Primary":<10} {"Accent":<10}')
    click.echo('-' * 86)
    for c in clients:
        click.echo(
            f'{c.name:<40} {c.slug:<16} {"yes" if c.is_active else "no":<8} '
            f'{c.primary_color or "—":<10} {c.accent_color or "—":<10}'
        )


@client_cli.command('update')
@click.option('--slug', required=True, help='Client slug to update')
@click.option('--name', default=None, help='New display name')
@click.option('--primary', default=None, help='Primary hex color')
@click.option('--accent', default=None, help='Accent hex color')
@click.option('--logo', default=None, help='Logo URL')
@click.option('--banner', default=None, help='Banner image URL')
@click.option('--tagline', default=None, help='Short welcome tagline')
@click.option('--font-url', default=None, help='Google Fonts CSS URL')
@click.option('--font-display', default=None, help='Display font-family')
@with_appcontext
def update_client(slug, name, primary, accent, logo, banner, tagline, font_url, font_display):
    """Update an existing client organization."""
    client = Client.query.filter_by(slug=slug).first()
    if not client:
        click.echo(f'Client "{slug}" not found.')
        return

    if name is not None:
        client.name = name
    if primary is not None:
        client.primary_color = primary
    if accent is not None:
        client.accent_color = accent
    if logo is not None:
        client.logo_url = logo
    if banner is not None:
        client.banner_url = banner
    if tagline is not None:
        client.tagline = tagline
    if font_url is not None:
        client.font_url = font_url
    if font_display is not None:
        client.font_display = font_display

    db.session.commit()
    click.echo(f'Updated client: {client.name} ({client.slug})')


# Known-good branding profiles applied idempotently on deploy.
#
# This dict is the source of truth for each client's portal branding.
# Edit a value here -> it reapplies on the next deploy via
# `flask client apply-branding --all` (called from deploy_release.sh).
#
# Adding a new client: append an entry with the same shape. If the matching
# Client row does not exist yet it will be created (only `name` + `slug` are
# required alongside the branding fields).
BRANDING_PROFILES = {
    'ctai': {
        'name': 'Catherine Truman Architects',
        'primary_color': '#FA6202',
        'accent_color': '#878787',
        'logo_url': '/static/images/ctai-logo.svg',
        'tagline': 'Modernizing New England Home Design',
        'font_url': (
            'https://fonts.googleapis.com/css2?'
            'family=Special+Gothic&display=swap'
        ),
        # Free Google Fonts stand-in for the site's proprietary
        # "Sackers Gothic Std Heavy" display face.
        'font_display': "'Special Gothic', sans-serif",
    },
    'acme': {
        'name': 'ACME Corporation',
        # Warm desert palette — ochre primary, muted sand accent.
        # Quinn can tune hex values later.
        'primary_color': '#D7282F',
        'accent_color': '#1A1A1A',
        'logo_url': '/static/images/acme-logo.webp',
        # Badge logo is visually dense — cap height so it doesn't loom.
        'logo_max_height': '10rem',
        'tagline': (
            'Purveyors of fine products to the discerning predator since 1949.'
        ),
        'font_url': (
            'https://fonts.googleapis.com/css2?'
            'family=Bungee+Inline&family=Inter:wght@400;600&display=swap'
        ),
        # Bungee Inline gives the retro-mail-order-catalog feel for
        # display headings; Inter handles body copy.
        'font_display': "'Bungee Inline', 'Inter', sans-serif",
    },
}


def _apply_profile(slug, profile):
    """Idempotently create/update a Client row from a BRANDING_PROFILES entry.

    Returns a tuple (client, created, changed_fields).
    """
    client = Client.query.filter_by(slug=slug).first()
    created = False
    if client is None:
        client = Client(slug=slug, name=profile.get('name') or slug.upper())
        db.session.add(client)
        created = True

    changed = []
    for field, value in profile.items():
        if getattr(client, field, None) != value:
            setattr(client, field, value)
            changed.append(field)

    if changed or created:
        db.session.commit()
    return client, created, changed


@client_cli.command('apply-branding')
@click.option('--slug', default=None, help='Client slug (omit with --all)')
@click.option('--all', 'apply_all', is_flag=True,
              help='Apply every profile in BRANDING_PROFILES')
@with_appcontext
def apply_branding(slug, apply_all):
    """Apply known-good branding to one or all clients (idempotent).

    Safe to run on every deploy. Creates the Client row if missing,
    then upserts branding fields from BRANDING_PROFILES.
    """
    if not apply_all and not slug:
        click.echo('Pass --slug <slug> or --all.')
        raise click.exceptions.Exit(code=2)

    if apply_all:
        targets = list(BRANDING_PROFILES.items())
    else:
        if slug not in BRANDING_PROFILES:
            click.echo(
                f'No branding profile defined for "{slug}". '
                f'Known: {", ".join(sorted(BRANDING_PROFILES)) or "(none)"}'
            )
            raise click.exceptions.Exit(code=1)
        targets = [(slug, BRANDING_PROFILES[slug])]

    for s, profile in targets:
        client, created, changed = _apply_profile(s, profile)
        verb = 'Created' if created else ('Updated' if changed else 'Unchanged')
        detail = f' ({", ".join(changed)})' if changed and not created else ''
        click.echo(f'{verb}: {client.name} [{client.slug}]{detail}')


# Demo user identity for the ACME showcase client.
# Kept module-level so tests and seeders share the constant.
ACME_DEMO_EMAIL = 'demo@acme.com'


@client_cli.command('seed-acme-demo')
@click.option(
    '--password', default=None,
    help=(
        'Password for the demo user. If omitted, ACME_DEMO_PASSWORD env '
        'var is used; if that is also unset, a random 16-char password '
        'is generated and printed once.'
    ),
)
@click.option(
    '--display-name', default='ACME Demo',
    help='Display name for the demo user (default: "ACME Demo").',
)
@click.option(
    '--reset-password', is_flag=True, default=False,
    help=(
        'Force regeneration of the demo user password even if the user '
        'is already registered. The new password is printed once, exactly '
        'like first-time seed. Has no effect when --password or '
        'ACME_DEMO_PASSWORD is also provided (those win).'
    ),
)
@with_appcontext
def seed_acme_demo(password, display_name, reset_password):
    """Seed the ACME showcase demo user (idempotent).

    Ensures the ACME client row exists (via the branding profile), then
    creates or updates demo@acme.com as a regular, fully-registered user
    tied to that client. Safe to re-run.

    Password resolution order:
      1. --password CLI flag
      2. ACME_DEMO_PASSWORD env var (only used if user is unregistered
         OR --reset-password is set)
      3. Randomly generated 16-char password (printed once) when the
         user is unregistered OR --reset-password is set

    Existing passwords are NOT overwritten on re-run unless --password
    or --reset-password is given (so deploy-time re-seeds don't rotate
    the demo creds).
    """
    # Make sure the ACME client row exists. Reuse the branding profile so
    # we don't drift from BRANDING_PROFILES.
    profile = BRANDING_PROFILES.get('acme')
    if profile is None:
        click.echo(
            'No branding profile for "acme" — add one to BRANDING_PROFILES '
            'before seeding the demo user.'
        )
        raise click.exceptions.Exit(code=1)

    client_org, created_client, _ = _apply_profile('acme', profile)
    if created_client:
        click.echo(f'Created client: {client_org.name} [{client_org.slug}]')

    user = User.query.filter_by(email=ACME_DEMO_EMAIL).first()
    created_user = False
    if user is None:
        user = User(
            email=ACME_DEMO_EMAIL,
            display_name=display_name,
            client_id=client_org.id,
            is_active_user=True,
            is_admin=False,
        )
        db.session.add(user)
        created_user = True
    else:
        # Keep the demo user pointed at the right client + active state,
        # but don't clobber a manually-edited display name unless the
        # caller passed --display-name explicitly. Click can't easily
        # tell us "was this flag explicit" without context; the default
        # value is harmless to re-apply.
        if user.client_id != client_org.id:
            user.client_id = client_org.id
        if not user.is_active_user:
            user.is_active_user = True
        if user.is_admin:
            # The demo user must never be an admin.
            user.is_admin = False
        if not user.display_name:
            user.display_name = display_name

    # Password handling.
    explicit_password = password
    env_password = os.environ.get('ACME_DEMO_PASSWORD')
    generated_password = None

    needs_new_password = (not user.is_registered) or reset_password

    if explicit_password:
        user.set_password(explicit_password)
        password_source = 'cli flag'
    elif needs_new_password and env_password:
        user.set_password(env_password)
        password_source = (
            'ACME_DEMO_PASSWORD env var (reset)' if reset_password
            else 'ACME_DEMO_PASSWORD env var'
        )
    elif needs_new_password:
        generated_password = secrets.token_urlsafe(12)[:16]
        user.set_password(generated_password)
        password_source = (
            'generated (printed below — store it now; reset)' if reset_password
            else 'generated (printed below — store it now)'
        )
    else:
        password_source = 'unchanged (user already registered)'

    db.session.commit()

    verb = 'Created' if created_user else 'Updated'
    click.echo(f'{verb} demo user: {user.email} → {client_org.name}')
    click.echo(f'Password source: {password_source}')
    if generated_password is not None:
        click.echo('')
        click.echo('  Generated password (NOT logged anywhere else):')
        click.echo(f'    {generated_password}')
        click.echo('')
        click.echo(
            '  Save this in your secrets store now. Re-running this '
            'command will not regenerate it.'
        )


# Seed payload for the ACME showcase resources. Each entry is the full
# kwargs dict for a ClientResource row. Idempotency is keyed on
# (client_id, title) — re-running the seeder updates existing rows in
# place rather than creating duplicates.
ACME_DEMO_RESOURCES = [
    # Engagement & Process — the Psi Function service arc.
    {
        'title': 'Engagement Charter',
        'description': (
            'Scope, roles, and the Discover → Blueprint → Construct → '
            'Realize cadence for this engagement.'
        ),
        'category': 'engagement',
        'external_url': 'https://psifunction.com/showcase/acme/charter',
        'sort_order': 10,
    },
    {
        'title': 'Discovery Notes',
        'description': 'Stakeholder interviews and current-state findings.',
        'category': 'engagement',
        'external_url': 'https://psifunction.com/showcase/acme/discovery',
        'sort_order': 20,
    },
    # Deliverables — example artifacts a real client would receive.
    {
        'title': 'Architecture Blueprint',
        'description': (
            'Target-state architecture diagram and decision log for the '
            'ACME platform modernization.'
        ),
        'category': 'deliverables',
        'external_url': 'https://psifunction.com/showcase/acme/blueprint',
        'sort_order': 10,
    },
    {
        'title': 'Implementation Roadmap',
        'description': (
            'Phased delivery plan with milestones, dependencies, and '
            'risk callouts.'
        ),
        'category': 'deliverables',
        'external_url': 'https://psifunction.com/showcase/acme/roadmap',
        'sort_order': 20,
    },
    # Tools & Dashboards — the live systems clients work in with us.
    {
        'title': 'OpenProject Workspace',
        'description': 'Live project board, backlog, and sprint reports.',
        'category': 'tools',
        'external_url': 'https://psifunction.com/showcase/acme/openproject',
        'sort_order': 10,
    },
    {
        'title': 'Status Dashboard',
        'description': 'Weekly status, burn-up, and risk register.',
        'category': 'tools',
        'external_url': 'https://psifunction.com/showcase/acme/dashboard',
        'sort_order': 20,
    },
]


@client_cli.command('seed-acme-resources')
@with_appcontext
def seed_acme_resources():
    """Seed the ACME showcase ClientResource rows (idempotent).

    Ensures the ACME client row exists (via BRANDING_PROFILES), then
    upserts each entry in ACME_DEMO_RESOURCES keyed on (client, title).
    Existing rows have their description / category / url / sort_order
    fields synced; titles are the stable identifier.
    """
    from app.models.client import ClientResource

    profile = BRANDING_PROFILES.get('acme')
    if profile is None:
        click.echo(
            'No branding profile for "acme" — add one to BRANDING_PROFILES '
            'before seeding resources.'
        )
        raise click.exceptions.Exit(code=1)

    client_org, created_client, _ = _apply_profile('acme', profile)
    if created_client:
        click.echo(f'Created client: {client_org.name} [{client_org.slug}]')

    created_count = 0
    updated_count = 0
    unchanged_count = 0

    for entry in ACME_DEMO_RESOURCES:
        existing = ClientResource.query.filter_by(
            client_id=client_org.id, title=entry['title'],
        ).first()

        if existing is None:
            resource = ClientResource(
                client_id=client_org.id,
                title=entry['title'],
                description=entry.get('description'),
                category=entry['category'],
                external_url=entry.get('external_url'),
                file_path=entry.get('file_path'),
                sort_order=entry.get('sort_order', 0),
            )
            db.session.add(resource)
            created_count += 1
            click.echo(f'  + {entry["title"]} ({entry["category"]})')
            continue

        changed_fields = []
        for field in ('description', 'category', 'external_url',
                      'file_path', 'sort_order'):
            new_value = entry.get(field, 0 if field == 'sort_order' else None)
            if getattr(existing, field) != new_value:
                setattr(existing, field, new_value)
                changed_fields.append(field)

        if changed_fields:
            updated_count += 1
            click.echo(
                f'  ~ {entry["title"]} '
                f'({", ".join(changed_fields)})'
            )
        else:
            unchanged_count += 1

    db.session.commit()
    click.echo('')
    click.echo(
        f'Seeded ACME resources: {created_count} created, '
        f'{updated_count} updated, {unchanged_count} unchanged '
        f'(total {len(ACME_DEMO_RESOURCES)}).'
    )


@click.group('resource')
def resource_cli():
    """Manage client resources (guides, tools, links)."""
    pass


@resource_cli.command('add')
@click.option('--client', required=True, help='Client slug')
@click.option('--title', required=True, help='Resource display title')
@click.option(
    '--category', required=True,
    type=click.Choice(
        ['proposal', 'backlog', 'custom', 'guide'],
        case_sensitive=False,
    ),
    help='Dashboard category',
)
@click.option('--url', default=None, help='External URL')
@click.option(
    '--file', 'file_path', default=None,
    help='Static file path (relative to app/static/)',
)
@click.option('--order', 'sort_order', default=0, help='Sort order within category')
@with_appcontext
def add_resource(client, title, category, url, file_path, sort_order):
    """Add a resource to a client portal."""
    from app.models.client import ClientResource

    client_org = Client.query.filter_by(slug=client).first()
    if not client_org:
        click.echo(f'Client "{client}" not found.')
        return

    resource = ClientResource(
        client_id=client_org.id,
        title=title,
        category=category.lower(),
        external_url=url,
        file_path=file_path,
        sort_order=sort_order,
    )
    db.session.add(resource)
    db.session.commit()
    click.echo(f'Added "{title}" ({category}) to {client_org.name}')


@resource_cli.command('remove')
@click.option('--client', required=True, help='Client slug')
@click.option('--title', required=True, help='Resource title to remove')
@with_appcontext
def remove_resource(client, title):
    """Remove a resource from a client portal."""
    from app.models.client import ClientResource

    client_org = Client.query.filter_by(slug=client).first()
    if not client_org:
        click.echo(f'Client "{client}" not found.')
        return

    resources = ClientResource.query.filter_by(
        client_id=client_org.id, title=title,
    ).all()

    if not resources:
        click.echo(f'No resource "{title}" found for {client_org.name}.')
        return

    for r in resources:
        db.session.delete(r)
        target = r.external_url or r.file_path or 'no url'
        click.echo(f'Removed "{r.title}" ({r.category}) — {target}')

    db.session.commit()
    click.echo(f'Deleted {len(resources)} resource(s).')


@resource_cli.command('list')
@click.option('--client', default=None, help='Filter by client slug')
@with_appcontext
def list_resources(client):
    """List client resources."""
    from app.models.client import ClientResource

    query = ClientResource.query
    if client:
        client_org = Client.query.filter_by(slug=client).first()
        if not client_org:
            click.echo(f'Client "{client}" not found.')
            return
        query = query.filter_by(client_id=client_org.id)

    resources = query.order_by(
        ClientResource.client_id,
        ClientResource.category,
        ClientResource.sort_order,
    ).all()

    if not resources:
        click.echo('No resources found.')
        return

    click.echo(f'{"Title":<40} {"Category":<12} {"Client":<12} {"URL/Path"}')
    click.echo('-' * 100)
    for r in resources:
        client_slug = r.client.slug if r.client else '?'
        target = r.external_url or r.file_path or '—'
        click.echo(f'{r.title:<40} {r.category:<12} {client_slug:<12} {target}')


# ---------------------------------------------------------------------------
# Taxonomy + work-showcase seeders
# ---------------------------------------------------------------------------

# Canonical taxonomy axes. Sourced from the shared Obsidian vault
# ("Psi Function Taxonomy") -- these labels are authoritative. Order within
# each axis becomes the tag sort_order.
TAXONOMY_AXES = {
    'vertical': [
        'Architecture & Design',
        'Creative & Media',
        'Financial & Insurance Services',
        'Health & Wellness',
        'Hospitality & Entertainment',
        'Manufacturing, Logistics & Supply Chain',
        'Professional Services',
        'Construction & Trades',
        'Retail & E-commerce',
        'Nonprofit & Education',
    ],
    'function': [
        'Compliance, Risk & Legal',
        'Customer Experience & Service',
        'Finance & Administration',
        'Marketing & Brand Management',
        'Metrics & Reporting',
        'Operations & Workflow',
        'Organization & Culture',
        'Product & Service Delivery',
        'Sales & Revenue',
    ],
    'technology': [
        'Applications & Integrations',
        'Artificial Intelligence & Process Automation',
        'Cloud Computing',
        'Data & Analytics',
        'Security & Identity',
        'Immersive & Visualization',
        'Infrastructure & Networking',
        'Web & Digital Presence',
    ],
}


def taxonomy_slug(label: str) -> str:
    """Deterministic slug: lowercase, '&' -> 'and', commas dropped,
    spaces -> hyphens.

    Examples:
        'Architecture & Design'      -> 'architecture-and-design'
        'Compliance, Risk & Legal'   -> 'compliance-risk-and-legal'
        'Retail & E-commerce'        -> 'retail-and-e-commerce'
    """
    text = label.lower().replace('&', 'and').replace(',', '')
    # Collapse any run of whitespace into a single hyphen.
    return '-'.join(text.split())


@click.command('seed-taxonomy')
@with_appcontext
def seed_taxonomy():
    """Idempotently upsert the canonical taxonomy tags (match on slug)."""
    from app.models.taxonomy import TaxonomyTag

    created = 0
    updated = 0
    unchanged = 0

    for axis, labels in TAXONOMY_AXES.items():
        for sort_order, label in enumerate(labels):
            slug = taxonomy_slug(label)
            tag = TaxonomyTag.query.filter_by(slug=slug).first()

            if tag is None:
                db.session.add(TaxonomyTag(
                    axis=axis,
                    label=label,
                    slug=slug,
                    sort_order=sort_order,
                ))
                created += 1
                click.echo(f'  + [{axis}] {label} ({slug})')
                continue

            changed = []
            for field, value in (
                ('axis', axis), ('label', label), ('sort_order', sort_order),
            ):
                if getattr(tag, field) != value:
                    setattr(tag, field, value)
                    changed.append(field)
            if changed:
                updated += 1
                click.echo(f'  ~ [{axis}] {label} ({", ".join(changed)})')
            else:
                unchanged += 1

    db.session.commit()
    total = sum(len(v) for v in TAXONOMY_AXES.values())
    click.echo('')
    click.echo(
        f'Seeded taxonomy: {created} created, {updated} updated, '
        f'{unchanged} unchanged (total {total} tags).'
    )


# Real engagements for the home-page showcase. Public-safe descriptions.
# Tags are referenced by exact canonical label and resolved to slugs.
WORK_DEMO_ITEMS = [
    {
        'title': 'CTAI / TruRender -- Render-to-Photo Pipeline',
        'description': (
            'We built a GPU-backed pipeline that turns raw architectural '
            'renders into photorealistic images on demand. Using diffusion '
            'models with depth- and edge-guided controls, the system '
            'preserves a design\u2019s exact geometry while adding '
            'lifelike lighting, materials, and atmosphere. The result lets '
            'the studio produce client-ready marketing imagery in minutes '
            'rather than commissioning costly manual photo-retouching.'
        ),
        'is_projected': False,
        'sort_order': 0,
        'tags': [
            'Architecture & Design',
            'Product & Service Delivery',
            'Marketing & Brand Management',
            'Immersive & Visualization',
            'Artificial Intelligence & Process Automation',
        ],
    },
    {
        'title': 'Global Arts Live -- Infrastructure & SharePoint Sync',
        'description': (
            'For a nonprofit performing-arts presenter, we modernized the '
            'back-office foundation that keeps programming and operations '
            'running. We stood up reliable networking and a SharePoint '
            'synchronization layer so staff across functions work from a '
            'single, always-current source of files and event data. The '
            'buildout replaced brittle manual hand-offs with dependable, '
            'automated infrastructure the team can trust.'
        ),
        'is_projected': False,
        'sort_order': 1,
        'tags': [
            'Nonprofit & Education',
            'Hospitality & Entertainment',
            'Operations & Workflow',
            'Infrastructure & Networking',
            'Applications & Integrations',
        ],
    },
    {
        'title': 'Havarti Risk -- Reserves Analysis & Reporting',
        'description': (
            'We partnered with an insurance-sector client to sharpen how '
            'loss reserves are analyzed and reported. By consolidating the '
            'underlying data and building repeatable analytical reporting, '
            'we gave the team clearer, faster visibility into reserve '
            'adequacy. The work strengthens both regulatory confidence and '
            'day-to-day decision-making around risk.'
        ),
        'is_projected': False,
        'sort_order': 2,
        'tags': [
            'Financial & Insurance Services',
            'Compliance, Risk & Legal',
            'Metrics & Reporting',
            'Data & Analytics',
        ],
    },
]


@click.command('seed-work-demo')
@with_appcontext
def seed_work_demo():
    """Idempotently seed real WorkItems (match on title) with tags."""
    from app.models.taxonomy import TaxonomyTag, WorkItem

    created = 0
    updated = 0
    unchanged = 0

    for entry in WORK_DEMO_ITEMS:
        # Resolve tag labels -> TaxonomyTag rows (must be seeded first).
        wanted_tags = []
        missing = []
        for label in entry['tags']:
            slug = taxonomy_slug(label)
            tag = TaxonomyTag.query.filter_by(slug=slug).first()
            if tag is None:
                missing.append(label)
            else:
                wanted_tags.append(tag)
        if missing:
            click.echo(
                f'  ! "{entry["title"]}" skipped -- missing tags '
                f'(run seed-taxonomy first): {", ".join(missing)}'
            )
            continue

        item = WorkItem.query.filter_by(title=entry['title']).first()
        if item is None:
            item = WorkItem(
                title=entry['title'],
                description=entry['description'],
                is_projected=entry['is_projected'],
                sort_order=entry['sort_order'],
            )
            item.tags = wanted_tags
            db.session.add(item)
            created += 1
            click.echo(f'  + {entry["title"]} ({len(wanted_tags)} tags)')
            continue

        changed = []
        for field in ('description', 'is_projected', 'sort_order'):
            if getattr(item, field) != entry[field]:
                setattr(item, field, entry[field])
                changed.append(field)
        if set(item.tags) != set(wanted_tags):
            item.tags = wanted_tags
            changed.append('tags')
        if changed:
            updated += 1
            click.echo(f'  ~ {entry["title"]} ({", ".join(changed)})')
        else:
            unchanged += 1

    db.session.commit()
    click.echo('')
    click.echo(
        f'Seeded work items: {created} created, {updated} updated, '
        f'{unchanged} unchanged (total {len(WORK_DEMO_ITEMS)}).'
    )


def register_cli(app):
    """Register CLI commands with the Flask app."""
    app.cli.add_command(user_cli)
    app.cli.add_command(client_cli)
    app.cli.add_command(resource_cli)
    app.cli.add_command(seed_taxonomy)
    app.cli.add_command(seed_work_demo)
