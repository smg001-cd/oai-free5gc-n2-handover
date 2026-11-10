# 4. IUF VM — 웹 설치와 intent 전송

[전체 목차](../README.md) · 이전: [Core NEF·Flask](../core/README.md) · 다음: [운영·오류 해결](../docs/03-operations.md)

## 1. 시작 전 확인

이 문서의 명령은 모두 **VM5 IUF**에서 실행합니다. Core VM에서 NRF `8001`, 수정한 NEF `8005`, Core Flask `5001`이 준비되어 있어야 합니다. VM5의 React 웹과 Flask backend는 `5000`을 사용합니다. `npm start`를 별도 실행하지 않고, 빌드된 React를 Flask가 제공합니다.

```bash
source "$HOME/lab.env"
test -f "$IUF_ROOT/backend/app.py"
curl -i --max-time 5 "http://$CORE_VM_IP:8001/nnrf-nfm/v1/nf-instances"
curl -i --max-time 5 -X POST \
  "http://$CORE_VM_IP:8005/lab-intents/v1/intents" \
  -H 'Content-Type: application/json' --data '{"intentId":"probe"}'
```

NRF의 HTTP 응답이 오는지, 두 번째 NEF 요청이 `401`인지 봅니다. 토큰 없는 요청에서 `401`은 OAuth 보호 점검의 정상 결과입니다. `404`는 라우트가 없다는 뜻일 수 있고, `Connection refused`는 서비스·포트·주소를 확인해야 합니다.

## 2. Node.js 설치와 React 빌드

이미 Node 22를 사용한다면 설치 단계는 건너뜁니다.

```bash
node --version
npm --version
```

Node 또는 nvm이 없다면 [nvm v0.40.3 공식 설치 안내](https://github.com/nvm-sh/nvm/tree/v0.40.3#installing-and-updating)에 따라 설치합니다. 아래는 설치 스크립트를 내려받아 확인한 뒤 실행하는 예제입니다.

```bash
curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh \
  -o /tmp/install-nvm.sh
less /tmp/install-nvm.sh
bash /tmp/install-nvm.sh
export NVM_DIR="$HOME/.nvm"
source "$NVM_DIR/nvm.sh"
nvm install 22
nvm use 22
node --version
npm --version
```

`less`는 `q`로 나갑니다. 기존 nvm 설치 경로가 다르면 그 경로의 `nvm.sh`를 읽습니다.

React를 빌드합니다.

```bash
source "$HOME/lab.env"
cd "$IUF_ROOT/frontend"
if [ -f package-lock.json ]; then npm ci; else npm install; fi
npm run build
test -f build/index.html && echo 'React build OK'
```

원본에는 lockfile이 없으므로 첫 설치는 `npm install`입니다. 만들어진 lockfile을 유지하면 같은 환경에서 `npm ci`로 재설치할 수 있습니다. 이 가이드는 lockfile과 `node_modules`를 무조건 삭제하는 절차를 사용하지 않습니다. 소스를 바꾼 뒤에는 `npm run build`를 다시 실행합니다.

## 3. Python backend 설치

```bash
source "$HOME/lab.env"
cd "$IUF_ROOT/backend"
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
python3 -m py_compile app.py
```

처음 한 번 환경 파일을 만듭니다. 기존 파일은 덮어쓰지 않습니다.

```bash
cp -n iuf.env.example iuf.env
chmod 600 iuf.env
nano iuf.env
```

`<Core VM IPv4 address>`, `<IUF VM IPv4 address>`를 실제 IPv4로 바꿉니다. 예를 들어 이 가이드의 주소라면:

```bash
CORE_VM_IP="192.168.192.145"
IUF_VM_IP="192.168.192.147"
NEF_URL="http://${CORE_VM_IP}:8005/lab-intents/v1/intents"
NRF_URL="http://${CORE_VM_IP}:8001"
AF_IP="${IUF_VM_IP}"
PLMN_MCC="001"
PLMN_MNC="01"
```

이 파일은 Bash로 `source`합니다. 주소 변수 선언을 URL 선언보다 위에 둬야 `${CORE_VM_IP}`가 올바르게 확장됩니다. `AF_IP`는 IUF VM의 IP입니다. Core의 IP로 넣지 않습니다.

## 4. IUF 웹 실행

VM5의 전용 터미널에서:

```bash
source "$HOME/lab.env"
cd "$IUF_ROOT/backend"
source .venv/bin/activate
set -a
source iuf.env
set +a
mkdir -p logs
set -o pipefail
python3 -m gunicorn --bind 0.0.0.0:5000 \
  --workers 1 --threads 4 --timeout 120 \
  --access-logfile - --error-logfile - \
  app:app 2>&1 | tee -a logs/iuf-web.log
```

`Listening at: http://0.0.0.0:5000`가 나오면 이 터미널은 켜 둡니다. 단일 worker를 사용하여 메모리 토큰·파일 상태 관리를 단순하게 유지합니다.

VM5의 다른 터미널에서:

```bash
source "$HOME/lab.env"
curl --fail-with-body -sS http://127.0.0.1:5000/api/health | python3 -m json.tool
```

`status=ok`, `service=iuf-web`, `automaticOAuth=true`와 실제 `nefUrl`을 확인합니다. 이 health는 backend 설정만 확인하며 NRF·NEF까지 호출하지는 않습니다.

Windows 또는 다른 장비의 브라우저에서 `http://IUF실제IP:5000`을 엽니다. VM5 안의 브라우저라면 `http://127.0.0.1:5000`입니다.

## 5. 웹 화면에서 입력할 값

현재 화면은 **High-level intent**를 만듭니다. 예전 형식의 `ueIp`, `appId`, `targetDnai`, `policy.action=record-only`는 현재 변환기의 입력 형식이 아닙니다.

| 항목 | 첫 시험 값 |
|---|---|
| Intent ID | `handover-fw-001` |
| UE SUPI | `imsi-001010000000001` |
| DNN | `oai` |
| SST / SD | `1` / `010203` |
| Destination IPv4/CIDR | `8.8.8.8/32` |
| Protocol | `icmp` 또는 `any` |
| Direction | `n6-egress` |
| NSF Type / Action | `firewall` / `drop` |
| Handover stage | `before-path-switch` |
| Migration mode | `make-before-break` |

ICMP·any에는 destination port를 지정하지 않습니다. TCP·UDP일 때만 1~65535의 port를 선택합니다. Intent ID는 영문·숫자·`_.:-` 1~128자입니다.

전송 버튼을 누르면 IUF backend가 자동으로 다음 작업을 수행합니다.

```text
AF ID 생성 또는 재사용
→ NRF에 AF profile 등록
→ targetNfType=NEF, scope=3gpp-traffic-influence 토큰 발급
→ NEF에 Bearer token으로 intent 전송
→ NEF가 Core Flask 응답 중계
→ 웹에서 Low-level YAML 확인·다운로드
```

Core에서 별도의 `issue_token.py`를 실행할 필요가 없습니다. 토큰 만료 60초 전부터 다음 요청 시 갱신하고, NEF가 `401`이면 강제로 토큰을 갱신하여 한 번 재시도합니다.

## 6. 웹 대신 curl로 같은 경로 시험

VM5의 점검 터미널에서:

```bash
source "$HOME/lab.env"
python3 -m json.tool "$IUF_ROOT/examples/policy.json" >/dev/null
curl --fail-with-body -i --max-time 90 \
  -X POST http://127.0.0.1:5000/api/intents \
  -H 'Content-Type: application/json' \
  --data-binary @"$IUF_ROOT/examples/policy.json"
```

이 브랜치의 `examples/policy.json`은 현재 Core 변환기가 요구하는 `subject`, `traffic`, `securityControl`을 포함합니다. `/api/intents`에 보내면 IUF backend가 인증을 처리하므로 curl에 token을 직접 붙이지 않습니다. NEF의 `/lab-intents/v1/intents`에 직접 보낼 때에는 별도 OAuth token이 필요합니다.

성공 시 HTTP `201`과 다음 주요 필드를 확인합니다. 아래는 응답에서 확인할 필드의 예시이며 전체 응답에는 정책 본문과 YAML도 들어 있습니다.

```json
{
  "ok": true,
  "upstreamStatus": 201,
  "requestId": "32자리 소문자 hex",
  "result": {
    "status": "translated",
    "intentId": "handover-fw-001",
    "forwardedToCore": false
  }
}
```

`result.lowLevelPolicy`, `result.lowLevelYaml`, `result.lowLevelPolicyFile`, 두 hash도 확인합니다. HTTP 201은 정책 변환·파일 저장 성공이며 실제 UE 차단 성공을 뜻하지 않습니다. 실제 차단은 [2단계](../docs/02-firewall.md)에서 따로 시험합니다.

## 7. 로그와 token 상태 확인

VM5에서:

```bash
source "$HOME/lab.env"
tail -n 30 "$IUF_ROOT/backend/logs/iuf-web.log"
ls -l "$IUF_ROOT/backend/oauth"
```

최초 token 발급 이후 `oauth/af-id.txt`, `oauth/token.json`이 생깁니다. `af-id.txt`만 있으면 AF 등록 또는 token 발급 단계에서 중단되었을 수 있습니다. token 원문 대신 존재·만료 정보만 확인합니다.

```bash
cd "$IUF_ROOT/backend"
python3 - <<'PY'
import json
import time
from pathlib import Path
p = Path('oauth/token.json')
if not p.exists():
    raise SystemExit('No token file: send an intent and check NRF/IUF logs')
token = json.loads(p.read_text())
print('token present:', bool(token.get('access_token')))
print('seconds remaining:', int(float(token.get('_expires_at', 0)) - time.time()))
PY
```

VM1의 [JSONL·YAML 검증 명령](../core/README.md#8-iuf에서-전송-후-저장-결과-검증)으로 같은 `requestId`와 hash를 확인하면 전체 전달·변환 경로가 확인됩니다.

## 8. 지원 action의 의미

| NSF | 변환기가 built-in으로 표현하는 action |
|---|---|
| firewall | `drop`, `reject`, `accept`, `log` |
| anti-ddos | `rate-limit`, `drop`, `alert`, `redirect-scrubber` |

Anti-DDoS에는 `parameters.detectionThresholdPps >= 1`, `rate-limit`에는 추가로 `parameters.rateLimitMbps >= 1`이 필요합니다. 다른 유효 action 이름은 `actionProfile=extension`으로 보존됩니다. 이는 YAML 변환 기능이며 이 저장소에 해당 action 집행기가 모두 구현된 것은 아닙니다.

오류 해결·재시작: [5. 운영 문서](../docs/03-operations.md).
