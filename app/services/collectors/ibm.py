"""
app/services/collectors/ibm.py — coletor IBM Cloud (Billing + Resource Controller).

Reaproveita a lógica validada no Vegvísir:
  - Billing API: billing.cloud.ibm.com/v4/accounts/{account_id}/resource_instances/usage/{month}
  - Resource Controller resolve nomes: resource-controller.cloud.ibm.com/v2/resource_instances
  - Autenticação IAM via apikey -> token Bearer
"""
import requests
from collections import defaultdict
from datetime import datetime, date

from .base import BaseCollector, CollectorError

IAM_URL = "https://iam.cloud.ibm.com/identity/token"
BILLING_BASE = "https://billing.cloud.ibm.com"
RESOURCE_CTRL = "https://resource-controller.cloud.ibm.com"

AI_SERVICE_IDS = {
    "watsonx-orchestrate": "WatsonX Orchestrate",
    "pm-20": "WatsonX.ai / Machine Learning",
    "data-science-experience": "WatsonX Studio",
    "conversation": "Watson Assistant",
    "discovery": "Watson Discovery",
    "natural-language-understanding": "Watson NLU",
    "text-to-speech": "Watson Text to Speech",
    "speech-to-text": "Watson Speech to Text",
}

TOKEN_KEYS = ("token", "input_token", "output_token", "nlu_item",
              "prompt", "completion", "inference", "generated")
CALL_KEYS = ("call", "request", "transaction", "api_call",
             "message", "query", "class_a", "class_b")


def _metric_cost(metric: dict) -> float:
    """Custo de uma métrica de uso.

    Estrutura confirmada em produção (endpoint resource_instances/usage):
    cada item de usage[] traz 'rated_cost' (antes de descontos/créditos) e
    'cost' (após créditos). Usamos rated_cost — é o valor que reflete o
    consumo real, sem zerar quando há créditos aplicados.
    """
    c = metric.get("rated_cost")
    if c in (None, 0, 0.0):
        c = metric.get("cost", 0)
    try:
        return float(c or 0)
    except (TypeError, ValueError):
        return 0.0


class IBMCollector(BaseCollector):
    provider = "ibm"

    def _token(self) -> str:
        apikey = self.credentials.get("apikey")
        if not apikey:
            raise CollectorError("Credencial IBM ausente: informe a 'apikey'.")
        r = requests.post(
            IAM_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "urn:ibm:params:oauth:grant-type:apikey", "apikey": apikey},
            timeout=30,
        )
        if r.status_code != 200:
            raise CollectorError(f"Falha ao autenticar na IBM (HTTP {r.status_code}).")
        return r.json()["access_token"]

    def _resource_names(self, token: str) -> dict:
        names = {}
        try:
            r = requests.get(
                f"{RESOURCE_CTRL}/v2/resource_instances?limit=200",
                headers={"Authorization": f"Bearer {token}"}, timeout=30,
            )
            for it in r.json().get("resources", []):
                names[it.get("id", "")] = it.get("name", "")
                names[it.get("guid", "")] = it.get("name", "")
        except Exception:
            pass
        return names

    def _usage_resources(self, period: str) -> list[dict]:
        """Busca os recursos de uso do mês (endpoint resource_instances/usage)."""
        acc = self.account_ref
        if not acc:
            raise CollectorError("Informe o Account ID da conta IBM.")
        token = self._token()
        url = f"{BILLING_BASE}/v4/accounts/{acc}/resource_instances/usage/{period}"
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"},
                         params={"_limit": 200}, timeout=60)
        if r.status_code == 403:
            raise CollectorError(
                "Sem permissão para o billing. Atribua a role 'Viewer' em "
                "Billing (IAM) para a API Key utilizada.")
        if r.status_code != 200:
            raise CollectorError(f"Billing IBM retornou HTTP {r.status_code}.")
        return r.json().get("resources", []), token

    def fetch_billing(self, period: str) -> list[dict]:
        resources, token = self._usage_resources(period)
        names = self._resource_names(token)
        # A API pode fragmentar o mesmo recurso por plano; agrega por instância.
        agg = {}
        for res in resources:
            iid = res.get("resource_instance_id", "")
            key = iid or res.get("resource_id", "?")
            # usage[] vem direto no recurso; cada item é uma métrica com rated_cost
            cost = sum(_metric_cost(m) for m in (res.get("usage") or []))
            if key not in agg:
                fallback = (iid.split(":")[-3] if iid.count(":") >= 3 else "") or iid[-12:]
                agg[key] = {
                    "resource_type": res.get("resource_id", "desconhecido"),
                    "resource_name": names.get(iid) or res.get("resource_name") or fallback,
                    "resource_group": res.get("resource_group_name",
                                              res.get("resource_group_id", "")),
                    "region": res.get("region", ""),
                    "cost": 0.0,
                    "currency": res.get("currency_code", "BRL"),
                }
            agg[key]["cost"] += cost
        out = list(agg.values())
        for o in out:
            o["cost"] = round(o["cost"], 6)
        return out

    def fetch_ai_usage(self, period: str) -> list[dict]:
        resources, _token = self._usage_resources(period)
        agg = defaultdict(lambda: {"input_tokens": 0, "output_tokens": 0,
                                   "calls": 0, "cost": 0.0})
        for res in resources:
            sid = res.get("resource_id", "")
            if sid not in AI_SERVICE_IDS:
                continue
            bucket = agg[sid]
            for m in res.get("usage", []) or []:
                metric = (m.get("metric") or m.get("metric_name") or "").lower()
                qty = int(float(m.get("quantity", 0) or 0))
                bucket["cost"] += _metric_cost(m)
                if "output" in metric:
                    bucket["output_tokens"] += qty
                elif any(k in metric for k in TOKEN_KEYS):
                    bucket["input_tokens"] += qty
                elif any(k in metric for k in CALL_KEYS):
                    bucket["calls"] += qty
                else:
                    bucket["calls"] += qty
        return [
            {"service": AI_SERVICE_IDS[sid], "model": sid,
             "input_tokens": v["input_tokens"], "output_tokens": v["output_tokens"],
             "calls": v["calls"], "cost": round(v["cost"], 6), "currency": "BRL"}
            for sid, v in agg.items()
        ]

    # ───────────────────────── Assinatura / créditos ─────────────────────────
    @staticmethod
    def _to_date(s):
        """Converte 'YYYY-MM-DDTHH:MM:SS.mmmZ' (ou similar) em date."""
        if not s:
            return None
        try:
            return datetime.fromisoformat(str(s).replace("Z", "+00:00")).date()
        except (ValueError, TypeError):
            try:
                return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                return None

    def fetch_subscription(self, period: str):
        """Lê as assinaturas/créditos da conta no endpoint de summary da IBM.

        Reflete EXATAMENTE o que o painel da IBM mostra, sem cálculos:
          - subscription.subscriptions[].terms[]: cada termo é uma assinatura
            com validade (start/end) e créditos {total, used, balance}.
          - offers[]: créditos promocionais com validade e {starting_balance,
            used, balance}.
        Retorna lista de dicts (cada um vira uma assinatura no cliente) com
        total_credits, used_credits e balance vindos diretamente da API.
        Nunca levanta exceção: em falha retorna lista vazia.
        """
        acc = self.account_ref
        if not acc:
            return []
        try:
            token = self._token()
            url = f"{BILLING_BASE}/v4/accounts/{acc}/summary/{period}"
            r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=60)
            if r.status_code != 200:
                return []
            data = r.json()
        except Exception:
            return []

        currency = data.get("billing_currency_code") or data.get("currency_code") or "BRL"
        out = []

        # Assinaturas contratadas: uma entrada por termo (validade/créditos próprios)
        for sub in (data.get("subscription") or {}).get("subscriptions") or []:
            sid = sub.get("subscription_id", "")
            stype = sub.get("type", "Subscription")
            terms = sub.get("terms", []) or []
            if terms:
                for i, term in enumerate(terms):
                    cr = term.get("credits", {}) or {}
                    start = self._to_date(term.get("start") or sub.get("start"))
                    end = self._to_date(term.get("end") or sub.get("end"))
                    if not (start and end):
                        continue
                    label = f"IBM {stype} {sid}".strip()
                    if len(terms) > 1:
                        label += f" · termo {i + 1}"
                    out.append({
                        "plan_name": label,
                        "start_date": start, "end_date": end,
                        "total_credits": float(cr.get("total", cr.get("starting_balance", 0)) or 0),
                        "used_credits": float(cr.get("used", 0) or 0),
                        "balance": float(cr.get("balance", 0) or 0),
                        "currency": currency,
                        "external_ref": f"sub:{sid}:term:{i}",
                    })
            else:
                start = self._to_date(sub.get("start"))
                end = self._to_date(sub.get("end"))
                if start and end:
                    out.append({
                        "plan_name": f"IBM {stype} {sid}".strip(),
                        "start_date": start, "end_date": end,
                        "total_credits": float(sub.get("credits_total", 0) or 0),
                        "used_credits": 0.0,
                        "balance": float(sub.get("credits_total", 0) or 0),
                        "currency": currency,
                        "external_ref": f"sub:{sid}",
                    })

        # Ofertas / créditos promocionais: uma entrada por oferta
        for off in data.get("offers") or []:
            cr = off.get("credits", {}) or {}
            start = self._to_date(off.get("valid_from"))
            end = self._to_date(off.get("expires_on"))
            if not (start and end):
                continue
            oid = off.get("offer_id", "")
            out.append({
                "plan_name": f"IBM Crédito {oid}".strip(),
                "start_date": start, "end_date": end,
                "total_credits": float(cr.get("starting_balance", off.get("credits_total", 0)) or 0),
                "used_credits": float(cr.get("used", 0) or 0),
                "balance": float(cr.get("balance", 0) or 0),
                "currency": currency,
                "external_ref": f"offer:{oid}",
            })
        return out
