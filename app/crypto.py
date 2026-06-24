"""
app/crypto.py — criptografia simétrica das credenciais de nuvem.

Usa Fernet (cryptography). A chave vem de config FERNET_KEY; se vazia,
deriva uma chave determinística do SECRET_KEY (apenas para não quebrar em
ambiente de teste — em produção defina HEIMDALL_FERNET_KEY).
"""
import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


def _get_fernet() -> Fernet:
    key = current_app.config.get("FERNET_KEY") or ""
    if not key:
        # Deriva de SECRET_KEY (fallback). NÃO recomendado em produção.
        digest = hashlib.sha256(current_app.config["SECRET_KEY"].encode()).digest()
        key = base64.urlsafe_b64encode(digest).decode()
    if isinstance(key, str):
        key = key.encode()
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    if plaintext is None:
        return ""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return ""
