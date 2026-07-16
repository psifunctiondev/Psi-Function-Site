from flask import Flask
from markupsafe import Markup

from .blueprints.health.routes import bp as health_bp
from .config import get_config
from .extensions import db, login_manager, migrate

# Theme switcher icons (lucide-style 24×24 SVGs, stroke="currentColor").
# Inlined here so the template can call {{ theme_icon('auto') }} and the
# SVG inherits the surrounding text color via currentColor.
THEME_ICONS: dict[str, str] = {
    'auto': (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true" class="theme-icon theme-icon--auto">'
        '<circle cx="12" cy="12" r="10"/>'
        '<path d="M12 6v6l4 2"/>'
        '</svg>'
    ),
    'day': (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true" class="theme-icon theme-icon--day">'
        '<circle cx="12" cy="12" r="4"/>'
        '<path d="M12 2v2"/><path d="M12 20v2"/>'
        '<path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/>'
        '<path d="M2 12h2"/><path d="M20 12h2"/>'
        '<path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>'
        '</svg>'
    ),
    'twilight': (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true" class="theme-icon theme-icon--twilight">'
        '<path d="M12 10V2"/>'
        '<path d="m4.93 10.93 1.41 1.41"/>'
        '<path d="M2 18h2"/><path d="M20 18h2"/>'
        '<path d="m19.07 10.93-1.41 1.41"/>'
        '<path d="M22 22H2"/>'
        '<path d="m16 6-4 4-4-4"/>'
        '<path d="M16 18a4 4 0 0 0-8 0"/>'
        '</svg>'
    ),
    'night': (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true" class="theme-icon theme-icon--night">'
        # The moon path is a single uninterrupted d-string; splitting it would break the SVG.
        '<path d="M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6 6 0 0 0 8.268 8.268c.344-.215.825-.004.803.401"/>'  # noqa: E501
        '</svg>'
    ),
}


def theme_icon(name: str) -> Markup:
    """Return inline SVG markup for a theme icon by name (auto/day/twilight/night).

    Wrapped in Markup so Jinja's autoescape does not HTML-encode the angle
    brackets — these are intentional SVG elements, not user text.
    """
    return Markup(THEME_ICONS.get(name, THEME_ICONS['auto']))


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(get_config(config_name))

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # Eager model imports so every db.Model subclass registers with
    # db.metadata before db.create_all() runs (tests) or before Alembic
    # autogenerate walks the metadata (deploys).
    from . import models  # noqa: F401  (side-effect import)
    from .blueprints.admin.routes import admin_bp
    from .blueprints.api.routes import api_bp
    from .blueprints.auth.routes import auth_bp
    from .blueprints.portal.routes import portal_bp
    from .blueprints.public.routes import public_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)     # Routes use /p/ prefix directly
    app.register_blueprint(portal_bp)   # Routes use /p/ prefix directly
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(health_bp)

    # Update login redirect to portal login
    login_manager.login_view = 'auth.login'

    # Register CLI commands
    from .cli import register_cli
    register_cli(app)

    # Register theme_icon as a Jinja global so site_header.html can inline
    # the lucide SVGs in the theme switcher.
    app.jinja_env.globals['theme_icon'] = theme_icon

    return app
