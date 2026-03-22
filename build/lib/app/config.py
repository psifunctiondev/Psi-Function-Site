import os


class BaseConfig:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///instance/dev.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    REDIS_URL = os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/0')
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    WTF_CSRF_ENABLED = os.getenv('WTF_CSRF_ENABLED', 'true').lower() == 'true'

class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SESSION_COOKIE_SECURE = False

class TestingConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False

class StagingConfig(BaseConfig):
    SESSION_COOKIE_SECURE = True

class ProductionConfig(BaseConfig):
    SESSION_COOKIE_SECURE = True

CONFIG_MAP = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'staging': StagingConfig,
    'production': ProductionConfig,
}

def get_config(name: str | None = None):
    resolved = name or os.getenv('FLASK_ENV_PROFILE', 'development')
    return CONFIG_MAP[resolved]
