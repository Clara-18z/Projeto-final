import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, "instance", "clinica_nexo.db")
DEFAULT_BACKUP_DIRECTORY = os.environ.get(
    "BACKUP_DIR",
    os.path.join(BASE_DIR, "instance", "backups"),
)


class Config:
    APP_ENV = os.environ.get("APP_ENV", "development")
    DEBUG = APP_ENV == "development" and os.environ.get("FLASK_DEBUG", "1").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    HOST = os.environ.get("HOST", "127.0.0.1")
    PORT = int(os.environ.get("PORT", "5000"))
    SECRET_KEY = os.environ.get("SECRET_KEY")
    ADMIN_INITIAL_PASSWORD = os.environ.get("ADMIN_INITIAL_PASSWORD")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{DATABASE_PATH}"
    )
    BACKUP_DIRECTORY = DEFAULT_BACKUP_DIRECTORY
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = APP_ENV == "production"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = APP_ENV == "production"
    REMEMBER_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SAMESITE = "Lax"
    WTF_CSRF_TIME_LIMIT = 3600
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
