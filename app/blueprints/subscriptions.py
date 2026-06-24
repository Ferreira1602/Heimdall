"""app/blueprints/subscriptions.py — assinaturas dos clientes (vigência/créditos)."""
from datetime import datetime, date

from flask import (Blueprint, render_template, redirect, url_for, request, flash, abort)
from flask_login import login_required, current_user

from app.extensions import db
from app.models import Client, Subscription
from app.decorators import admin_required, audit
from app.scoping import accessible_clients

subscriptions_bp = Blueprint("subscriptions", __name__, url_prefix="/subscriptions")


def _pdate(s):
    return datetime.strptime(s, "%Y-%m-%d").date() if s else None


@subscriptions_bp.route("/")
@login_required
def index():
    clients = accessible_clients()
    rows = []
    for c in clients:
        for s in c.subscriptions:
            rows.append({"client": c, "sub": s})
    rows.sort(key=lambda r: r["sub"].end_date)
    return render_template("subscriptions/index.html", rows=rows, clients=clients)


@subscriptions_bp.route("/new", methods=["POST"])
@admin_required
def new():
    client_id = request.form.get("client_id", type=int)
    c = db.get_or_404(Client, client_id)
    try:
        start = _pdate(request.form.get("start_date"))
        end = _pdate(request.form.get("end_date"))
        if not start or not end:
            flash("Informe início e fim da vigência (AAAA-MM-DD).", "danger")
            return redirect(url_for("subscriptions.index"))
        s = Subscription(
            client_id=c.id,
            plan_name=request.form.get("plan_name", "Padrão"),
            start_date=start,
            end_date=end,
            total_credits=float(request.form.get("total_credits", 0) or 0),
            used_credits=float(request.form.get("used_credits", 0) or 0),
            currency=request.form.get("currency", "BRL"),
        )
        db.session.add(s)
        db.session.commit()
        audit("subscription_new", c.name)
        flash("Assinatura cadastrada.", "success")
    except (TypeError, ValueError):
        db.session.rollback()
        flash("Datas inválidas. Use o formato AAAA-MM-DD.", "danger")
    except Exception as e:  # noqa: BLE001 — surface DB errors instead of failing silently
        db.session.rollback()
        flash(f"Não foi possível salvar a assinatura: {e}", "danger")
    return redirect(url_for("subscriptions.index"))


@subscriptions_bp.route("/<int:sub_id>/edit", methods=["POST"])
@admin_required
def edit(sub_id):
    s = db.get_or_404(Subscription, sub_id)
    s.plan_name = request.form.get("plan_name", s.plan_name)
    s.start_date = _pdate(request.form.get("start_date")) or s.start_date
    s.end_date = _pdate(request.form.get("end_date")) or s.end_date
    s.total_credits = float(request.form.get("total_credits", s.total_credits) or 0)
    s.used_credits = float(request.form.get("used_credits", s.used_credits) or 0)
    s.currency = request.form.get("currency", s.currency)
    db.session.commit()
    audit("subscription_edit", str(sub_id))
    flash("Assinatura atualizada.", "success")
    return redirect(url_for("subscriptions.index"))
