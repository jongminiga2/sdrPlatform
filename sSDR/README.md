# sSDR (Rev3)

[sSDR](https://docs.wsdr.io/hardware/ssdr.html) — M.2 폼팩터 기반 고성능 SDR 트랜시버입니다. AMD UltraScale+ FPGA와 LMS7002M + LMS8001 RFIC를 탑재하여 30 MHz ~ 11 GHz 광대역을 지원합니다.

## 사양

### RF 성능

| 항목 | MIMO 모드 | SISO 모드 |
|------|-----------|-----------|
| 주파수 범위 | 30 MHz – 11 GHz | 30 MHz – 11 GHz |
| 샘플링 레이트 | 0.1 – 86 MSps | 122.88 MSps |
| 채널 대역폭 | 0.5 – 120 MHz | 122.88 MHz |
| 채널 구성 | 2 RX / 2 TX | 1 RX / 1 TX |

### 하드웨어

| 항목 | 사양 |
|------|------|
| FPGA | AMD UltraScale+ XCAU7P |
| RF 칩 | LMS7002M + LMS8001 |
| 폼팩터 | M.2 2242 (22 × 42 × ~3 mm) |
| 인터페이스 | M.2 2242 M key (PCIe 3.0 ×4 + USB 2.0) |
| RF 커넥터 | MHF 7S |
| 클럭 동기화 | 외부 동기화 지원 (멀티보드 어레이) |
| 소비 전력 | 2.9 W (일반) / 5.5 W (최대) |
| 전원 전압 | 2.85 – 5.5 V |

## 소프트웨어 지원

| 항목 | 내용 |
|------|------|
| OS | Ubuntu 20.04 / 22.04 / 24.04, Debian 12, Raspberry Pi OS |
| 드라이버 | usdr-lib (feature_pe_sync branch) |
| 커널 모듈 | usdr_pcie_uram |
| SDR 프레임워크 | SoapySDR |
| GUI 도구 | CubicSDR, GNU Radio, Gqrx |

## 요구사항

```
cmake
python3
libsoapysdr-dev
libusb-1.0-0-dev
```

## 설치

```bash
# usdr-lib 빌드 및 설치
git clone -b feature_pe_sync https://github.com/wavesdr/usdr-lib.git
cd usdr-lib
mkdir build && cd build
cmake .. && make -j$(nproc)
sudo make install

# 커널 드라이버 로드
sudo modprobe usdr_pcie_uram

# SoapySDR 플러그인 확인
SoapySDRUtil --find
```

## 사용법

```bash
# 장치 확인
SoapySDRUtil --find="driver=usdr"

# CubicSDR 실행
cubicsdr

# GNU Radio 실행
gnuradio-companion
```

## 주요 응용 분야

- 5G / 4G 무선 통신 연구
- 레이더 및 원격 탐지
- X-밴드 시스템
- 임베디드 주파수 분석
- 위성 데이터 링크

## 참고

- [sSDR 공식 문서](https://docs.wsdr.io/hardware/ssdr.html)
- [상위 디렉토리로](../README.md)
