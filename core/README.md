# 3. Core VM — NEF OAuth relay와 Flask 정책 변환기

[전체 목차](../README.md) · 이전: [Firewall NSF](../docs/02-firewall.md) · 다음: [IUF 웹](../iuf/README.md)

## 1. 이 단계의 목표

```text
IUF backend (VM5:5000)
  → NRF (VM1:8001): AF 등록·OAuth token 발급
  → 수정한 NEF (VM1:8005): Bearer token 검증·requestId 생성
  → Core Flask (VM1:5001): relay key 검증·intent 검증·정책 YAML 변환
  → flask-nef/logs/intents.jsonl
  → flask-nef/policies/<intentId>/<requestId>.yaml 및 latest.yaml
```

현재 `flask-nef/app.py`는 단순 원문 수신기를 넘어 High-level intent를 Low-level YAML로 변환합니다. HTTP 201은 변환·저장이 완료되었다는 뜻입니다. SMF·AMF 호출, UE IP 조회, Firewall NSF 설치와 자동 HO 제어는 수행하지 않습니다.

실행 위치는 `$FREE5GC_COMPOSE`입니다. 이 저장소의 `core/docker-compose.yaml`은 upstream 전체 `config/`, `cert/`, 로컬 빌드 소스를 참조하므로 `cd core && docker compose up`만 실행하면 준비가 끝나지 않습니다.

아래 명령은 모두 **VM1**에서 실행합니다. [0단계](../docs/00-environment.md)와 [1단계 Core 배치](../docs/01-handover.md)를 먼저 완료하세요. IUF 전달만 시험할 때에는 OAI/UPF 없이 Core NRF·NEF·Flask와 IUF를 준비할 수 있습니다.

## 2. free5GC v4.2.3 빌드 소스 준비

NEF에 커스텀 API를 추가하므로 기본 `free5gc/nef:v4.2.3` 이미지만 받아서는 동작하지 않습니다. 소스가 없을 때:

```bash
source "$HOME/lab.env"
cd "$FREE5GC_COMPOSE"
git clone --branch v4.2.3 --recursive \
  https://github.com/free5gc/free5gc.git base/free5gc
git -C base/free5gc submodule status NFs/nef
test -f base/free5gc/NFs/nef/internal/sbi/server.go
test -f base/Dockerfile.nf
sudo apt install -y golang-go
```

이미 `base/free5gc`가 있으면 재 clone하지 않습니다. `git -C base/free5gc status --short`, `describe --tags --always`, `submodule status`를 확인하고 기존 수정 사항을 보존합니다. 다른 free5GC 버전을 섞으면 NEF의 내부 API와 패치 위치가 달라질 수 있습니다. 호스트 Go는 여기서 `gofmt`에 사용하고 실제 NEF 컴파일은 upstream Docker 빌드 환경에서 수행합니다.

## 3. NEF 라우트 추가

```bash
cd "$FREE5GC_COMPOSE"
cp -n base/free5gc/NFs/nef/internal/sbi/server.go \
  base/free5gc/NFs/nef/internal/sbi/server.go.before-iuf-relay
if [ -f base/free5gc/NFs/nef/internal/sbi/lab_scf.go ]; then
  cp -n base/free5gc/NFs/nef/internal/sbi/lab_scf.go \
    base/free5gc/NFs/nef/internal/sbi/lab_scf.go.before-iuf-relay
fi
cp "$PROJECT_SOURCE/core/nef/lab_scf.go" \
  base/free5gc/NFs/nef/internal/sbi/lab_scf.go

grep -n -C 3 'InboundMetrics\|NewGinWithLogrus\|mountSCFRelay' \
  base/free5gc/NFs/nef/internal/sbi/server.go
nano base/free5gc/NFs/nef/internal/sbi/server.go
```

router 생성 직후, 다음 두 줄 아래에 `s.mountSCFRelay()`를 한 번 추가합니다.

```go
s.router = logger_util.NewGinWithLogrus(logger.GinLog)
s.router.Use(metrics.InboundMetrics())
s.mountSCFRelay()
```

`nano`: `Ctrl+W`로 `InboundMetrics` 검색 → 줄 추가 → `Ctrl+O`, `Enter`, `Ctrl+X`. 같은 줄이 이미 있으면 추가하지 않습니다. 위치가 다르면 해당 버전 소스를 확인하고, router가 생성되기 전에 호출하지 않습니다. `nef/server.go.patch`는 변경 위치를 보여 주는 참고 diff입니다. hunk 줄 번호가 없는 파일이므로 `git apply` 명령으로 적용하지 않습니다.

```bash
gofmt -w base/free5gc/NFs/nef/internal/sbi/lab_scf.go \
  base/free5gc/NFs/nef/internal/sbi/server.go
grep -n 's.mountSCFRelay()' base/free5gc/NFs/nef/internal/sbi/server.go
```

출력이 한 줄인지 확인합니다.

## 4. Flask 파일·공유 키 배치

```bash
cd "$FREE5GC_COMPOSE"
mkdir -p flask-nef/logs flask-nef/policies
if [ -f flask-nef/app.py ]; then
  cp -n flask-nef/app.py flask-nef/app.py.before-iuf-relay
fi
cp "$PROJECT_SOURCE/core/flask-nef/app.py" flask-nef/app.py
cp "$PROJECT_SOURCE/core/flask-nef/requirements.txt" flask-nef/requirements.txt

if [ ! -s flask-nef/scf.env ]; then
  (umask 077; openssl rand -hex 32 | sed 's/^/SCF_RELAY_KEY=/' > flask-nef/scf.env)
fi
chmod 600 flask-nef/scf.env
```

1단계에서 만든 키를 그대로 사용합니다. 재실행할 때 키를 바꾸면 이미 실행 중인 NEF와 Flask의 키가 달라집니다. 두 인증 수단은 다릅니다.

| 연결 | 인증 |
|---|---|
| IUF → NEF | NRF에서 발급받은 OAuth Bearer token |
| NEF → Core Flask | 동일 `scf.env`의 `X-SCF-Relay-Key` |

키·토큰·실행 로그·생성 정책 파일은 Git에 올리지 않습니다.

## 5. NRF·NEF 설정과 Compose 확인

NRF의 OAuth 위치는 **`configuration.sbi.oauth`**입니다. `configuration.oauth`로 잘못 넣지 않습니다. [upstream v4.2.3 설정](https://github.com/free5gc/free5gc-compose/blob/v4.2.3/config/nrfcfg.yaml)의 구조를 따릅니다.

```yaml
configuration:
  sbi:
    oauth: true
  DefaultPlmnId:
    mcc: "001"
    mnc: "01"
```

이는 확인할 부분만 보여 주는 발췌입니다. 기존 설정 파일 전체를 이 조각으로 덮어쓰지 않습니다. 1단계의 설정 명령은 이 값을 이미 적용합니다.

```bash
cd "$FREE5GC_COMPOSE"
nano config/nefcfg.yaml
```

NEF의 `configuration.serviceList`에 아래 서비스가 있는지 확인합니다. 기존 서비스 설정은 유지합니다.

```yaml
serviceList:
  - serviceName: 3gpp-traffic-influence
```

커스텀 API의 OAuth scope는 `3gpp-traffic-influence`를 재사용합니다. `lab-intents`를 표준 서비스 이름으로 등록하지 않습니다.

1단계에서 복사한 Compose의 NEF 설정은 다음과 연결됩니다.

| 항목 | 값 |
|---|---|
| NRF 포트 | `${CORE_VM_IP}:8001:8000` |
| NEF 포트 | `${CORE_VM_IP}:8005:8000` |
| NEF image | `free5gc/nef:scf-local` |
| NEF build | `context: ./base`, `dockerfile: Dockerfile.nf`, `F5GC_MODULE: nef` |
| NEF env_file | `./flask-nef/scf.env` |
| NEF `SCF_INTENT_URL` | `http://${CORE_VM_IP}:5001/intent` |

```bash
source "$HOME/lab.env"
cd "$FREE5GC_COMPOSE"
docker compose config --quiet
```

실제 NEF 컨테이너에서 Core 호스트 `5001`에 접근할 수 있어야 합니다. NEF 내부의 `127.0.0.1`은 Core 호스트가 아닌 NEF 컨테이너 자신입니다.

## 6. NEF 이미지 빌드와 실행

```bash
cd "$FREE5GC_COMPOSE"
docker image inspect free5gc/base >/dev/null 2>&1 || \
  docker build -t free5gc/base -f base/Dockerfile base
docker compose build free5gc-nef
docker compose up -d free5gc-nef
docker compose ps free5gc-nrf free5gc-nef
docker compose port free5gc-nrf 8000
docker compose port free5gc-nef 8000
docker inspect nef --format '{{.Config.Image}}'
docker compose logs --since 5m free5gc-nrf free5gc-nef
```

`free5gc/nef:scf-local`, NRF·NEF의 외부 포트와 NRF 등록 성공을 확인합니다. `OAuth2 setting receive from NRF: true`, `register to NRF successfully`와 같은 메시지를 찾습니다. NRF 설정을 바꾼 경우에는 NRF를 재생성한 뒤 **다른 NF들도 재시작해 다시 등록**합니다. 진행 중인 UE 실험은 먼저 종료합니다.

```bash
docker compose up -d --no-deps --force-recreate free5gc-nrf
docker compose restart free5gc-amf free5gc-smf free5gc-ausf \
  free5gc-udm free5gc-udr free5gc-nssf free5gc-pcf free5gc-webui free5gc-nef
```

NEF만 처음 추가할 때에는 NRF를 불필요하게 재생성할 필요가 없습니다.

## 7. Core Flask 실행

처음 한 번 Python 가상환경을 설치합니다.

```bash
source "$HOME/lab.env"
cd "$FREE5GC_COMPOSE"
python3 -m venv .venv-core
source .venv-core/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r flask-nef/requirements.txt
python3 -m py_compile flask-nef/app.py
```

전용 터미널에서 실행하고 켜 둡니다.

```bash
source "$HOME/lab.env"
source "$FREE5GC_COMPOSE/.venv-core/bin/activate"
cd "$FREE5GC_COMPOSE/flask-nef"
set -a
source scf.env
set +a
mkdir -p logs policies
set -o pipefail
python3 -m gunicorn --bind 0.0.0.0:5001 \
  --workers 1 --threads 4 --timeout 30 \
  --access-logfile - --error-logfile - \
  app:app 2>&1 | tee -a logs/flask.log
```

worker는 1개를 유지합니다. 파일 쓰기 잠금은 현재 프로세스 내부의 `threading.Lock`이며 여러 worker 간 공유 잠금이 아닙니다.

다른 VM1 터미널에서:

```bash
source "$HOME/lab.env"
curl --fail-with-body -sS http://127.0.0.1:5001/health | python3 -m json.tool
cd "$FREE5GC_COMPOSE"
docker compose exec free5gc-nef wget -qO- "http://$CORE_VM_IP:5001/health"
```

정상 health의 주요 필드:

```json
{"status":"ok","service":"flask-nef-scf","translator":"i2nsf.5gc/v1alpha1"}
```

health 성공은 OAuth·정책 변환까지 시험한 결과는 아닙니다. 토큰 없는 NEF 요청도 확인합니다.

```bash
curl -i --max-time 5 -X POST \
  "http://$CORE_VM_IP:8005/lab-intents/v1/intents" \
  -H 'Content-Type: application/json' --data '{"intentId":"probe"}'
```

OAuth가 정상 적용되어 있으면 `401`입니다. `404`면 수정한 이미지·라우트 적용을 확인합니다. 이 요청은 토큰이 없어야 하는 인증 점검용이며 실제 변환 예제가 아닙니다.

## 8. IUF에서 전송 후 저장 결과 검증

먼저 [IUF 설치·전송](../iuf/README.md)을 완료합니다. 그 뒤 VM1에서:

```bash
source "$HOME/lab.env"
cd "$FREE5GC_COMPOSE"
docker compose logs --since 10m free5gc-nef | grep NEF_INTENT
tail -n 20 flask-nef/logs/flask.log
tail -n 1 flask-nef/logs/intents.jsonl | python3 -m json.tool
find flask-nef/policies -type f -name '*.yaml'
cat flask-nef/policies/handover-fw-001/latest.yaml
```

같은 `intentId`를 여러 번 전송하면 request ID별 YAML을 남기고 `latest.yaml`이 최신 변환으로 갱신됩니다.

다음 명령은 마지막 JSONL 레코드가 가리키는 YAML의 hash를 확인합니다.

```bash
python3 - <<'PY'
import hashlib
import json
from pathlib import Path
root = Path('flask-nef')
record = json.loads((root / 'logs/intents.jsonl').read_text().splitlines()[-1])
path = root / record['lowLevelPolicyFile']
assert hashlib.sha256(path.read_bytes()).hexdigest() == record['lowLevelSha256']
print('requestId:', record['requestId'])
print('highLevelSha256:', record['highLevelSha256'])
print('YAML hash OK:', path)
PY
```

IUF 응답의 `requestId`, `result.highLevelSha256`가 NEF 로그의 `requestId`, `sha256` 및 JSONL 값과 같아야 합니다. IUF backend가 JSON을 다시 직렬화하므로 원본 예제 파일의 `sha256sum`은 NEF가 받은 HTTP body hash와 다를 수 있습니다.

`spec.selector.ueAddressSource=smf-pdu-session-context`, `migrationMode=make-before-break`는 생성 정책의 선언입니다. SMF 조회·Target 적용을 실제로 실행했다는 뜻은 아닙니다. `forwardedToCore=false`와 함께 해석합니다.

다음: [4. IUF 웹 설치·intent 전송](../iuf/README.md). 오류는 [운영 문서](../docs/03-operations.md)를 확인합니다.
