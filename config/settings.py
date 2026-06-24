"""
config/settings.py — Configuração do Heimdall por ambiente.

Lê variáveis de ambiente quando disponíveis; caso contrário usa defaults
seguros para o servidor local 10.250.128.114.
"""
import os
from urllib.parse import quote_plus

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


class BaseConfig:
    SECRET_KEY = os.environ.get("HEIMDALL_SECRET_KEY", "troque-esta-chave-em-producao-heimdall")

    # Chave de criptografia (Fernet) para credenciais de nuvem armazenadas.
    # Gere uma nova com: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    FERNET_KEY = os.environ.get("HEIMDALL_FERNET_KEY", "")

    # --- Banco de dados MySQL / MariaDB ---
    DB_USER = os.environ.get("HEIMDALL_DB_USER", "heimdall")
    DB_PASS = os.environ.get("HEIMDALL_DB_PASS", "Heimdall@2025!")
    DB_HOST = os.environ.get("HEIMDALL_DB_HOST", "127.0.0.1")
    DB_PORT = os.environ.get("HEIMDALL_DB_PORT", "3306")
    DB_NAME = os.environ.get("HEIMDALL_DB_NAME", "heimdall")

    # As credenciais são codificadas (URL-encode) porque a senha pode conter
    # caracteres reservados na URI, como "@" ou "!" (ex.: "Heimdall@2025!").
    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{quote_plus(DB_USER)}:{quote_plus(DB_PASS)}"
        f"@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_recycle": 280,
        "pool_pre_ping": True,
    }

    # Sessão / cookies
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    WTF_CSRF_TIME_LIMIT = None

    # Admin inicial (criado no primeiro boot)
    BOOTSTRAP_ADMIN_EMAIL = os.environ.get("HEIMDALL_ADMIN_EMAIL", "admin@heimdall.local")
    BOOTSTRAP_ADMIN_PASS = os.environ.get("HEIMDALL_ADMIN_PASS", "Heimdall@2025!")
    BOOTSTRAP_ADMIN_NAME = os.environ.get("HEIMDALL_ADMIN_NAME", "Administrador")


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SESSION_COOKIE_SECURE = False


class ProductionConfig(BaseConfig):
    DEBUG = False
    # O Apache encerra o TLS; mantemos False porque o WSGI recebe HTTP interno.
    SESSION_COOKIE_SECURE = False


CONFIG_MAP = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
}


def get_config(name: str = "production"):
    return CONFIG_MAP.get(name, ProductionConfig)
