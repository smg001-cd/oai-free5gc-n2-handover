import hashlib
import hmac
import ipaddress
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

import yaml
from flask import Flask, jsonify, request


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024


# -------------------------------------------------------------------
# 기본 설정
# -------------------------------------------------------------------

RELAY_KEY = os.environ["SCF_RELAY_KEY"]

if len(RELAY_KEY) < 32:
    raise RuntimeError(
        "SCF_RELAY_KEY must contain at least 32 characters"
    )


INTENT_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9_.:-]{1,128}$"
)

EXTENSION_NAME_PATTERN = re.compile(
    r"^[a-z0-9][a-z0-9_.:-]{0,63}$"
)


BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
POLICY_DIR = BASE_DIR / "policies"

INTENT_LOG = LOG_DIR / "intents.jsonl"

LOG_DIR.mkdir(parents=True, exist_ok=True)
POLICY_DIR.mkdir(parents=True, exist_ok=True)


write_lock = threading.Lock()


# 현재 실험에서 기본으로 지원하는 Action
BUILT_IN_ACTIONS = {
    "firewall": {
        "drop",
        "reject",
        "accept",
        "log",
    },

    "anti-ddos": {
        "rate-limit",
        "drop",
        "alert",
        "redirect-scrubber",
    },
}


class IntentValidationError(ValueError):
    """High-level Intent 검증 오류."""


# -------------------------------------------------------------------
# 검증 함수
# -------------------------------------------------------------------

def require_object(parent, name):
    value = parent.get(name)

    if not isinstance(value, dict):
        raise IntentValidationError(
            f"{name} must be a JSON object"
        )

    return value


def require_string(parent, name):
    value = parent.get(name)

    if not isinstance(value, str) or not value.strip():
        raise IntentValidationError(
            f"{name} must be a non-empty string"
        )

    return value.strip()


def normalize_destination_ipv4(value):
    try:
        network = ipaddress.ip_network(
            value,
            strict=False,
        )
    except ValueError as error:
        raise IntentValidationError(
            "traffic.destinationIpv4Cidr must be "
            "an IPv4 address or IPv4 CIDR"
        ) from error

    if network.version != 4:
        raise IntentValidationError(
            "only IPv4 destination is currently supported"
        )

    return str(network)


def validate_snssai(subject):
    snssai = require_object(subject, "snssai")

    try:
        sst = int(snssai.get("sst"))
    except (TypeError, ValueError) as error:
        raise IntentValidationError(
            "subject.snssai.sst must be an integer"
        ) from error

    if not 0 <= sst <= 255:
        raise IntentValidationError(
            "subject.snssai.sst must be between 0 and 255"
        )

    sd = require_string(snssai, "sd").upper()

    if not re.fullmatch(r"[0-9A-F]{6}", sd):
        raise IntentValidationError(
            "subject.snssai.sd must be "
            "a 6-digit hexadecimal string"
        )

    return {
        "sst": sst,
        "sd": sd,
    }


def validate_port(traffic, protocol):
    value = traffic.get("destinationPort")

    if value in (None, ""):
        return None

    if protocol not in ("tcp", "udp"):
        raise IntentValidationError(
            "destinationPort can only be used with TCP or UDP"
        )

    try:
        port = int(value)
    except (TypeError, ValueError) as error:
        raise IntentValidationError(
            "traffic.destinationPort must be an integer"
        ) from error

    if not 1 <= port <= 65535:
        raise IntentValidationError(
            "traffic.destinationPort must be between 1 and 65535"
        )

    return port


# -------------------------------------------------------------------
# High-level Intent → Low-level Policy 변환
# -------------------------------------------------------------------

def translate_intent(intent):
    subject = require_object(intent, "subject")
    traffic = require_object(intent, "traffic")
    security = require_object(
        intent,
        "securityControl",
    )

    intent_id = require_string(
        intent,
        "intentId",
    )

    supi = require_string(
        subject,
        "supi",
    )

    dnn = require_string(
        subject,
        "dnn",
    )

    snssai = validate_snssai(subject)

    destination = normalize_destination_ipv4(
        require_string(
            traffic,
            "destinationIpv4Cidr",
        )
    )

    protocol = require_string(
        traffic,
        "protocol",
    ).lower()

    if protocol not in {
        "any",
        "tcp",
        "udp",
        "icmp",
    }:
        raise IntentValidationError(
            "traffic.protocol must be "
            "any, tcp, udp, or icmp"
        )

    direction = require_string(
        traffic,
        "direction",
    )

    if direction not in {
        "n6-egress",
        "n6-ingress",
        "bidirectional",
    }:
        raise IntentValidationError(
            "traffic.direction must be "
            "n6-egress, n6-ingress, or bidirectional"
        )

    destination_port = validate_port(
        traffic,
        protocol,
    )

    nsf_type = require_string(
        security,
        "nsfType",
    ).lower()

    action = require_string(
        security,
        "action",
    ).lower()

    if not EXTENSION_NAME_PATTERN.fullmatch(nsf_type):
        raise IntentValidationError(
            "invalid securityControl.nsfType"
        )

    if not EXTENSION_NAME_PATTERN.fullmatch(action):
        raise IntentValidationError(
            "invalid securityControl.action"
        )

    supported_actions = BUILT_IN_ACTIONS.get(
        nsf_type,
        set(),
    )

    if action in supported_actions:
        action_profile = "built-in"
    else:
        # 이후 추가할 새로운 NSF Action임을 YAML에 표시한다.
        action_profile = "extension"

    parameters = security.get(
        "parameters",
        {},
    )

    if not isinstance(parameters, dict):
        raise IntentValidationError(
            "securityControl.parameters must be an object"
        )

    normalized_parameters = {}

    if nsf_type == "anti-ddos":
        threshold = parameters.get(
            "detectionThresholdPps"
        )

        try:
            threshold = int(threshold)
        except (TypeError, ValueError) as error:
            raise IntentValidationError(
                "Anti-DDoS requires "
                "detectionThresholdPps"
            ) from error

        if threshold < 1:
            raise IntentValidationError(
                "detectionThresholdPps must be at least 1"
            )

        normalized_parameters[
            "detectionThresholdPps"
        ] = threshold

    if action == "rate-limit":
        rate_limit = parameters.get(
            "rateLimitMbps"
        )

        try:
            rate_limit = int(rate_limit)
        except (TypeError, ValueError) as error:
            raise IntentValidationError(
                "rate-limit requires rateLimitMbps"
            ) from error

        if rate_limit < 1:
            raise IntentValidationError(
                "rateLimitMbps must be at least 1"
            )

        normalized_parameters[
            "rateLimitMbps"
        ] = rate_limit

    # 정의되지 않은 확장 파라미터도 보존한다.
    for name, value in parameters.items():
        if name not in normalized_parameters:
            normalized_parameters[name] = value

    trigger = intent.get(
        "trigger",
        {},
    )

    if not isinstance(trigger, dict):
        raise IntentValidationError(
            "trigger must be an object"
        )

    trigger_type = trigger.get(
        "type",
        "n2-handover",
    )

    enforcement_stage = trigger.get(
        "enforcementStage",
        "before-path-switch",
    )

    if trigger_type != "n2-handover":
        raise IntentValidationError(
            "only n2-handover trigger is currently supported"
        )

    if enforcement_stage not in {
        "before-path-switch",
        "after-path-switch",
    }:
        raise IntentValidationError(
            "invalid trigger.enforcementStage"
        )

    migration = intent.get(
        "policyMigration",
        {},
    )

    if not isinstance(migration, dict):
        raise IntentValidationError(
            "policyMigration must be an object"
        )

    migration_mode = migration.get(
        "mode",
        "make-before-break",
    )

    if migration_mode not in {
        "make-before-break",
        "break-before-make",
        "target-only",
    }:
        raise IntentValidationError(
            "invalid policyMigration.mode"
        )

    match = {
        "destinationIpv4Cidr": destination,
        "protocol": protocol,
    }

    if destination_port is not None:
        match["destinationPort"] = destination_port

    enforcement = {
        "nsf": nsf_type,
        "action": action,

        # built-in 또는 extension
        "actionProfile": action_profile,
    }

    if normalized_parameters:
        enforcement["parameters"] = (
            normalized_parameters
        )

    low_level_policy = {
        # 이 실험을 위한 커스텀 Low-level 스키마
        "apiVersion": "i2nsf.5gc/v1alpha1",
        "kind": "SecurityPolicy",

        "metadata": {
            "name": intent_id,
            "createdAt": datetime.now(
                timezone.utc
            ).isoformat(),
        },

        "spec": {
            "selector": {
                "supi": supi,
                "dnn": dnn,
                "snssai": snssai,

                # UE IP는 IUF에서 받지 않고
                # SMF의 PDU Session Context에서 조회한다.
                "ueAddressSource":
                    "smf-pdu-session-context",
            },

            "trigger": {
                "type": trigger_type,
                "enforcementStage":
                    enforcement_stage,
            },

            "enforcementPoint": {
                "interface": "n6",
                "direction": direction,
                "target": "target-upf",
            },

            "lifecycle": {
                "migrationMode": migration_mode,
                "sourceRemoval":
                    "after-target-active",
            },

            "rules": [
                {
                    "name":
                        f"{intent_id}-rule-1",

                    "priority": 100,

                    "match": match,

                    "enforcement": enforcement,
                }
            ],
        },
    }

    return low_level_policy


# -------------------------------------------------------------------
# 파일 저장
# -------------------------------------------------------------------

def write_text_atomic(path, contents):
    temporary_path = path.with_name(
        f".{path.name}.{os.getpid()}.tmp"
    )

    with temporary_path.open(
        "w",
        encoding="utf-8",
    ) as output:
        output.write(contents)
        output.flush()
        os.fsync(output.fileno())

    os.replace(
        temporary_path,
        path,
    )


def store_low_level_policy(
    intent_id,
    request_id,
    low_level_policy,
):
    intent_policy_dir = POLICY_DIR / intent_id

    intent_policy_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    yaml_text = yaml.safe_dump(
        low_level_policy,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )

    version_path = (
        intent_policy_dir /
        f"{request_id}.yaml"
    )

    latest_path = (
        intent_policy_dir /
        "latest.yaml"
    )

    write_text_atomic(
        version_path,
        yaml_text,
    )

    write_text_atomic(
        latest_path,
        yaml_text,
    )

    return yaml_text, version_path


def append_intent_log(record):
    with INTENT_LOG.open(
        "a",
        encoding="utf-8",
    ) as log_file:
        log_file.write(
            json.dumps(
                record,
                ensure_ascii=False,
            ) + "\n"
        )

        log_file.flush()
        os.fsync(log_file.fileno())


# -------------------------------------------------------------------
# HTTP API
# -------------------------------------------------------------------

@app.get("/health")
def health():
    return jsonify(
        status="ok",
        service="flask-nef-scf",
        translator="i2nsf.5gc/v1alpha1",
    ), 200


@app.post("/intent")
def receive_intent():
    provided_key = request.headers.get(
        "X-SCF-Relay-Key",
        "",
    )

    if not hmac.compare_digest(
        provided_key,
        RELAY_KEY,
    ):
        return jsonify(
            error="NEF relay key invalid"
        ), 401

    if not request.is_json:
        return jsonify(
            error=(
                "Content-Type must be "
                "application/json"
            )
        ), 400

    raw_body = request.get_data(
        cache=True
    )

    try:
        data = json.loads(raw_body)
    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
    ):
        return jsonify(
            error="valid UTF-8 JSON required"
        ), 400

    if not isinstance(data, dict):
        return jsonify(
            error="JSON object required"
        ), 400

    intent_id = data.get("intentId")

    if (
        not isinstance(intent_id, str)
        or not INTENT_ID_PATTERN.fullmatch(
            intent_id
        )
    ):
        return jsonify(
            error="valid string intentId required"
        ), 400

    request_id = request.headers.get(
        "X-Request-ID",
        "",
    )

    if not re.fullmatch(
        r"[a-f0-9]{32}",
        request_id,
    ):
        return jsonify(
            error="valid NEF request ID required"
        ), 400

    try:
        low_level_policy = translate_intent(
            data
        )
    except IntentValidationError as error:
        app.logger.warning(
            "SCF_TRANSLATION_REJECTED "
            "intentId=%s requestId=%s error=%s",
            intent_id,
            request_id,
            error,
        )

        return jsonify(
            status="rejected",
            intentId=intent_id,
            requestId=request_id,
            error=str(error),
        ), 400

    body_hash = hashlib.sha256(
        raw_body
    ).hexdigest()

    with write_lock:
        yaml_text, policy_path = (
            store_low_level_policy(
                intent_id,
                request_id,
                low_level_policy,
            )
        )

        yaml_hash = hashlib.sha256(
            yaml_text.encode("utf-8")
        ).hexdigest()

        record = {
            "receivedAt": datetime.now(
                timezone.utc
            ).isoformat(),

            "intentId": intent_id,
            "requestId": request_id,

            "highLevelSha256": body_hash,
            "lowLevelSha256": yaml_hash,

            "status": "translated",
            "forwardedToCore": False,

            "intent": data,

            "lowLevelPolicyFile": str(
                policy_path.relative_to(
                    BASE_DIR
                )
            ),
        }

        append_intent_log(record)

    app.logger.warning(
        "SCF_TRANSLATED "
        "intentId=%s requestId=%s "
        "highLevelSha256=%s "
        "lowLevelSha256=%s "
        "policyFile=%s",
        intent_id,
        request_id,
        body_hash,
        yaml_hash,
        policy_path,
    )

    return jsonify(
        status="translated",
        intentId=intent_id,
        requestId=request_id,

        highLevelSha256=body_hash,
        lowLevelSha256=yaml_hash,

        lowLevelPolicyFile=str(
            policy_path.relative_to(
                BASE_DIR
            )
        ),

        # NEF 응답을 통해 IUF 화면에서도
        # 변환 결과를 확인할 수 있다.
        lowLevelPolicy=low_level_policy,
        lowLevelYaml=yaml_text,

        forwardedToCore=False,
    ), 201
