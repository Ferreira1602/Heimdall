"""
app/services/collectors/google.py — coletor Google Cloud.

O billing detalhado do GCP é exposto via export para BigQuery. Caminho
suportado: consulta à tabela de export usando o SDK google-cloud-bigquery.
Credenciais esperadas:
  {service_account_json, bq_dataset, bq_table}
account_ref = billing_account_id (informativo).
"""
import json
from datetime import datetime
from dateutil.relativedelta import relativedelta

from .base import BaseCollector, CollectorError


class GoogleCollector(BaseCollector):
    provider = "google"

    def _bq(self):
        try:
            from google.cloud import bigquery
            from google.oauth2 import service_account
        except ImportError:
            raise CollectorError(
                "SDK google-cloud-bigquery não instalado. Rode "
                "'pip install google-cloud-bigquery' ou lance valores manualmente."
            )
        raw = self.credentials.get("service_account_json")
        if not raw:
            raise CollectorError("Credencial Google ausente (service_account_json).")
        info = json.loads(raw) if isinstance(raw, str) else raw
        creds = service_account.Credentials.from_service_account_info(info)
        return bigquery.Client(credentials=creds, project=info.get("project_id"))

    def _table(self):
        ds = self.credentials.get("bq_dataset")
        tb = self.credentials.get("bq_table")
        if not (ds and tb):
            raise CollectorError("Informe bq_dataset e bq_table do export de billing.")
        return f"`{ds}.{tb}`"

    def fetch_billing(self, period: str) -> list[dict]:
        client = self._bq()
        start = datetime.strptime(period + "-01", "%Y-%m-%d").date()
        end = start + relativedelta(months=1)
        q = f"""
            SELECT service.description AS svc, project.name AS proj,
                   location.region AS region, SUM(cost) AS total,
                   ANY_VALUE(currency) AS currency
            FROM {self._table()}
            WHERE usage_start_time >= '{start}' AND usage_start_time < '{end}'
            GROUP BY svc, proj, region
        """
        rows = client.query(q).result()
        return [{"resource_type": r["svc"], "resource_name": r["svc"],
                 "resource_group": r["proj"] or "", "region": r["region"] or "",
                 "cost": float(r["total"] or 0), "currency": r["currency"] or "USD"}
                for r in rows]

    def fetch_ai_usage(self, period: str) -> list[dict]:
        client = self._bq()
        start = datetime.strptime(period + "-01", "%Y-%m-%d").date()
        end = start + relativedelta(months=1)
        q = f"""
            SELECT service.description AS svc, SUM(cost) AS total,
                   ANY_VALUE(currency) AS currency
            FROM {self._table()}
            WHERE usage_start_time >= '{start}' AND usage_start_time < '{end}'
              AND (LOWER(service.description) LIKE '%vertex%'
                   OR LOWER(service.description) LIKE '%generative%'
                   OR LOWER(service.description) LIKE '%ai platform%')
            GROUP BY svc
        """
        rows = client.query(q).result()
        return [{"service": r["svc"], "model": r["svc"], "input_tokens": 0,
                 "output_tokens": 0, "calls": 0, "cost": float(r["total"] or 0),
                 "currency": r["currency"] or "USD"} for r in rows]
