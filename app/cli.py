"""Flask CLI commands for user and client management."""

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


def register_cli(app):
    """Register CLI commands with the Flask app."""
    app.cli.add_command(user_cli)
