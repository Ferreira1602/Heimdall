"""
app/services/collectors/aws.py — coletor AWS (Cost Explorer + Bedrock).

Usa boto3 quando disponível. Credenciais esperadas:
  {access_key, secret_key, session_token?}
Billing: Cost Explorer get_cost_and_usage agrupado por SERVICE.
IA: filtra serviços Amazon Bedrock no Cost Explorer (tokens não são expostos
diretamente pelo billing; o consumo de tokens deve vir do CloudWatch ou ser
lançado manualmente).
"""
from datetime import datetime
from dateutil.relativedelta import relativedelta

from .base import BaseCollector, CollectorError


class AWSCollector(BaseCollector):
    provider = "aws"

    def _client(self, service):
        try:
            import boto3
        except ImportError:
            raise CollectorError(
                "boto3 não instalado. Rode 'pip install boto3' no servidor "
                "ou lance os valores manualmente."
            )
        ak = self.credentials.get("access_key")
        sk = self.credentials.get("secret_key")
        if not (ak and sk):
            raise CollectorError("Credenciais AWS ausentes (access_key/secret_key).")
        return boto3.client(
            service,
            aws_access_key_id=ak,
            aws_secret_access_key=sk,
            aws_session_token=self.credentials.get("session_token"),
            region_name=self.region or "us-east-1",
        )

    def _period_range(self, period: str):
        start = datetime.strptime(period + "-01", "%Y-%m-%d").date()
        end = start + relativedelta(months=1)
        return start.isoformat(), end.isoformat()

    def fetch_billing(self, period: str) -> list[dict]:
        ce = self._client("ce")
        start, end = self._period_range(period)
        resp = ce.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
        out = []
        for grp in resp.get("ResultsByTime", [{}])[0].get("Groups", []):
            svc = grp["Keys"][0]
            amt = grp["Metrics"]["UnblendedCost"]
            out.append({
                "resource_type": svc, "resource_name": svc,
                "resource_group": "", "region": self.region or "global",
                "cost": float(amt["Amount"]), "currency": amt.get("Unit", "USD"),
            })
        return out

    def fetch_ai_usage(self, period: str) -> list[dict]:
        ce = self._client("ce")
        start, end = self._period_range(period)
        resp = ce.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="MONTHLY", Metrics=["UnblendedCost"],
            Filter={"Dimensions": {"Key": "SERVICE",
                                   "Values": ["Amazon Bedrock", "Amazon SageMaker"]}},
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
        out = []
        for grp in resp.get("ResultsByTime", [{}])[0].get("Groups", []):
            svc = grp["Keys"][0]
            cost = float(grp["Metrics"]["UnblendedCost"]["Amount"])
            out.append({"service": svc, "model": svc, "input_tokens": 0,
                        "output_tokens": 0, "calls": 0, "cost": cost, "currency": "USD"})
        return out
