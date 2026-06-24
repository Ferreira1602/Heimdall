"""app/blueprints/dashboard.py — visão geral de monitoramento dos clientes."""
from flask import Blueprint, render_template, request, abort
from flask_login import login_required, current_user

from app.models import Client, Subscription
from app.scoping import accessible_clients
from app.services.analytics import client_summary

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@login_required
def index():
    clients = accessible_clients()
    cards = []
    for c in clients:
        summ = client_summary(c.id)
        sub = c.current_subscription()
        cards.append({"client": c, "summary": summ, "sub": sub})
    # totais gerais
    total_cost = sum(c["summary"]["current_cost"] for c in cards)
    total_tokens = sum(c["summary"]["total_tokens"] for c in cards)
    total_est = sum(c["summary"]["est_cost"] for c in cards)
    return render_template("dashboard/index.html", cards=cards,
                           total_cost=total_cost, total_tokens=total_tokens,
                           total_est=total_est, n_clients=len(clients))


@dashboard_bp.route("/client/<int:client_id>")
@login_required
def client_view(client_id):
    if not current_user.can_access(client_id):
        abort(403)
    from app.extensions import db
    c = db.get_or_404(Client, client_id)
    summ = client_summary(client_id)
    sub = c.current_subscription()
    return render_template("dashboard/client.html", c=c, summary=summ, sub=sub)
