# IUF Web Intent Console

이 폴더는 IUF VM에서 웹으로 security intent를 작성하고 OAuth로 보호된 free5GC NEF에 전달하는 코드다. `patrick8link/i2nsf-security-controller`의 React 정책 입력 방식을 참고했으며, 이 실험에 필요한 필드만 남겼다.

## 전체 흐름

```text
Browser
  → IUF Flask backend (IUF VM :5000)
  → NRF token issuance (Core VM :8001)
  → free5GC NEF custom API (Core VM :8005)
  → Flask SCF substitute (Core VM :5001)
  → flask-nef/logs/intents.jsonl
```

React는 화면만 담당한다. 브라우저에 OAuth 토큰을 저장하지 않는다. IUF의 `backend/app.py`가 AF로 NRF에 등록하고 NEF 접근 토큰을 발급받아 요청에 넣는다. 토큰 만료 60초 전에는 다음 intent 전송 시 새 토큰을 발급하며, NEF가 `401`을 반환하면 강제로 갱신한 뒤 한 번 재시도한다.

## 폴더 구조

```text
iuf/
├── README.md
├── .gitignore
├── examples/
│   └── policy.json
├── backend/
│   ├── app.py
│   ├── iuf.env.example
│   └── requirements.txt
└── frontend/
    ├── package.json
    ├── public/
    │   └── index.html
    └── src/
        ├── App.js
        ├── App.css
        └── index.js
```

실행 중 `backend/.venv`, `backend/oauth`, `backend/logs`, `frontend/node_modules`, `frontend/build`가 생성된다. 토큰과 AF ID는 Git에 포함하지 않는다.

## 1. Core VM 준비 확인

IUF를 실행하기 전에 Core VM에서 다음 서비스가 실행 중이어야 한다.

| 서비스 | IUF에서 접근할 주소 |
|---|---|
| NRF | `http://192.168.192.145:8001` |
| NEF custom API | `http://192.168.192.145:8005/lab-intents/v1/intents` |
| Flask SCF substitute | NEF가 `http://192.168.192.145:5001/intent`로 접근 |

IUF VM에서 포트를 확인한다.

```bash
curl -i --max-time 5 http://192.168.192.145:8001/nnrf-nfm/v1/nf-instances

curl -i --max-time 5 \
  -X POST \
  http://192.168.192.145:8005/lab-intents/v1/intents \
  -H 'Content-Type: application/json' \
  --data '{"intentId":"connection-test"}'
```

두 번째 요청에서 `401 Unauthorized`가 나오면 NEF 연결과 OAuth 보호가 정상이다.

## 2. 소스 준비

저장소 전체를 IUF VM에 clone하는 경우:

```bash
cd /home/tjralsrb
git clone https://github.com/smg001-cd/oai-free5gc-n2-handover.git
cd /home/tjralsrb/oai-free5gc-n2-handover/iuf
```

기존 `/home/tjralsrb/iuf`를 사용하려면 저장소의 `iuf` 폴더 안쪽 파일을 해당 디렉터리로 복사하고 아래 경로를 실제 위치로 바꾼다. 이하 예시는 저장소를 clone한 경로를 사용한다.

```bash
export IUF_ROOT=/home/tjralsrb/oai-free5gc-n2-handover/iuf
```

## 3. Node.js 확인과 React 빌드

```bash
node -v
npm -v
```

`react-scripts` 빌드에는 최신 LTS Node.js 사용을 권장한다. 오래된 Node에서 `_ending; SyntaxError`가 발생하면 `nvm`으로 Node.js 22 이상을 설치한 후 기존 의존성을 지우고 다시 설치한다.

```bash
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
nvm install 22
nvm use 22
nvm alias default 22
```

React를 빌드한다.

```bash
cd "$IUF_ROOT/frontend"
rm -rf node_modules
rm -f package-lock.json
npm install
npm run build
```

확인:

```bash
test -f "$IUF_ROOT/frontend/build/index.html" && echo 'React build OK'
```

React는 처음과 소스 변경 후에만 다시 빌드한다. 운영 시 `npm start`는 필요하지 않으며 IUF Flask backend가 `frontend/build`를 제공한다.

## 4. Python backend 설치

```bash
cd "$IUF_ROOT/backend"
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
python3 -m py_compile app.py
```

환경 설정 파일을 만든다.

```bash
cp iuf.env.example iuf.env
chmod 600 iuf.env
```

다른 환경에서는 `iuf.env`의 Core VM IP, IUF VM IP, PLMN 값을 수정한다.

```bash
cat iuf.env
```

```text
NEF_URL=http://192.168.192.145:8005/lab-intents/v1/intents
NRF_URL=http://192.168.192.145:8001
AF_IP=192.168.192.147
PLMN_MCC=001
PLMN_MNC=01
```

## 5. IUF 웹 실행

```bash
cd "$IUF_ROOT/backend"
source .venv/bin/activate

set -a
source iuf.env
set +a

mkdir -p logs

python3 -m gunicorn \
  --bind 0.0.0.0:5000 \
  --workers 1 \
  --threads 4 \
  --timeout 30 \
  --access-logfile - \
  --error-logfile - \
  app:app 2>&1 | tee -a logs/iuf-web.log
```

정상 출력:

```text
Listening at: http://0.0.0.0:5000
Booting worker with pid: ...
```

이 터미널은 실행 상태로 둔다. IUF VM의 브라우저에서는 다음 주소를 연다.

```text
http://127.0.0.1:5000
```

다른 장비에서 IUF VM으로 접근한다면:

```text
http://192.168.192.147:5000
```

## 6. 상태와 OAuth 자동 발급 확인

```bash
curl -s http://127.0.0.1:5000/api/health | python3 -m json.tool
```

정상 응답:

```json
{
  "automaticOAuth": true,
  "nefUrl": "http://192.168.192.145:8005/lab-intents/v1/intents",
  "service": "iuf-web",
  "status": "ok"
}
```

웹에서 처음 intent를 전송하면 backend가 자동으로 다음 파일을 만든다.

```text
backend/oauth/af-id.txt
backend/oauth/token.json
```

```bash
ls -l "$IUF_ROOT/backend/oauth"
```

토큰 문자열을 출력하지 않고 상태만 확인한다.

```bash
cd "$IUF_ROOT/backend"
python3 - <<'PY'
import json

with open("oauth/token.json", encoding="utf-8") as token_file:
    token = json.load(token_file)

print("token present:", bool(token.get("access_token")))
print("expires in:", token.get("expires_in"))
PY
```

Core VM의 `issue_token.py`는 사용하지 않는다. IUF backend가 NRF에서 직접 토큰을 발급받고 갱신한다.

## 7. 웹에서 intent 전송

화면에서 다음 값을 입력할 수 있다.

- Intent ID
- UE ID
- UE IPv4
- DNN
- Application ID
- Target DNAI
- Policy Action
- Description

**Intent 전송**을 누르면 성공 시 `HTTP 201`, `requestId`, NEF와 Core Flask의 저장 응답이 표시된다.

웹을 사용하지 않고 IUF backend API만 시험하려면:

```bash
curl -i --max-time 30 \
  -X POST \
  http://127.0.0.1:5000/api/intents \
  -H 'Content-Type: application/json' \
  --data-binary @"$IUF_ROOT/examples/policy.json"
```

## 8. 로그 확인

IUF backend 로그:

```bash
tail -f "$IUF_ROOT/backend/logs/iuf-web.log"
```

정상 전달 로그:

```text
IUF_WEB intentId=intent-001 requestId=... nef_status=201
```

Core VM의 NEF 및 Flask 로그 확인은 `core/README_IUF_NEF_FLASK.md`를 따른다. IUF 웹 응답, NEF 로그, Core의 `intents.jsonl`에서 동일한 `requestId`가 나오면 전달 경로가 확인된 것이다.

## 오류 해결

| 증상 | 의미와 확인 사항 |
|---|---|
| `React build not found` | `frontend`에서 `npm run build` 실행 |
| `_ending; SyntaxError` | Node.js가 너무 오래됨. Node 22 이상으로 교체 후 `node_modules` 재설치 |
| `502 NEF connection failed` | `NEF_URL`, Core `8005` 포트, 방화벽 확인 |
| `503 No valid NEF token` | `NRF_URL` 설정과 Core `8001` 포트 확인 |
| `Token issuance failed: HTTP 400` | NRF 로그의 `invalid_client`, NEF 등록과 서비스 scope 확인 |
| `401 verify OAuth Authorization header invalid` | 자동 갱신 재시도 후에도 실패. NRF·NEF 시간과 인증서 확인 |
| `af-id.txt`만 생성됨 | AF ID 생성 후 NRF 등록 또는 토큰 발급에서 중단됨 |

NRF를 재시작했다면 Core VM에서 NEF를 다시 시작하여 NRF 등록을 갱신한다.

```bash
docker compose restart free5gc-nef
```


