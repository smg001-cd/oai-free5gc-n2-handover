# IUF → free5GC NEF → Flask intent 전달 실험

이 문서는 별도의 기존 SCF 프로젝트를 실행하지 않고 Flask `app.py`를 최소한의 SCF 대체 수신기로 사용하여 다음 경로를 검증한 방법을 설명한다.

```text
IUF VM (192.168.192.147)
  → free5GC NEF (Core VM 192.168.192.145:8005)
  → Flask app.py (Core VM 192.168.192.145:5001)
  → flask-nef/logs/intents.jsonl
```

검증 범위는 intent 원문이 OAuth 인증을 거쳐 실제 NEF에 도착하고, NEF가 Flask로 전달하여 파일에 저장되는 단계까지다. `forwardedToCore=false`는 SMF·AMF 정책 적용과 핸드오버 실행은 아직 연결하지 않았다는 의미다.

추가한 `/lab-intents/v1/intents`는 실험용 API이며 표준 3GPP NEF API가 아니다. 기존 free5GC Traffic Influence API는 단일 UE 요청을 PCF로, 그룹 요청을 UDR로 처리하므로 임의 intent 원문 전달에는 별도 라우트가 필요하다.

## 저장소 파일

```text
core/
├── README_IUF_NEF_FLASK.md
├── docker-compose.nef-snippet.yaml
├── examples/policy.json
├── nef/
│   ├── lab_scf.go
│   └── server.go.patch
└── flask-nef/
    ├── app.py
    ├── issue_token.py
    └── requirements.txt
```

토큰, AF UUID, 공유 키, 가상환경과 실행 로그는 저장소에 포함하지 않는다. `core/.gitignore`가 이를 제외한다.

## 1. 전제 조건

- free5GC v4.2.3 기반 `free5gc-compose`
- `base/free5gc/NFs/nef` 소스와 `base/Dockerfile.nf`가 존재
- NRF OAuth 활성화
- NEF의 `serviceList`에 `3gpp-traffic-influence` 존재
- Python 3, Docker, Docker Compose, OpenSSL
- 아래 예시의 Core VM IP는 `192.168.192.145`, IUF VM IP는 `192.168.192.147`

다른 환경에서는 두 IP, PLMN, Docker 네트워크와 포트를 실제 값으로 바꾼다.

저장소와 free5gc-compose가 서로 다른 디렉터리에 있다고 가정한다.

```bash
git clone https://github.com/smg001-cd/oai-free5gc-n2-handover.git \
  /home/tjralsrb/oai-free5gc-n2-handover
RELAY_SOURCE=/home/tjralsrb/oai-free5gc-n2-handover
FREE5GC_COMPOSE=/home/tjralsrb/free5gc-compose
```

`config/nrfcfg.yaml`의 관련 설정:

```yaml
configuration:
  oauth: true
  DefaultPlmnId:
    mcc: "001"
    mnc: "01"
```

`config/nefcfg.yaml`에는 다음 서비스가 있어야 한다.

```yaml
serviceList:
  - serviceName: 3gpp-traffic-influence
```

커스텀 이름인 `lab-intents`는 `nefcfg.yaml`에 추가하지 않는다.

## 2. NEF 소스 수정

free5gc-compose 루트에서 실행한다.

```bash
cd "$FREE5GC_COMPOSE"
```

기존 서버 파일을 백업한다.

```bash
cp -n \
  base/free5gc/NFs/nef/internal/sbi/server.go \
  base/free5gc/NFs/nef/internal/sbi/server.go.before-scf
```

저장소의 Go 파일을 NEF 소스에 복사한다. 저장소를 별도 위치에 clone했다면 앞 경로를 해당 위치로 변경한다.

```bash
cp "$RELAY_SOURCE/core/nef/lab_scf.go" \
  base/free5gc/NFs/nef/internal/sbi/lab_scf.go
```

`base/free5gc/NFs/nef/internal/sbi/server.go`에서 다음 코드 바로 아래에 라우트 등록 한 줄을 추가한다.

```go
s.router = logger_util.NewGinWithLogrus(logger.GinLog)
s.router.Use(metrics.InboundMetrics())
s.mountSCFRelay()
```

변경 내용은 `core/nef/server.go.patch`에도 표시되어 있다. 같은 줄을 중복 추가하지 않는다.

```bash
grep -n -C 3 'mountSCFRelay' \
  base/free5gc/NFs/nef/internal/sbi/server.go
```

Go가 설치되어 있으면 형식을 정리한다.

```bash
gofmt -w \
  base/free5gc/NFs/nef/internal/sbi/lab_scf.go \
  base/free5gc/NFs/nef/internal/sbi/server.go
```

## 3. Flask 코드 배치와 공유 키 생성

```bash
cd "$FREE5GC_COMPOSE"
mkdir -p flask-nef/logs
```

기존 `flask-nef/app.py`가 있다면 먼저 백업하고 저장소 파일을 복사한다.

```bash
cp -n flask-nef/app.py flask-nef/app.py.before-iuf-nef-relay
cp "$RELAY_SOURCE/core/flask-nef/app.py" flask-nef/app.py
cp "$RELAY_SOURCE/core/flask-nef/issue_token.py" flask-nef/issue_token.py
cp "$RELAY_SOURCE/core/flask-nef/requirements.txt" flask-nef/requirements.txt
```

NEF와 Flask가 공유할 키를 한 번 생성한다.

```bash
cd /home/tjralsrb/free5gc-compose/flask-nef
umask 077
openssl rand -hex 32 | sed 's/^/SCF_RELAY_KEY=/' > scf.env
chmod 600 scf.env
```

`scf.env`는 Git에 올리지 않는다.

## 4. Docker Compose의 NEF 서비스 수정

`core/docker-compose.nef-snippet.yaml`을 참고하여 실제 `docker-compose.yaml`의 `free5gc-nef` 서비스에 `build`, 새 이미지, 외부 포트, `env_file`, `SCF_INTENT_URL`을 병합한다. 기존 `volumes`, `networks`, `depends_on`은 유지한다.

```yaml
free5gc-nef:
  container_name: nef
  build:
    context: ./base
    dockerfile: Dockerfile.nf
    args:
      F5GC_MODULE: nef
  image: free5gc/nef:scf-local
  command: ./nef -c ./config/nefcfg.yaml
  expose:
    - "8000"
  ports:
    - "192.168.192.145:8005:8000"
  volumes:
    - ./config/nefcfg.yaml:/free5gc/config/nefcfg.yaml
    - ./cert:/free5gc/cert
  env_file:
    - ./flask-nef/scf.env
  environment:
    GIN_MODE: release
    SCF_INTENT_URL: http://192.168.192.145:5001/intent
  networks:
    privnet:
      aliases:
        - nef.free5gc.org
  depends_on:
    - db
    - free5gc-nrf
```

외부 IUF VM이 접근해야 하므로 `127.0.0.1:8005:8000`만 사용하지 않는다. 다른 환경에서는 `192.168.192.145`를 Core VM IP로 바꾼다.

```bash
docker compose config --quiet
```

## 5. NEF 이미지 빌드 및 적용

`base/Dockerfile.nf`가 사용하는 기반 이미지가 없으면 먼저 빌드한다.

```bash
docker image inspect free5gc/base >/dev/null 2>&1 || \
docker build -t free5gc/base -f base/Dockerfile base
```

NEF를 빌드하고 교체한다.

```bash
docker compose build free5gc-nef
docker compose up -d --no-deps --force-recreate free5gc-nef
```

전체 코어를 기동하면서 변경사항을 빌드하려면 다음 명령을 사용할 수 있다.

```bash
docker compose up -d --build
```

확인:

```bash
docker compose port free5gc-nef 8000
docker inspect nef --format '{{.Config.Image}}'
docker compose logs --since 2m free5gc-nef free5gc-nrf
```

정상 상태에서는 `192.168.192.145:8005`, `free5gc/nef:scf-local`, NRF 등록 성공과 OAuth 활성화 로그가 확인된다.

## 6. Python 환경과 Flask 실행

```bash
cd /home/tjralsrb/free5gc-compose
python3 -m venv .venv-core
source .venv-core/bin/activate
python3 -m pip install -r flask-nef/requirements.txt
python3 -m py_compile flask-nef/app.py flask-nef/issue_token.py
```

Flask를 실행한다.

```bash
cd /home/tjralsrb/free5gc-compose/flask-nef
source /home/tjralsrb/free5gc-compose/.venv-core/bin/activate
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

다른 터미널에서 상태를 확인한다.

```bash
curl -i http://127.0.0.1:5001/health
docker compose exec free5gc-nef \
  wget -qO- http://192.168.192.145:5001/health
```

## 7. OAuth 토큰 발급

현재 NRF 컨테이너 IP를 조회한다. 이 변수는 현재 셸에만 존재하므로 토큰 발급도 같은 셸에서 실행한다.

```bash
cd /home/tjralsrb/free5gc-compose
NRF_CONTAINER_IP="$(
  docker inspect nrf \
    --format '{{range .NetworkSettings.Networks}}{{println .IPAddress}}{{end}}' |
  sed -n '/./{p;q;}'
)"
printf 'NRF IP: %s\n' "$NRF_CONTAINER_IP"
```

토큰을 발급한다.

```bash
source .venv-core/bin/activate
NRF_URL="http://${NRF_CONTAINER_IP}:8000" \
AF_IP="192.168.192.145" \
PLMN_MCC="001" \
PLMN_MNC="01" \
python3 flask-nef/issue_token.py
```

정상 결과:

```text
AF registration: HTTP 200 또는 201
Token issuance: HTTP 200
Scope: 3gpp-traffic-influence
Expires in: 1000 seconds
```

토큰은 `flask-nef/oauth/token.json`에 저장되고 약 1000초 동안 유효하다.

## 8. IUF VM으로 토큰과 예제 복사

SSH를 사용하는 예:

```bash
cd ~/iuf
scp tjralsrb@192.168.192.145:/home/tjralsrb/free5gc-compose/flask-nef/oauth/token.json ./nef-token.json
chmod 600 nef-token.json
export NEF_ACCESS_TOKEN="$(python3 -c 'import json; print(json.load(open("nef-token.json"))["access_token"])')"
printf 'token length: %s\n' "${#NEF_ACCESS_TOKEN}"
```

예제 intent를 `policy.json`으로 준비하고 JSON 문법을 확인한다.

```bash
python3 -m json.tool policy.json
```

`intentId`는 최상위 문자열이며 영문, 숫자, `_`, `.`, `:`, `-`를 사용한 1~128자 값이어야 한다.

## 9. IUF에서 NEF로 전송

```bash
curl -i --max-time 20 \
  -X POST \
  'http://192.168.192.145:8005/lab-intents/v1/intents' \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer ${NEF_ACCESS_TOKEN}" \
  --data-binary '@policy.json'
```

성공 응답:

```http
HTTP/1.1 201 Created
```

```json
{
  "status": "stored",
  "intentId": "intent-001",
  "requestId": "...",
  "sha256": "...",
  "forwardedToCore": false
}
```

## 10. 전달 검증과 로그

NEF 로그:

```bash
docker compose logs --since 10m free5gc-nef | grep 'NEF_INTENT'
```

Flask 로그와 저장된 원본:

```bash
tail -n 20 flask-nef/logs/flask.log
tail -n 5 flask-nef/logs/intents.jsonl
```

성공 시 다음 세 기록의 `requestId`와 `sha256`가 일치한다.

```text
IUF HTTP 201 응답
NEF_INTENT ... received / scf_status=201
SCF_STORED ... POST /intent 201
```

실험에서는 IUF 주소 `192.168.192.147`, HTTP `201`, 동일한 request ID와 SHA-256을 통해 IUF → NEF → Flask → JSONL 저장 경로를 확인했다.

## 오류 해석

| 오류 | 확인할 내용 |
|---|---|
| `401 verify OAuth Authorization header invalid` | 토큰 누락·만료·잘못된 환경변수 |
| `400 valid string intentId required` | 최상위 문자열 `intentId` 확인 |
| `404 Not Found` | 커스텀 NEF 이미지와 라우트 적용 확인 |
| `Connection refused` on 8005 | NEF 컨테이너 및 Compose `ports` 확인 |
| `502 SCF connection failed` | Flask 5001 실행과 컨테이너→호스트 접근 확인 |
| `503 SCF relay is not configured` | `scf.env`, `env_file`, `SCF_INTENT_URL` 확인 |
| `No module named requests` | 활성 Python에서 `python3 -m pip install requests` |
| `No space left on device` | `docker builder prune -f`; MongoDB 볼륨은 삭제하지 않음 |

`docker system prune --volumes`는 MongoDB 데이터 볼륨까지 삭제할 수 있으므로 사용하지 않는다.
