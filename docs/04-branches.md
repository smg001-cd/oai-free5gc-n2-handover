# 브랜치 비교와 통합 기준

[전체 목차](../README.md)

## 1. 확인한 원본

2026-11-10 기준 원격 브랜치는 다음 두 개였습니다.

| 브랜치 | 확인한 commit | 내용 |
|---|---|---|
| `main` | `9f1095ab2c8dc6b00d7a334a44e114839779e187` | Core·두 Edge·UE 설정, N2 HO, Firewall NSF·Manager |
| `feature/iuf-nef-flask-relay` | `e6ac28d9779fc300923513f54c5e8a2dc0cff220` | main의 파일 + IUF React/Flask, NEF relay, Core 정책 변환 |

기능 브랜치는 확인한 `main` commit을 조상으로 포함합니다. 두 tip의 파일 차이는 19개이며, main 전용 파일을 삭제하지 않고 `core/docker-compose.yaml`을 확장하고 IUF·NEF·Flask 파일을 추가한 형태입니다. 따라서 통합 브랜치는 기능 브랜치 tip에서 시작해 두 경로를 하나의 문서 순서로 연결합니다. 억지 merge commit이나 main 덮어쓰기는 필요하지 않습니다.

고정된 원본 보기: [main snapshot](https://github.com/smg001-cd/oai-free5gc-n2-handover/tree/9f1095ab2c8dc6b00d7a334a44e114839779e187), [feature snapshot](https://github.com/smg001-cd/oai-free5gc-n2-handover/tree/e6ac28d9779fc300923513f54c5e8a2dc0cff220), [두 commit 비교](https://github.com/smg001-cd/oai-free5gc-n2-handover/compare/9f1095ab2c8dc6b00d7a334a44e114839779e187...e6ac28d9779fc300923513f54c5e8a2dc0cff220).

## 2. 파일별 출처와 읽는 위치

| 파일·폴더 | 출처·역할 | 통합 가이드 |
|---|---|---|
| `core/amfcfg.yaml`, `core/smfcfg.yaml` | main, AMF·두 UPF topology | [Core 배치](01-handover.md) |
| `edge1/*.conf`, `edge2/*.conf` | main, PCI 0/1 gNB와 이웃 설정 | [OAI 실행](01-handover.md) |
| `edge1/upfcfg.yaml`, `edge2/upfcfg.yaml` | main, UPF PFCP·GTP-U | [UPF 실행](01-handover.md) |
| `ue/nrue.uicc.conf` | main, 가입자 키·DNN·slice | [가입자·UE](01-handover.md) |
| `edge1/firewall-nsf/` | main, host iptables DROP | [Firewall 시험](02-firewall.md) |
| `edge1/upf-nsf-manager/` | main, Docker NSF 기동·API 중계 | [Manager 실행](02-firewall.md) |
| `core/docker-compose.yaml` | feature에서 NRF·NEF 외부 포트와 로컬 NEF 빌드 확장 | [Core NEF](../core/README.md) |
| `core/nef/` | feature, OAuth 보호 커스텀 route | [소스 수정](../core/README.md) |
| `core/flask-nef/` | feature, intent 검증·YAML 변환·JSONL 저장 | [정책 변환](../core/README.md) |
| `iuf/backend/` | feature, AF 등록·token 갱신·NEF 호출 | [IUF 설치](../iuf/README.md) |
| `iuf/frontend/` | feature, High-level intent 생성·YAML 표시 | [IUF 웹](../iuf/README.md) |
| `examples/`, `docs/` | 이번 통합 브랜치의 안내·실행 예제 | [전체 목차](../README.md) |

## 3. 이번 정리에서 바로잡은 부분

| 기존 상태 | 통합 브랜치의 처리 |
|---|---|
| root README에 HO·방화벽만 설명 | 전체 구성·브랜치 출처·단계별 문서 연결 |
| 삭제된 `README_IUF_NEF_FLASK.md`, `docker-compose.nef-snippet.yaml` 참조 | 실제 `core/README.md`, Compose 경로로 교체 |
| `/home/tjralsrb` 등 개인 경로 | `$HOME`, 공통 `~/lab.env` 사용 |
| README의 `docker-compose-upf-only.yaml`이 저장소에 없음 | 실제 존재하는 Edge 최소 Compose 추가 |
| 원본 Edge Compose에 Manager 서비스 없음 | socket·환경 변수를 포함한 실행 예제 추가 |
| Flask를 record-only로 설명하지만 실제로는 YAML 변환 구현됨 | 현재 schema·입력 필드·저장 결과 문서화 |
| `iuf/examples/policy.json`이 구형 `ueIp`·`policy` 형식 | 현재 `subject/traffic/securityControl` 형식으로 수정 |
| NRF OAuth의 YAML 위치가 부정확 | v4.2.3의 `configuration.sbi.oauth`로 안내 |
| upstream AUSF·NSSF의 기본 PLMN은 `208/93` | 복사한 실행 환경을 `001/01`, SST 1·SD 010203에 맞추는 명령 제공 |
| SMF·UPF 주소 풀이 불일치 | 원본은 보존, 복사한 실행 설정을 공통 UE pool로 맞추는 명령 제공 |
| source IP·NAT·FORWARD의 반복 추가 | 존재 확인 뒤 추가하는 명령 사용 |
| 생성 YAML의 Git 제외 누락 | `core/.gitignore`에 `flask-nef/policies/` 추가 |

기존 OAI 설정·NF 설정·Python/React/Go 로직은 보존합니다. 본 가이드의 실험용 주소·pool 정리는 런타임 복사본에 적용합니다. 신규 Edge Compose는 기존 원본을 대체 삭제하지 않고 별도 예제로 제공합니다.

## 4. 직접 비교하는 Git 명령

Linux의 저장소에서:

```bash
source "$HOME/lab.env"
cd "$PROJECT_SOURCE"
git fetch origin
git branch -r
git diff --stat origin/main origin/feature/iuf-nef-flask-relay
git diff origin/main origin/feature/iuf-nef-flask-relay -- core/docker-compose.yaml
git log --oneline origin/main..origin/feature/iuf-nef-flask-relay
git show origin/main:README.md
```

문서에 고정한 시점으로 비교하려면:

```bash
git diff --stat \
  9f1095ab2c8dc6b00d7a334a44e114839779e187 \
  e6ac28d9779fc300923513f54c5e8a2dc0cff220
git merge-base --is-ancestor \
  9f1095ab2c8dc6b00d7a334a44e114839779e187 \
  e6ac28d9779fc300923513f54c5e8a2dc0cff220
echo $?
```

마지막 결과 `0`은 main tip이 기능 브랜치의 조상이라는 뜻입니다. 원본 브랜치가 나중에 변경되면 고정 SHA 비교와 최신 tip 비교 결과는 달라질 수 있습니다.

## 5. 남은 개발 작업

현재 코드가 지원하는 끝은 **정책 변환·보관**과 **별도 수동 방화벽 API 시험**입니다. 자동 연동에는 다음 작업이 필요합니다.

1. SUPI·DNN·slice로 SMF 세션의 UE IP·현재 UPF·Target UPF를 찾는 인터페이스.
2. Low-level YAML을 실제 NSF별 정책으로 변환·배포하는 controller.
3. HO 이벤트의 시점과 정책 lifecycle을 연결하는 처리.
4. Target 적용 성공 확인 → 경로 전환 확인 → Source 해제 및 실패 복구.
5. destination/protocol/port, Anti-DDoS·확장 action의 실제 집행기와 검증.

이 브랜치의 문서가 위 기능을 구현하거나 동작을 보장하는 것으로 해석하지 않습니다.
