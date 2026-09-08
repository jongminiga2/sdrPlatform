# XTRX

[XTRX](https://xtrx.io/) 미니PCIe SDR 트랜시버를 위한 드라이버 및 유틸리티 모음입니다.

## 개요

XTRX는 미니PCIe 폼팩터의 고성능 SDR 트랜시버로, LMS7002M RF 트랜시버 칩을 기반으로 합니다. 소형 사이즈에 높은 성능을 제공합니다.

## 사양

| 항목 | 사양 |
|------|------|
| 주파수 범위 | 30 MHz – 3.7 GHz |
| 대역폭 | 최대 120 MHz |
| 인터페이스 | PCIe (미니PCIe) |
| RF 칩 | LMS7002M |
| 채널 | 2×2 MIMO |

## 요구사항

- xtrx-linux-pcie-drv (PCIe 드라이버)
- libxtrx
- (선택) SoapySDR, GNU Radio

## 설치

```bash
# 드라이버 설치 (Linux)
git clone https://github.com/xtrx-sdr/xtrx-linux-pcie-drv.git
cd xtrx-linux-pcie-drv
make && sudo make install
sudo modprobe xtrx

# libxtrx 설치
git clone https://github.com/xtrx-sdr/libxtrx.git
cd libxtrx
mkdir build && cd build
cmake .. && make && sudo make install
```

## 사용법

```bash
# 장치 확인
xtrx_test

# 예제 실행
# (세부 내용은 추후 추가)
```

## 참고

- [XTRX 공식 GitHub](https://github.com/xtrx-sdr)
- [상위 디렉토리로](../README.md)
