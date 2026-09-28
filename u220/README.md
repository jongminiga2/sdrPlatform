# ANTSDR U220

[MicroPhase ANTSDR U220](https://antsdr-docs.microphase.cn/en/latest/) — USB 3.0 기반 광대역 SDR 트랜시버입니다. ADI AD9361/AD9363 RFIC를 탑재하여 USRP B210과 호환되는 인터페이스를 제공합니다.

## 사양

### RF 성능

| 항목 | AD9361 | AD9363 |
|------|--------|--------|
| 주파수 범위 | 70 MHz – 6 GHz | 325 MHz – 3.8 GHz |
| 순시 대역폭 | 최대 56 MHz | 최대 20 MHz |
| 샘플링 레이트 | 61.44 MSps | 61.44 MSps |
| ADC/DAC 해상도 | 12-bit | 12-bit |
| TX 최대 출력 | 10 dBm | 10 dBm |
| 노이즈 지수 | < 8 dB | < 8 dB |
| 채널 구성 | 2×2 MIMO | 2×2 MIMO |

### 하드웨어

| 항목 | 사양 |
|------|------|
| FPGA | Xilinx Artix-7 |
| RF 칩 | ADI AD9361 / AD9363 |
| 클럭 | ±0.5 ppm VCTCXO |
| RF 커넥터 | SMA × 4 (2 RX + 2 TX) |
| 인터페이스 | USB 3.0 (Type-C), Gigabit Ethernet |
| 확장 | FPC GPIO, MMCX (PPS/GPS) |
| 디버그 | USB-JTAG, USB-UART |
| 전원 | USB-C 버스 파워 (2–6 W) |

## 소프트웨어 지원

| 항목 | 내용 |
|------|------|
| API | UHD (USRP 호환), SoapySDR |
| GUI 도구 | GNU Radio, Gqrx, SDRangel, SDR# |
| 엔지니어링 툴 | MATLAB Simulink |
| 오픈소스 | srsRAN, Open5G-PHY, gps_sdr_sim |
| OS | Linux (Ubuntu 20.04+), Windows |

## 요구사항

- UHD (USRP Hardware Driver)
- GNU Radio (선택)
- libad9361 (선택)

## 설치

```bash
# UHD 설치 (Ubuntu)
sudo apt-get install libuhd-dev uhd-host python3-uhd

# 펌웨어 이미지 다운로드
sudo uhd_images_downloader

# 장치 확인
uhd_find_devices
```

## 사용법

```bash
# 장치 정보 확인
uhd_usrp_probe

# RX 스트리밍 예시
uhd_rx_samples_to_file --freq 915e6 --rate 1e6 --gain 30 --nsamps 1e6 output.dat

# GNU Radio를 통한 사용
gnuradio-companion
```

## GNSS/GPSDO (중요 — 2026-09-28 실측 확인)

U220 은 MMCX(PPS/GPS) 커넥터로 내장 GNSS 모듈을 갖고 있지만, 기본 설치 방법
(위 "설치" 절 — apt 의 `uhd-host`/`python3-uhd`)만으로는 `gps_locked` 등
GPS 센서가 **절대 인식되지 않는다**. 하드웨어·안테나가 멀쩡해도 "GNSS 미검출"
로 보인다. 아래 두 조건이 모두 맞아야 한다.

1. **`device_args` 에 `name=u220v2` 포함** — 예: `type=b200,name=u220v2`.
   [MicroPhase/antsdr_uhd](https://github.com/MicroPhase/antsdr_uhd) 소스의
   `host/lib/usrp/b200/b200_impl.cpp` 를 보면 `device_addr["name"] == "u220"`
   (또는 `"u220v2"`) 일 때만 GPS UART 통신 속도를 9600bps 로 맞추고(기본은
   Ettus 표준 115200bps), u-blox 모듈 초기화 시퀀스(UBX 바이너리 명령,
   `gps_ctrl.cpp` 의 `is_mp` 플래그)를 보낸다. 이 키가 없으면 드라이버가
   잘못된 baud/프로토콜로 GPS 칩과 통신을 시도해 항상 실패한다.
2. **ANTSDR 패치가 들어간 UHD 빌드 사용** — 위 로직 자체가 Ettus 정식 UHD
   에는 없고 `antsdr_uhd` 포크에만 있다. `antsdr_uhd` 저장소의
   `host/README.md` 대로 소스 빌드(예: `/opt/antsdr-uhd` 에 설치)해서 그
   라이브러리로 열어야 하며, apt 로 설치한 시스템 UHD 만으로는 인식되지
   않는다:
   ```bash
   export PATH=/opt/antsdr-uhd/bin:$PATH
   export LD_LIBRARY_PATH=/opt/antsdr-uhd/lib:$LD_LIBRARY_PATH
   export UHD_IMAGES_DIR=/opt/antsdr-uhd/share/uhd/images
   uhd_usrp_probe --args="type=b200,name=u220v2"
   # Sensors 항목에 gps_locked, gps_gpgga, ... 가 보이면 정상
   ```

`antsdr_uhd` 의 `host/README.md` 자체에는 **GPSDO/GNSS 관련 내용이 없다**
(E200/E310V2 이더넷 보드 빌드 안내만 있음). 위 두 조건은 README 본문이 아니라
소스 코드(`b200_impl.cpp`, `gps_ctrl.cpp`)를 직접 확인해 찾은 내용이다.

**빌드 시 주의 — FPGA 이미지 버전**: `host/README.md` 순서대로 빌드하면
`uhd_images_downloader` 가 그 UHD 버전 시절의 스톡 Ettus B210 FPGA 이미지를
받아오는데, 오래된 버전이면 `fx3 is in state 5` 오류로 장치 오픈 자체가
실패할 수 있다(실측: UHD 4.1.0 빌드의 기본 이미지에서 재현). 이 경우
시스템에 apt 로 설치된 최신 UHD(`uhd-host` 패키지)의
`/usr/share/uhd/images/usrp_b210_fpga.bin` 을 antsdr 빌드의
`share/uhd/images/usrp_b210_fpga.bin` 에 덮어써서 해결했다(원본은 백업 후
교체).

## 참고

- [ANTSDR 공식 문서](https://antsdr-docs.microphase.cn/en/latest/)
- [antsdr_uhd (GitHub)](https://github.com/MicroPhase/antsdr_uhd)
- [상위 디렉토리로](../README.md)
