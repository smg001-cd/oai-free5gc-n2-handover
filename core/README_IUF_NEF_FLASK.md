# IUF Web → free5GC NEF → Flask SCF 대체 수신기

이 문서는 IUF VM의 웹 화면에서 입력한 security intent를 OAuth로 보호된 free5GC NEF가 받은 뒤, Core VM의 Flask `app.py`로 전달하고 JSONL 파일에 저장하는 전체 적용 절차를 설명한다.

## 주소 표기

이 문서에서는 특정 실험 환경의 고정 IP를 사용하지 않고 다음 변수로 VM을 구분한다.

| 표기 | 의미 |
|---|---|
| `${CORE_VM_IP}` | free5GC NRF, NEF와 Flask 수신기가 실행되는 Core VM의 IPv4 주소 |
| `${IUF_VM_IP}` | IUF 웹 또는 명령줄 클라이언트가 실행되는 IUF VM의 IPv4 주소 |

각 VM에서 실제 주소를 확인한다.

```bash
ip -4 -br addr
```

명령을 실행하기 전에 현재 터미널에 자신의 주소를 설정한다. 아래의 `<...>` 부분은 실제 값으로 바꾼다.

```bash
export CORE_VM_IP="<Core VM IPv4 address>"
export IUF_VM_IP="<IUF VM IPv4 address>"
```

이 변수는 문서의 명령과 Docker Compose 예제에서 계속 사용된다.

## 구현 범위

```text
Browser
  → IUF Web backend (${IUF_VM_IP}:5000)
  → NRF OAuth token issuance (${CORE_VM_IP}:8001)
  → free5GC NEF custom API (${CORE_VM_IP}:8005)
  → Flask SCF substitute (${CORE_VM_IP}:5001)
  → flask-nef/logs/intents.jsonl
```

현재 구현은 IUF → NEF → Flask 기반 SCF 대체 수신기의 통신과 원문 보관을 검증한다. Flask는 정책 변환, PCF·SMF·AMF 호출과 실제 핸드오버 제어를 수행하지 않는다. 응답의 `forwardedToCore=false`는 intent가 Core VM에 저장되지 않았다는 뜻이 아니라, SMF·AMF 정책 처리까지 전달하지 않았다는 뜻이다.

추가한 `/lab-intents/v1/intents`는 실험용 API이며 표준 3GPP NEF API가 아니다.

## 역할 구분

| 구성요소 | 역할 |
|---|---|
| IUF React | intent 입력과 결과 표시 |
| IUF Flask backend | AF 등록, OAuth 토큰 자동 발급·갱신, NEF 호출 |
| NRF | NEF 접근용 OAuth Access Token 발행 |
| 수정된 NEF | OAuth 검증, request ID와 SHA-256 생성, Core Flask로 중계 |
| Core Flask `app.py` | NEF relay key 검증, intent 원문 저장, HTTP 201 응답 |

Core VM의 Python 토큰 발급 파일은 사용하지 않는다. 토큰은 IUF backend가 NRF의 `/oauth2/token`을 호출해 직접 받는다.

## 저장소 파일

```text
core/
├── README_IUF_NEF_FLASK.md
├── docker-compose.nef-snippet.yaml
├── nef/
│   ├── lab_scf.go
│   └── server.go.patch
└── flask-nef/
    ├── app.py
    └── requirements.txt

iuf/
├── README.md
├── examples/policy.json
├── backend/
│   ├── app.py
│   ├── iuf.env.example
│   └── requirements.txt
└── frontend/
    ├── package.json
    ├── public/index.html
    └── src/
        ├── App.js
        ├── App.css
        └── index.js
```

## 1. 전제 조건

- free5GC v4.2.3 기반 `free5gc-compose`
- `base/free5gc/NFs/nef` 소스와 `base/Dockerfile.nf` 존재
- Core VM: `${CORE_VM_IP}`
- IUF VM: `${IUF_VM_IP}`
- NRF OAuth 활성화
- Python 3, Docker, Docker Compose, OpenSSL

다른 환경에서는 IP, PLMN, 포트와 Docker 서비스 이름을 실제 값으로 바꾼다.

```bash
export PROJECT_SOURCE=/home/tjralsrb/oai-free5gc-n2-handover
export FREE5GC_COMPOSE=/home/tjralsrb/free5gc-compose
```

## 2. NRF와 NEF 설정 확인

`$FREE5GC_COMPOSE/config/nrfcfg.yaml`:

```yaml
configuration:
  oauth: true
  DefaultPlmnId:
    mcc: "001"
    mnc: "01"
```

`$FREE5GC_COMPOSE/config/nefcfg.yaml`의 `serviceList`에는 다음 항목이 있어야 한다.

```yaml
serviceList:
  - serviceName: 3gpp-traffic-influence
```

커스텀 API 이름인 `lab-intents`는 `nefcfg.yaml`에 넣지 않는다. NEF 커스텀 라우트의 OAuth scope로 기존 `3gpp-traffic-influence` 서비스를 사용한다.

## 3. NEF 소스 수정

기존 파일을 백업한다.

```bash
cd "$FREE5GC_COMPOSE"

cp -n \
  base/free5gc/NFs/nef/internal/sbi/server.go \
  base/free5gc/NFs/nef/internal/sbi/server.go.before-iuf-relay
```

커스텀 라우트 코드를 복사한다.

```bash
cp "$PROJECT_SOURCE/core/nef/lab_scf.go" \
  base/free5gc/NFs/nef/internal/sbi/lab_scf.go
```

`base/free5gc/NFs/nef/internal/sbi/server.go`에서 다음 두 줄을 찾는다.

```go
s.router = logger_util.NewGinWithLogrus(logger.GinLog)
s.router.Use(metrics.InboundMetrics())
```

바로 아래에 한 줄을 추가한다.

```go
s.mountSCFRelay()
```

최종 형태:

```go
s.router = logger_util.NewGinWithLogrus(logger.GinLog)
s.router.Use(metrics.InboundMetrics())
s.mountSCFRelay()
```

`core/nef/server.go.patch`에서도 같은 변경을 볼 수 있다. 같은 줄을 두 번 추가하지 않는다.

```bash
grep -n -C 3 mountSCFRelay \
  base/free5gc/NFs/nef/internal/sbi/server.go
```

Go 형식을 정리한다.

```bash
gofmt -w \
  base/free5gc/NFs/nef/internal/sbi/lab_scf.go \
  base/free5gc/NFs/nef/internal/sbi/server.go
```

## 4. Core Flask SCF 대체 수신기 배치

```bash
cd "$FREE5GC_COMPOSE"
mkdir -p flask-nef/logs
```

기존 파일이 있다면 백업한 뒤 저장소 파일을 복사한다.

```bash
cp -n flask-nef/app.py flask-nef/app.py.before-iuf-relay

cp "$PROJECT_SOURCE/core/flask-nef/app.py" \
  flask-nef/app.py

cp "$PROJECT_SOURCE/core/flask-nef/requirements.txt" \
  flask-nef/requirements.txt
```

NEF와 Core Flask 사이에서만 사용하는 공유 키를 한 번 생성한다.

```bash
cd "$FREE5GC_COMPOSE/flask-nef"
umask 077
openssl rand -hex 32 | sed 's/^/SCF_RELAY_KEY=/' > scf.env
chmod 600 scf.env
```

이 키는 OAuth Access Token과 다르다.

```text
IUF → NEF    : NRF가 발행한 OAuth Bearer Token
NEF → Flask  : scf.env의 X-SCF-Relay-Key
```

`scf.env`는 Git에 올리지 않는다.

## 5. Docker Compose 수정

`core/docker-compose.nef-snippet.yaml`을 참고하여 실제 `$FREE5GC_COMPOSE/docker-compose.yaml`에 필요한 항목을 병합한다. 기존 서비스의 `volumes`, `networks`, `depends_on`, `command`는 유지한다.

### NRF 외부 포트

IUF backend가 NRF에서 토큰을 직접 발급받을 수 있도록 Core VM `8001`을 NRF 컨테이너 `8000`에 연결한다.

```yaml
free5gc-nrf:
  ports:
    - "${CORE_VM_IP}:8001:8000"
```

### NEF 빌드와 외부 포트

```yaml
free5gc-nef:
  build:
    context: ./base
    dockerfile: Dockerfile.nf
    args:
      F5GC_MODULE: nef
  image: free5gc/nef:iuf-relay
  ports:
    - "${CORE_VM_IP}:8005:8000"
  env_file:
    - ./flask-nef/scf.env
  environment:
    GIN_MODE: release
    SCF_INTENT_URL: http://${CORE_VM_IP}:5001/intent
```

설정을 검사한다.

```bash
cd "$FREE5GC_COMPOSE"
docker compose config --quiet
```

호스트 방화벽을 사용하면 IUF VM만 허용한다.

```bash
sudo ufw allow from ${IUF_VM_IP} to any port 8001 proto tcp
sudo ufw allow from ${IUF_VM_IP} to any port 8005 proto tcp
```

Core Flask `5001`은 NEF 컨테이너가 접근해야 한다. Docker와 호스트 방화벽 구성에 따라 `privnet` 대역 또는 필요한 출발지만 허용한다.

## 6. NEF 이미지 빌드와 Core 서비스 적용

기반 이미지가 없으면 먼저 만든다.

```bash
cd "$FREE5GC_COMPOSE"

docker image inspect free5gc/base >/dev/null 2>&1 || \
docker build -t free5gc/base -f base/Dockerfile base
```

NEF를 빌드한다.

```bash
docker compose build free5gc-nef
```

NRF를 먼저 적용하고 NEF를 시작한다. NRF 재시작 뒤 NEF를 다시 시작하면 NEF profile이 NRF에 등록된다.

```bash
docker compose up -d --no-deps --force-recreate free5gc-nrf
docker compose up -d --no-deps --force-recreate free5gc-nef
```

전체 코어를 함께 시작하려면:

```bash
docker compose up -d --build
```

상태를 확인한다.

```bash
docker compose ps free5gc-nrf free5gc-nef
docker compose port free5gc-nrf 8000
docker compose port free5gc-nef 8000
docker inspect nef --format '{{.Config.Image}}'
```

예상 외부 주소:

```text
NRF  ${CORE_VM_IP}:8001
NEF  ${CORE_VM_IP}:8005
```

등록 로그를 확인한다.

```bash
docker compose logs --since 2m free5gc-nrf free5gc-nef
```

NEF 로그에 다음 내용이 있어야 한다.

```text
OAuth2 setting receive from NRF: true
register to NRF successfully
```

## 7. Core Flask 실행

Python 환경을 한 번 만든다.

```bash
cd "$FREE5GC_COMPOSE"
python3 -m venv .venv-core
source .venv-core/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r flask-nef/requirements.txt
python3 -m py_compile flask-nef/app.py
```

Core Flask를 실행한다.

```bash
cd "$FREE5GC_COMPOSE/flask-nef"
source "$FREE5GC_COMPOSE/.venv-core/bin/activate"

set -a
source scf.env
set +a

mkdir -p logs

python3 -m gunicorn \
  --bind 0.0.0.0:5001 \
  --workers 1 \
  --threads 4 \
  --timeout 30 \
  --access-logfile - \
  --error-logfile - \
  app:app 2>&1 | tee -a logs/flask.log
```

정상 상태:

```bash
curl -s http://127.0.0.1:5001/health | python3 -m json.tool
```

```json
{
  "service": "flask-nef-scf",
  "status": "ok"
}
```

NEF 컨테이너에서도 확인한다.

```bash
docker compose exec free5gc-nef \
  wget -qO- http://${CORE_VM_IP}:5001/health
```

## 8. IUF 설치와 실행

IUF VM에서는 저장소의 `iuf/README.md`를 따른다. IUF backend가 다음 작업을 자동으로 수행한다.

```text
AF ID 생성 및 유지
→ NRF에 AF profile 등록
→ targetNfType=NEF, scope=3gpp-traffic-influence 토큰 요청
→ IUF VM의 backend/oauth/token.json 저장
→ NEF 요청에 Bearer Token 추가
→ 만료 전 자동 재발급
```

Core VM에서는 별도의 Python 토큰 발급 스크립트를 실행하지 않는다.

## 9. 전체 전달 검증

IUF 웹에서 intent를 보내고 응답의 `requestId`를 기록한다.

NEF 로그:

```bash
cd "$FREE5GC_COMPOSE"
docker compose logs --since 10m free5gc-nef | grep NEF_INTENT
```

예상 로그:

```text
NEF_INTENT intentId=intent-001 requestId=... sha256=... received
NEF_INTENT intentId=intent-001 requestId=... scf_status=201
```

Core Flask 실행 로그:

```bash
tail -n 20 "$FREE5GC_COMPOSE/flask-nef/logs/flask.log"
```

저장된 전체 intent:

```bash
tail -n 1 "$FREE5GC_COMPOSE/flask-nef/logs/intents.jsonl" | \
python3 -m json.tool
```

실시간 확인:

```bash
tail -f "$FREE5GC_COMPOSE/flask-nef/logs/intents.jsonl"
```

IUF 웹 응답, NEF 로그와 `intents.jsonl`의 `requestId` 및 SHA-256이 같으면 다음 경로가 확인된 것이다.

```text
IUF Web → IUF backend → NEF → Flask SCF substitute → JSONL
```

## 10. 재시작 순서

Core VM 재부팅 또는 Docker 재생성 후:

```bash
cd "$FREE5GC_COMPOSE"
docker compose up -d
docker compose restart free5gc-nef
```

Core Flask를 실행하고 IUF backend를 실행한다. IUF backend의 메모리 토큰이 없어도 첫 intent 전송 시 NRF에서 자동 발급하므로 Core의 토큰 발급 작업은 필요 없다.

## 오류 해결

| 오류 | 확인할 내용 |
|---|---|
| `401 verify OAuth Authorization header invalid` | IUF backend 자동 갱신 로그, NRF·NEF 시간과 인증서 확인 |
| `400 valid string intentId required` | 최상위 문자열 `intentId` 확인 |
| `404 Not Found` | 수정한 NEF 이미지와 `mountSCFRelay()` 적용 확인 |
| NRF `8001 Connection refused` | `free5gc-nrf`의 `${CORE_VM_IP}:8001:8000` 매핑 확인 |
| NEF `8005 Connection refused` | `free5gc-nef`의 `${CORE_VM_IP}:8005:8000` 매핑 확인 |
| `invalid_client` 또는 `no producerNfInfor` | NRF 기동 후 NEF 재시작 및 등록 성공 확인 |
| `502 SCF connection failed` | Core Flask `5001`, `SCF_INTENT_URL`, 방화벽 확인 |
| `401 NEF relay key invalid` | NEF와 Core Flask가 같은 `scf.env` 값을 읽는지 확인 |
| `No space left on device` | `docker builder prune -f`; MongoDB 볼륨은 삭제하지 않음 |

`docker system prune --volumes`는 MongoDB 데이터 볼륨까지 삭제할 수 있으므로 사용하지 않는다.


