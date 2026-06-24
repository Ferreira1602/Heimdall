"""app/blueprints/exports.py — exportações para Excel (.xlsx)."""
from datetime import datetime

from flask import Blueprint, request, send_file, abort
from flask_login import login_required, current_user

from app.models import Client, PROVIDER_LABELS
from app.scoping import accessible_clients
from app.services.excel import build_workbook
from app.services.analytics import (billing_breakdown, ai_products_detail,
                                     client_summary)

exports_bp = Blueprint("exports", __name__, url_prefix="/exports")


def _send(buf, name):
    return send_file(buf, as_attachment=True, download_name=name,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@exports_bp.route("/client/<int:client_id>")
@login_required
def client_report(client_id):
    if not current_user.can_access(client_id):
        abort(403)
    from app.extensions import db
    c = db.get_or_404(Client, client_id)
    summ = client_summary(client_id)
    sub = c.current_subscription()

    resumo_rows = [
        ["Cliente", c.name],
        ["Custo do mês atual", summ["current_cost"]],
        ["Estimativa próximo mês", summ["est_cost"]],
        ["Tendência de custo (%)", summ["cost_trend"]],
        ["Total de tokens", summ["total_tokens"]],
        ["Custo de IA", summ["ai_cost"]],
        ["Contas de nuvem", summ["n_accounts"]],
        ["Produtos de IA", summ["n_products"]],
    ]
    if sub:
        resumo_rows += [
            ["Plano", sub.plan_name],
            ["Vigência início", sub.start_date.isoformat()],
            ["Vigência fim", sub.end_date.isoformat()],
            ["Créditos totais", float(sub.total_credits)],
            ["Créditos restantes", sub.remaining_credits],
        ]

    billing_rows = []
    for g in billing_breakdown(client_id):
        for it in g["items"]:
            billing_rows.append([
                PROVIDER_LABELS.get(it["provider"], it["provider"]),
                g["resource_type"], it["name"], it["group"], it["region"],
                it["period"], it["source"], round(it["cost"], 2), g["currency"],
            ])

    ia_rows = []
    for p in ai_products_detail(client_id):
        ia_rows.append([
            p["product"].name, p["product"].service, p["product"].model,
            p["total_tokens"], p["total_cost"], p["est_tokens"], p["est_cost"],
            f"{p['trend']}%",
        ])

    sheets = {
        "Resumo": {"headers": ["Indicador", "Valor"], "rows": resumo_rows},
        "Billing FinOps": {"headers": ["Provedor", "Tipo", "Recurso", "Grupo",
                                       "Região", "Período", "Origem", "Custo", "Moeda"],
                           "rows": billing_rows},
        "Consumo IA": {"headers": ["Produto", "Serviço", "Modelo", "Tokens",
                                   "Custo total", "Estim. tokens", "Estim. custo",
                                   "Tendência"], "rows": ia_rows},
    }
    buf = build_workbook(sheets)
    stamp = datetime.now().strftime("%Y%m%d")
    return _send(buf, f"heimdall_{c.slug}_{stamp}.xlsx")


@exports_bp.route("/dashboard")
@login_required
def dashboard_report():
    rows = []
    for c in accessible_clients():
        s = client_summary(c.id)
        sub = c.current_subscription()
        rows.append([
            c.name, s["current_cost"], s["est_cost"], f"{s['cost_trend']}%",
            s["total_tokens"], s["ai_cost"], s["n_accounts"], s["n_products"],
            sub.remaining_credits if sub else 0,
            sub.end_date.isoformat() if sub else "",
        ])
    sheets = {"Dashboard": {
        "headers": ["Cliente", "Custo atual", "Estimativa", "Tendência",
                    "Tokens", "Custo IA", "Contas", "Produtos",
                    "Créditos restantes", "Fim vigência"],
        "rows": rows}}
    buf = build_workbook(sheets)
    stamp = datetime.now().strftime("%Y%m%d")
    return _send(buf, f"heimdall_dashboard_{stamp}.xlsx")
