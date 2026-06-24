"""
app/services/analytics.py — agregações de consumo e custo por cliente.

Centraliza as consultas usadas por dashboard, FinOps e governança.
"""
from collections import defaultdict, OrderedDict

from sqlalchemy import func

from app.extensions import db
from app.models import (Client, CloudAccount, AIProduct, TokenUsage, BillingRecord)
from app.services.estimator import estimate_next, trend_pct


def _account_ids(client_id):
    return [a.id for a in CloudAccount.query.filter_by(client_id=client_id).all()]


def billing_by_period(client_id):
    """{ 'YYYY-MM': custo_total } ordenado cronologicamente."""
    ids = _account_ids(client_id)
    if not ids:
        return OrderedDict()
    rows = (db.session.query(BillingRecord.period,
                             func.sum(BillingRecord.cost))
            .filter(BillingRecord.cloud_account_id.in_(ids))
            .group_by(BillingRecord.period)
            .order_by(BillingRecord.period).all())
    return OrderedDict((p, float(c or 0)) for p, c in rows)


def billing_breakdown(client_id, period=None):
    """Detalhamento de recursos para drill-down de custos."""
    ids = _account_ids(client_id)
    if not ids:
        return []
    q = BillingRecord.query.filter(BillingRecord.cloud_account_id.in_(ids))
    if period:
        q = q.filter_by(period=period)
    records = q.all()
    # Agrupa por (provider, resource_type)
    groups = defaultdict(lambda: {"cost": 0.0, "items": [], "currency": "USD"})
    acc_map = {a.id: a for a in CloudAccount.query.filter(CloudAccount.id.in_(ids)).all()}
    for r in records:
        acc = acc_map.get(r.cloud_account_id)
        key = (acc.provider if acc else "?", r.resource_type or "outros")
        g = groups[key]
        g["cost"] += float(r.cost or 0)
        g["currency"] = r.currency or "USD"
        g["items"].append({
            "name": r.resource_name, "group": r.resource_group,
            "region": r.region, "cost": float(r.cost or 0),
            "period": r.period, "source": r.source,
            "provider": acc.provider if acc else "?",
        })
    out = []
    for (provider, rtype), g in groups.items():
        g["items"].sort(key=lambda x: x["cost"], reverse=True)
        out.append({"provider": provider, "resource_type": rtype,
                    "cost": round(g["cost"], 2), "currency": g["currency"],
                    "count": len(g["items"]), "items": g["items"]})
    out.sort(key=lambda x: x["cost"], reverse=True)
    return out


def tokens_by_period(client_id):
    """{ 'YYYY-MM': total_tokens } e custo de IA por período."""
    ids = _account_ids(client_id)
    if not ids:
        return OrderedDict(), OrderedDict()
    prod_ids = [p.id for p in AIProduct.query
                .filter(AIProduct.cloud_account_id.in_(ids)).all()]
    if not prod_ids:
        return OrderedDict(), OrderedDict()
    rows = (db.session.query(
        TokenUsage.period,
        func.sum(TokenUsage.input_tokens + TokenUsage.output_tokens),
        func.sum(TokenUsage.cost))
        .filter(TokenUsage.product_id.in_(prod_ids))
        .group_by(TokenUsage.period)
        .order_by(TokenUsage.period).all())
    toks = OrderedDict((p, int(t or 0)) for p, t, c in rows)
    cost = OrderedDict((p, float(c or 0)) for p, t, c in rows)
    return toks, cost


def ai_products_detail(client_id):
    """Lista produtos de IA com totais e estimativa por produto."""
    ids = _account_ids(client_id)
    out = []
    for prod in AIProduct.query.filter(AIProduct.cloud_account_id.in_(ids)).all():
        usages = sorted(prod.usages, key=lambda u: u.period or "")
        series = [float(u.cost or 0) for u in usages]
        tok_series = [u.total_tokens for u in usages]
        out.append({
            "product": prod,
            "total_tokens": sum(tok_series),
            "total_cost": round(sum(series), 2),
            "months": len(series),
            "est_cost": estimate_next(series),
            "est_tokens": int(estimate_next([float(t) for t in tok_series])),
            "trend": trend_pct(series),
            "history": [{"period": u.period, "tokens": u.total_tokens,
                         "calls": u.calls, "cost": float(u.cost or 0)} for u in usages],
        })
    out.sort(key=lambda x: x["total_cost"], reverse=True)
    return out


def client_summary(client_id):
    """Resumo consolidado para cards do dashboard."""
    bperiod = billing_by_period(client_id)
    toks, ai_cost = tokens_by_period(client_id)
    billing_series = list(bperiod.values())
    current_cost = billing_series[-1] if billing_series else 0.0
    est_cost = estimate_next(billing_series)
    total_tokens = sum(toks.values())
    return {
        "current_cost": round(current_cost, 2),
        "est_cost": est_cost,
        "cost_trend": trend_pct(billing_series),
        "total_tokens": total_tokens,
        "ai_cost": round(sum(ai_cost.values()), 2),
        "periods": list(bperiod.keys()),
        "billing_series": billing_series,
        "token_series": list(toks.values()),
        "n_accounts": len(_account_ids(client_id)),
        "n_products": AIProduct.query.filter(
            AIProduct.cloud_account_id.in_(_account_ids(client_id) or [0])).count(),
    }
