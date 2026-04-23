import os

_basedir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


class BaseConfig:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret')
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URL',
        f'sqlite:///{os.path.join(_basedir, "instance", "dev.db")}',
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    REDIS_URL = os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/0')
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    WTF_CSRF_ENABLED = os.getenv('WTF_CSRF_ENABLED', 'true').lower() == 'true'

class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SESSION_COOKIE_SECURE = False

class TestingConfig(BaseConfig):
    """Deployed testing environment (testing.psifunction.com).

    Uses DATABASE_URL from app.env — same as staging/production.
    """
    SESSION_COOKIE_SECURE = True

class StagingConfig(BaseConfig):
    SESSION_COOKIE_SECURE = True

class ProductionConfig(BaseConfig):
    SESSION_COOKIE_SECURE = True

class PytestConfig(BaseConfig):
    """In-process test runner config — no real database needed."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False

CONFIG_MAP = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'staging': StagingConfig,
    'production': ProductionConfig,
    'pytest': PytestConfig,
}

def get_config(name: str | None = None):
    resolved = name or os.getenv('FLASK_ENV_PROFILE', 'development')
    return CONFIG_MAP[resolved]
