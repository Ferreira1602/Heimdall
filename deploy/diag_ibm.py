"""
deploy/diag_ibm.py — diagnóstico da coleta IBM contra a conta real.

Uso no servidor:
    cd /var/www/heimdall
    set -a; . /etc/apache2/envvars; set +a
    sudo -E /var/www/heimdall/venv/bin/python deploy/diag_ibm.py [AAAA-MM]

Mostra a estrutura crua de alguns recursos e os totais que o coletor extrai,
para confirmar se o custo (rated_cost) está chegando.
"""
import sys, json
from datetime import date

sys.path.insert(0, "/var/www/heimdall")
sys.path.insert(0, ".")

from app import create_app
from app.extensions import db
from app.models import CloudAccount
from app.crypto import decrypt
from app.services.collectors import get_collector, CollectorError

period = sys.argv[1] if len(sys.argv) > 1 else date.today().strftime("%Y-%m")

app = create_app("production")
with app.app_context():
    acc = CloudAccount.query.filter_by(provider="ibm").first()
    if not acc:
        print("ERRO: nenhuma conta IBM cadastrada.")
        sys.exit(1)
    creds = json.loads(decrypt(acc.credentials_enc) or "{}")
    print(f"Conta: {acc.name} | account_ref={acc.account_ref} | região={acc.region}")
    print(f"apikey presente: {bool(creds.get('apikey'))}")
    print(f"Período: {period}\n")

    col = get_collector("ibm", acc.account_ref, acc.region, creds)

    # 1) Estrutura crua direto do endpoint
    try:
        resources, _tok = col._usage_resources(period)
    except CollectorError as e:
        print("CollectorError:", e); sys.exit(1)
    print(f"Total de recursos retornados: {len(resources)}")
    if resources:
        r0 = resources[0]
        print("Exemplo de recurso (chaves):", list(r0.keys()))
        print("  resource_id:", r0.get("resource_id"))
        print("  currency_code:", r0.get("currency_code"), "| currency_rate:", r0.get("currency_rate"))
        u0 = (r0.get("usage") or [])[:3]
        for m in u0:
            print("   métrica:", m.get("metric"), "| qty:", m.get("quantity"),
                  "| cost:", m.get("cost"), "| rated_cost:", m.get("rated_cost"))
    print()

    # 2) Totais que o coletor extrai
    billing = col.fetch_billing(period)
    ai = col.fetch_ai_usage(period)
    print(f"Billing: {len(billing)} recurso(s). Top 5 por custo:")
    for b in sorted(billing, key=lambda x: x["cost"], reverse=True)[:5]:
        print(f"  {b['resource_type']:26} {b['cost']:>10} {b['currency']}  ({b['resource_name']})")
    print("  TOTAL billing:", round(sum(b["cost"] for b in billing), 2))
    print(f"\nIA: {len(ai)} serviço(s).")
    for a in ai:
        print(f"  {a['service']:30} cost={a['cost']} in={a['input_tokens']} out={a['output_tokens']} calls={a['calls']}")

    # 3) Assinaturas / créditos da conta (endpoint summary) — agora lista
    print("\n--- Assinaturas / créditos (summary) ---")
    subs = col.fetch_subscription(period) or []
    if not subs:
        print("  Nenhuma assinatura/crédito retornado pelo summary "
              "(conta PayGo sem subscription/offers, ou sem permissão de billing).")
    else:
        for s in subs:
            print(f"  • {s['plan_name']}")
            print(f"      validade: {s['start_date']} → {s['end_date']}")
            print(f"      total={s['total_credits']} usado={s['used_credits']} "
                  f"saldo(API)={s.get('balance')} {s['currency']}  ref={s.get('external_ref')}")
