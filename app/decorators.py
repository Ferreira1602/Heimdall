"""app/decorators.py — controle de acesso por papel e por cliente."""
from functools import wraps
from flask import abort, request, redirect, url_for, flash
from flask_login import current_user

from app.extensions import db
from app.models import AuditLog


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return wrapper


def client_read_required(param="client_id"):
    """Exige que o usuário tenha leitura no cliente identificado por <param>."""
    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            cid = kwargs.get(param) or request.args.get(param) or request.view_args.get(param)
            if cid is None:
                abort(400)
            if not current_user.can_access(int(cid)):
                abort(403)
            return f(*args, **kwargs)
        return wrapper
    return deco


def client_write_required(param="client_id"):
    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            cid = kwargs.get(param) or request.args.get(param) or request.view_args.get(param)
            if cid is None:
                abort(400)
            if not current_user.can_write(int(cid)):
                flash("Você tem acesso somente leitura a este cliente.", "danger")
                abort(403)
            return f(*args, **kwargs)
        return wrapper
    return deco


def audit(action: str, detail: str = ""):
    try:
        uid = current_user.id if current_user.is_authenticated else None
        db.session.add(AuditLog(user_id=uid, action=action, detail=detail[:500]))
        db.session.commit()
    except Exception:
        db.session.rollback()
