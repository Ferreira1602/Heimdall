"""
app/__init__.py — App factory do Heimdall.
"""
from flask import Flask, render_template

from config.settings import get_config
from app.extensions import db, login_manager, csrf


def create_app(config_name: str = "production") -> Flask:
    app = Flask(__name__)
    app.config.from_object(get_config(config_name))

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    # Blueprints
    from app.blueprints.auth import auth_bp
    from app.blueprints.dashboard import dashboard_bp
    from app.blueprints.clients import clients_bp
    from app.blueprints.providers import providers_bp
    from app.blueprints.products import products_bp
    from app.blueprints.governance import governance_bp
    from app.blueprints.finops import finops_bp
    from app.blueprints.subscriptions import subscriptions_bp
    from app.blueprints.schedules import schedules_bp
    from app.blueprints.exports import exports_bp
    from app.blueprints.api import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(clients_bp)
    app.register_blueprint(providers_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(governance_bp)
    app.register_blueprint(finops_bp)
    app.register_blueprint(subscriptions_bp)
    app.register_blueprint(schedules_bp)
    app.register_blueprint(exports_bp)
    app.register_blueprint(api_bp)

    # API REST usa Bearer token -> isenta de CSRF
    csrf.exempt(api_bp)

    # Helpers de template
    _register_helpers(app)

    # Error handlers
    @app.errorhandler(403)
    def _403(e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def _404(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def _500(e):
        db.session.rollback()
        return render_template("errors/500.html"), 500

    # Cria tabelas e admin inicial
    with app.app_context():
        db.create_all()
        _auto_migrate(app)
        _bootstrap_admin(app)

    return app


def _auto_migrate(app):
    """Migrações leves e idempotentes para bancos já existentes.

    db.create_all() não altera tabelas já criadas, então adicionamos aqui as
    colunas novas. Usa 'ADD COLUMN IF NOT EXISTS' (suportado pelo MariaDB);
    em SQLite verifica o pragma. Falhas são ignoradas para não impedir o boot.
    """
    from sqlalchemy import text
    dialect = db.engine.dialect.name
    cols = {
        "balance": "NUMERIC(14,2) NULL",
        "source": "VARCHAR(10) DEFAULT 'manual'",
        "external_ref": "VARCHAR(160) NULL",
    }
    try:
        if dialect in ("mysql", "mariadb"):
            for name, ddl in cols.items():
                try:
                    db.session.execute(text(
                        f"ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS {name} {ddl}"))
                except Exception:
                    db.session.rollback()
            db.session.commit()
        elif dialect == "sqlite":
            existing = {r[1] for r in db.session.execute(
                text("PRAGMA table_info(subscriptions)")).fetchall()}
            for name, ddl in cols.items():
                if name not in existing:
                    db.session.execute(text(
                        f"ALTER TABLE subscriptions ADD COLUMN {name} {ddl}"))
            db.session.commit()
    except Exception:
        db.session.rollback()


def _register_helpers(app):
    from app.models import PROVIDER_LABELS

    @app.context_processor
    def inject_globals():
        return {"PROVIDER_LABELS": PROVIDER_LABELS, "app_name": "Heimdall"}

    @app.template_filter("money")
    def money(v, cur="R$"):
        try:
            return f"{cur} {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except (TypeError, ValueError):
            return f"{cur} 0,00"

    @app.template_filter("num")
    def num(v):
        try:
            return f"{int(v):,}".replace(",", ".")
        except (TypeError, ValueError):
            return "0"


def _bootstrap_admin(app):
    from app.models import User
    email = app.config["BOOTSTRAP_ADMIN_EMAIL"]
    if not User.query.filter_by(email=email).first():
        u = User(name=app.config["BOOTSTRAP_ADMIN_NAME"], email=email, is_admin=True)
        u.set_password(app.config["BOOTSTRAP_ADMIN_PASS"])
        db.session.add(u)
        db.session.commit()
        app.logger.info("Admin inicial criado: %s", email)
