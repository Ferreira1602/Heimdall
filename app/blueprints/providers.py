"""app/blueprints/providers.py — contas de provedores de nuvem e coleta."""
import json
from datetime import date

from flask import (Blueprint, render_template, redirect, url_for, request, flash, abort)
from flask_login import login_required, current_user

from app.extensions import db
from app.models import Client, CloudAccount, BillingRecord, AIProduct, TokenUsage, PROVIDERS, PROVIDER_LABELS
from app.crypto import encrypt, decrypt
from app.decorators import audit
from app.services.collectors import get_collector, CollectorError

providers_bp = Blueprint("providers", __name__, url_prefix="/providers")


@providers_bp.route("/client/<int:client_id>")
@login_required
def index(client_id):
    if not current_user.can_access(client_id):
        abort(403)
    c = db.get_or_404(Client, client_id)
    today = date.today()
    years = list(range(today.year, today.year - 8, -1))  # ano atual e 7 anteriores
    months = [(f"{m:02d}", MONTHS_PT[m - 1]) for m in range(1, 13)]
    return render_template("providers/index.html", c=c, providers=PROVIDERS,
                           labels=PROVIDER_LABELS,
                           can_write=current_user.can_write(client_id),
                           years=years, months=months,
                           cur_year=today.year, cur_month=f"{today.month:02d}")


MONTHS_PT = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
             "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]


@providers_bp.route("/client/<int:client_id>/new", methods=["POST"])
@login_required
def new(client_id):
    if not current_user.can_write(client_id):
        flash("Acesso somente leitura.", "danger")
        abort(403)
    provider = request.form.get("provider")
    if provider not in PROVIDERS:
        flash("Provedor inválido.", "danger")
        return redirect(url_for("providers.index", client_id=client_id))
    creds = _collect_credentials(provider, request.form)
    acc = CloudAccount(
        client_id=client_id, provider=provider,
        name=request.form.get("name", PROVIDER_LABELS[provider]).strip(),
        account_ref=request.form.get("account_ref", "").strip(),
        region=request.form.get("region", "").strip(),
        credentials_enc=encrypt(json.dumps(creds)),
    )
    db.session.add(acc)
    db.session.commit()
    audit("cloudaccount_new", f"{provider}/{acc.name}")
    flash("Conta de nuvem cadastrada.", "success")
    return redirect(url_for("providers.index", client_id=client_id))


@providers_bp.route("/account/<int:account_id>/edit", methods=["POST"])
@login_required
def edit(account_id):
    acc = db.get_or_404(CloudAccount, account_id)
    if not current_user.can_write(acc.client_id):
        abort(403)
    acc.name = request.form.get("name", acc.name).strip()
    acc.account_ref = request.form.get("account_ref", acc.account_ref).strip()
    acc.region = request.form.get("region", acc.region).strip()
    acc.active = bool(request.form.get("active"))
    creds = _collect_credentials(acc.provider, request.form)
    if any(creds.values()):  # só sobrescreve se algo foi informado
        acc.credentials_enc = encrypt(json.dumps(creds))
    db.session.commit()
    audit("cloudaccount_edit", acc.name)
    flash("Conta atualizada.", "success")
    return redirect(url_for("providers.index", client_id=acc.client_id))


def _month_range(p_from, p_to, cap=36):
    from app.services.collection import month_range
    return month_range(p_from, p_to, cap)


@providers_bp.route("/account/<int:account_id>/collect", methods=["POST"])
@login_required
def collect(account_id):
    acc = db.get_or_404(CloudAccount, account_id)
    if not current_user.can_write(acc.client_id):
        abort(403)
    today = date.today().strftime("%Y-%m")

    def _compose(prefix, fallback):
        y = request.form.get(f"{prefix}_year")
        m = request.form.get(f"{prefix}_month")
        if y and m:
            return f"{int(y):04d}-{int(m):02d}"
        return fallback

    p_from = _compose("from", request.form.get("period_from") or request.form.get("period") or today)
    p_to = _compose("to", request.form.get("period_to") or None) or p_from
    periods = _month_range(p_from, p_to)
    from app.services.collection import collect_account
    try:
        res = collect_account(acc, periods)
        audit("collect", f"{acc.provider}/{p_from}..{p_to}")
        rng = p_from if p_from == p_to else f"{p_from} a {p_to}"
        sub_msg = f" {res['subscriptions']} assinatura(s) sincronizada(s)." if res["subscriptions"] else ""
        flash(f"Coleta concluída ({rng}): {res['billing']} registros de billing, "
              f"{res['ai']} serviços de IA.{sub_msg}", "success")
    except CollectorError as e:
        flash(f"Coleta automática indisponível: {e} Você pode lançar os valores manualmente.",
              "warning")
    except Exception as e:  # noqa
        flash(f"Erro inesperado na coleta: {e}", "danger")
    return redirect(url_for("providers.index", client_id=acc.client_id))


@providers_bp.route("/account/<int:account_id>/manual-billing", methods=["POST"])
@login_required
def manual_billing(account_id):
    acc = db.get_or_404(CloudAccount, account_id)
    if not current_user.can_write(acc.client_id):
        abort(403)
    db.session.add(BillingRecord(
        cloud_account_id=acc.id,
        period=request.form.get("period") or date.today().strftime("%Y-%m"),
        source="manual",
        resource_type=request.form.get("resource_type", "Recurso"),
        resource_name=request.form.get("resource_name", ""),
        resource_group=request.form.get("resource_group", ""),
        region=request.form.get("region", acc.region),
        cost=float(request.form.get("cost", 0) or 0),
        currency=request.form.get("currency", "BRL")))
    db.session.commit()
    flash("Lançamento manual de billing registrado.", "success")
    return redirect(url_for("providers.index", client_id=acc.client_id))


def _collect_credentials(provider, form):
    """Monta o dict de credenciais conforme o provedor."""
    fields = {
        "ibm": ["apikey"],
        "aws": ["access_key", "secret_key", "session_token"],
        "azure": ["tenant_id", "client_id", "client_secret"],
        "oracle": ["user_ocid", "tenancy_ocid", "fingerprint", "private_key"],
        "google": ["service_account_json", "bq_dataset", "bq_table"],
    }.get(provider, [])
    return {f: form.get(f"cred_{f}", "").strip() for f in fields}
