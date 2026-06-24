"""app/scoping.py — helpers de escopo de clientes por usuário."""
from flask_login import current_user
from app.models import Client


def accessible_clients():
    """Lista de clientes que o usuário atual pode visualizar."""
    q = Client.query.filter_by(active=True).order_by(Client.name)
    if current_user.is_admin:
        return q.all()
    ids = current_user.allowed_client_ids()
    if not ids:
        return []
    return q.filter(Client.id.in_(ids)).all()
