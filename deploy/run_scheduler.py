"""
deploy/run_scheduler.py — executa as coletas agendadas vencidas.

Invocado periodicamente pelo systemd timer (heimdall-scheduler.timer).
Carrega o app em modo produção e roda run_due_schedules().
"""
import sys
from datetime import datetime

sys.path.insert(0, "/var/www/heimdall")
sys.path.insert(0, ".")

from app import create_app
from app.services.collection import run_due_schedules

app = create_app("production")
with app.app_context():
    results = run_due_schedules(now=datetime.now())
    if not results:
        print(f"[{datetime.now():%Y-%m-%d %H:%M}] Nenhum agendamento vencido.")
    for r in results:
        status = "OK" if r.get("ok") else "FALHA"
        extra = (f"billing={r.get('billing')} ia={r.get('ai')} "
                 f"assin={r.get('subscriptions')}") if r.get("ok") else r.get("error", "")
        print(f"[{datetime.now():%Y-%m-%d %H:%M}] {status} {r['account']}: {extra}")
