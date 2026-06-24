"""
app/services/collectors/azure.py — coletor Microsoft Azure (Cost Management).

Autenticação OAuth2 client_credentials. Credenciais esperadas:
  {tenant_id, client_id, client_secret}
account_ref = subscription_id.
Billing: POST .../providers/Microsoft.CostManagement/query agrupado por ServiceName.
IA: filtra serviços "Azure OpenAI" / "Cognitive Services".
"""
import requests
from datetime import datetime
from dateutil.relativedelta import relativedelta

from .base import BaseCollector, CollectorError

MGMT = "https://management.azure.com"


class AzureCollector(BaseCollector):
    provider = "azure"

    def _token(self) -> str:
        t = self.credentials.get("tenant_id")
        cid = self.credentials.get("client_id")
        sec = self.credentials.get("client_secret")
        if not (t and cid and sec):
            raise CollectorError("Credenciais Azure ausentes (tenant_id/client_id/client_secret).")
        r = requests.post(
            f"https://login.microsoftonline.com/{t}/oauth2/v2.0/token",
            data={"grant_type": "client_credentials", "client_id": cid,
                  "client_secret": sec, "scope": f"{MGMT}/.default"},
            timeout=30,
        )
        if r.status_code != 200:
            raise CollectorError(f"Falha de autenticação Azure (HTTP {r.status_code}).")
        return r.json()["access_token"]

    def _query(self, token: str, period: str):
        sub = self.account_ref
        if not sub:
            raise CollectorError("Informe o Subscription ID da conta Azure.")
        start = datetime.strptime(period + "-01", "%Y-%m-%d").date()
        end = start + relativedelta(months=1, days=-1)
        url = (f"{MGMT}/subscriptions/{sub}/providers/Microsoft.CostManagement/"
               f"query?api-version=2023-11-01")
        body = {
            "type": "ActualCost", "timeframe": "Custom",
            "timePeriod": {"from": start.isoformat(), "to": end.isoformat()},
            "dataset": {
                "granularity": "None",
                "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
                "grouping": [{"type": "Dimension", "name": "ServiceName"}],
            },
        }
        r = requests.post(url, headers={"Authorization": f"Bearer {token}"},
                          json=body, timeout=60)
        if r.status_code != 200:
            raise CollectorError(f"Cost Management Azure retornou HTTP {r.status_code}.")
        data = r.json().get("properties", {})
        cols = [c["name"] for c in data.get("columns", [])]
        rows = data.get("rows", [])
        ci_cost = cols.index("Cost") if "Cost" in cols else 0
        ci_svc = cols.index("ServiceName") if "ServiceName" in cols else 1
        ci_cur = cols.index("Currency") if "Currency" in cols else None
        return [(row[ci_svc], float(row[ci_cost]),
                 row[ci_cur] if ci_cur is not None else "USD") for row in rows]

    def fetch_billing(self, period: str) -> list[dict]:
        token = self._token()
        return [{"resource_type": svc, "resource_name": svc, "resource_group": "",
                 "region": self.region or "global", "cost": cost, "currency": cur}
                for svc, cost, cur in self._query(token, period)]

    def fetch_ai_usage(self, period: str) -> list[dict]:
        token = self._token()
        out = []
        for svc, cost, cur in self._query(token, period):
            if "openai" in svc.lower() or "cognitive" in svc.lower():
                out.append({"service": svc, "model": svc, "input_tokens": 0,
                            "output_tokens": 0, "calls": 0, "cost": cost, "currency": cur})
        return out
