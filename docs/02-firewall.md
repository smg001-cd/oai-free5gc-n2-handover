# 2. Firewall NSF 정책 적용·해제

[전체 목차](../README.md) · 이전: [핸드오버](01-handover.md) · 다음: [Core NEF·Flask](../core/README.md)

이 실험은 `curl → UPF NSF Manager → Firewall NSF → iptables` 경로를 직접 시험합니다. IUF가 생성한 YAML을 이 API에 그대로 보내면 안 됩니다. Manager는 별도의 `policy_id`, `ue_ip`, `required_nsfs` 형식을 받으며, 현재 방화벽은 **해당 UE의 지정 N6 NIC 방향 트래픽 전체를 DROP**합니다. 목적지·프로토콜 단위 정책과 YAML의 action 전체를 집행하는 구현은 아닙니다.

## 1. VM2·VM3 — 이미지 빌드와 Manager 실행

양쪽 Edge에서 모두 실행합니다. NSF 코드는 저장소 `edge1/`에 공통으로 있습니다.

```bash
source "$HOME/lab.env"
docker build -t firewall-nsf:latest "$PROJECT_SOURCE/edge1/firewall-nsf"
docker build -t upf-nsf-manager:latest "$PROJECT_SOURCE/edge1/upf-nsf-manager"
cd "$FREE5GC_COMPOSE"
docker compose config --quiet
docker compose up -d free5gc-upf upf-nsf-manager
docker compose ps
curl --fail-with-body -sS http://127.0.0.1:9095/status | python3 -m json.tool
```

VM2 응답은 `edge_id=S-UPF`, VM3은 `T-UPF`여야 합니다. 초기 `firewall_running=false`는 정상입니다. 첫 `/policy/install`에서 Manager가 방화벽 컨테이너를 만듭니다. Manager가 Docker API를 쓰므로 예제 Compose의 Docker socket mount가 필요합니다. 이 API와 socket은 접근을 제한한 실험 VM에서만 사용합니다.

VM2 로그:

```bash
docker logs --tail 50 s-upf-nsf-manager
```

VM3 로그:

```bash
docker logs --tail 50 t-upf-nsf-manager
```

## 2. VM4 — 차단 전 기본 통신 확인

```bash
ip -4 addr show dev oaitun_ue1
ping -I oaitun_ue1 -c 3 8.8.8.8
```

먼저 이 Ping이 성공해야 차단과 기존 통신 장애를 구분할 수 있습니다. VM2 호스트의 `ping -c 3 8.8.8.8`도 확인합니다. UE가 어느 UPF를 통과하는지 [1단계의 캡처](01-handover.md)로 확인하세요. 아래는 VM2 UPF1을 통과하는 상황을 기준으로 합니다.

## 3. VM2 — 실제 UE IP로 설치 요청 만들기

VM4에 표시된 실제 IPv4를 입력합니다. SUPI와 RRC ID 대신 IP를 입력해야 합니다.

```bash
source "$HOME/lab.env"
read -r -p 'VM4 oaitun_ue1의 실제 IPv4: ' UE_IP
export UE_IP
export POLICY_ID=policy-001

python3 - <<'PY' > /tmp/i2nsf-policy-001.json
import ipaddress
import json
import os
ue_ip = str(ipaddress.IPv4Address(os.environ['UE_IP']))
print(json.dumps({
    'policy_id': os.environ['POLICY_ID'],
    'ue_id': 'imsi-001010000000001',
    'ue_ip': ue_ip,
    'n6_if': os.environ['N6_IF'],
    'required_nsfs': ['firewall'],
}))
PY

cat /tmp/i2nsf-policy-001.json
curl --fail-with-body -sS --max-time 15 \
  -X POST http://127.0.0.1:9095/policy/install \
  -H 'Content-Type: application/json' \
  --data-binary @/tmp/i2nsf-policy-001.json | python3 -m json.tool
```

최상위 `status=installed`만 보고 성공으로 판단하지 않습니다. Manager는 내부 방화벽 결과가 실패해도 바깥쪽 `installed`를 반환할 수 있습니다. `results` 안의 `status`가 `installed` 또는 `already_installed`인지, `stderr`와 실제 규칙이 정상인지 확인합니다.

```bash
docker ps --filter name=s-firewall-nsf
docker logs --tail 50 s-firewall-nsf
curl -sS http://127.0.0.1:18080/status | python3 -m json.tool
sudo iptables -L I2NSF-N6 -n -v --line-numbers
sudo iptables -L FORWARD -n -v --line-numbers
docker exec s-firewall-nsf iptables --version
sudo iptables --version
```

`FORWARD`의 앞부분에 `I2NSF-N6` jump, 그 chain 안에 UE IP와 `I2NSF:policy-001` 주석의 DROP이 있어야 합니다. 호스트에 chain이 안 보이면 host network 사용 여부와 iptables backend를 확인합니다.

## 4. VM4 — 차단 확인

```bash
ping -I oaitun_ue1 -c 3 8.8.8.8
```

차단되면 Ping이 실패합니다. VM2에서 다시:

```bash
ping -c 3 8.8.8.8
sudo iptables -L I2NSF-N6 -n -v
```

성공 판정은 다음 세 조건을 함께 봅니다.

1. VM2 호스트 자체의 인터넷 통신은 유지됩니다.
2. VM4의 UE 터널을 통한 통신은 차단됩니다.
3. 정확한 UE IP DROP 규칙의 `pkts`, `bytes`가 증가합니다.

차단 후에도 UE 통신이 되면 UE IP·현재 UPF·`N6_IF`·FORWARD 순서를 확인합니다. 차단되었지만 counter가 그대로라면 다른 원인으로 통신이 실패했을 수 있습니다.

## 5. VM2 — 같은 값으로 정책 제거

설치에 사용한 JSON 파일을 그대로 사용하면 IP·NIC·정책 ID 불일치를 피할 수 있습니다.

```bash
curl --fail-with-body -sS --max-time 15 \
  -X POST http://127.0.0.1:9095/policy/delete \
  -H 'Content-Type: application/json' \
  --data-binary @/tmp/i2nsf-policy-001.json | python3 -m json.tool
sudo iptables -L I2NSF-N6 -n -v
```

내부 `result.removed`가 1 이상이면 해당 규칙이 삭제되었습니다. 0이면 이미 삭제되었는지, IP·NIC·정책 ID가 원래 값과 같은지 확인합니다.

VM4에서:

```bash
ping -I oaitun_ue1 -c 3 8.8.8.8
```

통신이 복구되어야 합니다. 방화벽 컨테이너를 종료하는 것만으로 host namespace에 설치된 규칙이 삭제되지는 않습니다. 반드시 delete API로 먼저 제거합니다.

## 6. VM3에서 별도 시험하기

UE의 실제 데이터 경로가 VM3 UPF2인 것을 확인한 후 VM3에서 3~5절을 실행합니다. 요청 URL `127.0.0.1:9095`는 **실행 중인 VM의 Manager**를 가리킵니다. 컨테이너·로그 이름은 `t-firewall-nsf`, `t-upf-nsf-manager`입니다. UE IP는 핸드오버 후 다시 확인합니다.

이 절차는 수동 시험입니다. Source 정책을 설치했다고 Target에 자동 복제되지 않습니다. 향후 자동 이전에는 HO 이벤트 수신, SMF의 세션 조회, YAML→Manager 정책 변환, Target 적용 확인과 Source 해제가 추가되어야 합니다.

## 7. 자주 생기는 문제

| 증상 | 확인·조치 |
|---|---|
| `No such service: upf-nsf-manager` | 원본 Edge Compose 대신 `examples/compose.edge.yaml`을 실행 위치에 복사했는지 확인 |
| `/var/run/docker.sock` 연결 실패 | socket mount와 Docker daemon 확인 |
| install 시 `409 ... container name ... in use` | Manager가 정지된 동일 이름 컨테이너를 재사용하지 못함. 아래 복구 절차 |
| API는 installed, 내부 status failed | 내부 `stderr`, NET_ADMIN, NIC, backend 확인 |
| 호스트·컨테이너의 규칙이 다름 | `network_mode: host`, `iptables --version` 비교 |
| HO 후 counter가 늘지 않음 | 현재 UE IP·UPF 경로 재확인 |

정지된 방화벽 컨테이너가 남은 경우 VM2에서:

```bash
docker inspect s-firewall-nsf --format '{{.State.Status}}'
docker start s-firewall-nsf
docker logs --tail 30 s-firewall-nsf
```

정상 실행된 것을 확인한 뒤 install을 재시도합니다. VM3에서는 이름을 `t-firewall-nsf`로 바꿉니다. 무작정 다른 컨테이너를 지우거나 iptables 전체를 flush하지 않습니다.

다음: [3. Core NEF·Flask 정책 변환기](../core/README.md).
