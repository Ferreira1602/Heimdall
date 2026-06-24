"""
app/services/collectors/base.py — contrato comum dos coletores de nuvem.

Cada provedor implementa:
  - fetch_billing(period)  -> list[dict] com {resource_type, resource_name,
                              resource_group, region, cost, currency}
  - fetch_ai_usage(period) -> list[dict] com {service, model, input_tokens,
                              output_tokens, calls, cost, currency}

As credenciais chegam já descriptografadas como dict.
Quando a coleta automática não é possível (faltam credenciais, erro de auth,
ou a API não expõe os dados), o coletor levanta CollectorError com mensagem
amigável — o sistema então permite o lançamento manual dos valores.
"""
from abc import ABC, abstractmethod


class CollectorError(Exception):
    pass


class BaseCollector(ABC):
    provider = "base"

    def __init__(self, account_ref: str, region: str, credentials: dict):
        self.account_ref = account_ref or ""
        self.region = region or ""
        self.credentials = credentials or {}

    @abstractmethod
    def fetch_billing(self, period: str) -> list[dict]:
        ...

    @abstractmethod
    def fetch_ai_usage(self, period: str) -> list[dict]:
        ...

    def fetch_subscription(self, period: str) -> list[dict]:
        """Assinaturas/créditos da conta no provedor.

        Opcional. Retorna uma lista (um cliente pode ter várias assinaturas),
        cada item com {plan_name, start_date (date), end_date (date),
        total_credits, used_credits, balance, currency, external_ref}, todos
        vindos diretamente da API (sem cálculo). Lista vazia quando o provedor
        não expõe esse dado. Nunca deve levantar exceção.
        """
        return []
