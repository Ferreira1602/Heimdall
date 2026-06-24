"""
app/models.py — Modelos de dados do Heimdall (MySQL/MariaDB).

Entidades:
  User                 — usuários do sistema
  ClientPermission     — permissão de um usuário sobre um cliente (read/write)
  Client               — cliente final monitorado
  Subscription         — assinatura do cliente (vigência + créditos)
  CloudAccount         — conta de provedor de nuvem vinculada a um cliente
  AIProduct            — produto/serviço de IA cadastrado numa conta de nuvem
  TokenUsage           — consumo de tokens de IA (eventos/agregados)
  BillingRecord        — registro de billing FinOps por recurso/mês
  AuditLog             — trilha de auditoria de ações
"""
from datetime import datetime, date, timezone

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db, login_manager

PROVIDERS = ["ibm", "aws", "oracle", "google", "azure"]
PROVIDER_LABELS = {
    "ibm": "IBM Cloud",
    "aws": "AWS",
    "oracle": "Oracle Cloud",
    "google": "Google Cloud",
    "azure": "Microsoft Azure",
}


def _utcnow():
    return datetime.now(timezone.utc)


# ───────────────────────────── Usuários / Permissões ──────────────────────────
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(180), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow)

    permissions = db.relationship(
        "ClientPermission", back_populates="user",
        cascade="all, delete-orphan",
    )

    def set_password(self, raw: str):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    # Flask-Login usa is_active
    @property
    def is_active(self):
        return self.active

    def can_access(self, client_id: int) -> bool:
        if self.is_admin:
            return True
        return any(p.client_id == client_id for p in self.permissions)

    def can_write(self, client_id: int) -> bool:
        if self.is_admin:
            return True
        return any(
            p.client_id == client_id and p.access == "write"
            for p in self.permissions
        )

    def allowed_client_ids(self):
        return [p.client_id for p in self.permissions]


class ClientPermission(db.Model):
    __tablename__ = "client_permissions"
    __table_args__ = (db.UniqueConstraint("user_id", "client_id", name="uq_user_client"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    access = db.Column(db.String(10), default="read", nullable=False)  # read | write

    user = db.relationship("User", back_populates="permissions")
    client = db.relationship("Client", back_populates="permissions")


# ───────────────────────────── Clientes / Assinatura ──────────────────────────
class Client(db.Model):
    __tablename__ = "clients"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    slug = db.Column(db.String(80), unique=True, nullable=False)
    notes = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow)

    permissions = db.relationship("ClientPermission", back_populates="client",
                                  cascade="all, delete-orphan")
    subscriptions = db.relationship("Subscription", back_populates="client",
                                    cascade="all, delete-orphan", order_by="Subscription.start_date")
    cloud_accounts = db.relationship("CloudAccount", back_populates="client",
                                     cascade="all, delete-orphan")

    def current_subscription(self):
        today = date.today()
        for s in self.subscriptions:
            if s.start_date <= today <= s.end_date:
                return s
        return self.subscriptions[-1] if self.subscriptions else None


class Subscription(db.Model):
    __tablename__ = "subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    plan_name = db.Column(db.String(120), default="Padrão")
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    total_credits = db.Column(db.Numeric(14, 2), default=0)
    used_credits = db.Column(db.Numeric(14, 2), default=0)
    # Saldo informado diretamente pelo provedor (sem cálculo). NULL = lançamento
    # manual, em que o saldo é total - usado.
    balance = db.Column(db.Numeric(14, 2), nullable=True)
    currency = db.Column(db.String(8), default="BRL")
    source = db.Column(db.String(10), default="manual")   # manual | api
    external_ref = db.Column(db.String(160), nullable=True)  # id da assinatura no provedor
    created_at = db.Column(db.DateTime, default=_utcnow)

    client = db.relationship("Client", back_populates="subscriptions")

    @property
    def remaining_credits(self):
        # Reflete o saldo da API quando disponível; só calcula para lançamento manual.
        if self.balance is not None:
            return float(self.balance)
        return float(self.total_credits or 0) - float(self.used_credits or 0)

    @property
    def days_remaining(self):
        return (self.end_date - date.today()).days

    @property
    def is_active(self):
        return self.start_date <= date.today() <= self.end_date


# ───────────────────────────── Contas de Nuvem ────────────────────────────────
class CloudAccount(db.Model):
    __tablename__ = "cloud_accounts"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    provider = db.Column(db.String(20), nullable=False)  # ibm/aws/oracle/google/azure
    name = db.Column(db.String(160), nullable=False)
    account_ref = db.Column(db.String(180))   # account_id / subscription_id / tenancy / project_id
    region = db.Column(db.String(60))
    credentials_enc = db.Column(db.Text)       # JSON criptografado (Fernet)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow)

    client = db.relationship("Client", back_populates="cloud_accounts")
    ai_products = db.relationship("AIProduct", back_populates="cloud_account",
                                  cascade="all, delete-orphan")
    billing_records = db.relationship("BillingRecord", back_populates="cloud_account",
                                      cascade="all, delete-orphan")

    @property
    def provider_label(self):
        return PROVIDER_LABELS.get(self.provider, self.provider)


# ───────────────────────────── Produtos de IA ─────────────────────────────────
class AIProduct(db.Model):
    __tablename__ = "ai_products"

    id = db.Column(db.Integer, primary_key=True)
    cloud_account_id = db.Column(db.Integer, db.ForeignKey("cloud_accounts.id"), nullable=False)
    name = db.Column(db.String(160), nullable=False)
    service = db.Column(db.String(120))   # ex: watsonx-orchestrate, bedrock, vertex-ai
    model = db.Column(db.String(120))     # ex: llama-3-70b, gpt-4o, gemini-1.5-pro
    price_input = db.Column(db.Numeric(14, 8), default=0)   # custo por 1K tokens de entrada
    price_output = db.Column(db.Numeric(14, 8), default=0)  # custo por 1K tokens de saída
    currency = db.Column(db.String(8), default="USD")
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow)

    cloud_account = db.relationship("CloudAccount", back_populates="ai_products")
    usages = db.relationship("TokenUsage", back_populates="product",
                             cascade="all, delete-orphan")


class TokenUsage(db.Model):
    __tablename__ = "token_usage"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("ai_products.id"), nullable=False)
    period = db.Column(db.String(7), index=True)   # YYYY-MM (agregado mensal)
    ts = db.Column(db.DateTime, default=_utcnow)
    input_tokens = db.Column(db.BigInteger, default=0)
    output_tokens = db.Column(db.BigInteger, default=0)
    calls = db.Column(db.BigInteger, default=0)
    cost = db.Column(db.Numeric(14, 6), default=0)
    source = db.Column(db.String(30), default="manual")  # manual | api

    product = db.relationship("AIProduct", back_populates="usages")

    @property
    def total_tokens(self):
        return (self.input_tokens or 0) + (self.output_tokens or 0)


# ───────────────────────────── Billing / FinOps ───────────────────────────────
class BillingRecord(db.Model):
    __tablename__ = "billing_records"

    id = db.Column(db.Integer, primary_key=True)
    cloud_account_id = db.Column(db.Integer, db.ForeignKey("cloud_accounts.id"), nullable=False)
    period = db.Column(db.String(7), index=True)   # YYYY-MM
    resource_type = db.Column(db.String(160))
    resource_name = db.Column(db.String(255))
    resource_group = db.Column(db.String(160))
    region = db.Column(db.String(60))
    cost = db.Column(db.Numeric(14, 4), default=0)
    currency = db.Column(db.String(8), default="USD")
    source = db.Column(db.String(30), default="manual")  # manual | api

    cloud_account = db.relationship("CloudAccount", back_populates="billing_records")


# ─────────────────────────── Agendamento de coleta ────────────────────────────
class CollectionSchedule(db.Model):
    __tablename__ = "collection_schedules"

    id = db.Column(db.Integer, primary_key=True)
    cloud_account_id = db.Column(db.Integer, db.ForeignKey("cloud_accounts.id"), nullable=False)
    frequency = db.Column(db.String(10), default="daily")   # daily | weekly | monthly
    hour = db.Column(db.Integer, default=3)                  # hora do dia (0-23)
    minute = db.Column(db.Integer, default=0)
    weekday = db.Column(db.Integer, default=0)               # 0=segunda (para weekly)
    day_of_month = db.Column(db.Integer, default=1)          # 1-28 (para monthly)
    months_back = db.Column(db.Integer, default=1)           # períodos anteriores a coletar
    active = db.Column(db.Boolean, default=True, nullable=False)
    last_run = db.Column(db.DateTime, nullable=True)
    last_status = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow)

    cloud_account = db.relationship("CloudAccount")

    FREQ_LABELS = {"daily": "Diária", "weekly": "Semanal", "monthly": "Mensal"}
    WEEKDAYS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]

    @property
    def freq_label(self):
        return self.FREQ_LABELS.get(self.frequency, self.frequency)

    def schedule_label(self):
        hm = f"{self.hour:02d}:{self.minute:02d}"
        if self.frequency == "daily":
            return f"Todo dia às {hm}"
        if self.frequency == "weekly":
            return f"Toda {self.WEEKDAYS[self.weekday % 7]} às {hm}"
        return f"Dia {self.day_of_month} de cada mês às {hm}"


# ───────────────────────────── Auditoria ──────────────────────────────────────
class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.String(120))
    detail = db.Column(db.String(500))
    ts = db.Column(db.DateTime, default=_utcnow)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
