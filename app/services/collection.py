"""
app/services/collection.py — núcleo reutilizável de coleta.

Usado tanto pela rota "Coletar via API" quanto pelo agendador (systemd timer).
Mantém a lógica única de gravação de billing, uso de IA e sincronização de
assinaturas, para que a coleta manual e a agendada sejam idênticas.
"""
import json
from datetime import date

from app.extensions import db
from app.models import (CloudAccount, BillingRecord, AIProduct, TokenUsage,
                        Subscription)
from app.crypto import decrypt
from app.services.collectors import get_collector, CollectorError  # noqa: F401


def month_range(p_from, p_to, cap=36):
    """Lista de períodos 'YYYY-MM' de p_from a p_to (inclusive)."""
    y1, m1 = int(p_from[:4]), int(p_from[5:7])
    y2, m2 = int(p_to[:4]), int(p_to[5:7])
    if (y1, m1) > (y2, m2):
        y1, m1, y2, m2 = y2, m2, y1, m1
    out, y, m = [], y1, m1
    while (y, m) <= (y2, m2) and len(out) < cap:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def periods_back(months_back: int, ref: date = None):
    """Período atual e os 'months_back' meses anteriores (lista 'YYYY-MM')."""
    ref = ref or date.today()
    y, m = ref.year, ref.month
    start_m = m - months_back
    start_y = y
    while start_m < 1:
        start_m += 12
        start_y -= 1
    return month_range(f"{start_y:04d}-{start_m:02d}", f"{y:04d}-{m:02d}")


def _sync_subscriptions(col, acc, period):
    """Cria/atualiza/remove as assinaturas 'api' do cliente conforme o provedor."""
    try:
        subs = col.fetch_subscription(period) or []
    except Exception:  # noqa: BLE001
        return 0
    seen = []
    for s in subs:
        ref = s.get("external_ref") or s["plan_name"]
        seen.append(ref)
        existing = (Subscription.query
                    .filter_by(client_id=acc.client_id, source="api", external_ref=ref)
                    .first())
        if not existing:
            existing = Subscription(client_id=acc.client_id, source="api", external_ref=ref)
            db.session.add(existing)
        existing.plan_name = s["plan_name"]
        existing.start_date = s["start_date"]
        existing.end_date = s["end_date"]
        existing.total_credits = s["total_credits"]
        existing.used_credits = s["used_credits"]
        existing.balance = s.get("balance")
        existing.currency = s["currency"]
    if subs:
        stale = (Subscription.query
                 .filter_by(client_id=acc.client_id, source="api")
                 .filter(~Subscription.external_ref.in_(seen)).all())
        for s in stale:
            db.session.delete(s)
    return len(subs)


def collect_account(acc: CloudAccount, periods: list[str]) -> dict:
    """Executa a coleta de uma conta para os períodos informados e faz commit.

    Retorna {'billing': n, 'ai': n, 'subscriptions': n}.
    Levanta CollectorError quando a coleta automática não é possível.
    """
    creds = json.loads(decrypt(acc.credentials_enc) or "{}")
    col = get_collector(acc.provider, acc.account_ref, acc.region, creds)
    n_billing = n_ai = 0
    try:
        for period in periods:
            billing = col.fetch_billing(period)
            n_billing += len(billing)
            BillingRecord.query.filter_by(cloud_account_id=acc.id, period=period,
                                          source="api").delete()
            for b in billing:
                db.session.add(BillingRecord(
                    cloud_account_id=acc.id, period=period, source="api",
                    resource_type=b["resource_type"], resource_name=b["resource_name"],
                    resource_group=b.get("resource_group", ""), region=b.get("region", ""),
                    cost=b["cost"], currency=b.get("currency", "USD")))
            ai = col.fetch_ai_usage(period)
            n_ai += len(ai)
            for u in ai:
                prod = AIProduct.query.filter_by(cloud_account_id=acc.id,
                                                 service=u.get("service")).first()
                if not prod:
                    prod = AIProduct(cloud_account_id=acc.id, name=u.get("service", "IA"),
                                     service=u.get("service"), model=u.get("model"),
                                     currency=u.get("currency", "USD"))
                    db.session.add(prod)
                    db.session.flush()
                TokenUsage.query.filter_by(product_id=prod.id, period=period,
                                           source="api").delete()
                db.session.add(TokenUsage(
                    product_id=prod.id, period=period, source="api",
                    input_tokens=u.get("input_tokens", 0), output_tokens=u.get("output_tokens", 0),
                    calls=u.get("calls", 0), cost=u.get("cost", 0)))
        n_subs = _sync_subscriptions(col, acc, periods[-1] if periods else date.today().strftime("%Y-%m"))
        db.session.commit()
        return {"billing": n_billing, "ai": n_ai, "subscriptions": n_subs}
    except Exception:
        db.session.rollback()
        raise


def _is_due(sched, now):
    """Decide se um agendamento deve rodar agora.

    O runner é chamado periodicamente (ex.: de hora em hora pelo systemd timer).
    Um agendamento está 'vencido' se o horário programado de hoje/da semana/do
    mês já passou e ainda não houve execução desde esse horário.
    """
    if not sched.active:
        return False
    scheduled_today = now.replace(hour=sched.hour, minute=sched.minute,
                                  second=0, microsecond=0)
    if now < scheduled_today:
        return False
    if sched.frequency == "weekly" and now.weekday() != (sched.weekday % 7):
        return False
    if sched.frequency == "monthly" and now.day != sched.day_of_month:
        return False
    # Já rodou após o horário programado de hoje?
    if sched.last_run and sched.last_run >= scheduled_today:
        return False
    return True


def run_due_schedules(now=None, force_account_id=None):
    """Executa todas as coletas agendadas vencidas. Retorna lista de resultados.

    force_account_id: ignora a janela de horário e roda o agendamento da conta
    informada (usado pelo botão 'Executar agora').
    """
    from datetime import datetime
    from app.models import CollectionSchedule
    now = now or datetime.now()
    results = []
    query = CollectionSchedule.query
    if force_account_id:
        scheds = query.filter_by(cloud_account_id=force_account_id).all()
    else:
        scheds = query.filter_by(active=True).all()
    for sched in scheds:
        if not force_account_id and not _is_due(sched, now):
            continue
        acc = db.session.get(CloudAccount, sched.cloud_account_id)
        if not acc:
            continue
        periods = periods_back(sched.months_back or 0, now.date())
        try:
            res = collect_account(acc, periods)
            sched.last_status = (f"OK — {res['billing']} billing, {res['ai']} IA, "
                                 f"{res['subscriptions']} assinaturas")
            results.append({"account": acc.name, "ok": True, **res})
        except CollectorError as e:
            sched.last_status = f"Indisponível: {e}"
            results.append({"account": acc.name, "ok": False, "error": str(e)})
        except Exception as e:  # noqa: BLE001
            sched.last_status = f"Erro: {e}"
            results.append({"account": acc.name, "ok": False, "error": str(e)})
        sched.last_run = now
        db.session.commit()
    return results
