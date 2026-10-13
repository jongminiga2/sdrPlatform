#!/usr/bin/env python3
"""ANTSDR U220 Device Check GUI

Tabs:
  1. IQ Analysis  — A/B path RX, 61.44/30.72/15.36 MHz, 8192 sample capture
                    Time domain (I/Q waveform) + Frequency domain (PSD)
  2. Device Info  — UHD version, FPGA image, device details (uhd_usrp_probe)
  3. GNSS         — GNSS/GPSDO module detection and live positioning status
"""

import os
import sys

# ── Linux: ANTSDR patched UHD auto-bootstrap ────────────────────────────────
_ANTSDR_UHD = '/opt/antsdr-uhd'
if (os.name != 'nt'
        and os.path.isdir(_ANTSDR_UHD)
        and not os.environ.get('_U220_CHECK_ANTSDR_SET')):
    _site = (f'{_ANTSDR_UHD}/lib/python'
             f'{sys.version_info.major}.{sys.version_info.minor}/site-packages')
    if os.path.isdir(_site):
        os.environ['_U220_CHECK_ANTSDR_SET'] = '1'
        os.environ['LD_LIBRARY_PATH'] = (
            _ANTSDR_UHD + '/lib:' + os.environ.get('LD_LIBRARY_PATH', ''))
        os.environ['PYTHONPATH'] = _site + ':' + os.environ.get('PYTHONPATH', '')
        os.environ.setdefault('UHD_IMAGES_DIR',
                              _ANTSDR_UHD + '/share/uhd/images')
        os.execve(sys.executable, [sys.executable] + sys.argv, os.environ)

# ── Windows: register UHD DLL directory ─────────────────────────────────────
if os.name == 'nt' and hasattr(os, 'add_dll_directory'):
    _uhd_dll_dir = os.environ.get('UHD_DLL_DIR', r'C:\msys64\mingw64\bin')
    if os.path.isdir(_uhd_dll_dir):
        os.add_dll_directory(_uhd_dll_dir)

import json
import queue
import shutil
import subprocess
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

os.environ.setdefault('UHD_LOG_LEVEL', 'warning')

try:
    import uhd
    _UHD_AVAILABLE = True
    _UHD_ERROR = ''
except Exception as _e:
    _UHD_AVAILABLE = False
    _UHD_ERROR = str(_e)

import numpy as np
import matplotlib
matplotlib.use('TkAgg')
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

def _set_korean_font():
    import matplotlib.font_manager as fm
    _kr_candidates = ['Malgun Gothic', 'Gulim', 'Batang', 'NanumGothic']
    for name in _kr_candidates:
        if any(f.name == name for f in fm.fontManager.ttflist):
            matplotlib.rc('font', family=name)
            matplotlib.rcParams['axes.unicode_minus'] = False
            return
_set_korean_font()

_U220_FPGA = os.environ.get('U220_FPGA_IMAGE', r'C:\Temp\antsdr_u220_ad9361.bin')
_SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'u220_check_settings.json')

NUM_SAMPLES = 8192
SAMPLE_RATES  = [61_440_000, 30_720_000, 15_360_000]
SAMPLE_LABELS = ['61.44 MHz', '30.72 MHz', '15.36 MHz']

_FIX_QUALITY = {
    '0': 'No fix',      '1': 'GPS only',   '2': 'DGPS',       '3': 'PPS',
    '4': 'RTK fixed',   '5': 'RTK float',  '6': 'Estimated',  '7': 'Manual',
    '8': 'Simulation',
}


# ─── common helpers ───────────────────────────────────────────────────────────

def _build_dev_args(base: str) -> str:
    args = base.strip()
    if os.path.isfile(_U220_FPGA):
        fpga = f'fpga={_U220_FPGA}'
        return f'{args},{fpga}' if args else fpga
    return args


def _dm_to_deg(val: str, hemi: str):
    if not val:
        return None
    v = float(val)
    deg = int(v // 100)
    dd = deg + (v - deg * 100) / 60.0
    return -dd if hemi in ('S', 'W') else dd


def _parse_gpgga(s: str):
    f = s.split(',')
    if len(f) < 11 or not f[0].endswith('GGA'):
        return None
    t = f[1]
    return dict(
        utc=f'{t[0:2]}:{t[2:4]}:{t[4:6]} UTC' if len(t) >= 6 else '--:--:--',
        fix=_FIX_QUALITY.get(f[6], f'? ({f[6]})'),
        sats=f[7] or '?', hdop=f[8] or '?',
        lat=_dm_to_deg(f[2], f[3]), lon=_dm_to_deg(f[4], f[5]),
        alt=f'{f[9]} {f[10]}' if f[9] else '?',
    )


def _parse_gprmc(s: str):
    f = s.split(',')
    if len(f) < 10 or not f[0].endswith('RMC'):
        return None
    d = f[9]
    return dict(
        status='Valid(A)' if f[2] == 'A' else 'Invalid(V)',
        date=f'20{d[4:6]}-{d[2:4]}-{d[0:2]}' if len(d) >= 6 else '-------',
        speed_kn=f[7] or '0',
    )


def _load_cfg() -> dict:
    try:
        with open(_SETTINGS_FILE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


# ─── worker threads ───────────────────────────────────────────────────────────

class IQCaptureWorker(threading.Thread):
    def __init__(self, out_queue: queue.Queue, params: dict):
        super().__init__(daemon=True)
        self.out_queue = out_queue
        self.params = params

    def run(self):
        usrp = streamer = None
        try:
            usrp = uhd.usrp.MultiUSRP(_build_dev_args(self.params['device_args']))

            num_hw_ch = usrp.get_rx_num_channels()
            channels = [0, 1] if num_hw_ch >= 2 else [0]

            for ch in channels:
                usrp.set_rx_rate(self.params['samplerate'], ch)
                usrp.set_rx_freq(
                    uhd.types.TuneRequest(self.params['freq']), ch)
                usrp.set_rx_bandwidth(self.params['samplerate'] * 0.8, ch)
                if self.params['agc']:
                    usrp.set_rx_agc(True, ch)
                else:
                    usrp.set_rx_agc(False, ch)
                    usrp.set_rx_gain(self.params['gain'], ch)

            fs = usrp.get_rx_rate(0)
            fc = usrp.get_rx_freq(0)

            st_args = uhd.usrp.StreamArgs('fc32', 'sc16')
            st_args.channels = channels
            streamer = usrp.get_rx_stream(st_args)

            buf = np.zeros(
                (len(channels), streamer.get_max_num_samps()), dtype=np.complex64)
            meta = uhd.types.RXMetadata()

            cmd = uhd.types.StreamCMD(uhd.types.StreamMode.start_cont)
            if len(channels) > 1:
                cmd.stream_now = False
                cmd.time_spec = usrp.get_time_now() + uhd.types.TimeSpec(0.1)
            else:
                cmd.stream_now = True
            streamer.issue_stream_cmd(cmd)

            acc = [np.empty(0, dtype=np.complex64) for _ in channels]
            while any(len(a) < NUM_SAMPLES for a in acc):
                n = streamer.recv(buf, meta, 1.0)
                if meta.error_code == uhd.types.RXMetadataErrorCode.timeout:
                    continue
                if meta.error_code == uhd.types.RXMetadataErrorCode.overflow:
                    acc = [np.empty(0, dtype=np.complex64) for _ in channels]
                    continue
                if meta.error_code != uhd.types.RXMetadataErrorCode.none:
                    raise RuntimeError(f'RX error: {meta.strerror()}')
                if n == 0:
                    continue
                for i in range(len(channels)):
                    acc[i] = np.concatenate([acc[i], buf[i, :n]])

            streamer.issue_stream_cmd(
                uhd.types.StreamCMD(uhd.types.StreamMode.stop_cont))

            samples = [a[:NUM_SAMPLES] for a in acc]
            if len(samples) == 1:
                samples.append(samples[0].copy())

            self.out_queue.put({'ok': True, 'samples': samples, 'fs': fs, 'fc': fc})

        except Exception as exc:
            self.out_queue.put({'ok': False, 'error': str(exc)})
        finally:
            try:
                if streamer is not None:
                    streamer.issue_stream_cmd(
                        uhd.types.StreamCMD(uhd.types.StreamMode.stop_cont))
            except Exception:
                pass
            del streamer, usrp


class DeviceInfoWorker(threading.Thread):
    def __init__(self, out_queue: queue.Queue, device_args: str):
        super().__init__(daemon=True)
        self.out_queue = out_queue
        self.device_args = device_args

    def run(self):
        usrp = None
        try:
            lines = []

            lines.append('=' * 58)
            lines.append('  UHD / FPGA Version Info')
            lines.append('=' * 58)
            lines.append(f'  UHD Python Module Version : '
                         f'{getattr(uhd, "__version__", "N/A")}')
            lines.append(f'  FPGA Image Path           : {_U220_FPGA}')
            lines.append(f'  FPGA Image File           : '
                         f'{"Found" if os.path.isfile(_U220_FPGA) else "Not found"}')

            probe = (shutil.which('uhd_usrp_probe')
                     or shutil.which('uhd_usrp_probe.exe'))
            lines.append('')
            lines.append('=' * 58)
            lines.append('  uhd_usrp_probe Output')
            lines.append('=' * 58)
            if probe:
                built_args = _build_dev_args(self.device_args)
                cmd = [probe]
                if built_args:
                    cmd.append(f'--args={built_args}')
                try:
                    r = subprocess.run(
                        cmd, text=True, capture_output=True, timeout=25)
                    lines.append(r.stdout or '  (no output)')
                    if r.stderr:
                        lines.append(f'[stderr]\n{r.stderr}')
                except subprocess.TimeoutExpired:
                    lines.append('  (timeout — exceeded 25 s)')
                except Exception as e:
                    lines.append(f'  (execution failed: {e})')
            else:
                lines.append('  uhd_usrp_probe binary not found.')

            lines.append('')
            lines.append('=' * 58)
            lines.append('  Python UHD API Device Info')
            lines.append('=' * 58)

            usrp = uhd.usrp.MultiUSRP(_build_dev_args(self.device_args))

            try:
                rx_info = usrp.get_usrp_rx_info(0)
                lines.append('\n  ─ RX Info (Ch0) ─')
                for k in rx_info.keys():
                    lines.append(f'    {k:24s}: {rx_info.get(k)}')
            except Exception as e:
                lines.append(f'  RX info query failed: {e}')

            try:
                tx_info = usrp.get_usrp_tx_info(0)
                lines.append('\n  ─ TX Info (Ch0) ─')
                for k in tx_info.keys():
                    lines.append(f'    {k:24s}: {tx_info.get(k)}')
            except Exception as e:
                lines.append(f'  TX info query failed: {e}')

            try:
                sensor_names = list(usrp.get_mboard_sensor_names())
                lines.append(f'\n  ─ Motherboard Sensors ({len(sensor_names)}) ─')
                for name in sensor_names:
                    try:
                        val = usrp.get_mboard_sensor(name)
                        lines.append(f'    {name:24s}: {val.value}')
                    except Exception:
                        lines.append(f'    {name:24s}: (read failed)')
            except Exception as e:
                lines.append(f'  Sensor list query failed: {e}')

            try:
                lines.append('\n  ─ RX Specs ─')
                lines.append(f'    RX Channels       : {usrp.get_rx_num_channels()}')
                fr = usrp.get_rx_freq_range(0)
                lines.append(
                    f'    Freq Range        : {fr.start()/1e6:.1f} – {fr.stop()/1e6:.1f} MHz')
                gr = usrp.get_rx_gain_range(0)
                lines.append(
                    f'    Gain Range        : {gr.start():.0f} – {gr.stop():.0f} dB')
            except Exception as e:
                lines.append(f'  RX spec query failed: {e}')

            try:
                lines.append('\n  ─ Clock/Time Source ─')
                lines.append(
                    f'    Supported Clocks  : {list(usrp.get_clock_sources(0))}')
                lines.append(
                    f'    Supported Times   : {list(usrp.get_time_sources(0))}')
                lines.append(f'    Clock Source      : {usrp.get_clock_source(0)}')
                lines.append(f'    Time Source       : {usrp.get_time_source(0)}')
            except Exception as e:
                lines.append(f'  Clock/time query failed: {e}')

            self.out_queue.put({'ok': True, 'text': '\n'.join(lines)})

        except Exception as exc:
            self.out_queue.put({'ok': False, 'error': str(exc)})
        finally:
            try:
                del usrp
            except Exception:
                pass


class GnssWorker(threading.Thread):
    def __init__(self, out_queue: queue.Queue, device_args: str):
        super().__init__(daemon=True)
        self.out_queue = out_queue
        self.device_args = device_args
        self._stop = threading.Event()
        self.error = None

    def stop(self):
        self._stop.set()

    def run(self):
        usrp = None
        try:
            usrp = uhd.usrp.MultiUSRP(_build_dev_args(self.device_args))
            while not self._stop.is_set():
                gps_names = [n for n in usrp.get_mboard_sensor_names()
                             if n.startswith('gps')]
                if gps_names:
                    self._put(self._read_gps(usrp))
                else:
                    self._put({
                        'present': False,
                        'sensor_names': list(usrp.get_mboard_sensor_names()),
                        'time_sources': list(usrp.get_time_sources(0)),
                        'ref_locked': self._ref_locked(usrp),
                    })
                self._stop.wait(1.0)
        except Exception as exc:
            self.error = str(exc)
        finally:
            try:
                del usrp
            except Exception:
                pass

    @staticmethod
    def _ref_locked(usrp) -> bool:
        try:
            s = usrp.get_mboard_sensor('ref_locked')
            return bool(s and s.to_bool())
        except Exception:
            return False

    def _read_gps(self, usrp) -> dict:
        def sensor(name):
            try:
                return usrp.get_mboard_sensor(name)
            except Exception:
                return None

        locked = sensor('gps_locked')
        gtime  = sensor('gps_time')
        gga    = sensor('gps_gpgga')
        rmc    = sensor('gps_gprmc')

        epoch = None
        if gtime is not None:
            try:
                epoch = gtime.to_int()
            except Exception:
                pass

        return {
            'present':    True,
            'locked':     bool(locked and locked.to_bool()),
            'ref_locked': self._ref_locked(usrp),
            'epoch':      epoch,
            'gga':        _parse_gpgga(gga.value) if gga else None,
            'rmc':        _parse_gprmc(rmc.value) if rmc else None,
        }

    def _put(self, payload: dict):
        try:
            self.out_queue.put_nowait(payload)
        except queue.Full:
            pass


# ─── main app ─────────────────────────────────────────────────────────────────

class U220CheckApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title('ANTSDR U220 — Device Check')
        self._iq_worker   = None
        self._info_worker = None
        self._gnss_worker = None
        self._iq_queue    = queue.Queue(maxsize=4)
        self._info_queue  = queue.Queue(maxsize=4)
        self._gnss_queue  = queue.Queue(maxsize=8)

        self._cfg = _load_cfg()

        if not _UHD_AVAILABLE:
            messagebox.showwarning(
                'UHD Module Missing',
                f'Failed to load python uhd module:\n{_UHD_ERROR}')

        self._build_top_bar()
        self._build_notebook()
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

    def _save_cfg(self):
        cfg = {
            'device_args':       self._args_var.get(),
            'freq':              self._freq_var.get(),
            'agc':               self._agc_var.get(),
            'gain':              self._gain_var.get(),
            'sample_rate_label': self._rate_var.get(),
        }
        try:
            with open(_SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ─── top bar ───────────────────────────────────────────────────────────────
    def _build_top_bar(self):
        bar = ttk.Frame(self.root, padding=(8, 6, 8, 2))
        bar.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(bar, text='Device Args:').pack(side=tk.LEFT, padx=(0, 4))
        self._args_var = tk.StringVar(
            value=self._cfg.get('device_args', 'type=b200,name=u220v2'))
        ttk.Entry(bar, textvariable=self._args_var, width=26).pack(
            side=tk.LEFT, padx=(0, 16))

        ttk.Label(bar, text='Center Freq (Hz):').pack(side=tk.LEFT, padx=(0, 4))
        self._freq_var = tk.StringVar(
            value=self._cfg.get('freq', '889000000'))
        ttk.Entry(bar, textvariable=self._freq_var, width=13).pack(
            side=tk.LEFT, padx=(0, 16))

        self._agc_var = tk.BooleanVar(value=self._cfg.get('agc', True))
        ttk.Checkbutton(bar, text='AGC', variable=self._agc_var,
                        command=self._toggle_gain).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(bar, text='Gain (dB):').pack(side=tk.LEFT, padx=(0, 4))
        self._gain_var = tk.StringVar(value=self._cfg.get('gain', '40'))
        self._gain_entry = ttk.Entry(bar, textvariable=self._gain_var, width=6)
        self._gain_entry.pack(side=tk.LEFT)
        self._toggle_gain()

        sep = ttk.Separator(self.root, orient='horizontal')
        sep.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(4, 0))

    def _toggle_gain(self):
        self._gain_entry.configure(
            state='disabled' if self._agc_var.get() else 'normal')

    def _common_params(self) -> dict | None:
        try:
            return {
                'device_args': self._args_var.get(),
                'freq':        float(self._freq_var.get()),
                'agc':         self._agc_var.get(),
                'gain':        float(self._gain_var.get()),
            }
        except ValueError:
            messagebox.showerror('Input Error', 'Please check numeric values.')
            return None

    # ─── tabs ──────────────────────────────────────────────────────────────────
    def _build_notebook(self):
        self._nb = ttk.Notebook(self.root)
        self._nb.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=(4, 8))

        self._tab_iq   = ttk.Frame(self._nb)
        self._tab_info = ttk.Frame(self._nb)
        self._tab_gnss = ttk.Frame(self._nb)
        self._nb.add(self._tab_iq,   text='  IQ Analysis  ')
        self._nb.add(self._tab_info, text='  Device Info  ')
        self._nb.add(self._tab_gnss, text='  GNSS  ')

        self._build_iq_tab()
        self._build_info_tab()
        self._build_gnss_tab()

    # ═══════════════════════════════════════════════════════════════════════════
    # Tab 1: IQ Analysis
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_iq_tab(self):
        ctrl = ttk.Frame(self._tab_iq, padding=(6, 4))
        ctrl.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(ctrl, text='Sample Rate:').pack(side=tk.LEFT, padx=(0, 4))
        self._rate_var = tk.StringVar(
            value=self._cfg.get('sample_rate_label', SAMPLE_LABELS[0]))
        ttk.Combobox(ctrl, textvariable=self._rate_var, values=SAMPLE_LABELS,
                     width=10, state='readonly').pack(side=tk.LEFT, padx=(0, 16))

        self._iq_btn = ttk.Button(
            ctrl, text=f'Capture  ({NUM_SAMPLES} samples)', command=self._iq_capture)
        self._iq_btn.pack(side=tk.LEFT, padx=(0, 12))

        self._iq_status = tk.StringVar(value='Ready')
        ttk.Label(ctrl, textvariable=self._iq_status,
                  foreground='gray').pack(side=tk.LEFT)

        fig = Figure(figsize=(11, 7), dpi=96)
        fig.patch.set_facecolor('#f5f5f5')
        self._ax_ta = fig.add_subplot(2, 2, 1)
        self._ax_tb = fig.add_subplot(2, 2, 2)
        self._ax_fa = fig.add_subplot(2, 2, 3)
        self._ax_fb = fig.add_subplot(2, 2, 4)

        labels = [
            (self._ax_ta, 'A-path  Time Domain (Ch 0 / RX1)'),
            (self._ax_tb, 'B-path  Time Domain (Ch 1 / RX2)'),
            (self._ax_fa, 'A-path  Freq Domain (Ch 0)'),
            (self._ax_fb, 'B-path  Freq Domain (Ch 1)'),
        ]
        for ax, title in labels:
            ax.set_facecolor('#fefefe')
            ax.set_title(title, fontsize=9)
            ax.grid(True, alpha=0.3)

        self._ax_ta.set_ylabel('Amplitude', fontsize=8)
        self._ax_tb.set_ylabel('Amplitude', fontsize=8)
        self._ax_fa.set_ylabel('PSD (dB)', fontsize=8)
        self._ax_fb.set_ylabel('PSD (dB)', fontsize=8)
        self._ax_fa.set_xlabel('Freq Offset (MHz)', fontsize=8)
        self._ax_fb.set_xlabel('Freq Offset (MHz)', fontsize=8)
        self._ax_ta.set_xlabel('Sample #', fontsize=8)
        self._ax_tb.set_xlabel('Sample #', fontsize=8)

        fig.tight_layout(pad=2.5)
        self._iq_canvas = FigureCanvasTkAgg(fig, master=self._tab_iq)
        self._iq_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self._iq_fig = fig

    def _iq_capture(self):
        if self._iq_worker and self._iq_worker.is_alive():
            return
        params = self._common_params()
        if params is None:
            return
        idx = SAMPLE_LABELS.index(self._rate_var.get())
        params['samplerate'] = SAMPLE_RATES[idx]

        self._iq_btn.configure(state='disabled')
        self._iq_status.set('Capturing...')
        self._iq_queue = queue.Queue(maxsize=4)
        self._iq_worker = IQCaptureWorker(self._iq_queue, params)
        self._iq_worker.start()
        self.root.after(200, self._poll_iq)

    def _poll_iq(self):
        try:
            result = self._iq_queue.get_nowait()
        except queue.Empty:
            if self._iq_worker and self._iq_worker.is_alive():
                self.root.after(200, self._poll_iq)
            else:
                self._iq_btn.configure(state='normal')
                self._iq_status.set('Worker stopped')
            return

        self._iq_btn.configure(state='normal')
        if not result['ok']:
            self._iq_status.set(f"Error: {result['error']}")
            messagebox.showerror('Capture Error', result['error'])
            return

        fs, fc = result['fs'], result['fc']
        self._iq_status.set(
            f"Done — Fc={fc/1e6:.3f} MHz, Fs={fs/1e6:.2f} MHz, {NUM_SAMPLES} samples")
        self._render_iq(result['samples'], fs, fc)

    def _render_iq(self, samples: list, fs: float, fc: float):
        win      = np.hanning(NUM_SAMPLES)
        t        = np.arange(NUM_SAMPLES)
        f_offset = np.fft.fftshift(np.fft.fftfreq(NUM_SAMPLES, d=1.0 / fs)) / 1e6

        amp_max = max(np.max(np.abs(s)) for s in samples)
        amp_lim = amp_max * 1.1 if amp_max > 0 else 1.0

        pairs = [
            (self._ax_ta, self._ax_fa, samples[0], 'A', '0'),
            (self._ax_tb, self._ax_fb, samples[1], 'B', '1'),
        ]
        for ax_t, ax_f, samp, path, ch in pairs:
            ax_t.cla()
            ax_t.set_facecolor('#fefefe')
            ax_t.set_title(f'{path}-path  Time Domain (Ch {ch})', fontsize=9)
            ax_t.plot(t, samp.real, lw=0.7, label='I', color='#1f77b4')
            ax_t.plot(t, samp.imag, lw=0.7, label='Q',
                      color='#ff7f0e', alpha=0.8)
            ax_t.set_ylim(-amp_lim, amp_lim)
            ax_t.set_xlabel('Sample #', fontsize=8)
            ax_t.set_ylabel('Amplitude', fontsize=8)
            ax_t.legend(fontsize=7, loc='upper right')
            ax_t.grid(True, alpha=0.3)

            spec   = np.fft.fftshift(np.fft.fft(samp * win))
            psd_db = 20 * np.log10(np.abs(spec) / NUM_SAMPLES + 1e-12)

            ax_f.cla()
            ax_f.set_facecolor('#fefefe')
            ax_f.set_title(
                f'{path}-path  Freq Domain (Ch {ch})  Fc={fc/1e6:.3f} MHz',
                fontsize=9)
            ax_f.plot(f_offset, psd_db, lw=0.8, color='#2ca02c')
            peak_i = int(np.argmax(psd_db))
            ax_f.axvline(f_offset[peak_i], color='red', lw=0.9, alpha=0.7,
                         linestyle='--',
                         label=f'Peak {psd_db[peak_i]:.1f} dB @ {f_offset[peak_i]:+.3f} MHz')
            ax_f.set_xlabel('Freq Offset (MHz)', fontsize=8)
            ax_f.set_ylabel('PSD (dB)', fontsize=8)
            ax_f.legend(fontsize=7, loc='upper right')
            ax_f.grid(True, alpha=0.3)

        self._iq_fig.tight_layout(pad=2.5)
        self._iq_canvas.draw_idle()

    # ═══════════════════════════════════════════════════════════════════════════
    # Tab 2: Device Info
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_info_tab(self):
        ctrl = ttk.Frame(self._tab_info, padding=(6, 4))
        ctrl.pack(side=tk.TOP, fill=tk.X)

        self._info_btn = ttk.Button(
            ctrl, text='Query Device Info', command=self._query_info)
        self._info_btn.pack(side=tk.LEFT, padx=(0, 6))

        self._info_save_btn = ttk.Button(
            ctrl, text='Save Text', command=self._save_info_text, state='disabled')
        self._info_save_btn.pack(side=tk.LEFT, padx=(0, 12))

        self._info_status = tk.StringVar(value='Ready')
        ttk.Label(ctrl, textvariable=self._info_status,
                  foreground='gray').pack(side=tk.LEFT)

        ver_lf = ttk.LabelFrame(self._tab_info, text='Version Info', padding=(8, 4))
        ver_lf.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(2, 4))

        uhd_ver = (getattr(uhd, '__version__', 'N/A')
                   if _UHD_AVAILABLE else f'Missing — {_UHD_ERROR}')
        static_rows = [
            ('UHD Python Module Version', uhd_ver),
            ('FPGA Image Path',           _U220_FPGA),
            ('FPGA Image File',
             'Found' if os.path.isfile(_U220_FPGA) else 'Not found (using default B210 image)'),
        ]
        for label, val in static_rows:
            row = ttk.Frame(ver_lf)
            row.pack(side=tk.TOP, fill=tk.X, pady=1)
            ttk.Label(row, text=f'{label}:', width=28, anchor='w').pack(
                side=tk.LEFT)
            ttk.Label(row, text=val, anchor='w').pack(
                side=tk.LEFT, padx=(6, 0))

        detail_lf = ttk.LabelFrame(
            self._tab_info, text='Device Details (uhd_usrp_probe + Python API)',
            padding=(8, 4))
        detail_lf.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        self._info_text = tk.Text(
            detail_lf, state='disabled', font=('Courier', 9),
            wrap='none', relief='flat', bg='#fafafa')
        sb_y = ttk.Scrollbar(detail_lf, orient='vertical',
                              command=self._info_text.yview)
        sb_x = ttk.Scrollbar(detail_lf, orient='horizontal',
                              command=self._info_text.xview)
        self._info_text.configure(
            yscrollcommand=sb_y.set, xscrollcommand=sb_x.set)
        sb_y.pack(side=tk.RIGHT,  fill=tk.Y)
        sb_x.pack(side=tk.BOTTOM, fill=tk.X)
        self._info_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def _query_info(self):
        if self._info_worker and self._info_worker.is_alive():
            return
        self._info_btn.configure(state='disabled')
        self._info_status.set('Querying...')
        self._info_queue = queue.Queue(maxsize=4)
        self._info_worker = DeviceInfoWorker(
            self._info_queue, self._args_var.get())
        self._info_worker.start()
        self.root.after(300, self._poll_info)

    def _poll_info(self):
        try:
            result = self._info_queue.get_nowait()
        except queue.Empty:
            if self._info_worker and self._info_worker.is_alive():
                self.root.after(300, self._poll_info)
            else:
                self._info_btn.configure(state='normal')
            return

        self._info_btn.configure(state='normal')
        if not result['ok']:
            self._info_status.set(f"Error: {result['error']}")
            self._set_info_text(f"[Error]\n{result['error']}")
            self._info_save_btn.configure(state='disabled')
            return

        self._info_status.set('Query complete')
        self._set_info_text(result['text'])
        self._info_save_btn.configure(state='normal')

    def _set_info_text(self, text: str):
        self._info_text.configure(state='normal')
        self._info_text.delete('1.0', tk.END)
        self._info_text.insert(tk.END, text)
        self._info_text.configure(state='disabled')

    def _save_info_text(self):
        text = self._info_text.get('1.0', tk.END).rstrip('\n')
        if not text:
            messagebox.showinfo('Save', 'Nothing to save.')
            return
        import datetime
        default_name = f'u220_info_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
        path = filedialog.asksaveasfilename(
            defaultextension='.txt',
            filetypes=[('Text files', '*.txt'), ('All files', '*.*')],
            initialfile=default_name,
            title='Save Device Info',
        )
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(text)
            self._info_status.set(f'Saved: {path}')
        except OSError as e:
            messagebox.showerror('Save Failed', str(e))

    # ═══════════════════════════════════════════════════════════════════════════
    # Tab 3: GNSS
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_gnss_tab(self):
        ctrl = ttk.Frame(self._tab_gnss, padding=(6, 4))
        ctrl.pack(side=tk.TOP, fill=tk.X)

        self._gnss_start_btn = ttk.Button(
            ctrl, text='Start GNSS Check', command=self._gnss_start)
        self._gnss_start_btn.pack(side=tk.LEFT, padx=(0, 4))
        self._gnss_stop_btn = ttk.Button(
            ctrl, text='Stop', command=self._gnss_stop, state='disabled')
        self._gnss_stop_btn.pack(side=tk.LEFT, padx=(0, 20))

        self._gnss_gpsdo_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            ctrl, text='Set clock/time source = gpsdo',
            variable=self._gnss_gpsdo_var).pack(side=tk.LEFT)

        self._gnss_status_var = tk.StringVar(value='Ready')
        ttk.Label(self._tab_gnss, textvariable=self._gnss_status_var,
                  padding=(8, 2), foreground='gray').pack(
                      side=tk.TOP, anchor='w')

        sf = ttk.LabelFrame(self._tab_gnss, text='GNSS Status', padding=12)
        sf.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=4)

        self._gnss_lock_var = tk.StringVar(value='—')
        self._gnss_lock_lbl = ttk.Label(
            sf, textvariable=self._gnss_lock_var,
            font=('TkDefaultFont', 20, 'bold'))
        self._gnss_lock_lbl.grid(row=0, column=0, columnspan=2,
                                  sticky='w', pady=(0, 10))

        field_rows = [
            ('Ref Clock (ref_locked)', '_g_ref'),
            ('GPS Time (gps_time)',    '_g_gtime'),
            ('Fix Status',             '_g_fix'),
            ('Satellites / HDOP',      '_g_sats'),
            ('Latitude',               '_g_lat'),
            ('Longitude',              '_g_lon'),
            ('Altitude',               '_g_alt'),
            ('UTC Time',               '_g_utc'),
            ('Date / Speed',           '_g_date'),
        ]
        for i, (label, attr) in enumerate(field_rows, start=1):
            ttk.Label(sf, text=label + ' :').grid(
                row=i, column=0, sticky='w', pady=2)
            var = tk.StringVar(value='---')
            setattr(self, attr, var)
            ttk.Label(sf, textvariable=var).grid(
                row=i, column=1, sticky='w', padx=(10, 0), pady=2)

        ttk.Label(sf, text='Diagnostics').grid(
            row=len(field_rows) + 1, column=0, sticky='nw', pady=(14, 2))
        self._gnss_diag = tk.Text(
            sf, height=6, width=64, state='disabled',
            font=('Courier', 8), relief='flat', bg='#fafafa')
        self._gnss_diag.grid(
            row=len(field_rows) + 1, column=1, sticky='ew',
            padx=(10, 0), pady=(14, 2))

    def _gnss_start(self):
        if self._gnss_worker and self._gnss_worker.is_alive():
            return
        self._gnss_queue  = queue.Queue(maxsize=8)
        self._gnss_worker = GnssWorker(self._gnss_queue, self._args_var.get())
        self._gnss_worker.start()
        self._gnss_status_var.set(f'Connecting... ({self._args_var.get().strip()})')
        self._gnss_start_btn.configure(state='disabled')
        self._gnss_stop_btn.configure(state='normal')
        self.root.after(300, self._poll_gnss)
        self.root.after(600, self._check_gnss_error)

    def _gnss_stop(self):
        if self._gnss_worker:
            self._gnss_worker.stop()
            self._gnss_worker.join(timeout=3)
            self._gnss_worker = None
        self._gnss_start_btn.configure(state='normal')
        self._gnss_stop_btn.configure(state='disabled')
        self._gnss_status_var.set('Stopped')

    def _check_gnss_error(self):
        if self._gnss_worker:
            if self._gnss_worker.error:
                messagebox.showerror('GNSS Error', self._gnss_worker.error)
                self._gnss_stop()
                return
            if self._gnss_worker.is_alive():
                self.root.after(600, self._check_gnss_error)

    def _poll_gnss(self):
        if not self._gnss_worker:
            return
        payload = None
        try:
            while True:
                payload = self._gnss_queue.get_nowait()
        except queue.Empty:
            pass
        if payload is not None:
            self._render_gnss(payload)
        if self._gnss_worker:
            self.root.after(300, self._poll_gnss)

    def _render_gnss(self, p: dict):
        if not p.get('present', True):
            self._gnss_status_var.set('GPS sensor not detected')
            self._gnss_lock_var.set('✖  GNSS Not Detected')
            self._gnss_lock_lbl.configure(foreground='red')
            self._g_ref.set('Locked' if p.get('ref_locked') else 'Unlocked')
            for v in (self._g_gtime, self._g_fix, self._g_sats, self._g_lat,
                      self._g_lon, self._g_alt, self._g_utc, self._g_date):
                v.set('---')
            self._gnss_diag.configure(state='normal')
            self._gnss_diag.delete('1.0', tk.END)
            self._gnss_diag.insert(tk.END,
                f"Motherboard sensors : {p.get('sensor_names')}\n"
                f"Supported time src  : {p.get('time_sources')}\n\n"
                "Check:\n"
                "  1. Device Args includes name=u220v2\n"
                "  2. ANTSDR patched UHD build (/opt/antsdr-uhd) in use\n"
                "     (see comments at top of u220_check_gui.py)")
            self._gnss_diag.configure(state='disabled')
            return

        self._gnss_status_var.set('GPS sensor detected')
        locked = p.get('locked', False)
        self._gnss_lock_var.set(
            '✔  GPS LOCKED' if locked else '✖  GPS UNLOCKED')
        self._gnss_lock_lbl.configure(
            foreground='green' if locked else 'orange')
        self._g_ref.set('Locked' if p.get('ref_locked') else 'Unlocked')

        epoch = p.get('epoch')
        self._g_gtime.set(
            time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(epoch))
            if epoch is not None else '---')

        g = p.get('gga')
        if g:
            self._g_fix.set(g['fix'])
            self._g_sats.set(f"{g['sats']} / HDOP {g['hdop']}")
            self._g_lat.set(
                f"{g['lat']:.6f}°" if g['lat'] is not None else '---')
            self._g_lon.set(
                f"{g['lon']:.6f}°" if g['lon'] is not None else '---')
            self._g_alt.set(g['alt'])
            self._g_utc.set(g['utc'])
        else:
            self._g_fix.set('No fix data (GPGGA) — waiting for satellites')
            for v in (self._g_sats, self._g_lat, self._g_lon,
                      self._g_alt, self._g_utc):
                v.set('---')

        r = p.get('rmc')
        self._g_date.set(
            f"{r['date']}  {r['status']}  {r['speed_kn']} kn" if r else '---')

    # ─── close ─────────────────────────────────────────────────────────────────
    def _on_close(self):
        self._gnss_stop()
        self._save_cfg()
        self.root.destroy()


def main():
    root = tk.Tk()
    U220CheckApp(root)
    root.geometry('1160x820')
    root.mainloop()


if __name__ == '__main__':
    main()
