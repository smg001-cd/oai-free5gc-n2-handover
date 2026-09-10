import hashlib
import hmac
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024

RELAY_KEY = os.environ["SCF_RELAY_KEY"]
if len(RELAY_KEY) < 32:
    raise RuntimeError("SCF_RELAY_KEY must contain at least 32 characters")

INTENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
INTENT_LOG = LOG_DIR / "intents.jsonl"
LOG_DIR.mkdir(parents=True, exist_ok=True)
write_lock = threading.Lock()


@app.get("/health")
def health():
    return jsonify(status="ok", service="flask-nef-scf"), 200


@app.post("/intent")
def receive_intent():
    provided_key = request.headers.get("X-SCF-Relay-Key", "")
    if not hmac.compare_digest(provided_key, RELAY_KEY):
        return jsonify(error="NEF relay key invalid"), 401

    if not request.is_json:
        return jsonify(error="Content-Type must be application/json"), 400

    raw_body = request.get_data(cache=True)
    try:
        data = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return jsonify(error="valid UTF-8 JSON required"), 400

    if not isinstance(data, dict):
        return jsonify(error="JSON object required"), 400

    intent_id = data.get("intentId")
    if not isinstance(intent_id, str) or not INTENT_ID_PATTERN.fullmatch(intent_id):
        return jsonify(error="valid string intentId required"), 400

    request_id = request.headers.get("X-Request-ID", "")
    if not re.fullmatch(r"[a-f0-9]{32}", request_id):
        return jsonify(error="valid NEF request ID required"), 400

    body_hash = hashlib.sha256(raw_body).hexdigest()
    record = {
        "receivedAt": datetime.now(timezone.utc).isoformat(),
        "intentId": intent_id,
        "requestId": request_id,
        "sha256": body_hash,
        "status": "stored",
        "forwardedToCore": False,
        "intent": data,
        "rawJson": raw_body.decode("utf-8"),
    }

    with write_lock:
        with INTENT_LOG.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            log_file.flush()
            os.fsync(log_file.fileno())

    app.logger.warning(
        "SCF_STORED intentId=%s requestId=%s sha256=%s",
        intent_id,
        request_id,
        body_hash,
    )
    return jsonify(
        status="stored",
        intentId=intent_id,
        requestId=request_id,
        sha256=body_hash,
        forwardedToCore=False,
    ), 201
