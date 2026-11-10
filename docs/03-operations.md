# 5. 재시작·오류 해결·검증 기록

[전체 목차](../README.md) · [환경](00-environment.md) · [핸드오버](01-handover.md) · [방화벽](02-firewall.md) · [Core](../core/README.md) · [IUF](../iuf/README.md)

## 1. 실행 중인 터미널 구분

| VM | 계속 켜 둘 프로세스 | 점검용 별도 터미널 |
|---|---|---|
| VM1 | Core Flask Gunicorn | Compose·NEF·JSONL·YAML 확인 |
| VM2 | gNB1 | UPF·NSF Manager·HO trigger |
| VM3 | gNB2 | UPF·NSF Manager·역방향 HO |
| VM4 | nr-uesoftmodem | UE 터널·Ping |
| VM5 | IUF Gunicorn | curl·웹 로그 |

Docker 서비스는 `-d`로 실행하므로 터미널을 닫아도 유지됩니다. OAI·Gunicorn은 foreground 실행입니다. `tmux new -s lab`으로 시작했다면 `Ctrl+B` 후 `D`로 분리하고 `tmux attach -t lab`으로 돌아옵니다. 새 셸에서는 항상 `source "$HOME/lab.env"`를 실행합니다.

## 2. VM 재부팅 후 시작 순서

1. VM1: 공통 변수 로드 → Core 필수 서비스 실행 → NRF·NF 등록 확인.
2. VM2·VM3: UPF 추가 IP → `modprobe gtp5g` → IP forwarding → UPF 실행 → `upfgtp` route·NAT·FORWARD 재적용.
3. VM2 gNB1 → VM4 UE → 터널·기본 통신 → VM3 gNB2.
4. 필요하면 NSF Manager 실행. 이전 정책이 자동 복원된다고 가정하지 않고 규칙·counter를 확인.
5. VM1: NEF 실행·등록 → Core Flask의 공유 키 로드·Gunicorn 실행.
6. VM5: IUF 환경 파일 로드·Gunicorn 실행 → health → 실제 intent 전송.

Core 필수 서비스 명령은 [1단계](01-handover.md), NEF·Flask 명령은 [Core 문서](../core/README.md), IUF 실행 명령은 [IUF 문서](../iuf/README.md)에 있습니다. `docker compose up -d`만 무조건 실행하면 불필요한 TNGF나 준비되지 않은 NEF도 실행될 수 있으므로 문서의 서비스 목록을 사용합니다.

NRF만 재시작했다면 NEF 및 관련 NF의 profile 등록이 남아 있는지 확인하고 다시 등록되도록 재시작합니다. OAuth token은 IUF backend가 다음 요청 시 발급·갱신하므로 Core에 별도 token 발급 스크립트를 실행하지 않습니다.

## 3. 종료와 정책 정리

먼저 방화벽 정책을 해당 Edge의 delete API로 제거하고 UE 통신 복구를 확인합니다. [방화벽 문서](02-firewall.md)의 설치 JSON을 그대로 재사용하세요. 그 뒤 UE·gNB·Gunicorn 전용 터미널에서 `Ctrl+C`로 종료합니다.

VM2·VM3에서:

```bash
source "$HOME/lab.env"
cd "$FREE5GC_COMPOSE"
docker compose stop upf-nsf-manager free5gc-upf
```

Manager가 생성한 Firewall NSF는 Compose가 직접 관리하는 서비스가 아닙니다. **정책 제거가 끝난 뒤** VM2에서 `docker stop s-firewall-nsf`, VM3에서 `docker stop t-firewall-nsf`를 사용할 수 있습니다. 다음 설치 때에는 먼저 `docker start`로 복구합니다. Manager는 같은 이름의 정지 컨테이너를 자동으로 시작하지 못합니다.

VM1에서 실험 Core 전체를 정지하려면:

```bash
source "$HOME/lab.env"
cd "$FREE5GC_COMPOSE"
docker compose stop
```

`stop`은 MongoDB 볼륨을 보존합니다. 가입자 정보를 유지하려면 `docker compose down -v`나 `docker system prune --volumes`를 실행하지 않습니다. host namespace의 iptables는 컨테이너 삭제만으로 복구되지 않으므로 정책부터 제거합니다.

## 4. 장애 구간별 확인표

| 증상 | 먼저 볼 곳 | 조치 |
|---|---|---|
| `docker: permission denied` | `id`, `/var/run/docker.sock` | Docker 그룹 적용 후 재로그인 |
| `Cannot assign requested address` | `ip -4 -br addr` | Core bind IP 또는 UPF 추가 IP 수정 |
| `Module gtp5g not found` | `uname -r`, `modinfo gtp5g` | 현재 kernel용 모듈 빌드·로드 |
| UPF에 `upfgtp`가 없음 | `docker logs upf` | gtp5g·권한·UPF 설정 확인 |
| `oaitun_ue1`이 없음 | UE·AMF·SMF·UPF 로그 | 인증 키, PLMN, DNN, slice, PFCP 확인 |
| UE 터널은 있으나 인터넷 불통 | Edge route·NAT·FORWARD | 실제 UE IP 대역·N6 NIC·counter 확인 |
| gNB가 AMF에 붙지 못함 | gNB 로그·SCTP `38412` | Core IP, 포트 공개, 양방향 방화벽 확인 |
| RF Simulator 연결 실패 | UE 서버·gNB client·설정 포트 | `UE_VM_IP`, 통신 방향, OAI commit 일치 확인 |
| `neighbour-config-rfsim.conf` 읽기 실패 | `$OAI_ROOT/lab-config` | 이웃 파일 복사·include 경로 확인 |
| `trigger_n2_ho`가 없음 | OAI 소스·telnetsrv 빌드 | 명령 지원 버전·라이브러리 확인 |
| NSF API는 성공인데 통신이 안 막힘 | 내부 결과·DROP counter | 실제 UPF·UE IP·NIC·규칙 순서 확인 |
| install 시 Docker 409 충돌 | `docker inspect ...firewall-nsf` | 정지된 컨테이너 `docker start` 후 재시도 |
| IUF `React build not found` | `frontend/build/index.html` | `npm run build` |
| IUF `Address already in use` | `ss -lntp` | Core WebUI와 같은 호스트 `5000` 충돌 확인 |
| IUF `NEF_URL must identify...` | `iuf.env`, 현재 환경 | `set -a; source iuf.env; set +a` 후 재시작 |
| IUF `503` AF registration/token 실패 | IUF·NRF·NEF 로그 | `AF_IP`, NRF `8001`, NEF profile·scope·PLMN |
| NEF `401` | OAuth token·시간·인증서 | 자동 갱신 후에도 실패하면 NRF·NEF 일치 확인 |
| NEF `404` | 이미지 tag·route mount | `scf-local` 빌드, `s.mountSCFRelay()` 확인 |
| NEF `503 SCF relay is not configured` | NEF 환경 | URL·32자 이상 키 설정 후 컨테이너 재생성 |
| NEF `502 SCF connection failed` | Core Flask `5001` | 컨테이너→호스트 접근·Flask 실행 확인 |
| Flask `401 NEF relay key invalid` | `scf.env` 로딩 | NEF·Flask에 같은 키 로드 후 재시작 |
| Flask `400 subject must be...` | 보낸 JSON | 이 브랜치의 `iuf/examples/policy.json` 사용 |
| Flask `valid NEF request ID required` | Flask 직접 호출 여부 | IUF→NEF 경로 사용, `X-Request-ID`는 NEF가 생성 |
| `forwardedToCore=false` | 정상 응답 범위 | 변환·저장 완료, 실제 집행은 아직 미구현 |

`curl -s`만 쓰면 오류 원인을 놓칠 수 있어 이 가이드의 전송 명령은 `--fail-with-body`, 점검 명령은 `-i`를 사용합니다. API 응답의 HTTP status·본문과 실제 상태를 함께 확인합니다.

## 5. 실험 결과를 기록할 항목

각 VM에서 환경 버전을 남깁니다.

```bash
source "$HOME/lab.env"
uname -a
git -C "$PROJECT_SOURCE" rev-parse HEAD
```

Docker VM에서는:

```bash
docker version
docker compose version
git -C "$FREE5GC_COMPOSE" rev-parse HEAD
```

OAI VM에서는:

```bash
git -C "$OAI_ROOT" rev-parse HEAD
```

Edge에서는 `modinfo gtp5g`, VM5에서는 `node --version`, `npm --version`, 각 venv에서는 `python3 --version`, `python3 -m pip freeze`를 함께 기록합니다. 이미지 digest와 lockfile까지 보관하면 이후 재현에 도움이 됩니다.

| 시험 | 성공 판정 | 실제 결과 기록 |
|---|---|---|
| UE 등록·PDU | 터널과 IPv4, 실제 데이터 통신 | 미실측 — VM에서 기록 |
| N2 HO | Source·Target·AMF 절차 완료, 통신 상태 | 미실측 — RRC ID·시각·로그 기록 |
| UPF 경로 | PFCP·GTP-U로 실제 UPF 확인 | 미실측 — HO 전·후 비교 |
| 수동 방화벽 | 기본 통신 성공 → DROP counter 증가 → 해제 복구 | 미실측 — 실제 IP·NIC 기록 |
| 전체 intent relay | IUF HTTP 201, NEF·Flask 같은 request ID | 미실측 — VM에서 기록 |
| 정책 변환 | `translated`, YAML·JSONL·hash 일치 | 로컬 샘플 검증 + VM 경로 별도 확인 |
| 자동 정책 이전 | 현재 구현 없음 | 완료로 기록하지 않음 |

## 6. 이 브랜치 작성 시 검증 범위

2026-11-10 로컬 검증에서 다음을 확인했습니다. 검증용 키·request ID와 임시 디렉터리를 사용했으며 실제 NRF/NEF에 연결하지 않았습니다.

| 검증 | 결과 |
|---|---|
| 가이드 Markdown 8개, 내부 파일·anchor 링크 63개 | 통과 |
| Bash 코드 블록 84개 | Git Bash의 `bash -n` 구문 검사 통과 |
| 내장 Python 블록 6개 | Python 구문 검사 통과 |
| JSON 예제·문서 JSON, 저장소 YAML | 파싱 통과 |
| 예제 intent → 기존 Core Flask test client | HTTP 201, `translated` |
| 정책 YAML·latest.yaml·JSONL 생성, 응답의 YAML hash | 일치 확인 |
| relay key 없는 요청·subject 없는 요청 | 각각 HTTP 401·400 |
| 문서의 Core·양쪽 UPF·gNB 설정 변환 코드 | 임시 복사본에서 실행·주소·pool·PLMN·include 결과 확인 |

이 검증은 실험 VM의 네트워크·Docker Compose 실행·NEF Go 빌드·React 빌드·OAI 동작을 대신하지 않습니다. 해당 실행은 여기서 수행하지 않았습니다.

이 브랜치는 OAI·free5GC·NSF 애플리케이션 로직을 새로 구현하지 않습니다. 기존 기능을 보존하면서 문서·실행 예제·오래된 입력 JSON을 정리한 결과입니다.
