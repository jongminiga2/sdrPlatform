#!/usr/bin/env python3
"""ANTSDR U220 드라이버(UHD) 설치 및 연결 확인 스크립트.

product/bladeRF 가 libbladeRF 계열 apt 패키지 + python3-bladerf 로 접속을 확인하는 것과
같은 패턴으로 작성했다. 단, U220 은 libiio 기반이 아니라

    - USB 3.0(Type-C)으로 연결되고
    - USRP B210 과 호환되는 UHD(USRP Hardware Driver) 펌웨어로 동작한다
      (공식 문서: "ANTSDR runs firmware compatible with USRP UHD")
    - USB 장치로도 실제 Ettus USRP B210 과 동일한 VID:PID(2500:0020) 로 열거된다

따라서 필요한 것은 libiio 가 아니라 UHD 계열 패키지(uhd-host, libuhd-dev, python3-uhd)이고,
확인은 `uhd_find_devices` / `uhd_usrp_probe` 및 python `uhd` 모듈로 수행한다.

참고 문서:
  https://antsdr-docs.microphase.cn/en/latest/device_and_usage_manual/ANTSDR_U_Series_Module/
      ANTSDR_U220_Reference_Manual/AntsdrU220_Unpacking_examination.html

사용법:
    python3 install_check_driver.py                  # 설치 + 확인 모두 수행
    python3 install_check_driver.py --skip-install    # 확인만 수행
    python3 install_check_driver.py --skip-images     # 설치는 하되 uhd_images_downloader 생략
    python3 install_check_driver.py --args "serial=U220200"  # 특정 장치 지정
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import urllib.request

APT_PACKAGES = [
    "uhd-host",     # uhd_find_devices, uhd_usrp_probe, uhd_images_downloader 등 CLI 도구
    "libuhd-dev",   # 헤더/라이브러리 (C++ 연동 시 필요)
    "python3-uhd",  # python `uhd` 모듈
]

USB_VID_PID = "2500:0020"  # U220 이 USRP B210 호환 펌웨어로 열거될 때의 VID:PID

UHD_IMAGES_DIR = "/usr/share/uhd/images"
STOCK_FPGA_IMAGE = os.path.join(UHD_IMAGES_DIR, "usrp_b210_fpga.bin")

# 실측으로 확인된 사실: Ubuntu uhd-host 패키지의 스톡 usrp_b210_fpga.bin(진짜 Ettus B210용)을
# 그대로 쓰면 U220 에서 "fx3 is in state 5" 오류가 난다. U220 은 실제로는 Artix-7 200T 기반이라
# MicroPhase 공식 저장소(antsdr_uhd)가 배포하는 U220 전용 FPGA 이미지로 교체해야 한다.
VENDOR_FPGA_URLS = {
    "ad9361": "https://github.com/MicroPhase/antsdr_uhd/releases/download/v1.0/antsdr_u220_ad9361.bin",
    "ad9363": "https://github.com/MicroPhase/antsdr_uhd/releases/download/v1.0/antsdr_u220_ad9363.bin",
}


def run(cmd, check=False, use_sudo=False):
    if use_sudo and os.geteuid() != 0:
        cmd = ["sudo"] + cmd
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    if check and result.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}")
    return result


def apt_installed(pkg):
    result = subprocess.run(
        ["dpkg-query", "-W", "-f=${Status}", pkg],
        text=True, capture_output=True,
    )
    return result.returncode == 0 and "install ok installed" in result.stdout


def install_apt_packages(pkgs):
    missing = [p for p in pkgs if not apt_installed(p)]
    if not missing:
        print("[apt] 필요한 패키지가 이미 모두 설치되어 있습니다:", ", ".join(pkgs))
        return True
    print("[apt] 설치할 패키지:", ", ".join(missing))
    run(["apt-get", "update"], use_sudo=True)
    result = run(["apt-get", "install", "-y"] + missing, use_sudo=True)
    return result.returncode == 0


def download_uhd_images():
    """USRP B200/B210 계열 펌웨어(usrp_b200_fw.hex, usrp_b210_fpga.bin)를 내려받는다.

    U220 은 표준 B210 이미지로도 USB VID:PID/시리얼까지 인식되지만, 벤더 문서는
    GPSDO 등 U220 전용 기능을 위해 U220 전용 usrp_b210_fpga.bin 으로 교체하도록
    안내한다. 그 파일은 장치 동봉 자료나
    https://github.com/MicroPhase/antsdr_uhd 저장소에서 별도로 받아야 하며 이
    스크립트가 자동으로 받지는 않는다.
    """
    downloader = shutil.which("uhd_images_downloader")
    if not downloader:
        print("[WARN] uhd_images_downloader 를 찾을 수 없습니다 (uhd-host 설치 확인 필요)")
        return False
    result = run([downloader], use_sudo=True)
    return result.returncode == 0


def install_vendor_fpga_image(rfic):
    """U220 전용 FPGA 이미지로 usrp_b210_fpga.bin 을 교체하고 FX3 를 리셋한다.

    스톡 uhd-host 패키지의 usrp_b210_fpga.bin(진짜 Ettus B210용)을 그대로 쓰면
    U220 에서는 "fx3 is in state 5" 오류가 나는 것을 실제로 확인했다. rfic 은
    보드에 실장된 RFIC 종류에 맞춰 "ad9361" 또는 "ad9363" 을 지정한다.
    """
    url = VENDOR_FPGA_URLS.get(rfic)
    if not url:
        print(f"[FAIL] 알 수 없는 RFIC 종류: {rfic}")
        return False

    tmp_path = f"/tmp/antsdr_u220_{rfic}.bin"
    print(f"[fpga] {url} 다운로드 중...")
    try:
        urllib.request.urlretrieve(url, tmp_path)
    except Exception as e:
        print(f"[FAIL] 다운로드 실패: {e}")
        return False

    backup_path = STOCK_FPGA_IMAGE + ".orig"
    if os.path.exists(STOCK_FPGA_IMAGE) and not os.path.exists(backup_path):
        run(["cp", STOCK_FPGA_IMAGE, backup_path], use_sudo=True)
        print(f"[fpga] 기존 이미지 백업: {backup_path}")

    result = run(["cp", tmp_path, STOCK_FPGA_IMAGE], use_sudo=True)
    if result.returncode != 0:
        print("[FAIL] FPGA 이미지 교체 실패")
        return False
    print(f"[OK] {STOCK_FPGA_IMAGE} 을(를) U220 전용({rfic}) 이미지로 교체했습니다.")

    fx3_util = shutil.which("b2xx_fx3_utils") or "/usr/libexec/uhd/utils/b2xx_fx3_utils"
    print("[fpga] FX3 리셋 중 (교체한 이미지를 반영하려면 필요)...")
    run([fx3_util, "--reset-device"], use_sudo=True)
    return True


def check_usb_enumeration():
    print("=== USB 열거 확인 (VID:PID = 2500:0020, USRP B210 호환) ===")
    result = subprocess.run(["lsusb", "-d", USB_VID_PID], text=True, capture_output=True)
    if result.returncode == 0 and result.stdout.strip():
        print(f"[OK] USB 장치 발견: {result.stdout.strip()}")
        return True
    print(f"[FAIL] USB 에서 {USB_VID_PID} 장치를 찾지 못했습니다.")
    print("  - USB 3.0(파란색) 포트에 연결했는지 확인하세요.")
    print("  - `lsusb` 명령으로 직접 확인해보세요.")
    return False


def check_python_module():
    print("\n=== python `uhd` 모듈 로드 확인 ===")
    try:
        import uhd
        print(f"[OK] uhd 모듈 로드 성공 (버전: {getattr(uhd, '__version__', 'unknown')})")
        return True
    except Exception as e:
        print(f"[FAIL] uhd 모듈 로드 실패: {e}")
        return False


def find_and_probe(device_args=""):
    print("\n=== uhd_find_devices / uhd_usrp_probe 로 U220 접속 확인 ===")

    find_bin = shutil.which("uhd_find_devices")
    probe_bin = shutil.which("uhd_usrp_probe")
    if not find_bin or not probe_bin:
        print("[FAIL] uhd_find_devices/uhd_usrp_probe 를 찾을 수 없습니다 (uhd-host 설치 필요)")
        return False

    result = run([find_bin] + ([f"--args={device_args}"] if device_args else []))
    if "No UHD Devices Found" in result.stdout or result.returncode != 0:
        print("[FAIL] uhd_find_devices 가 장치를 찾지 못했습니다.")
        return False
    print("[OK] uhd_find_devices 로 장치 발견")

    result = run([probe_bin] + ([f"--args={device_args}"] if device_args else []))
    if result.returncode != 0:
        print("[FAIL] uhd_usrp_probe 실행 실패")
        return False

    out = result.stdout
    mboard = re.search(r"Mboard:\s*(\S+)", out)
    serial = re.search(r"serial:\s*(\S+)", out)
    name = re.search(r"name:\s*(\S+)", out)
    print(f"[OK] Mboard={mboard.group(1) if mboard else '?'} "
          f"serial={serial.group(1) if serial else '?'} "
          f"name={name.group(1) if name else '?'}")

    return True


def probe_with_python(device_args=""):
    print("\n=== python `uhd` 모듈로 직접 접속 확인 (bladeRF 예제와 동일한 방식) ===")
    try:
        import uhd
    except Exception as e:
        print(f"[SKIP] uhd 모듈이 없어 생략: {e}")
        return False

    try:
        usrp = uhd.usrp.MultiUSRP(device_args)
        info = usrp.get_usrp_rx_info()
        print(f"[OK] MultiUSRP 접속 성공: {info}")
        print(f"  - RX 채널 수: {usrp.get_rx_num_channels()}")
        print(f"  - RX 주파수 범위: {usrp.get_rx_freq_range(0)}")
        return True
    except Exception as e:
        print(f"[FAIL] MultiUSRP 접속 실패: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-install", action="store_true",
                         help="apt 설치 단계를 건너뛰고 확인만 수행")
    parser.add_argument("--skip-images", action="store_true",
                         help="uhd_images_downloader(펌웨어 다운로드) 단계를 건너뜀")
    parser.add_argument("--args", dest="device_args", default="",
                         help="UHD device args (예: 'serial=U220200')")
    parser.add_argument("--vendor-fpga", choices=["ad9361", "ad9363"], default=None,
                         help="U220 전용 FPGA 이미지로 usrp_b210_fpga.bin 을 교체 "
                              "(스톡 이미지로 'fx3 is in state 5' 오류가 날 때 필요)")
    args = parser.parse_args()

    if not args.skip_install:
        print("=== 1. apt 드라이버 패키지 설치 (uhd-host, libuhd-dev, python3-uhd) ===")
        install_apt_packages(APT_PACKAGES)
        if not args.skip_images:
            print("\n=== 2. USRP B200/B210 펌웨어 이미지 다운로드 ===")
            download_uhd_images()
        print()

    if args.vendor_fpga:
        print(f"=== U220 전용 FPGA 이미지({args.vendor_fpga}) 교체 ===")
        install_vendor_fpga_image(args.vendor_fpga)
        print()

    usb_ok = check_usb_enumeration()
    module_ok = check_python_module()
    probe_ok = find_and_probe(args.device_args)
    python_ok = probe_with_python(args.device_args) if probe_ok else False

    print("\n=== 최종 결과 ===")
    print(f"USB 열거(2500:0020)   : {'OK' if usb_ok else 'FAIL'}")
    print(f"python uhd 모듈       : {'OK' if module_ok else 'FAIL'}")
    print(f"uhd_find/probe CLI    : {'OK' if probe_ok else 'FAIL'}")
    print(f"python MultiUSRP 접속 : {'OK' if python_ok else 'FAIL'}")

    sys.exit(0 if (usb_ok and module_ok and probe_ok) else 2)


if __name__ == "__main__":
    main()
