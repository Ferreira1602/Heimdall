"""app/blueprints/auth.py — login, logout e gestão de usuários/permissões."""
from flask import (Blueprint, render_template, redirect, url_for, request, flash)
from flask_login import login_user, logout_user, login_required, current_user

from app.extensions import db
from app.models import User, Client, ClientPermission
from app.decorators import admin_required, audit

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and user.active and user.check_password(pw):
            login_user(user)
            audit("login", email)
            return redirect(url_for("dashboard.index"))
        flash("Credenciais inválidas ou usuário inativo.", "danger")
    return render_template("auth/login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    audit("logout", current_user.email)
    logout_user()
    return redirect(url_for("auth.login"))


# ───────────────────────── Gestão de usuários (admin) ─────────────────────────
@auth_bp.route("/users")
@admin_required
def users():
    return render_template("auth/users.html",
                           users=User.query.order_by(User.name).all(),
                           clients=Client.query.order_by(Client.name).all())


@auth_bp.route("/users/new", methods=["POST"])
@admin_required
def user_new():
    email = request.form.get("email", "").strip().lower()
    if User.query.filter_by(email=email).first():
        flash("E-mail já cadastrado.", "danger")
        return redirect(url_for("auth.users"))
    u = User(
        name=request.form.get("name", "").strip(),
        email=email,
        is_admin=bool(request.form.get("is_admin")),
    )
    u.set_password(request.form.get("password", "Mudar@123"))
    db.session.add(u)
    db.session.commit()
    audit("user_new", email)
    flash("Usuário criado.", "success")
    return redirect(url_for("auth.user_edit", user_id=u.id))


@auth_bp.route("/users/<int:user_id>", methods=["GET", "POST"])
@admin_required
def user_edit(user_id):
    u = db.get_or_404(User, user_id)
    if request.method == "POST":
        u.name = request.form.get("name", u.name).strip()
        u.is_admin = bool(request.form.get("is_admin"))
        u.active = bool(request.form.get("active"))
        new_pw = request.form.get("password", "").strip()
        if new_pw:
            u.set_password(new_pw)
        # Atualiza permissões por cliente
        ClientPermission.query.filter_by(user_id=u.id).delete()
        for c in Client.query.all():
            level = request.form.get(f"perm_{c.id}", "none")
            if level in ("read", "write"):
                db.session.add(ClientPermission(user_id=u.id, client_id=c.id, access=level))
        db.session.commit()
        audit("user_edit", u.email)
        flash("Usuário atualizado.", "success")
        return redirect(url_for("auth.users"))
    perms = {p.client_id: p.access for p in u.permissions}
    return render_template("auth/user_edit.html", u=u,
                           clients=Client.query.order_by(Client.name).all(),
                           perms=perms)


@auth_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        cur = request.form.get("current", "")
        new = request.form.get("new", "")
        if not current_user.check_password(cur):
            flash("Senha atual incorreta.", "danger")
        elif len(new) < 6:
            flash("A nova senha deve ter ao menos 6 caracteres.", "danger")
        else:
            current_user.set_password(new)
            db.session.commit()
            flash("Senha alterada com sucesso.", "success")
    return render_template("auth/profile.html")
