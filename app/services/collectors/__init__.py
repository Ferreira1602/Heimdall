"""app/services/collectors/__init__.py — fábrica de coletores por provedor."""
from .base import CollectorError
from .ibm import IBMCollector
from .aws import AWSCollector
from .azure import AzureCollector
from .oracle import OracleCollector
from .google import GoogleCollector

_REGISTRY = {
    "ibm": IBMCollector,
    "aws": AWSCollector,
    "azure": AzureCollector,
    "oracle": OracleCollector,
    "google": GoogleCollector,
}


def get_collector(provider: str, account_ref: str, region: str, credentials: dict):
    cls = _REGISTRY.get(provider)
    if not cls:
        raise CollectorError(f"Provedor não suportado: {provider}")
    return cls(account_ref, region, credentials)
