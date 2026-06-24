"""
app/services/collectors/oracle.py — coletor Oracle Cloud (Usage/Cost API).

A OCI exige assinatura de requisições (API Signing Key). O caminho suportado
aqui usa o SDK oficial 'oci' quando instalado. Credenciais esperadas:
  {user_ocid, tenancy_ocid, fingerprint, private_key, region}
account_ref = tenancy_ocid (compartment raiz).
"""
from datetime import datetime
from dateutil.relativedelta import relativedelta

from .base import BaseCollector, CollectorError


class OracleCollector(BaseCollector):
    provider = "oracle"

    def _client(self):
        try:
            import oci
        except ImportError:
            raise CollectorError(
                "SDK 'oci' não instalado. Rode 'pip install oci' no servidor "
                "ou lance os valores manualmente."
            )
        c = self.credentials
        req = ("user_ocid", "tenancy_ocid", "fingerprint", "private_key")
        if not all(c.get(k) for k in req):
            raise CollectorError("Credenciais Oracle incompletas (user/tenancy/fingerprint/key).")
        cfg = {
            "user": c["user_ocid"], "tenancy": c["tenancy_ocid"],
            "fingerprint": c["fingerprint"], "region": self.region or "us-ashburn-1",
            "key_content": c["private_key"],
        }
        return oci, cfg

    def _summarize(self, period: str, group_dim: str):
        oci, cfg = self._client()
        client = oci.usage_api.UsageapiClient(cfg)
        start = datetime.strptime(period + "-01", "%Y-%m-%d")
        end = start + relativedelta(months=1)
        details = oci.usage_api.models.RequestSummarizedUsagesDetails(
            tenant_id=self.account_ref or cfg["tenancy"],
            time_usage_started=start, time_usage_ended=end,
            granularity="MONTHLY", query_type="COST",
            group_by=[group_dim],
        )
        resp = client.request_summarized_usages(details)
        return resp.data.items

    def fetch_billing(self, period: str) -> list[dict]:
        items = self._summarize(period, "service")
        return [{"resource_type": getattr(i, "service", "OCI"),
                 "resource_name": getattr(i, "service", "OCI"),
                 "resource_group": getattr(i, "compartment_name", "") or "",
                 "region": getattr(i, "region", self.region) or "",
                 "cost": float(getattr(i, "computed_amount", 0) or 0),
                 "currency": getattr(i, "currency", "USD")} for i in items]

    def fetch_ai_usage(self, period: str) -> list[dict]:
        items = self._summarize(period, "service")
        out = []
        for i in items:
            svc = (getattr(i, "service", "") or "").lower()
            if "generative" in svc or "ai" in svc or "language" in svc:
                out.append({"service": getattr(i, "service", "OCI AI"),
                            "model": getattr(i, "service", ""), "input_tokens": 0,
                            "output_tokens": 0, "calls": 0,
                            "cost": float(getattr(i, "computed_amount", 0) or 0),
                            "currency": getattr(i, "currency", "USD")})
        return out
