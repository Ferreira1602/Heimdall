"""app/blueprints/governance.py — governança de IA (consumo de tokens)."""
from flask import Blueprint, render_template, request, abort
from flask_login import login_required, current_user

from app.models import Client
from app.scoping import accessible_clients
from app.services.analytics import ai_products_detail, tokens_by_period

governance_bp = Blueprint("governance", __name__, url_prefix="/governance")


@governance_bp.route("/")
@login_required
def index():
    clients = accessible_clients()
    client_id = request.args.get("client_id", type=int)
    if not client_id and clients:
        client_id = clients[0].id
    selected = None
    products = []
    toks_periods, ai_cost = {}, {}
    if client_id:
        if not current_user.can_access(client_id):
            abort(403)
        from app.extensions import db
        selected = db.session.get(Client, client_id)
        products = ai_products_detail(client_id)
        toks_periods, ai_cost = tokens_by_period(client_id)
    return render_template("governance/index.html", clients=clients,
                           selected=selected, products=products,
                           periods=list(toks_periods.keys()),
                           token_series=list(toks_periods.values()),
                           cost_series=list(ai_cost.values()))
