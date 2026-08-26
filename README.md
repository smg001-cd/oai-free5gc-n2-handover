# oai-free5gc-n2-handover

## 1. UPF용 IP 추가

### VM2 (Edge1)

gNB1은 `192.168.192.140`, UPF1은 별도 IP `192.168.192.240`을 사용한다.

```bash
sudo ip addr add 192.168.192.240/24 dev ens33
```

확인:

```bash
ip addr show ens33
```

### VM3 (Edge2)

gNB2는 `192.168.192.141`, UPF2는 별도 IP `192.168.192.241`을 사용한다.

```bash
sudo ip addr add 192.168.192.241/24 dev ens33
```

확인:

```bash
ip addr show ens33
```

---

## 2. UPF 실행

VM2 / VM3 각각:

```bash
sudo modprobe gtp5g
cd ~/free5gc-compose
```

```bash
docker compose -f docker-compose-upf-only.yaml up -d
```

로그 확인:

```bash
docker logs -f upf
```

---

## 3. VM2 gNB1 실행

```bash
cd ~/openairinterface5g/cmake_targets/ran_build/build
```

```bash
sudo ./nr-softmodem \
  -O ../../../targets/PROJECTS/GENERIC-NR-5GC/CONF/gnb.sa.band78.fr1.106PRB.pci0.rfsim.conf \
  --telnetsrv \
  --telnetsrv.shrmod ci \
  --gNBs.[0].min_rxtxtime 6 \
  --rfsim \
  --rfsimulator.[0].serveraddr 192.168.192.146
```

---

## 4. VM4 UE 실행

```bash
cd ~/openairinterface5g/cmake_targets/ran_build/build
```

```bash
sudo ./nr-uesoftmodem \
  -O ../../../ci-scripts/conf_files/nrue.uicc.conf \
  -r 106 \
  --numerology 1 \
  --band 78 \
  -C 3619200000 \
  --rfsim \
  --rfsimulator.[0].serveraddr server
```

PDU Session 확인:

```bash
ifconfig oaitun_ue1
```

---

## 5. VM3 gNB2 실행

```bash
cd ~/openairinterface5g/cmake_targets/ran_build/build
```

```bash
sudo ./nr-softmodem \
  -O ../../../targets/PROJECTS/GENERIC-NR-5GC/CONF/gnb.sa.band78.fr1.106PRB.pci1.rfsim.conf \
  --telnetsrv \
  --telnetsrv.shrmod ci \
  --gNBs.[0].min_rxtxtime 6 \
  --rfsim \
  --rfsimulator.[0].serveraddr 192.168.192.146
```

---

## 6. N2 Handover 실행

Source gNB인 VM2에서:

```bash
echo "ci trigger_n2_ho 1,1" | nc 127.0.0.1 9090 && echo
```

첫 번째 `1`: Target gNB PCI  
두 번째 `1`: UE RRC ID

### 실행 순서

```text
VM2/VM3 UPF 실행
        ↓
VM2 gNB1 실행
        ↓
VM4 UE 실행
        ↓
oaitun_ue1 생성 확인
        ↓
VM3 gNB2 실행
        ↓
VM2에서 N2 Handover Trigger
```

---

## 7. UE 트래픽 NAT 설정 — VM2, VM3

```bash
sudo iptables -t nat -A POSTROUTING \
  -s 10.0.0.0/24 \
  -o ens33 \
  -j MASQUERADE
```

Forward 허용:

```bash
sudo iptables -A FORWARD \
  -i upfgtp \
  -o ens33 \
  -j ACCEPT
```

응답 트래픽 허용:

```bash
sudo iptables -A FORWARD \
  -i ens33 \
  -o upfgtp \
  -m conntrack \
  --ctstate RELATED,ESTABLISHED \
  -j ACCEPT
```

UPF 라우팅 확인:

```bash
sudo ip route add 10.0.0.0/24 dev upfgtp
```
## 8. Firewall NSF 정책 적용 및 테스트

UPF-side NSF Manager를 통해 Firewall NSF를 실행하고, UE의 N6 트래픽에 차단 정책을 적용한다.

### 8.1 Firewall NSF / UPF NSF Manager 이미지 빌드

VM2와 VM3에서 각각 실행한다.

Firewall NSF 이미지 빌드:

```bash
cd ~/i2nsf/firewall-nsf
docker build -t firewall-nsf:latest .
```

UPF NSF Manager 이미지 빌드:

```bash
cd ~/i2nsf/upf-nsf-manager
docker build -t upf-nsf-manager:latest .
```

### 8.2 UPF와 NSF Manager 실행

VM2 / VM3에서:

```bash
cd ~/free5gc-compose

docker compose up -d \
  free5gc-upf \
  upf-nsf-manager
```

실행 상태 확인:

```bash
docker ps
```

VM2 Source UPF Manager 로그 확인:

```bash
docker logs -f s-upf-nsf-manager
```

VM3 Target UPF Manager 로그 확인:

```bash
docker logs -f t-upf-nsf-manager
```

---

### 8.3 정책 적용 전 UE 통신 확인

`oaitun_ue1`은 VM4의 OAI UE에 생성된다.

VM4에서:

```bash
ifconfig oaitun_ue1
```

UE IP 확인:

```text
oaitun_ue1
inet 10.0.0.1
```

정책 적용 전에 인터넷 통신이 정상적으로 되는지 확인한다.

```bash
ping -I oaitun_ue1 -c 3 8.8.8.8
```

정상 상태에서는 Ping 응답이 수신되어야 한다.

---

### 8.4 Firewall 정책 적용

VM2 Source UPF의 NSF Manager에 UE 차단 정책을 전달한다.

```bash
curl -X POST \
  http://192.168.192.140:9095/policy/install \
  -H "Content-Type: application/json" \
  -d '{
    "policy_id": "policy-001",
    "ue_id": "imsi-001010000000001",
    "ue_ip": "10.0.0.1",
    "n6_if": "ens33",
    "required_nsfs": ["firewall"]
  }'
```

정책이 전달되면 NSF Manager가 Firewall NSF 컨테이너를 실행하고 UE `10.0.0.1`의 N6 트래픽을 차단하는 iptables rule을 설치한다.

Firewall NSF 실행 확인:

```bash
docker ps
```

Firewall NSF 로그 확인:

```bash
docker logs -f s-firewall-nsf
```

---

### 8.5 Firewall Rule 확인

VM2에서 생성된 Firewall chain을 확인한다.

```bash
sudo iptables -L I2NSF-N6 -v -n --line-numbers
```

FORWARD chain 연결도 확인한다.

```bash
sudo iptables -L FORWARD -v -n --line-numbers
```

`I2NSF-N6`에 UE `10.0.0.1`을 대상으로 하는 DROP rule이 생성되어 있어야 한다.

---

### 8.6 UE 트래픽 차단 확인

먼저 VM2 자체의 인터넷 연결을 확인한다.

```bash
ping -c 3 8.8.8.8
```

VM2의 일반 인터넷 통신은 정상적으로 동작해야 한다.

VM4에서 5G UE 트래픽을 확인한다.

```bash
ping -I oaitun_ue1 -c 3 8.8.8.8
```

Firewall 정책이 정상적으로 적용되었다면 UE의 Ping은 실패해야 한다.

VM2에서 Firewall rule의 packet counter를 확인한다.

```bash
sudo iptables -L I2NSF-N6 -v -n
```

UE에서 Ping을 전송할 때 DROP rule의 `pkts`, `bytes` 값이 증가하면 UE 트래픽이 Firewall NSF에 의해 차단되고 있는 것이다.

---

### 8.7 Firewall 정책 제거

VM2 Source UPF의 NSF Manager에 정책 삭제 요청을 전달한다.

```bash
curl -X POST \
  http://192.168.192.140:9095/policy/delete \
  -H "Content-Type: application/json" \
  -d '{
    "policy_id": "policy-001",
    "ue_ip": "10.0.0.1",
    "n6_if": "ens33"
  }'
```

DROP rule이 제거되었는지 확인한다.

```bash
sudo iptables -L I2NSF-N6 -v -n
```

VM4에서 다시 UE 통신을 확인한다.

```bash
ping -I oaitun_ue1 -c 3 8.8.8.8
```

정책이 정상적으로 제거되었다면 다시 Ping 응답이 수신되어야 한다.

### 테스트 결과

```text
정책 적용 전
VM2 Host Internet     → 성공
VM4 5G UE Internet    → 성공

정책 적용 후
VM2 Host Internet     → 성공
VM4 5G UE Internet    → 실패
I2NSF-N6 DROP counter → 증가

정책 제거 후
VM4 5G UE Internet    → 성공
```
