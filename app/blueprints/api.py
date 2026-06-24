"""
app/blueprints/api.py — ingestão de eventos via REST (Bearer token).

Endpoint para coletores externos enviarem consumo de tokens.
Autenticação: header Authorization: Bearer <HEIMDALL_INGEST_TOKEN>
(definido em config ou variável de ambiente).
"""
import os
from datetime import date

from flask import Blueprint, request, jsonify

from app.extensions import db
from app.models import AIProduct, TokenUsage

api_bp = Blueprint("api", __name__, url_prefix="/api/v1")

INGEST_TOKEN = os.environ.get("HEIMDALL_INGEST_TOKEN", "heimdall-ingest-token")


def _authorized():
    auth = request.headers.get("Authorization", "")
    return auth == f"Bearer {INGEST_TOKEN}"


@api_bp.route("/health")
def health():
    return jsonify(status="ok", service="heimdall")


@api_bp.route("/usage", methods=["POST"])
def ingest_usage():
    if not _authorized():
        return jsonify(error="unauthorized"), 401
    data = request.get_json(silent=True) or {}
    product_id = data.get("product_id")
    prod = db.session.get(AIProduct, product_id) if product_id else None
    if not prod:
        return jsonify(error="product_id inválido"), 400
    period = data.get("period") or date.today().strftime("%Y-%m")
    usage = TokenUsage.query.filter_by(product_id=prod.id, period=period,
                                       source="api").first()
    if not usage:
        usage = TokenUsage(product_id=prod.id, period=period, source="api")
        db.session.add(usage)
    usage.input_tokens = int(data.get("input_tokens", 0) or 0)
    usage.output_tokens = int(data.get("output_tokens", 0) or 0)
    usage.calls = int(data.get("calls", 0) or 0)
    usage.cost = float(data.get("cost", 0) or 0)
    db.session.commit()
    return jsonify(status="ok", product_id=prod.id, period=period)
