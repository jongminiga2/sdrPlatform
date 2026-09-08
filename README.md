# sdrPlatform

Software Defined Radio (SDR) 플랫폼 통합 저장소입니다. 다양한 SDR 하드웨어를 지원하는 드라이버, 설정, 예제 코드를 포함합니다.

## 지원 하드웨어

| 디렉토리 | 하드웨어 | 설명 |
|----------|----------|------|
| [`bladeRF/`](./bladeRF/) | Nuand bladeRF | 광대역 SDR 트랜시버 |
| [`sSDR/`](./sSDR/) | sSDR | 소프트웨어 SDR 모듈 |
| [`u220/`](./u220/) | U220 | SDR 하드웨어 플랫폼 |
| [`xtrx/`](./xtrx/) | XTRX | 미니PCIe SDR 트랜시버 |

## 프로젝트 구조

```
sdrPlatform/
├── bladeRF/        # Nuand bladeRF 관련 코드
├── sSDR/           # sSDR 관련 코드
├── u220/           # U220 관련 코드
└── xtrx/           # XTRX 관련 코드
```

## 시작하기

각 하드웨어 디렉토리의 README를 참고하세요.

## 요구사항

- OS: Linux / Windows
- 각 하드웨어별 드라이버 및 SDK (각 디렉토리 README 참조)

## 라이선스

[LICENSE](./LICENSE)
