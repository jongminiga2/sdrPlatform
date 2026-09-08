# bladeRF

[Nuand bladeRF](https://www.nuand.com/) SDR 하드웨어를 위한 드라이버 및 유틸리티 모음입니다.

## 개요

bladeRF는 Nuand에서 제작한 광대역 소프트웨어 정의 라디오(SDR) 트랜시버입니다. USB 3.0 인터페이스를 통해 47MHz ~ 6GHz 주파수 범위를 지원합니다.

## 사양

| 항목 | 사양 |
|------|------|
| 주파수 범위 | 47 MHz – 6 GHz |
| 대역폭 | 최대 56 MHz |
| 인터페이스 | USB 3.0 |
| FPGA | Altera Cyclone IV / V |

## 요구사항

- libbladeRF
- bladeRF CLI tools
- (선택) GNU Radio

## 설치

```bash
# Ubuntu/Debian
sudo apt-get install libbladerf-dev bladerf

# Windows
# Nuand 공식 사이트에서 드라이버 설치
```

## 사용법

```bash
# 장치 확인
bladeRF-cli -p

# 예제 실행
# (세부 내용은 추후 추가)
```

## 참고

- [bladeRF 공식 문서](https://github.com/Nuand/bladeRF)
- [상위 디렉토리로](../README.md)
