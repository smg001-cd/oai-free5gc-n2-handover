import json
import os
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests

BASE_DIR = Path(__file__).resolve().parent
OAUTH_DIR = BASE_DIR / "oauth"
AF_ID_FILE = OAUTH_DIR / "af-id.txt"
TOKEN_FILE = OAUTH_DIR / "token.json"
OAUTH_DIR.mkdir(parents=True, exist_ok=True)

NRF_URL = os.environ["NRF_URL"].rstrip("/")
AF_IP = os.environ["AF_IP"]
PLMN_MCC = os.environ.get("PLMN_MCC", "001")
PLMN_MNC = os.environ.get("PLMN_MNC", "01")

parsed_url = urlparse(NRF_URL)
if parsed_url.scheme not in ("http", "https") or not parsed_url.hostname:
    raise RuntimeError(f"Invalid NRF_URL: {NRF_URL!r}")

if AF_ID_FILE.exists():
    af_instance_id = AF_ID_FILE.read_text(encoding="utf-8").strip()
    uuid.UUID(af_instance_id)
else:
    af_instance_id = str(uuid.uuid4())
    AF_ID_FILE.write_text(af_instance_id, encoding="utf-8")
    os.chmod(AF_ID_FILE, 0o600)

profile = {
    "nfInstanceId": af_instance_id,
    "nfType": "AF",
    "nfStatus": "REGISTERED",
    "ipv4Addresses": [AF_IP],
    "plmnList": [{"mcc": PLMN_MCC, "mnc": PLMN_MNC}],
}

http = requests.Session()
http.trust_env = False

registration = http.put(
    f"{NRF_URL}/nnrf-nfm/v1/nf-instances/{af_instance_id}",
    json=profile,
    timeout=(3, 15),
    allow_redirects=False,
)
print("AF registration:", f"HTTP {registration.status_code}")
if registration.status_code not in (200, 201):
    print(registration.text)
    raise SystemExit(1)

print("AF instance ID:", af_instance_id)

token_response = http.post(
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
    print("Token issuance failed:", f"HTTP {token_response.status_code}")
    print(token_response.text)
    raise SystemExit(1)

token_data = token_response.json()
access_token = token_data.get("access_token")
if not isinstance(access_token, str) or not access_token:
    raise RuntimeError("NRF response does not contain access_token")

TOKEN_FILE.write_text(json.dumps(token_data, indent=2), encoding="utf-8")
os.chmod(TOKEN_FILE, 0o600)

print("Token issuance:", f"HTTP {token_response.status_code}")
print("Scope:", token_data.get("scope"))
print("Expires in:", token_data.get("expires_in"), "seconds")
print("Saved:", TOKEN_FILE)
