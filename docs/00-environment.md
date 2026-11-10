# 0. VM·도구·소스 준비

[전체 목차](../README.md) · 다음: [1. 핸드오버](01-handover.md)

## 1. 필요한 환경과 버전

이 가이드는 Ubuntu Linux VM 5대가 같은 실험망에서 통신하는 구성을 사용합니다. RF Simulator를 사용하므로 SDR 장비는 필요하지 않습니다. CPU·메모리는 OAI 빌드와 두 gNB·UE의 실행 부하를 감당할 만큼 할당하세요. 실행 중 CPU가 포화되면 RF 처리 지연을 먼저 확인합니다.

| 항목 | 기준 | 비고 |
|---|---|---|
| free5GC 이미지·compose·소스 | `v4.2.3` | 이 저장소 설정의 기준 |
| gtp5g | `v0.9.5` | free5gc-compose v4.2.3의 명시 버전 |
| Docker | Engine + Compose v2 | `docker compose version` 확인 |
| Python | Python 3 + venv | Flask는 각 venv, 설정 편집은 `python3-yaml` |
| Node.js | 22 계열 예제 | 기존 IUF 문서의 기준, 최신 버전 호환성 보장 아님 |
| OAI | 원본 실험 commit 미기록 | 세 VM에서 같은 commit을 사용하고 기록 |
| Linux kernel | 원본 실험 버전 미기록 | gtp5g v0.9.5 빌드 가능 여부 확인 |

OAI `develop`은 계속 변합니다. 아래 신규 설치는 시작점이며 원 실험의 검증된 버전 조합을 복원하는 절차는 아닙니다. 이미 동작하던 OAI checkout이 있다면 그것을 우선 사용하고 자동 업데이트하지 마세요.

공식 근거: [free5gc-compose v4.2.3](https://github.com/free5gc/free5gc-compose/tree/v4.2.3), [gtp5g](https://github.com/free5gc/gtp5g), [OAI 빌드 문서](https://github.com/OPENAIRINTERFACE/openairinterface5g/blob/develop/doc/BUILD.md). 모듈의 최신 버전이 지원하는 kernel과 `v0.9.5`가 지원하는 kernel은 같다고 가정하면 안 됩니다.

## 2. Windows에서 VM 접속

각 VM에 Ubuntu를 설치하고 SSH 서버를 준비합니다. VM 콘솔의 Bash에서:

```bash
sudo apt update
sudo apt install -y openssh-server
sudo systemctl enable --now ssh
whoami
ip -4 -br addr
```

`whoami` 결과가 로그인 사용자명입니다. IP는 `lo`가 아닌 실험망 NIC의 IPv4를 사용합니다. VM 네트워크는 서로 통신 가능한 브리지 또는 라우팅된 망으로 구성하세요. UPF 추가 IP도 같은 VM으로 전달되어야 합니다.

Windows CMD 또는 PowerShell에서 VM마다 별도 창을 열고 접속합니다. `ubuntu`와 IP는 실제 값으로 바꿉니다.

```powershell
ssh ubuntu@192.168.192.145
```

첫 접속 시 VM 콘솔의 호스트 키 지문과 비교한 뒤 접속을 승인합니다. 이후 문서의 Bash 명령은 이 SSH 창에서 실행합니다. OAI·Gunicorn이 계속 실행될 터미널과 점검용 터미널을 구분하세요. SSH가 끊기면 foreground 프로세스도 종료될 수 있으므로 장시간 실험에는 `tmux`를 사용할 수 있습니다.

## 3. 모든 VM에서 저장소와 공통 변수 준비

모든 VM에서:

```bash
sudo apt update
sudo apt install -y git curl ca-certificates openssl nano tmux \
  python3 python3-venv python3-pip python3-yaml \
  iproute2 iputils-ping netcat-openbsd tcpdump iptables

cd "$HOME"
git clone --branch codex/unified-beginner-guide \
  https://github.com/smg001-cd/oai-free5gc-n2-handover.git
cd "$HOME/oai-free5gc-n2-handover"
git branch --show-current
cp -n examples/lab.env.example "$HOME/lab.env"
nano "$HOME/lab.env"
```

이미 clone했다면 [루트 README의 전환 명령](../README.md)을 사용합니다. `nano`에서는 값을 바꾼 뒤 `Ctrl+O`, `Enter`로 저장하고 `Ctrl+X`로 나옵니다.

`~/lab.env`에서 다음을 수정합니다.

| 변수 | 넣을 값 |
|---|---|
| `CORE_VM_IP` | VM1의 실제 실험망 IP |
| `EDGE1_VM_IP`, `EDGE2_VM_IP` | VM2·VM3의 gNB/호스트 IP |
| `UPF1_IP`, `UPF2_IP` | VM2·VM3에 추가할 미사용 IP |
| `UE_VM_IP`, `IUF_VM_IP` | VM4·VM5의 실제 IP |
| `EDGE_IF` | 현재 Edge VM에서 UPF 추가 IP를 붙일 NIC |
| `N6_IF` | 현재 Edge VM에서 UE 외부 트래픽이 나갈 NIC |
| `LAB_PREFIX` | UPF 추가 IP의 prefix 길이, 예: `24` |
| `UE_CIDR` | 이 가이드에서는 양쪽 UPF 공통 `10.0.0.0/24` |
| 경로 변수 | 기본 설치 위치가 다를 때 수정 |

`EDGE_IF`와 `N6_IF`는 VM마다 달라도 됩니다. NIC 이름은 다음 명령으로 확인합니다.

```bash
ip -4 -br addr
ip route get 8.8.8.8
```

두 번째 명령의 `dev` 뒤가 인터넷 방향 NIC입니다. 외부 인터넷을 쓰지 않으면 시험 대상 데이터망 IP로 바꿉니다. 관리망·Docker망 `10.100.200.0/24`·UE망이 서로 겹치지 않도록 합니다.

**이후 새 터미널을 열 때마다** 공통 변수를 읽습니다.

```bash
source "$HOME/lab.env"
printf 'source=%s\ncore=%s\nue=%s\n' \
  "$PROJECT_SOURCE" "$CORE_VM_IP" "$UE_VM_IP"
```

이 파일의 항목은 `export`를 사용하므로 Python·Compose에서도 읽힙니다. 저장소에 있는 원본 `.conf`·`.yaml`의 고정 IP는 변수 파일만 바꿔서는 바뀌지 않습니다. 다음 문서에서 **실행 위치로 복사한 파일**을 실제 주소로 수정합니다.

## 4. Docker 설치 — VM1·VM2·VM3

이미 `docker version`, `docker compose version`이 정상이라면 설치 부분을 건너뜁니다. 다음은 새 Ubuntu VM에서 [Docker 공식 apt 설치 절차](https://docs.docker.com/engine/install/ubuntu/)를 사용하는 예제입니다. 기존 `docker.io` 등 다른 배포 패키지가 있다면 공식 문서의 충돌 패키지 항목을 먼저 확인합니다.

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker run --rm hello-world
sudo usermod -aG docker "$USER"
```

Docker 그룹은 호스트 관리 권한에 준하는 접근을 부여합니다. 이 실험 가이드는 실험 VM의 해당 사용자가 Docker를 사용할 수 있다고 가정합니다. 그룹 추가 뒤 SSH를 종료하고 다시 접속합니다.

```bash
exit
```

Windows에서 같은 `ssh 사용자@VM주소`로 다시 접속한 뒤:

```bash
source "$HOME/lab.env"
docker version
docker compose version
docker ps
```

`permission denied ... docker.sock`이면 그룹 변경이 현재 로그인에 적용되었는지 `id`로 확인합니다.

## 5. free5gc-compose 받기 — VM1·VM2·VM3

처음 설치할 때만:

```bash
source "$HOME/lab.env"
git clone --branch v4.2.3 --depth 1 \
  https://github.com/free5gc/free5gc-compose.git "$FREE5GC_COMPOSE"
test -d "$FREE5GC_COMPOSE/config"
test -d "$FREE5GC_COMPOSE/cert"
git -C "$FREE5GC_COMPOSE" rev-parse HEAD
```

기존 디렉터리가 있으면 재 clone하지 말고 버전과 수정 사항을 먼저 확인합니다.

```bash
git -C "$FREE5GC_COMPOSE" status --short
git -C "$FREE5GC_COMPOSE" describe --tags --always
```

이 저장소의 `core/`에는 AMF·SMF 설정만 있습니다. 나머지 NF 설정, 인증서, `uerouting.yaml`은 upstream의 `config/`, `cert/`를 사용합니다. 여기서는 Core에 로컬 UPF·UERANSIM·TNGF를 띄우지 않습니다.

## 6. gtp5g 준비 — VM2·VM3

먼저 이미 설치되어 있는지 확인합니다.

```bash
uname -r
modinfo gtp5g
sudo modprobe gtp5g
lsmod | grep gtp5g
```

모듈이 없다면 **현재 kernel에 맞는 headers**를 설치하고 v0.9.5를 빌드합니다.

```bash
sudo apt install -y build-essential cmake autoconf libtool pkg-config \
  libmnl-dev libyaml-dev "linux-headers-$(uname -r)"
git clone --branch v0.9.5 --depth 1 \
  https://github.com/free5gc/gtp5g.git "$HOME/gtp5g"
cd "$HOME/gtp5g"
make
sudo make install
sudo modprobe gtp5g
modinfo gtp5g | head
lsmod | grep gtp5g
```

컴파일 실패 시 UPF 실행으로 넘어가지 말고 kernel과 모듈 호환성을 확인합니다. Secure Boot가 서명되지 않은 모듈 로드를 막으면 VM의 모듈 서명 정책도 확인합니다. kernel 업데이트 후에는 모듈을 다시 빌드해야 할 수 있습니다.

## 7. OAI 준비 — VM2·VM3·VM4

동작하던 OAI가 있으면 먼저 commit을 기록합니다.

```bash
source "$HOME/lab.env"
git -C "$OAI_ROOT" rev-parse HEAD
```

새로 설치한다면 VM2에서:

```bash
git clone https://gitlab.eurecom.fr/oai/openairinterface5g.git "$OAI_ROOT"
git -C "$OAI_ROOT" switch develop
git -C "$OAI_ROOT" rev-parse HEAD
```

출력한 40자리 commit을 복사합니다. VM3·VM4도 clone하고 **VM2와 같은 commit**으로 맞춥니다. 아래 명령은 commit을 입력받습니다.

```bash
git clone https://gitlab.eurecom.fr/oai/openairinterface5g.git "$OAI_ROOT"
read -r -p 'VM2의 OAI 40자리 commit: ' OAI_COMMIT
git -C "$OAI_ROOT" checkout "$OAI_COMMIT"
git -C "$OAI_ROOT" rev-parse HEAD
```

빌드 전 공식 [BUILD.md](https://github.com/OPENAIRINTERFACE/openairinterface5g/blob/develop/doc/BUILD.md)와 해당 checkout의 `./build_oai -h`를 확인합니다. 다음은 `build_oai` 방식의 예제입니다.

VM2·VM3에서:

```bash
cd "$OAI_ROOT/cmake_targets"
./build_oai -I -w SIMU
./build_oai --gNB -w SIMU --ninja
./build_oai --build-lib telnetsrv
test -x "$OAI_BUILD/nr-softmodem"
find "$OAI_BUILD" -name '*telnetsrv*'
```

VM4에서:

```bash
cd "$OAI_ROOT/cmake_targets"
./build_oai -I -w SIMU
./build_oai --nrUE -w SIMU --ninja
test -x "$OAI_BUILD/nr-uesoftmodem"
```

`-I` 단계는 설치 과정에서 sudo를 요구할 수 있습니다. 실제 checkout에서 옵션이 달라졌다면 그 버전의 도움말을 따릅니다. `trigger_n2_ho` 구현이 존재하는지 VM2·VM3에서 확인합니다.

```bash
grep -R -n 'trigger_n2_ho' "$OAI_ROOT/common" "$OAI_ROOT/openair2" | head
```

심볼이 없거나 telnetsrv 빌드가 실패하면 이 문서의 HO 명령을 그대로 사용할 수 없습니다. 원 실험의 OAI commit 또는 해당 기능을 지원하는 버전을 확보해야 합니다.

## 8. 연결 방향과 포트

| 출발 → 도착 | 포트/프로토콜 | 목적 |
|---|---|---|
| gNB1·gNB2 → Core | `38412/SCTP` | NGAP / N2 |
| Core SMF ↔ UPF1·UPF2 | `8805/UDP` | PFCP / N4 |
| gNB ↔ UPF | `2152/UDP` | GTP-U / N3 |
| gNB1·gNB2 → UE VM | RF Simulator 설정 포트, 보통 `4043/TCP` | 모의 무선 연결 |
| 현재 Source gNB localhost | `9090/TCP` | telnet CI 수동 HO |
| 실험 클라이언트 → Edge | `9095/TCP` | NSF Manager |
| Edge Manager → 같은 Edge | `18080/TCP` | Firewall NSF API |
| IUF → Core | `8001/TCP`, `8005/TCP` | NRF OAuth·NEF |
| NEF 컨테이너 → Core 호스트 | `5001/TCP` | Flask 정책 변환 |
| 브라우저 → IUF | `5000/TCP` | intent 웹 |
| 브라우저 → Core | `5000/TCP` | free5GC 가입자 WebUI |

Docker bridge의 SMF가 Edge로 보낸 패킷과 응답이 왕복하는지 실제 캡처로 확인합니다. Core에서 `nc -z`로 UDP 포트를 검사하는 것만으로 PFCP 연결 성공을 판단하지 않습니다. Docker로 공개한 포트는 UFW 규칙만으로 차단되지 않을 수 있습니다([Docker 공식 설명](https://docs.docker.com/engine/install/ubuntu/)). 인증이 없는 NSF API와 Docker socket을 사용하는 구성은 접근을 제한한 실험망에서 사용합니다.

다음: [1. Core·UPF·OAI와 N2 핸드오버](01-handover.md).
