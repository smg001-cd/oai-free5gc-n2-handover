import base64
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests
from flask import Flask, jsonify, request, send_from_directory

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_BUILD = BASE_DIR.parent / "frontend" / "build"
OAUTH_DIR = Path(os.environ.get("IUF_OAUTH_DIR", BASE_DIR / "oauth"))
AF_ID_FILE = OAUTH_DIR / "af-id.txt"
TOKEN_FILE = OAUTH_DIR / "token.json"

NEF_URL = os.environ.get("NEF_URL", "").strip()
NRF_URL = os.environ.get("NRF_URL", "").strip().rstrip("/")
AF_IP = os.environ.get("AF_IP", "").strip()
PLMN_MCC = os.environ.get("PLMN_MCC", "001")
PLMN_MNC = os.environ.get("PLMN_MNC", "01")

INTENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
TOKEN_REFRESH_MARGIN = 60

app = Flask(__name__, static_folder=str(FRONTEND_BUILD), static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024


def validate_url(name, value):
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise RuntimeError(f"Invalid {name}: {value!r}")


if not NEF_URL:
    raise RuntimeError("NEF_URL must identify the NEF endpoint on the Core VM")
validate_url("NEF_URL", NEF_URL)
if NRF_URL:
    validate_url("NRF_URL", NRF_URL)
    if not AF_IP:
        raise RuntimeError("AF_IP must identify the IUF VM when NRF_URL is configured")


def jwt_expiry(token):
    """Read exp only to decide when to refresh; NEF still verifies the signature."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return float(json.loads(base64.urlsafe_b64decode(payload))["exp"])
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return 0


class OAuthTokenProvider:
    def __init__(self):
        self._lock = threading.Lock()
        self._token = ""
        self._expires_at = 0.0
        self._session = requests.Session()
        self._session.trust_env = False

    def invalidate(self):
        with self._lock:
            self._token = ""
            self._expires_at = 0.0

    def get(self, force_refresh=False):
        with self._lock:
            now = time.time()
            if not force_refresh and self._token and self._expires_at > now + TOKEN_REFRESH_MARGIN:
                return self._token

            if not force_refresh:
                saved = self._read_saved_token()
                if saved is not None:
                    self._token, self._expires_at = saved
                    return self._token

                env_token = os.environ.get("NEF_ACCESS_TOKEN", "").strip()
                env_expiry = jwt_expiry(env_token)
                if env_token and env_expiry > now + TOKEN_REFRESH_MARGIN:
                    self._token = env_token
                    self._expires_at = env_expiry
                    return self._token

            if not NRF_URL:
                raise RuntimeError(
                    "No valid NEF token. Configure NRF_URL for automatic renewal "
                    "or update NEF_ACCESS_TOKEN/IUF_OAUTH_DIR/token.json."
                )

            self._token, self._expires_at = self._issue_token()
            return self._token

    def _read_saved_token(self):
        try:
            token_data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
            token = token_data["access_token"].strip()
            expires_at = float(token_data.get("_expires_at") or jwt_expiry(token))
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

        if token and expires_at > time.time() + TOKEN_REFRESH_MARGIN:
            return token, expires_at
        return None

    def _get_af_instance_id(self):
        OAUTH_DIR.mkdir(parents=True, exist_ok=True)
        try:
            value = AF_ID_FILE.read_text(encoding="utf-8").strip()
            uuid.UUID(value)
            return value
        except (OSError, ValueError):
            value = str(uuid.uuid4())
            AF_ID_FILE.write_text(value, encoding="utf-8")
            try:
                os.chmod(AF_ID_FILE, 0o600)
            except OSError:
                pass
            return value

    def _issue_token(self):
        af_instance_id = self._get_af_instance_id()
        profile = {
            "nfInstanceId": af_instance_id,
            "nfType": "AF",
            "nfStatus": "REGISTERED",
            "ipv4Addresses": [AF_IP],
            "plmnList": [{"mcc": PLMN_MCC, "mnc": PLMN_MNC}],
        }

        registration = self._session.put(
            f"{NRF_URL}/nnrf-nfm/v1/nf-instances/{af_instance_id}",
            json=profile,
            timeout=(3, 15),
            allow_redirects=False,
        )
        if registration.status_code not in (200, 201):
            raise RuntimeError(
                f"AF registration failed: HTTP {registration.status_code}"
            )

        token_response = self._session.post(
            f"{NRF_URL}/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "nfInstanceId": af_instance_id,
                "nfType": "AF",
                "targetNfType": "NEF",
                "scope": "3gpp-traffic-influence",
            },
            timeout=(3, 15),
            allow_redirects=False,
        )
        if token_response.status_code != 200:
            raise RuntimeError(
                f"Token issuance failed: HTTP {token_response.status_code}"
            )

        token_data = token_response.json()
        token = token_data.get("access_token", "").strip()
        if not token:
            raise RuntimeError("NRF response does not contain access_token")

        try:
            lifetime = max(1, int(token_data.get("expires_in", 0)))
        except (TypeError, ValueError):
            lifetime = 0
        expires_at = jwt_expiry(token) or (time.time() + lifetime)
        token_data["_expires_at"] = expires_at

        OAUTH_DIR.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(json.dumps(token_data, indent=2), encoding="utf-8")
        try:
            os.chmod(TOKEN_FILE, 0o600)
        except OSError:
            pass

        app.logger.info(
            "OAuth token issued for AF %s; expires_in=%ss",
            af_instance_id,
            lifetime,
        )
        return token, expires_at


token_provider = OAuthTokenProvider()
nef_http = requests.Session()
nef_http.trust_env = False


def send_to_nef(intent, force_refresh=False):
    token = token_provider.get(force_refresh=force_refresh)
    return nef_http.post(
        NEF_URL,
        json=intent,
        headers={"Authorization": f"Bearer {token}"},
        timeout=(3, 20),
        allow_redirects=False,
    )


@app.get("/api/health")
def health():
    return jsonify(status="ok", service="iuf-web", nefUrl=NEF_URL, automaticOAuth=bool(NRF_URL))


@app.post("/api/intents")
def create_intent():
    intent = request.get_json(silent=True)
    if not isinstance(intent, dict):
        return jsonify(error="JSON object required"), 400

    intent_id = intent.get("intentId")
    if not isinstance(intent_id, str) or not INTENT_ID_PATTERN.fullmatch(intent_id):
        return jsonify(error="valid string intentId required"), 400

    try:
        upstream = send_to_nef(intent)
        if upstream.status_code == 401 and NRF_URL:
            token_provider.invalidate()
            upstream = send_to_nef(intent, force_refresh=True)
    except requests.Timeout:
        return jsonify(error="NEF response timeout"), 504
    except requests.RequestException:
        app.logger.exception("NEF connection failed")
        return jsonify(error="NEF connection failed"), 502
    except RuntimeError as exc:
        app.logger.error("OAuth setup failed: %s", exc)
        return jsonify(error=str(exc)), 503

    try:
        upstream_body = upstream.json()
    except ValueError:
        upstream_body = {"message": upstream.text[:4000]}

    request_id = upstream.headers.get("X-Request-ID")
    app.logger.info(
        "IUF_WEB intentId=%s requestId=%s nef_status=%s",
        intent_id,
        request_id or "-",
        upstream.status_code,
    )

    return (
        jsonify(
            ok=200 <= upstream.status_code < 300,
            upstreamStatus=upstream.status_code,
            requestId=request_id,
            result=upstream_body,
        ),
        upstream.status_code,
    )


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def frontend(path):
    if path and (FRONTEND_BUILD / path).is_file():
        return send_from_directory(FRONTEND_BUILD, path)
    if (FRONTEND_BUILD / "index.html").is_file():
        return send_from_directory(FRONTEND_BUILD, "index.html")
    return jsonify(
        error="React build not found",
        instruction="Run npm install && npm run build in iuf-web/frontend",
    ), 503


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)

