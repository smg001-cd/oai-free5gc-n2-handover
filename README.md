# oai-free5gc-n2-handover

## 1. UPF용 IP 추가

### VM2 (Edge1)

gNB1은 `192.168.192.140`, UPF1은 별도 IP `192.168.192.240`을 사용한다.

```bash
sudo ip addr add 192.168.192.240/24 dev ens33

확인
```bash
ip addr show ens33

VM3 (Edge2)

gNB2는 192.168.192.141, UPF2는 별도 IP 192.168.192.241을 사용한다.

sudo ip addr add 192.168.192.241/24 dev ens33

확인:

ip addr show ens33

##2.upf실행
VM2 / VM3 각각:

sudo modprobe gtp5g
cd ~/free5gc-compose


docker compose -f docker-compose-upf-only.yaml up -d

로그 확인:
docker logs -f upf

3. VM2 gNB1 실행
cd ~/openairinterface5g/cmake_targets/ran_build/build


sudo ./nr-softmodem \
  -O ../../../targets/PROJECTS/GENERIC-NR-5GC/CONF/gnb.sa.band78.fr1.106PRB.pci0.rfsim.conf \
  --telnetsrv \
  --telnetsrv.shrmod ci \
  --gNBs.[0].min_rxtxtime 6 \
  --rfsim \
  --rfsimulator.[0].serveraddr 192.168.192.146

4. VM4 UE 실행
cd ~/openairinterface5g/cmake_targets/ran_build/build


sudo ./nr-uesoftmodem \
  -O ../../../ci-scripts/conf_files/nrue.uicc.conf \
  -r 106 \
  --numerology 1 \
  --band 78 \
  -C 3619200000 \
  --rfsim \
  --rfsimulator.[0].serveraddr server

PDU Session 확인:

ifconfig oaitun_ue1
5. VM3 gNB2 실행
cd ~/openairinterface5g/cmake_targets/ran_build/build


sudo ./nr-softmodem \
  -O ../../../targets/PROJECTS/GENERIC-NR-5GC/CONF/gnb.sa.band78.fr1.106PRB.pci1.rfsim.conf \
  --telnetsrv \
  --telnetsrv.shrmod ci \
  --gNBs.[0].min_rxtxtime 6 \
  --rfsim \
  --rfsimulator.[0].serveraddr 192.168.192.146
6. N2 Handover 실행

Source gNB인 VM2에서:

echo "ci trigger_n2_ho 1,1" | nc 127.0.0.1 9090 && echo
첫 번째 1: Target gNB PCI
두 번째 1: UE RRC ID
실행 순서
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
