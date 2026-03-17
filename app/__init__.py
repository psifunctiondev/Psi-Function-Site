from flask import Flask
from .config import get_config
from .extensions import db, migrate, login_manager
from app.blueprints.health.routes import bp as health_bp

def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(get_config(config_name))

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    from .blueprints.public.routes import public_bp
    from .blueprints.auth.routes import auth_bp
    from .blueprints.portal.routes import portal_bp
    from .blueprints.api.routes import api_bp
    from .blueprints.admin.routes import admin_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(portal_bp, url_prefix='/portal')
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(health_bp)

    return app
