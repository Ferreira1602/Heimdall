"""app/blueprints/clients.py — cadastro e visão de clientes."""
import re
from flask import (Blueprint, render_template, redirect, url_for, request, flash, abort)
from flask_login import login_required, current_user

from app.extensions import db
from app.models import Client, CloudAccount, AIProduct, Subscription
from app.decorators import admin_required, audit
from app.scoping import accessible_clients

clients_bp = Blueprint("clients", __name__, url_prefix="/clients")


def _slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:80] or "cliente"


@clients_bp.route("/")
@login_required
def index():
    return render_template("clients/index.html", clients=accessible_clients())


@clients_bp.route("/new", methods=["POST"])
@admin_required
def new():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Informe o nome do cliente.", "danger")
        return redirect(url_for("clients.index"))
    slug = _slugify(name)
    n = 1
    base = slug
    while Client.query.filter_by(slug=slug).first():
        n += 1
        slug = f"{base}-{n}"
    c = Client(name=name, slug=slug, notes=request.form.get("notes", ""))
    db.session.add(c)
    db.session.commit()
    audit("client_new", name)
    flash("Cliente criado.", "success")
    return redirect(url_for("clients.detail", client_id=c.id))


@clients_bp.route("/<int:client_id>")
@login_required
def detail(client_id):
    c = db.get_or_404(Client, client_id)
    if not current_user.can_access(client_id):
        abort(403)
    return render_template("clients/detail.html", c=c,
                           can_write=current_user.can_write(client_id))


@clients_bp.route("/<int:client_id>/edit", methods=["POST"])
@admin_required
def edit(client_id):
    c = db.get_or_404(Client, client_id)
    c.name = request.form.get("name", c.name).strip()
    c.notes = request.form.get("notes", c.notes)
    c.active = bool(request.form.get("active"))
    db.session.commit()
    audit("client_edit", c.name)
    flash("Cliente atualizado.", "success")
    return redirect(url_for("clients.detail", client_id=c.id))
