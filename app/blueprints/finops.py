"""app/blueprints/finops.py — governança de nuvem / FinOps com drill-down."""
from flask import Blueprint, render_template, request, abort
from flask_login import login_required, current_user

from app.models import Client, CloudAccount
from app.scoping import accessible_clients
from app.services.analytics import (billing_by_period, billing_breakdown,
                                     client_summary)
from app.services.estimator import estimate_next

finops_bp = Blueprint("finops", __name__, url_prefix="/finops")


@finops_bp.route("/")
@login_required
def index():
    clients = accessible_clients()
    client_id = request.args.get("client_id", type=int)
    if not client_id and clients:
        client_id = clients[0].id
    period = request.args.get("period")

    selected = None
    summary = None
    breakdown = []
    periods, series = [], []
    accounts = []
    if client_id:
        if not current_user.can_access(client_id):
            abort(403)
        from app.extensions import db
        selected = db.session.get(Client, client_id)
        summary = client_summary(client_id)
        bp = billing_by_period(client_id)
        periods, series = list(bp.keys()), list(bp.values())
        if not period and periods:
            period = periods[-1]
        breakdown = billing_breakdown(client_id, period)
        accounts = CloudAccount.query.filter_by(client_id=client_id).all()

    return render_template("finops/index.html", clients=clients,
                           selected=selected, summary=summary,
                           breakdown=breakdown, periods=periods,
                           series=series, period=period, accounts=accounts,
                           est_next=estimate_next(series))
