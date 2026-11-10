# 1. Core·UPF·gNB·UE 실행과 N2 핸드오버

[전체 목차](../README.md) · 이전: [환경 준비](00-environment.md) · 다음: [Firewall NSF](02-firewall.md)

## 1. 실행 순서와 준비 상태

```text
Core 설정·가입자 등록 → Core 실행
→ VM2·VM3 UPF 실행 → VM2 gNB1 실행 → VM4 UE 실행
→ UE 터널·기본 통신 확인 → VM3 gNB2 실행
→ VM2에서 수동 N2 HO → 양쪽 gNB·AMF·데이터 경로 확인
```

각 새 터미널에서 `source "$HOME/lab.env"`를 먼저 실행합니다. 이 문서는 [0단계](00-environment.md)의 도구·소스 준비가 완료되었다고 가정합니다.

**원본 설정의 주의점:** SMF는 UPF1 `10.0.0.0/24`, UPF2 `10.0.1.0/24`를 쓰지만 UPF의 `oai` DNN은 `10.60.0.0/16` 계열입니다. 그대로 실행해 통신 성공을 가정할 수 없습니다. 아래에서는 복사한 실행 설정의 SMF·양쪽 UPF를 공통 `$UE_CIDR`로 맞춥니다. 이는 본 가이드의 출발 설정이며, 실제 UPF 재선택·UE IP 유지 여부는 세션 로그로 따로 확인합니다.

## 2. VM1 — Core 설정 배치

기존 free5gc-compose 파일을 백업하고 이 저장소 설정을 복사합니다.

```bash
source "$HOME/lab.env"
cd "$FREE5GC_COMPOSE"
BACKUP_DIR="$FREE5GC_COMPOSE/backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"
cp -a docker-compose.yaml config "$BACKUP_DIR/"
printf 'backup: %s\n' "$BACKUP_DIR"

cp "$PROJECT_SOURCE/core/docker-compose.yaml" docker-compose.yaml
cp "$PROJECT_SOURCE/core/amfcfg.yaml" config/amfcfg.yaml
cp "$PROJECT_SOURCE/core/smfcfg.yaml" config/smfcfg.yaml
```

NRF·NEF 포트의 주소를 공통 변수로 바꾸고, PLMN·slice·주소 풀을 정리합니다. 설정 편집용 `python3-yaml`은 0단계에서 설치했습니다.

```bash
python3 - <<'PY'
import os
import re
from pathlib import Path
import yaml

root = Path(os.environ['FREE5GC_COMPOSE'])
p = root / 'docker-compose.yaml'
p.write_text(p.read_text().replace('192.168.192.145', '${CORE_VM_IP}'))

def read_config(name):
    # 001/01/010203 등 식별자를 YAML 숫자로 해석하지 않도록 먼저 인용한다.
    text = (root / 'config' / name).read_text()
    text = re.sub(
        r'^(\s*(?:mcc|mnc|sd|tac):\s*)([0-9A-Fa-f]+)(\s*(?:#.*)?)$',
        r'\1"\2"\3', text, flags=re.M)
    return yaml.safe_load(text)

def save(name, value):
    (root / 'config' / name).write_text(yaml.safe_dump(value, sort_keys=False))

save('amfcfg.yaml', read_config('amfcfg.yaml'))
smf = read_config('smfcfg.yaml')
nodes = smf['configuration']['userplaneInformation']['upNodes']
for name, env in [('UPF1', 'UPF1_IP'), ('UPF2', 'UPF2_IP')]:
    node = nodes[name]
    node['nodeID'] = node['addr'] = os.environ[env]
    for interface in node['interfaces']:
        interface['endpoints'] = [os.environ[env]]
    for slice_info in node['sNssaiUpfInfos']:
        for dnn in slice_info['dnnUpfInfoList']:
            if dnn['dnn'] == 'oai':
                dnn['pools'] = [{'cidr': os.environ['UE_CIDR']}]
save('smfcfg.yaml', smf)

nrf = read_config('nrfcfg.yaml')
nrf['configuration']['sbi']['oauth'] = True
nrf['configuration']['DefaultPlmnId'] = {'mcc': '001', 'mnc': '01'}
save('nrfcfg.yaml', nrf)

# upstream 예제의 208/93 PLMN도 실험의 001/01에 맞춘다.
plmn = {'mcc': '001', 'mnc': '01'}
ausf = read_config('ausfcfg.yaml')
ausf['configuration']['plmnSupportList'] = [plmn]
save('ausfcfg.yaml', ausf)

nssf = read_config('nssfcfg.yaml')
nssf_cfg = nssf['configuration']
snssai = {'sst': 1, 'sd': '010203'}
nssf_cfg['supportedPlmnList'] = [plmn]
nssf_cfg['supportedNssaiInPlmnList'] = [
    {'plmnId': plmn, 'supportedSnssaiList': [snssai]}]
nssf_cfg['taList'] = [{
    'tai': {'plmnId': plmn, 'tac': '000001'},
    'accessType': '3GPP_ACCESS', 'supportedSnssaiList': [snssai]}]
save('nssfcfg.yaml', nssf)
print('Core config prepared')
PY
```

이 명령은 upstream의 [AUSF](https://github.com/free5gc/free5gc-compose/blob/v4.2.3/config/ausfcfg.yaml)·[NSSF](https://github.com/free5gc/free5gc-compose/blob/v4.2.3/config/nssfcfg.yaml)에 남아 있는 기본 PLMN도 실험용 `001/01`로 맞춥니다. 기존 다중 PLMN·slice 환경에 적용하면 지원 목록이 단일 실험값으로 바뀌므로 이 가이드는 별도 실험 VM 기준으로 사용합니다. 백업은 수정 전에 저장됩니다.

Core Compose에는 NEF의 `env_file`도 선언되어 있으므로 아직 NEF를 실행하지 않더라도 공유 키 파일을 만들어 둡니다. 기존 키는 재생성하지 않습니다.

```bash
mkdir -p flask-nef
if [ ! -s flask-nef/scf.env ]; then
  (umask 077; openssl rand -hex 32 | sed 's/^/SCF_RELAY_KEY=/' > flask-nef/scf.env)
fi
chmod 600 flask-nef/scf.env
docker compose config --quiet
```

오류가 없으면 아래의 필수 서비스만 실행합니다. 이 단계에서는 NEF 빌드·TNGF·로컬 UPF를 실행하지 않습니다.

```bash
docker compose up -d db free5gc-nrf free5gc-amf free5gc-smf \
  free5gc-ausf free5gc-udm free5gc-udr free5gc-nssf \
  free5gc-pcf free5gc-webui
docker compose ps
docker compose logs --tail 100 free5gc-amf free5gc-smf
sudo ss -lnp -A sctp
```

`38412/SCTP` 공개 설정이 있어야 gNB가 Core 호스트 IP로 접근할 수 있습니다. NRF OAuth가 활성화되어 있으므로 NF의 NRF 등록 실패도 로그에서 확인합니다.

## 3. VM1 — UE 가입자 등록

브라우저에서 `http://Core실제IP:5000`을 엽니다. 이는 IUF 웹과 다른 free5GC WebUI입니다. 해당 설치의 관리자 계정으로 로그인하고 가입자를 추가합니다. 계정 초기화·로그인은 [free5GC WebConsole 안내](https://free5gc.org/guide/Webconsole/)를 확인합니다.

VM4의 `ue/nrue.uicc.conf`와 아래 값이 같아야 합니다.

| 가입자 항목 | 이 저장소의 값 |
|---|---|
| SUPI / IMSI | SUPI `imsi-001010000000001`, 숫자 IMSI `001010000000001` |
| 인증 방식 | `5G_AKA` |
| K | `fec86ba6eb707ed08905757b1bb44b8f` |
| OP 유형 | `OPc` |
| OPc | `C42449363BBAD02B66D16BC975D77CC1` |
| PLMN | MCC `001`, MNC `01` |
| DNN | `oai` |
| S-NSSAI | SST `1`, SD `010203` |
| AMF 인증 필드 | WebUI 템플릿·인증 설정과 일치시킴. NAS AMF ID `cafe00`과 별개 |

WebUI의 SUPI 필드에는 접두사를 포함한 값, 숫자 IMSI 필드에는 숫자 부분을 넣습니다. 생성된 프로필의 DNN·slice와 인증 키를 다시 확인합니다. 예제 키는 실험용입니다. 이 문서는 subscriber DB를 직접 수정하지 않습니다.

## 4. VM2·VM3 — 실행 설정과 추가 IP

VM2에서:

```bash
source "$HOME/lab.env"
export EDGE_ROLE=edge1
export THIS_UPF_IP="$UPF1_IP"
export THIS_GNB_IP="$EDGE1_VM_IP"
export EDGE_ID=S-UPF
export MANAGER_NAME=s-upf-nsf-manager
export FIREWALL_NAME=s-firewall-nsf
```

VM3에서:

```bash
source "$HOME/lab.env"
export EDGE_ROLE=edge2
export THIS_UPF_IP="$UPF2_IP"
export THIS_GNB_IP="$EDGE2_VM_IP"
export EDGE_ID=T-UPF
export MANAGER_NAME=t-upf-nsf-manager
export FIREWALL_NAME=t-firewall-nsf
```

이후 이 절의 명령은 **두 Edge에서 각각** 실행합니다. 현재 터미널에 위 역할 변수가 설정되어 있어야 합니다.

```bash
cd "$FREE5GC_COMPOSE"
BACKUP_DIR="$FREE5GC_COMPOSE/backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"
cp -a docker-compose.yaml config "$BACKUP_DIR/"
if [ -f .env ]; then cp -a .env "$BACKUP_DIR/"; fi
cp "$PROJECT_SOURCE/examples/compose.edge.yaml" docker-compose.yaml
cp "$PROJECT_SOURCE/$EDGE_ROLE/upfcfg.yaml" config/upfcfg.yaml

cat > .env <<EOF
EDGE_ID=$EDGE_ID
MANAGER_NAME=$MANAGER_NAME
FIREWALL_NAME=$FIREWALL_NAME
EOF

python3 - <<'PY'
import os
from pathlib import Path
import yaml
p = Path(os.environ['FREE5GC_COMPOSE']) / 'config/upfcfg.yaml'
cfg = yaml.safe_load(p.read_text())
cfg['pfcp']['addr'] = cfg['pfcp']['nodeID'] = os.environ['THIS_UPF_IP']
for interface in cfg['gtpu']['ifList']:
    interface['addr'] = os.environ['THIS_UPF_IP']
cfg['dnnList'] = [{'dnn': 'oai', 'cidr': os.environ['UE_CIDR']}]
p.write_text(yaml.safe_dump(cfg, sort_keys=False))
print('UPF config prepared:', os.environ['THIS_UPF_IP'])
PY

ip -4 addr show dev "$EDGE_IF" | grep -Fq "inet $THIS_UPF_IP/" || \
  sudo ip addr add "$THIS_UPF_IP/$LAB_PREFIX" dev "$EDGE_IF"
ip -4 -br addr show dev "$EDGE_IF"
sudo modprobe gtp5g
sudo sysctl -w net.ipv4.ip_forward=1
docker compose config --quiet
docker compose up -d free5gc-upf
docker compose ps
docker compose logs --tail 100 free5gc-upf
ip link show upfgtp
```

`upfgtp`은 UPF가 정상 초기화된 후 생깁니다. 없으면 NAT 설정보다 UPF·gtp5g 로그를 먼저 확인합니다. 원본 `edge1/docker-compose.yaml`·`edge2/docker-compose.yaml`은 비교용으로 남겨 두었고 이 가이드는 최소 구성인 `examples/compose.edge.yaml`을 사용합니다. 이 구성은 upstream `upf-iptables.sh`의 광범위한 FORWARD 허용을 자동 실행하지 않습니다.

## 5. VM2·VM3 — UE 라우팅과 NAT

두 Edge에서 각각:

```bash
source "$HOME/lab.env"
sudo ip route replace "$UE_CIDR" dev upfgtp

sudo iptables -t nat -C POSTROUTING -s "$UE_CIDR" -o "$N6_IF" -j MASQUERADE 2>/dev/null || \
  sudo iptables -t nat -A POSTROUTING -s "$UE_CIDR" -o "$N6_IF" -j MASQUERADE

sudo iptables -C FORWARD -i upfgtp -o "$N6_IF" -s "$UE_CIDR" -j ACCEPT 2>/dev/null || \
  sudo iptables -A FORWARD -i upfgtp -o "$N6_IF" -s "$UE_CIDR" -j ACCEPT

sudo iptables -C FORWARD -i "$N6_IF" -o upfgtp -d "$UE_CIDR" \
  -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || \
  sudo iptables -A FORWARD -i "$N6_IF" -o upfgtp -d "$UE_CIDR" \
  -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT

ip route show dev upfgtp
sudo iptables -t nat -L POSTROUTING -n -v
sudo iptables -L FORWARD -n -v --line-numbers
```

기존 DROP이 이 규칙보다 앞에 있으면 허용 규칙까지 도달하지 못할 수 있습니다. 기존 규칙을 전부 flush하지 말고 순서와 counter를 확인합니다. Firewall NSF 실험에서는 `I2NSF-N6` jump가 이 허용 규칙보다 앞에 있어야 합니다. 호스트와 컨테이너의 iptables backend(`nf_tables`/`legacy`)도 같아야 같은 규칙을 볼 수 있습니다.

IP 추가·sysctl·route·iptables 명령은 여기서는 실행 중인 VM에만 적용합니다. 재부팅 뒤 [운영 문서](03-operations.md)의 순서로 다시 적용합니다.

## 6. VM2·VM3 — gNB 설정 복사

4절에서 설정한 역할 변수가 있는 터미널에서 두 Edge 각각 실행합니다.

```bash
source "$HOME/lab.env"
mkdir -p "$OAI_ROOT/lab-config"
cp "$PROJECT_SOURCE/$EDGE_ROLE/"*.conf "$OAI_ROOT/lab-config/"

python3 - <<'PY'
import os
from pathlib import Path
root = Path(os.environ['OAI_ROOT']) / 'lab-config'
mapping = {
    '192.168.192.145': os.environ['CORE_VM_IP'],
    '192.168.192.140/24': os.environ['EDGE1_VM_IP'] + '/' + os.environ['LAB_PREFIX'],
    '192.168.192.141/24': os.environ['EDGE2_VM_IP'] + '/' + os.environ['LAB_PREFIX'],
}
for path in root.glob('*.conf'):
    text = path.read_text()
    for old, new in mapping.items():
        text = text.replace(old, new)
    text = text.replace('@include "neighbour-config-rfsim.conf"',
                        '@include "' + str(root / 'neighbour-config-rfsim.conf') + '"')
    path.write_text(text)
PY

grep -nE 'amf_ip_address|GNB_IPV4|physCellId|gNB_ID|include' "$OAI_ROOT/lab-config/"*.conf
```

이웃 설정 파일도 함께 복사해야 합니다. 위 명령은 복사한 gNB 설정의 `@include`를 실제 파일의 절대 경로로 바꾸므로 실행 디렉터리와 관계없이 읽을 수 있습니다. gNB1은 PCI `0`, gNB2는 PCI `1`이고 gNB ID는 서로 달라야 합니다.

VM4에서는 UE 설정을 복사합니다.

```bash
source "$HOME/lab.env"
mkdir -p "$OAI_ROOT/lab-config"
cp "$PROJECT_SOURCE/ue/nrue.uicc.conf" "$OAI_ROOT/lab-config/"
sudo modprobe tun
test -c /dev/net/tun
```

## 7. VM2 — gNB1 실행

VM2의 전용 터미널에서 실행하고 켜 둡니다.

```bash
source "$HOME/lab.env"
cd "$OAI_BUILD"
mkdir -p "$OAI_ROOT/lab-logs"
set -o pipefail
sudo ./nr-softmodem \
  -O "$OAI_ROOT/lab-config/gnb.sa.band78.fr1.106PRB.pci0.rfsim.conf" \
  --telnetsrv --telnetsrv.shrmod ci \
  --gNBs.[0].min_rxtxtime 6 --rfsim \
  --rfsimulator.[0].serveraddr "$UE_VM_IP" \
  2>&1 | tee "$OAI_ROOT/lab-logs/gnb1.log"
```

AMF와 NG Setup이 성공하는지 로그를 확인합니다. UE 서버가 아직 없으면 RF 연결 대기 메시지가 나올 수 있습니다.

## 8. VM4 — UE 실행

VM4의 전용 터미널에서:

```bash
source "$HOME/lab.env"
cd "$OAI_BUILD"
mkdir -p "$OAI_ROOT/lab-logs"
set -o pipefail
sudo ./nr-uesoftmodem \
  -O "$OAI_ROOT/lab-config/nrue.uicc.conf" \
  -r 106 --numerology 1 --band 78 -C 3619200000 \
  --rfsim --rfsimulator.[0].serveraddr server \
  2>&1 | tee "$OAI_ROOT/lab-logs/ue.log"
```

VM4의 **다른 터미널**에서:

```bash
source "$HOME/lab.env"
ip -4 addr show dev oaitun_ue1
ping -I oaitun_ue1 -c 3 8.8.8.8
```

`oaitun_ue1`과 할당 IPv4를 기록합니다. `10.0.0.1`은 예시일 뿐, 실제 할당값을 이후 방화벽 시험에 사용합니다. 터널이 없으면 가입자 인증·PLMN·DNN·slice·SMF/UPF 연결부터 확인합니다. 외부망이 ICMP를 차단하면 응답 가능한 자신의 데이터망 주소로 시험 대상을 바꾸세요.

## 9. VM3 — gNB2 실행

UE가 gNB1에 붙고 기본 통신을 확인한 뒤 VM3의 전용 터미널에서:

```bash
source "$HOME/lab.env"
cd "$OAI_BUILD"
mkdir -p "$OAI_ROOT/lab-logs"
set -o pipefail
sudo ./nr-softmodem \
  -O "$OAI_ROOT/lab-config/gnb.sa.band78.fr1.106PRB.pci1.rfsim.conf" \
  --telnetsrv --telnetsrv.shrmod ci \
  --gNBs.[0].min_rxtxtime 6 --rfsim \
  --rfsimulator.[0].serveraddr "$UE_VM_IP" \
  2>&1 | tee "$OAI_ROOT/lab-logs/gnb2.log"
```

VM1에서 두 gNB의 NG Setup과 UPF PFCP association을 확인합니다.

```bash
source "$HOME/lab.env"
cd "$FREE5GC_COMPOSE"
docker compose logs --since 10m free5gc-amf free5gc-smf
```

## 10. VM2 — 수동 N2 핸드오버

아직 방화벽 차단 정책이 없는 상태에서 먼저 시험합니다. VM4의 점검 터미널에 연속 Ping을 켜 둡니다.

```bash
ping -I oaitun_ue1 8.8.8.8
```

VM2의 점검 터미널에서:

```bash
sudo ss -lntp | grep ':9090'
printf 'ci trigger_n2_ho 1,1\n' | nc -N -w 3 127.0.0.1 9090
```

`1,1`은 **target PCI 1, UE RRC ID 1**입니다. 두 번째 값은 IMSI가 아닙니다. 현재 OAI 로그에서 UE의 RRC ID가 1인지 먼저 확인하고 다르면 바꿉니다. OAI 버전에 따라 telnet 명령 지원·ID 표현이 다를 수 있습니다.

VM2·VM3에서 각각:

```bash
grep -iE 'handover|path.?switch|rrc.*reconfig' "$OAI_ROOT/lab-logs/gnb"*.log | tail -n 40
```

VM1에서:

```bash
source "$HOME/lab.env"
cd "$FREE5GC_COMPOSE"
docker compose logs --since 5m free5gc-amf free5gc-smf
```

VM4에서 터널 IP와 Ping 복구 여부를 확인합니다. Ping 중단이 없거나 복구되었다는 것만으로 UPF 이전까지 성공했다고 판단하지 않습니다. 필요하면 VM2·VM3 각각에서 GTP-U 트래픽을 비교합니다.

```bash
source "$HOME/lab.env"
sudo tcpdump -ni "$EDGE_IF" udp port 2152
```

역방향 HO는 **현재 Source가 된 VM3**에서 target PCI `0`으로 보냅니다. 현재 RRC ID를 다시 확인합니다.

```bash
printf 'ci trigger_n2_ho 0,1\n' | nc -N -w 3 127.0.0.1 9090
```

다음 방화벽 실험을 VM2 Source 기준으로 진행하려면 역방향 HO 후 VM2의 실제 데이터 경로를 확인하거나, gNB·UE를 종료하고 7~9절 순서로 다시 붙입니다. `Ctrl+C`는 실행 중인 전용 터미널에서 누릅니다.

다음: [2. Firewall NSF 적용·해제](02-firewall.md).
