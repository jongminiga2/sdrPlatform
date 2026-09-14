#!/usr/bin/env python3
"""ANTSDR U220 (UHD/USRP B210 호환) real-time spectrum analyzer (Tkinter + Matplotlib).

product/bladeRF/bladerf_spectrum_gui.py 와 동일한 UI/구조를 U220 에 맞춰 이식했다.
U220 은 libiio 가 아니라 UHD(USRP B210 호환) 로 동작하므로 `bladerf` 대신 python `uhd`
모듈(uhd.usrp.MultiUSRP)로 스트리밍한다. 사전 준비물은 product/u220/install_check_driver.py
로 설치 및 확인한다 (uhd-host, libuhd-dev, python3-uhd, U220 전용 FPGA 이미지).
"""

import threading
import queue
import tkinter as tk
from tkinter import ttk, messagebox

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

import uhd

FFT_SIZE = 4096
WATERFALL_ROWS = 120
RX_CHANNEL = 0
RECV_TIMEOUT_S = 1.0


class U220Worker(threading.Thread):
    """Owns the U220(UHD) device and streams PSD frames into a queue."""

    def __init__(self, out_queue, params):
        super().__init__(daemon=True)
        self.out_queue = out_queue
        self.params = params
        self._stop_event = threading.Event()
        self.error = None

    def stop(self):
        self._stop_event.set()

    def run(self):
        usrp = None
        streamer = None
        try:
            usrp = uhd.usrp.MultiUSRP(self.params["device_args"])

            usrp.set_rx_rate(self.params["samplerate"], RX_CHANNEL)
            usrp.set_rx_freq(uhd.types.TuneRequest(self.params["freq"]), RX_CHANNEL)
            usrp.set_rx_bandwidth(self.params["bandwidth"], RX_CHANNEL)
            if self.params["agc"]:
                usrp.set_rx_agc(True, RX_CHANNEL)
            else:
                usrp.set_rx_agc(False, RX_CHANNEL)
                usrp.set_rx_gain(self.params["gain"], RX_CHANNEL)

            fs = usrp.get_rx_rate(RX_CHANNEL)
            fc = usrp.get_rx_freq(RX_CHANNEL)

            st_args = uhd.usrp.StreamArgs("fc32", "sc16")
            st_args.channels = [RX_CHANNEL]
            streamer = usrp.get_rx_stream(st_args)

            max_samps = streamer.get_max_num_samps()
            recv_buffer = np.zeros((1, max_samps), dtype=np.complex64)
            metadata = uhd.types.RXMetadata()

            stream_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.start_cont)
            stream_cmd.stream_now = True
            streamer.issue_stream_cmd(stream_cmd)

            win = np.hanning(FFT_SIZE)
            acc = np.empty(0, dtype=np.complex64)

            while not self._stop_event.is_set():
                nsamps = streamer.recv(recv_buffer, metadata, RECV_TIMEOUT_S)

                if metadata.error_code == uhd.types.RXMetadataErrorCode.timeout:
                    continue
                if metadata.error_code != uhd.types.RXMetadataErrorCode.none:
                    raise RuntimeError(f"UHD RX error: {metadata.strerror()}")
                if nsamps == 0:
                    continue

                acc = np.concatenate([acc, recv_buffer[0, :nsamps]])

                while len(acc) >= FFT_SIZE:
                    chunk = acc[:FFT_SIZE]
                    acc = acc[FFT_SIZE:]

                    spec = np.fft.fftshift(np.fft.fft(chunk * win))
                    psd_db = 20 * np.log10(np.abs(spec) / FFT_SIZE + 1e-12)
                    freqs = np.fft.fftshift(np.fft.fftfreq(FFT_SIZE, d=1 / fs)) + fc

                    try:
                        self.out_queue.put_nowait((freqs, psd_db))
                    except queue.Full:
                        pass

            stop_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.stop_cont)
            streamer.issue_stream_cmd(stop_cmd)
        except Exception as exc:  # surface to UI thread
            self.error = str(exc)
        finally:
            try:
                if streamer is not None:
                    stop_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.stop_cont)
                    streamer.issue_stream_cmd(stop_cmd)
            except Exception:
                pass
            # MultiUSRP/rx_streamer 는 파이썬 GC 로 정리됨 (명시적 close API 없음)
            del streamer
            del usrp


class SpectrumApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ANTSDR U220 - Spectrum Analyzer")
        self.worker = None
        self.frame_queue = queue.Queue(maxsize=4)
        self.waterfall = np.full((WATERFALL_ROWS, FFT_SIZE), -140.0)

        self._build_controls()
        self._build_plots()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------------------------------------------------------------- UI
    def _build_controls(self):
        # 한 줄에 다 넣으면 창 폭보다 넓어져 뒤쪽(시작/정지 버튼)이 잘려 안 보이는
        # 문제가 있어, 창 폭에 상관없이 항상 보이도록 2줄로 나눈다.
        row1 = ttk.Frame(self.root, padding=(8, 8, 8, 0))
        row1.pack(side=tk.TOP, fill=tk.X)
        row2 = ttk.Frame(self.root, padding=(8, 4, 8, 8))
        row2.pack(side=tk.TOP, fill=tk.X)

        def add_field(parent, label, default, width=12):
            ttk.Label(parent, text=label).pack(side=tk.LEFT, padx=(0, 4))
            var = tk.StringVar(value=default)
            ent = ttk.Entry(parent, textvariable=var, width=width)
            ent.pack(side=tk.LEFT, padx=(0, 12))
            return var

        self.args_var = add_field(row1, "Device Args", "", width=16)
        self.freq_var = add_field(row1, "중심주파수(Hz)", "889000000")
        self.rate_var = add_field(row1, "샘플레이트(Hz)", "61440000")
        self.bw_var = add_field(row1, "대역폭(Hz)", "56000000")

        self.agc_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row2, text="AGC", variable=self.agc_var,
                         command=self._toggle_gain_entry).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(row2, text="Gain(dB)").pack(side=tk.LEFT, padx=(0, 4))
        self.gain_var = tk.StringVar(value="40")
        self.gain_entry = ttk.Entry(row2, textvariable=self.gain_var, width=6, state="disabled")
        self.gain_entry.pack(side=tk.LEFT, padx=(0, 12))

        self.start_btn = ttk.Button(row2, text="시작", command=self.start)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 4))
        self.stop_btn = ttk.Button(row2, text="정지", command=self.stop, state="disabled")
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
            "device_args": self.args_var.get().strip(),
            "freq": freq, "samplerate": rate, "bandwidth": bw,
            "agc": self.agc_var.get(), "gain": gain,
        }
        self.waterfall[:] = -140.0
        self.worker = U220Worker(self.frame_queue, params)
        self.worker.start()
        self.status_var.set(f"수신 중: {freq/1e6:.3f} MHz, Fs={rate/1e6:.2f} MHz")
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.root.after(100, self._poll_queue)
        self.root.after(500, self._check_worker_error)

    def stop(self):
        if self.worker is not None:
            self.worker.stop()
            self.worker.join(timeout=3)
            self.worker = None
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.status_var.set("정지됨")

    def _check_worker_error(self):
        if self.worker is not None:
            if self.worker.error:
                messagebox.showerror("U220(UHD) 오류", self.worker.error)
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
