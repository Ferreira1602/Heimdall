"""app/blueprints/products.py — cadastro de produtos de IA por conta de nuvem."""
from datetime import date

from flask import (Blueprint, render_template, redirect, url_for, request, flash, abort)
from flask_login import login_required, current_user

from app.extensions import db
from app.models import CloudAccount, AIProduct, TokenUsage
from app.decorators import audit

products_bp = Blueprint("products", __name__, url_prefix="/products")


@products_bp.route("/account/<int:account_id>/new", methods=["POST"])
@login_required
def new(account_id):
    acc = db.get_or_404(CloudAccount, account_id)
    if not current_user.can_write(acc.client_id):
        abort(403)
    p = AIProduct(
        cloud_account_id=acc.id,
        name=request.form.get("name", "Produto IA").strip(),
        service=request.form.get("service", "").strip(),
        model=request.form.get("model", "").strip(),
        price_input=float(request.form.get("price_input", 0) or 0),
        price_output=float(request.form.get("price_output", 0) or 0),
        currency=request.form.get("currency", "USD"),
    )
    db.session.add(p)
    db.session.commit()
    audit("product_new", p.name)
    flash("Produto de IA cadastrado.", "success")
    return redirect(url_for("providers.index", client_id=acc.client_id))


@products_bp.route("/<int:product_id>/edit", methods=["POST"])
@login_required
def edit(product_id):
    p = db.get_or_404(AIProduct, product_id)
    if not current_user.can_write(p.cloud_account.client_id):
        abort(403)
    p.name = request.form.get("name", p.name).strip()
    p.service = request.form.get("service", p.service)
    p.model = request.form.get("model", p.model)
    p.price_input = float(request.form.get("price_input", p.price_input) or 0)
    p.price_output = float(request.form.get("price_output", p.price_output) or 0)
    p.currency = request.form.get("currency", p.currency)
    p.active = bool(request.form.get("active"))
    db.session.commit()
    audit("product_edit", p.name)
    flash("Produto atualizado.", "success")
    return redirect(url_for("providers.index", client_id=p.cloud_account.client_id))


@products_bp.route("/<int:product_id>/usage", methods=["POST"])
@login_required
def manual_usage(product_id):
    """Lançamento manual de consumo de tokens de um período."""
    p = db.get_or_404(AIProduct, product_id)
    if not current_user.can_write(p.cloud_account.client_id):
        abort(403)
    period = request.form.get("period") or date.today().strftime("%Y-%m")
    inp = int(request.form.get("input_tokens", 0) or 0)
    out = int(request.form.get("output_tokens", 0) or 0)
    calls = int(request.form.get("calls", 0) or 0)
    # custo calculado pelo preço por 1K tokens, se informado
    cost = (inp / 1000.0) * float(p.price_input or 0) + (out / 1000.0) * float(p.price_output or 0)
    if request.form.get("cost"):
        cost = float(request.form.get("cost"))
    TokenUsage.query.filter_by(product_id=p.id, period=period, source="manual").delete()
    db.session.add(TokenUsage(product_id=p.id, period=period, source="manual",
                              input_tokens=inp, output_tokens=out, calls=calls, cost=cost))
    db.session.commit()
    flash("Consumo de tokens lançado.", "success")
    return redirect(url_for("providers.index", client_id=p.cloud_account.client_id))
