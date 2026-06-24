"""app/blueprints/schedules.py — agendamentos de coleta periódica."""
from flask import (Blueprint, render_template, redirect, url_for, request, flash, abort)
from flask_login import login_required, current_user

from app.extensions import db
from app.models import CloudAccount, CollectionSchedule
from app.decorators import audit
from app.scoping import accessible_clients

schedules_bp = Blueprint("schedules", __name__, url_prefix="/schedules")


def _accessible_accounts():
    client_ids = [c.id for c in accessible_clients()]
    if not client_ids:
        return []
    return (CloudAccount.query
            .filter(CloudAccount.client_id.in_(client_ids))
            .order_by(CloudAccount.name).all())


@schedules_bp.route("/")
@login_required
def index():
    accounts = _accessible_accounts()
    acc_ids = [a.id for a in accounts]
    rows = []
    if acc_ids:
        scheds = (CollectionSchedule.query
                  .filter(CollectionSchedule.cloud_account_id.in_(acc_ids)).all())
        amap = {a.id: a for a in accounts}
        for s in scheds:
            rows.append({"sched": s, "account": amap.get(s.cloud_account_id)})
    return render_template("schedules/index.html", rows=rows, accounts=accounts)


@schedules_bp.route("/new", methods=["POST"])
@login_required
def new():
    acc_id = request.form.get("cloud_account_id", type=int)
    acc = db.get_or_404(CloudAccount, acc_id)
    if not current_user.can_write(acc.client_id):
        abort(403)
    s = CollectionSchedule(
        cloud_account_id=acc.id,
        frequency=request.form.get("frequency", "daily"),
        hour=request.form.get("hour", type=int) or 3,
        minute=request.form.get("minute", type=int) or 0,
        weekday=request.form.get("weekday", type=int) or 0,
        day_of_month=request.form.get("day_of_month", type=int) or 1,
        months_back=request.form.get("months_back", type=int) or 0,
        active=True,
    )
    db.session.add(s)
    db.session.commit()
    audit("schedule_new", f"{acc.name}/{s.frequency}")
    flash("Agendamento criado.", "success")
    return redirect(url_for("schedules.index"))


@schedules_bp.route("/<int:sched_id>/toggle", methods=["POST"])
@login_required
def toggle(sched_id):
    s = db.get_or_404(CollectionSchedule, sched_id)
    if not current_user.can_write(s.cloud_account.client_id):
        abort(403)
    s.active = not s.active
    db.session.commit()
    flash("Agendamento " + ("ativado." if s.active else "pausado."), "success")
    return redirect(url_for("schedules.index"))


@schedules_bp.route("/<int:sched_id>/delete", methods=["POST"])
@login_required
def delete(sched_id):
    s = db.get_or_404(CollectionSchedule, sched_id)
    if not current_user.can_write(s.cloud_account.client_id):
        abort(403)
    db.session.delete(s)
    db.session.commit()
    audit("schedule_delete", str(sched_id))
    flash("Agendamento removido.", "success")
    return redirect(url_for("schedules.index"))


@schedules_bp.route("/<int:sched_id>/run", methods=["POST"])
@login_required
def run_now(sched_id):
    s = db.get_or_404(CollectionSchedule, sched_id)
    if not current_user.can_write(s.cloud_account.client_id):
        abort(403)
    from app.services.collection import run_due_schedules
    results = run_due_schedules(force_account_id=s.cloud_account_id)
    ok = sum(1 for r in results if r.get("ok"))
    flash(f"Execução manual concluída: {ok}/{len(results)} conta(s) coletada(s). "
          f"{s.last_status or ''}", "success" if ok else "warning")
    return redirect(url_for("schedules.index"))
