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

## 참고

- [ANTSDR 공식 문서](https://antsdr-docs.microphase.cn/en/latest/)
- [상위 디렉토리로](../README.md)
