#!/usr/bin/env python3
"""bladeRF 2.0 micro real-time spectrum analyzer (Tkinter + Matplotlib)."""

import threading
import queue
import tkinter as tk
from tkinter import ttk, messagebox

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

import bladerf
from bladerf import _bladerf

FFT_SIZE = 4096
WATERFALL_ROWS = 120
NUM_BUFFERS = 16
BUFFER_SIZE = 1024 * 16
NUM_TRANSFERS = 8
STREAM_TIMEOUT_MS = 3500


class BladeRFWorker(threading.Thread):
    """Owns the bladeRF device and streams PSD frames into a queue."""

    def __init__(self, out_queue, params):
        super().__init__(daemon=True)
        self.out_queue = out_queue
        self.params = params
        self._stop_event = threading.Event()
        self.error = None

    def stop(self):
        self._stop_event.set()

    def run(self):
        dev = None
        ch = None
        try:
            dev = bladerf.BladeRF()
            ch = dev.Channel(bladerf.CHANNEL_RX(0))

            ch.frequency = int(self.params["freq"])
            ch.sample_rate = int(self.params["samplerate"])
            ch.bandwidth = int(self.params["bandwidth"])
            if self.params["agc"]:
                ch.gain_mode = _bladerf.GainMode.SlowAttack_AGC
            else:
                ch.gain_mode = _bladerf.GainMode.Manual
                ch.gain = int(self.params["gain"])

            dev.sync_config(
                layout=_bladerf.ChannelLayout.RX_X1,
                fmt=_bladerf.Format.SC16_Q11,
                num_buffers=NUM_BUFFERS,
                buffer_size=BUFFER_SIZE,
                num_transfers=NUM_TRANSFERS,
                stream_timeout=STREAM_TIMEOUT_MS,
            )
            ch.enable = True

            fs = ch.sample_rate
            fc = ch.frequency
            win = np.hanning(FFT_SIZE)
            buf = bytearray(FFT_SIZE * 4)

            while not self._stop_event.is_set():
                dev.sync_rx(buf, FFT_SIZE)
                samples = np.frombuffer(buf, dtype=np.int16).astype(np.float32)
                iq = samples[0::2] + 1j * samples[1::2]
                spec = np.fft.fftshift(np.fft.fft(iq * win))
                psd_db = 20 * np.log10(np.abs(spec) / FFT_SIZE + 1e-12)
                freqs = np.fft.fftshift(np.fft.fftfreq(FFT_SIZE, d=1 / fs)) + fc

                try:
                    self.out_queue.put_nowait((freqs, psd_db))
                except queue.Full:
                    pass

            ch.enable = False
        except Exception as exc:  # surface to UI thread
            self.error = str(exc)
        finally:
            try:
                if ch is not None:
                    ch.enable = False
            except Exception:
                pass
            if dev is not None:
                dev.close()


class SpectrumApp:
    def __init__(self, root):
        self.root = root
        self.root.title("bladeRF 2.0 micro - Spectrum Analyzer")
        self.worker = None
        self.frame_queue = queue.Queue(maxsize=4)
        self.waterfall = np.full((WATERFALL_ROWS, FFT_SIZE), -140.0)

        self._build_controls()
        self._build_plots()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------------------------------------------------------------- UI
    def _build_controls(self):
        frm = ttk.Frame(self.root, padding=8)
        frm.pack(side=tk.TOP, fill=tk.X)

        def add_field(label, default):
            ttk.Label(frm, text=label).pack(side=tk.LEFT, padx=(0, 4))
            var = tk.StringVar(value=default)
            ent = ttk.Entry(frm, textvariable=var, width=12)
            ent.pack(side=tk.LEFT, padx=(0, 12))
            return var

        self.freq_var = add_field("중심주파수(Hz)", "889000000")
        self.rate_var = add_field("샘플레이트(Hz)", "61440000")
        self.bw_var = add_field("대역폭(Hz)", "56000000")

        self.agc_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(frm, text="AGC", variable=self.agc_var,
                         command=self._toggle_gain_entry).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(frm, text="Gain(dB)").pack(side=tk.LEFT, padx=(0, 4))
        self.gain_var = tk.StringVar(value="30")
        self.gain_entry = ttk.Entry(frm, textvariable=self.gain_var, width=6, state="disabled")
        self.gain_entry.pack(side=tk.LEFT, padx=(0, 12))

        self.start_btn = ttk.Button(frm, text="시작", command=self.start)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 4))
        self.stop_btn = ttk.Button(frm, text="정지", command=self.stop, state="disabled")
        self.stop_btn.pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="대기 중")
        ttk.Label(self.root, textvariable=self.status_var, padding=(8, 0)).pack(side=tk.TOP, anchor="w")

    def _toggle_gain_entry(self):
        self.gain_entry.configure(state="disabled" if self.agc_var.get() else "normal")

    def _build_plots(self):
        self.fig = Figure(figsize=(9, 6), dpi=100)
        self.ax_spec = self.fig.add_subplot(2, 1, 1)
        self.ax_wf = self.fig.add_subplot(2, 1, 2)

        (self.line,) = self.ax_spec.plot([], [], lw=1)
        self.ax_spec.set_ylabel("Power (dB)")
        self.ax_spec.set_ylim(-140, 0)
        self.ax_spec.grid(True, alpha=0.3)

        self.wf_img = self.ax_wf.imshow(
            self.waterfall, aspect="auto", origin="upper",
            cmap="viridis", vmin=-140, vmax=-20,
        )
        self.ax_wf.set_ylabel("시간 (과거 ->)")
        self.ax_wf.set_xlabel("Frequency (MHz)")

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.root)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

    # ------------------------------------------------------------- logic
    def start(self):
        try:
            freq = float(self.freq_var.get())
            rate = float(self.rate_var.get())
            bw = float(self.bw_var.get())
            gain = float(self.gain_var.get())
        except ValueError:
            messagebox.showerror("입력 오류", "숫자 값을 확인해주세요.")
            return

        params = {
            "freq": freq, "samplerate": rate, "bandwidth": bw,
            "agc": self.agc_var.get(), "gain": gain,
        }
        self.waterfall[:] = -140.0
        self.worker = BladeRFWorker(self.frame_queue, params)
        self.worker.start()
        self.status_var.set(f"수신 중: {freq/1e6:.3f} MHz, Fs={rate/1e6:.2f} MHz")
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.root.after(100, self._poll_queue)
        self.root.after(500, self._check_worker_error)

    def stop(self):
        if self.worker is not None:
            self.worker.stop()
            self.worker.join(timeout=2)
            self.worker = None
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.status_var.set("정지됨")

    def _check_worker_error(self):
        if self.worker is not None:
            if self.worker.error:
                messagebox.showerror("bladeRF 오류", self.worker.error)
                self.stop()
                return
            if self.worker.is_alive():
                self.root.after(500, self._check_worker_error)

    def _poll_queue(self):
        if self.worker is None:
            return
        drained = False
        try:
            while True:
                freqs, psd_db = self.frame_queue.get_nowait()
                drained = True
        except queue.Empty:
            pass

        if drained:
            vmin = np.percentile(psd_db, 2) - 5
            vmax = psd_db.max() + 5

            self.line.set_data(freqs / 1e6, psd_db)
            self.ax_spec.set_xlim(freqs[0] / 1e6, freqs[-1] / 1e6)
            self.ax_spec.set_ylim(vmin, vmax)
            self.ax_spec.set_title(f"Peak: {psd_db.max():.1f} dB @ {freqs[np.argmax(psd_db)]/1e6:.3f} MHz")

            self.waterfall = np.roll(self.waterfall, -1, axis=0)
            self.waterfall[-1, :] = psd_db
            self.wf_img.set_data(self.waterfall)
            self.wf_img.set_extent([freqs[0] / 1e6, freqs[-1] / 1e6, WATERFALL_ROWS, 0])
            self.wf_img.set_clim(vmin, vmax)
            self.canvas.draw_idle()

        if self.worker is not None:
            self.root.after(100, self._poll_queue)

    def on_close(self):
        self.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = SpectrumApp(root)
    root.geometry("950x750")
    root.mainloop()


if __name__ == "__main__":
    main()
