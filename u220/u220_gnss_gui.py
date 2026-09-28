#!/usr/bin/env python3
"""ANTSDR U220 (UHD/USRP B210 호환) GNSS/GPSDO 상태 모니터 (Tkinter GUI).

u220_spectrum_gui.py 와 동일한 UI/구조(Tkinter + 워커 스레드 + 큐 폴링)를
GNSS 상태 표시용으로 이식했다. 사전 준비물은 install_check_driver.py 로
설치 및 확인한다 (uhd-host, libuhd-dev, python3-uhd).

U220 의 GNSS 모듈은 아래 두 조건이 모두 맞아야 인식된다(2026-09-28 실측 —
README.md 의 "GNSS/GPSDO" 절 참고). 하나라도 빠지면 하드웨어·안테나가
멀쩡해도 GPS 센서 자체가 생기지 않아 "GNSS 미검출"로 보인다.

  1. Device Args 에 name=u220v2 포함 (예: type=b200,name=u220v2).
     MicroPhase/antsdr_uhd 소스의 host/lib/usrp/b200/b200_impl.cpp 를 보면
     device_addr["name"] == "u220"(또는 "u220v2") 일 때만 GPS UART 통신
     속도를 9600bps 로 맞추고(기본은 Ettus 표준 115200bps), u-blox 모듈
     초기화 시퀀스(gps_ctrl.cpp 의 is_mp 플래그)를 보낸다. 이 키가 없으면
     드라이버가 잘못된 baud/프로토콜로 GPS 칩과 통신을 시도해 항상 실패한다.
  2. ANTSDR 패치가 들어간 UHD 빌드 사용 — 위 로직 자체가 Ettus 정식 UHD
     에는 없고 antsdr_uhd 포크에만 있다(그 저장소의 host/README.md 로 빌드
     해 보통 /opt/antsdr-uhd 에 설치). 시스템에 apt 로 설치한 uhd-host/
     python3-uhd 만으로는 GNSS 를 인식할 수 없다. 이 스크립트는 그 경로가
     있으면 시작할 때 자동으로 LD_LIBRARY_PATH/PYTHONPATH/UHD_IMAGES_DIR 를
     맞춰 프로세스를 재실행한다(수동 export 불필요).

사용법:
    python3 u220_gnss_gui.py
"""

import os
import sys

# --- ANTSDR 패치 UHD 자동 부트스트랩 -----------------------------------------
# LD_LIBRARY_PATH 는 이미 떠 있는 프로세스의 이후 동적 로딩에는 반영되지
# 않는 경우가 있어(ld.so 가 시작 시점에 한 번만 파싱), /opt/antsdr-uhd 가
# 있으면 그 라이브러리를 쓰도록 프로세스 자체를 한 번 재실행한다.
_ANTSDR_UHD = '/opt/antsdr-uhd'
if os.path.isdir(_ANTSDR_UHD) and not os.environ.get('_U220_ANTSDR_UHD_SET'):
    _site = (f'{_ANTSDR_UHD}/lib/python'
             f'{sys.version_info.major}.{sys.version_info.minor}/site-packages')
    if os.path.isdir(_site):
        os.environ['_U220_ANTSDR_UHD_SET'] = '1'
        os.environ['LD_LIBRARY_PATH'] = (
            _ANTSDR_UHD + '/lib:' + os.environ.get('LD_LIBRARY_PATH', ''))
        os.environ['PYTHONPATH'] = _site + ':' + os.environ.get('PYTHONPATH', '')
        os.environ.setdefault('UHD_IMAGES_DIR', _ANTSDR_UHD + '/share/uhd/images')
        os.execve(sys.executable, [sys.executable] + sys.argv, os.environ)

import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

os.environ.setdefault('UHD_LOG_LEVEL', 'warning')

try:
    import uhd  # type: ignore
    _UHD_AVAILABLE = True
    _UHD_ERROR = ''
except Exception as _e:                          # noqa: BLE001
    _UHD_AVAILABLE = False
    _UHD_ERROR = str(_e)

POLL_INTERVAL_S = 1.0

_FIX_QUALITY = {
    '0': '측위 없음', '1': 'GPS 단독', '2': 'DGPS', '3': 'PPS',
    '4': 'RTK 고정', '5': 'RTK 플로트', '6': '추정', '7': '수동', '8': '시뮬',
}


# =============================================================================
# NMEA 파싱 (droneGun2026/u220_gps.py 와 동일 — uhd 에 의존하지 않는 순수 함수)
# =============================================================================

def _dm_to_deg(val: str, hemi: str):
    """NMEA ddmm.mmmm → 십진 도(度)."""
    if not val:
        return None
    v = float(val)
    deg = int(v // 100)
    dd = deg + (v - deg * 100) / 60.0
    return -dd if hemi in ('S', 'W') else dd


def parse_gpgga(s: str):
    """$--GGA → dict(fix, sats, hdop, lat, lon, alt, utc). 실패 시 None."""
    f = s.split(',')
    if len(f) < 11 or not f[0].endswith('GGA'):
        return None
    t = f[1]
    utc = (f'{t[0:2]}:{t[2:4]}:{t[4:6]} UTC' if len(t) >= 6 else '--:--:--')
    return dict(
        utc=utc,
        fix=_FIX_QUALITY.get(f[6], f'? ({f[6]})'),
        sats=f[7] or '?',
        hdop=f[8] or '?',
        lat=_dm_to_deg(f[2], f[3]),
        lon=_dm_to_deg(f[4], f[5]),
        alt=(f'{f[9]} {f[10]}' if f[9] else '?'),
    )


def parse_gprmc(s: str):
    """$--RMC → dict(status, date, speed_kn). 실패 시 None."""
    f = s.split(',')
    if len(f) < 10 or not f[0].endswith('RMC'):
        return None
    d = f[9]
    date = (f'20{d[4:6]}-{d[2:4]}-{d[0:2]}' if len(d) >= 6 else '-------')
    return dict(
        status=('유효(A)' if f[2] == 'A' else '무효(V)'),
        date=date,
        speed_kn=(f[7] or '0'),
    )


# =============================================================================
# 워커 스레드 — U220(UHD) 장치를 열고 GPS 센서를 주기적으로 읽어 큐로 보낸다
# =============================================================================

class GnssWorker(threading.Thread):
    def __init__(self, out_queue, device_args, use_gpsdo, interval_s):
        super().__init__(daemon=True)
        self.out_queue = out_queue
        self.device_args = device_args
        self.use_gpsdo = use_gpsdo
        self.interval_s = interval_s
        self._stop_event = threading.Event()
        self.error = None

    def stop(self):
        self._stop_event.set()

    def run(self):
        usrp = None
        try:
            usrp = uhd.usrp.MultiUSRP(self.device_args)
            if self.use_gpsdo:
                for setter in (usrp.set_clock_source, usrp.set_time_source):
                    try:
                        setter('gpsdo')
                    except Exception as e:        # noqa: BLE001
                        self._put({'present': None, 'warn': str(e)})

            while not self._stop_event.is_set():
                names = [n for n in usrp.get_mboard_sensor_names()
                         if n.startswith('gps')]
                if names:
                    self._put(self._read(usrp))
                else:
                    self._put({
                        'present': False,
                        'sensor_names': usrp.get_mboard_sensor_names(),
                        'time_sources': usrp.get_time_sources(0),
                        'ref_locked': self._ref_locked(usrp),
                    })
                self._stop_event.wait(self.interval_s)
        except Exception as exc:                  # noqa: BLE001
            self.error = str(exc)
        finally:
            del usrp

    @staticmethod
    def _ref_locked(usrp):
        try:
            s = usrp.get_mboard_sensor('ref_locked')
            return bool(s and s.to_bool())
        except Exception:                         # noqa: BLE001
            return False

    def _read(self, usrp):
        def sensor(name):
            try:
                return usrp.get_mboard_sensor(name)
            except Exception:                     # noqa: BLE001
                return None

        locked = sensor('gps_locked')
        gtime = sensor('gps_time')
        gga = sensor('gps_gpgga')
        rmc = sensor('gps_gprmc')

        epoch = None
        if gtime is not None:
            try:
                epoch = gtime.to_int()
            except Exception:                     # noqa: BLE001
                pass

        return {
            'present': True,
            'locked': bool(locked and locked.to_bool()),
            'ref_locked': self._ref_locked(usrp),
            'epoch': epoch,
            'gga': parse_gpgga(gga.value) if gga is not None else None,
            'rmc': parse_gprmc(rmc.value) if rmc is not None else None,
        }

    def _put(self, payload):
        try:
            self.out_queue.put_nowait(payload)
        except queue.Full:
            pass


# =============================================================================
# UI
# =============================================================================

class GnssApp:
    def __init__(self, root):
        self.root = root
        self.root.title('ANTSDR U220 - GNSS/GPSDO 모니터')
        self.worker = None
        self.status_queue = queue.Queue(maxsize=4)

        self._build_controls()
        self._build_status()
        if not _UHD_AVAILABLE:
            messagebox.showwarning(
                'UHD 모듈 없음',
                f'python uhd 모듈을 불러올 수 없습니다:\n{_UHD_ERROR}\n\n'
                '연결 시작을 눌러도 오류로 표시됩니다.')
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)

    # ------------------------------------------------------------------ UI
    def _build_controls(self):
        row = ttk.Frame(self.root, padding=(8, 8, 8, 4))
        row.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(row, text='Device Args').pack(side=tk.LEFT, padx=(0, 4))
        self.args_var = tk.StringVar(value='type=b200,name=u220v2')
        args_entry = ttk.Entry(row, textvariable=self.args_var, width=28)
        args_entry.pack(side=tk.LEFT, padx=(0, 12))

        self.gpsdo_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text='clock/time source = gpsdo 로 설정',
                        variable=self.gpsdo_var).pack(side=tk.LEFT, padx=(0, 12))

        self.start_btn = ttk.Button(row, text='연결 시작', command=self.start)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 4))
        self.stop_btn = ttk.Button(row, text='정지', command=self.stop,
                                    state='disabled')
        self.stop_btn.pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value='대기 중')
        ttk.Label(self.root, textvariable=self.status_var,
                  padding=(8, 0)).pack(side=tk.TOP, anchor='w')

    def _build_status(self):
        frame = ttk.Frame(self.root, padding=8)
        frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.lock_var = tk.StringVar(value='—')
        self.lock_lbl = ttk.Label(frame, textvariable=self.lock_var,
                                   font=('TkDefaultFont', 20, 'bold'))
        self.lock_lbl.grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 8))

        rows = [
            ('기준클럭(ref_locked)', 'ref_var'),
            ('GPS 시간(gps_time)', 'gtime_var'),
            ('측위 상태(fix)', 'fix_var'),
            ('위성 수 / HDOP', 'sats_var'),
            ('위도', 'lat_var'),
            ('경도', 'lon_var'),
            ('고도', 'alt_var'),
            ('UTC 시각', 'utc_var'),
            ('날짜 / 속도', 'daterate_var'),
        ]
        for i, (label, attr) in enumerate(rows, start=1):
            ttk.Label(frame, text=label + ' :').grid(
                row=i, column=0, sticky='w', pady=2)
            var = tk.StringVar(value='---')
            setattr(self, attr, var)
            ttk.Label(frame, textvariable=var).grid(
                row=i, column=1, sticky='w', padx=(8, 0), pady=2)

        ttk.Label(frame, text='진단(센서 미검출 시)').grid(
            row=len(rows) + 1, column=0, sticky='nw', pady=(12, 2))
        self.diag_text = tk.Text(frame, height=6, width=60, state='disabled')
        self.diag_text.grid(row=len(rows) + 1, column=1, sticky='w',
                             padx=(8, 0), pady=(12, 2))

    # --------------------------------------------------------------- logic
    def start(self):
        device_args = self.args_var.get().strip()
        self.worker = GnssWorker(self.status_queue, device_args,
                                  self.gpsdo_var.get(), POLL_INTERVAL_S)
        self.worker.start()
        self.status_var.set(f'연결 중... (device_args="{device_args}")')
        self.start_btn.configure(state='disabled')
        self.stop_btn.configure(state='normal')
        self.root.after(200, self._poll_queue)
        self.root.after(500, self._check_worker_error)

    def stop(self):
        if self.worker is not None:
            self.worker.stop()
            self.worker.join(timeout=3)
            self.worker = None
        self.start_btn.configure(state='normal')
        self.stop_btn.configure(state='disabled')
        self.status_var.set('정지됨')

    def _check_worker_error(self):
        if self.worker is not None:
            if self.worker.error:
                messagebox.showerror('U220(UHD) 오류', self.worker.error)
                self.stop()
                return
            if self.worker.is_alive():
                self.root.after(500, self._check_worker_error)

    def _poll_queue(self):
        if self.worker is None:
            return
        payload = None
        try:
            while True:
                payload = self.status_queue.get_nowait()
        except queue.Empty:
            pass

        if payload is not None:
            self._render(payload)

        if self.worker is not None:
            self.root.after(200, self._poll_queue)

    def _render(self, p: dict):
        if p.get('present') is False:
            self.status_var.set('GPS 센서 미검출 — GPSDO/GNSS 모듈이 인식되지 않았습니다')
            self.lock_var.set('✖ GNSS 미검출')
            self.lock_lbl.configure(foreground='red')
            self.ref_var.set('잠금' if p.get('ref_locked') else '미잠금')
            for v in (self.gtime_var, self.fix_var, self.sats_var, self.lat_var,
                      self.lon_var, self.alt_var, self.utc_var, self.daterate_var):
                v.set('---')
            self.diag_text.configure(state='normal')
            self.diag_text.delete('1.0', tk.END)
            self.diag_text.insert(tk.END,
                f"노출된 마더보드 센서: {p.get('sensor_names')}\n"
                f"지원 타임 소스      : {p.get('time_sources')}\n\n"
                "device_args 에 name=u220v2 가 있는지, ANTSDR 패치 UHD 빌드"
                "(/opt/antsdr-uhd)를 쓰고 있는지 확인하세요\n"
                "(README.md 의 'GNSS/GPSDO' 절 참고).")
            self.diag_text.configure(state='disabled')
            return

        if p.get('present') is None:
            # gpsdo 클럭/타임 소스 설정 경고
            self.diag_text.configure(state='normal')
            self.diag_text.insert(tk.END, f"[경고] {p.get('warn')}\n")
            self.diag_text.configure(state='disabled')
            return

        self.status_var.set('GPS 센서 검출됨')
        self.lock_var.set('✔ GPS LOCKED' if p['locked'] else '✖ GPS UNLOCK')
        self.lock_lbl.configure(foreground='green' if p['locked'] else 'orange')
        self.ref_var.set('잠금' if p['ref_locked'] else '미잠금')

        if p['epoch'] is not None:
            self.gtime_var.set(time.strftime('%Y-%m-%d %H:%M:%S UTC',
                                              time.gmtime(p['epoch'])))
        else:
            self.gtime_var.set('---')

        g = p.get('gga')
        if g:
            self.fix_var.set(g['fix'])
            self.sats_var.set(f"{g['sats']}개 / HDOP {g['hdop']}")
            self.lat_var.set(f"{g['lat']:.6f}°" if g['lat'] is not None else '---')
            self.lon_var.set(f"{g['lon']:.6f}°" if g['lon'] is not None else '---')
            self.alt_var.set(g['alt'])
            self.utc_var.set(g['utc'])
        else:
            self.fix_var.set('측위 정보(GPGGA) 없음 — 위성 수신 대기 중')
            for v in (self.sats_var, self.lat_var, self.lon_var,
                      self.alt_var, self.utc_var):
                v.set('---')

        r = p.get('rmc')
        if r:
            self.daterate_var.set(f"{r['date']}  {r['status']}  {r['speed_kn']} kn")
        else:
            self.daterate_var.set('---')

    def on_close(self):
        self.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    GnssApp(root)
    root.geometry('560x520')
    root.mainloop()


if __name__ == '__main__':
    main()
