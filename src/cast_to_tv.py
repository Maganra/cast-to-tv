#!/usr/bin/env python3
"""Cast to TV — pick a monitor, audio output, and Chromecast target, then
stream screen+audio (or audio-only) to it.

Backend: gpu-screen-recorder (NVENC/VAAPI capture) + ffmpeg (fragmented MP4,
or MP3 for audio-only) -> a tiny HTTP server -> catt cast --stream-type live.

The Advanced tab exposes the encoder/stream knobs; defaults are the measured
lowest-stable-latency configuration (~2s on a stock Chromecast receiver).
"""
import os, re, shutil, socket, signal, subprocess, sys
from PyQt6 import QtCore, QtWidgets

# catt: prefer PATH, fall back to a pipx install.
CATT = shutil.which("catt") or os.path.expanduser("~/.local/bin/catt")
# Server scripts live next to this file (works from /usr/share, ~/.local, or src).
_APPDIR = os.path.dirname(os.path.abspath(__file__))
SCREEN_SERVER = os.path.join(_APPDIR, "screen_server.py")
AUDIO_SERVER = os.path.join(_APPDIR, "audio_server.py")

# Advanced settings: (QSettings key, default). Defaults = proven ~2s config.
ADV_DEFAULTS = {
    "adv/bitrate": 6000,        # kbps, used in CBR mode
    "adv/bm": "cbr",            # cbr | qp | vbr
    "adv/quality": "very_high", # preset for qp/vbr modes
    "adv/keyint": 1.0,          # keyframe interval, seconds
    "adv/fm": "cfr",            # cfr | vfr | content
    "adv/frag_ms": 500,         # MP4 fragment duration, ms
    "adv/tune": "performance",  # performance | quality
    "adv/ab": 192,              # audio bitrate kbps (audio-only mode)
    "adv/stream_type": "live",  # live | buffered
}


def _run(cmd, timeout=15):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def list_monitors():
    mons = []
    for line in _run(["gpu-screen-recorder", "--list-monitors"]).splitlines():
        if "|" in line:
            name, res = line.split("|", 1)
            mons.append((name.strip(), f"{name.strip()} ({res.strip()})"))
    return mons


def list_audio():
    devs = []
    for line in _run(["gpu-screen-recorder", "--list-audio-devices"]).splitlines():
        if "|" in line:
            gid, desc = line.split("|", 1)
            devs.append((gid.strip(), desc.strip()))
    return devs or [("default_output", "Default output")]


def default_sink_monitor():
    s = _run(["pactl", "get-default-sink"]).strip()
    return (s + ".monitor") if s else "default"


def local_ip_for(dev_ip):
    """Source IP the host uses to reach the target — correct even with a VPN."""
    m = re.search(r"src (\S+)", _run(["ip", "-4", "route", "get", dev_ip]))
    if m:
        return m.group(1)
    m = re.search(r"src (\S+)", _run(["ip", "-4", "route", "get", "1.1.1.1"]))
    return m.group(1) if m else "127.0.0.1"


def free_port(base=5581):
    for p in range(base, base + 30):
        with socket.socket() as s:
            try:
                s.bind(("0.0.0.0", p))
                return p
            except OSError:
                continue
    return base


class ScanThread(QtCore.QThread):
    done = QtCore.pyqtSignal(list)

    def run(self):
        devs = []
        for line in _run([CATT, "scan"], timeout=40).splitlines():
            parts = [p.strip() for p in line.split(" - ")]
            if len(parts) >= 2 and parts[0].count(".") == 3:
                name = parts[1]
                model = parts[2] if len(parts) > 2 else ""
                devs.append((name, parts[0], model))
        self.done.emit(devs)


class CastApp(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Cast to TV")
        self.setMinimumWidth(470)
        self.settings = QtCore.QSettings("cast-to-tv", "cast-to-tv")
        self.server = None
        self.current_url = None
        self.paused = False
        self._build_ui()
        self._check_deps()
        self._load_lists()
        self._load_advanced()
        self.rescan()

    # ---------- UI ----------

    def _build_ui(self):
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._build_cast_tab(), "Cast")
        self.tabs.addTab(self._build_advanced_tab(), "Advanced")

        self.start_btn = QtWidgets.QPushButton("Start")
        self.start_btn.clicked.connect(self.start)
        self.pause_btn = QtWidgets.QPushButton("Pause")
        self.pause_btn.clicked.connect(self.pause_toggle)
        self.pause_btn.setEnabled(False)
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop)
        self.stop_btn.setEnabled(False)
        brow = QtWidgets.QHBoxLayout()
        brow.addWidget(self.start_btn)
        brow.addWidget(self.pause_btn)
        brow.addWidget(self.stop_btn)

        self.status = QtWidgets.QLabel("Idle.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: palette(mid);")

        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(self.tabs)
        root.addLayout(brow)
        root.addWidget(self.status)

    def _build_cast_tab(self):
        w = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(w)

        self.target = QtWidgets.QComboBox()
        rescan_btn = QtWidgets.QPushButton("Rescan")
        rescan_btn.clicked.connect(self.rescan)
        trow = QtWidgets.QHBoxLayout()
        trow.addWidget(self.target, 1)
        trow.addWidget(rescan_btn)
        form.addRow("Target:", self._wrap(trow))

        self.mode_screen = QtWidgets.QRadioButton("Screen + Audio")
        self.mode_audio = QtWidgets.QRadioButton("Audio only")
        self.mode_screen.setChecked(True)
        self.mode_screen.toggled.connect(self._mode_changed)
        mrow = QtWidgets.QHBoxLayout()
        mrow.addWidget(self.mode_screen)
        mrow.addWidget(self.mode_audio)
        mrow.addStretch(1)
        form.addRow("Mode:", self._wrap(mrow))

        self.monitor = QtWidgets.QComboBox()
        form.addRow("Monitor:", self.monitor)
        self.audio = QtWidgets.QComboBox()
        form.addRow("Audio:", self.audio)
        self.fps = QtWidgets.QComboBox()
        self.fps.addItems(["24", "30", "60"])
        self.fps.setCurrentText("30")
        form.addRow("FPS:", self.fps)
        return w

    def _build_advanced_tab(self):
        w = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(w)

        note = QtWidgets.QLabel(
            "Defaults are the lowest-stable-latency config (~2s on a stock "
            "Chromecast). Steady streams (CBR + CFR) buffer least; overly "
            "aggressive values can INCREASE latency.")
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(mid);")
        form.addRow(note)

        self.adv_bm = QtWidgets.QComboBox()
        self.adv_bm.addItems(["cbr", "qp", "vbr"])
        self.adv_bm.currentTextChanged.connect(self._bm_changed)
        form.addRow("Bitrate mode:", self.adv_bm)

        self.adv_bitrate = QtWidgets.QSpinBox()
        self.adv_bitrate.setRange(1000, 50000)
        self.adv_bitrate.setSingleStep(500)
        self.adv_bitrate.setSuffix(" kbps")
        form.addRow("Video bitrate (CBR):", self.adv_bitrate)

        self.adv_quality = QtWidgets.QComboBox()
        self.adv_quality.addItems(["medium", "high", "very_high", "ultra"])
        form.addRow("Quality preset (QP/VBR):", self.adv_quality)

        self.adv_keyint = QtWidgets.QDoubleSpinBox()
        self.adv_keyint.setRange(0.25, 10.0)
        self.adv_keyint.setSingleStep(0.25)
        self.adv_keyint.setSuffix(" s")
        form.addRow("Keyframe interval:", self.adv_keyint)

        self.adv_fm = QtWidgets.QComboBox()
        self.adv_fm.addItems(["cfr", "vfr", "content"])
        form.addRow("Frame rate mode:", self.adv_fm)

        self.adv_frag = QtWidgets.QSpinBox()
        self.adv_frag.setRange(100, 5000)
        self.adv_frag.setSingleStep(50)
        self.adv_frag.setSuffix(" ms")
        form.addRow("MP4 fragment duration:", self.adv_frag)

        self.adv_tune = QtWidgets.QComboBox()
        self.adv_tune.addItems(["performance", "quality"])
        form.addRow("Encoder tune:", self.adv_tune)

        self.adv_ab = QtWidgets.QSpinBox()
        self.adv_ab.setRange(96, 320)
        self.adv_ab.setSingleStep(32)
        self.adv_ab.setSuffix(" kbps")
        form.addRow("Audio bitrate (audio-only):", self.adv_ab)

        self.adv_stream = QtWidgets.QComboBox()
        self.adv_stream.addItems(["live", "buffered"])
        form.addRow("Cast stream type:", self.adv_stream)

        reset = QtWidgets.QPushButton("Reset to defaults")
        reset.clicked.connect(self._reset_advanced)
        form.addRow(reset)
        return w

    def _wrap(self, layout):
        w = QtWidgets.QWidget()
        w.setLayout(layout)
        return w

    def _mode_changed(self):
        screen = self.mode_screen.isChecked()
        self.monitor.setEnabled(screen)
        self.fps.setEnabled(screen)

    def _bm_changed(self, bm=None):
        bm = bm or self.adv_bm.currentText()
        self.adv_bitrate.setEnabled(bm == "cbr")
        self.adv_quality.setEnabled(bm != "cbr")

    def _check_deps(self):
        missing = [t for t in ("gpu-screen-recorder", "ffmpeg", "pactl")
                   if not shutil.which(t)]
        if not (CATT and os.path.exists(CATT)):
            missing.append("catt")
        if missing:
            self.status.setText("Missing: " + ", ".join(missing) +
                                " — see the README to install dependencies.")

    # ---------- settings ----------

    def _load_lists(self):
        for name, label in list_monitors():
            self.monitor.addItem(label, name)
        for gid, desc in list_audio():
            self.audio.addItem(desc, gid)
        lm = self.settings.value("monitor")
        if lm is not None and (i := self.monitor.findData(lm)) >= 0:
            self.monitor.setCurrentIndex(i)
        la = self.settings.value("audio")
        if la is not None and (i := self.audio.findData(la)) >= 0:
            self.audio.setCurrentIndex(i)
        if lf := self.settings.value("fps"):
            self.fps.setCurrentText(str(lf))
        if self.settings.value("mode") == "audio":
            self.mode_audio.setChecked(True)
        self._mode_changed()

    def _adv(self, key):
        return self.settings.value(key, ADV_DEFAULTS[key])

    def _load_advanced(self):
        self.adv_bitrate.setValue(int(self._adv("adv/bitrate")))
        self.adv_bm.setCurrentText(str(self._adv("adv/bm")))
        self.adv_quality.setCurrentText(str(self._adv("adv/quality")))
        self.adv_keyint.setValue(float(self._adv("adv/keyint")))
        self.adv_fm.setCurrentText(str(self._adv("adv/fm")))
        self.adv_frag.setValue(int(self._adv("adv/frag_ms")))
        self.adv_tune.setCurrentText(str(self._adv("adv/tune")))
        self.adv_ab.setValue(int(self._adv("adv/ab")))
        self.adv_stream.setCurrentText(str(self._adv("adv/stream_type")))
        self._bm_changed()

    def _reset_advanced(self):
        for k in ADV_DEFAULTS:
            self.settings.remove(k)
        self._load_advanced()
        self.status.setText("Advanced settings reset to defaults.")

    def _save(self):
        if d := self.target.currentData():
            self.settings.setValue("target", list(d))
        self.settings.setValue("monitor", self.monitor.currentData())
        self.settings.setValue("audio", self.audio.currentData())
        self.settings.setValue("fps", self.fps.currentText())
        self.settings.setValue("mode", "screen" if self.mode_screen.isChecked() else "audio")
        self.settings.setValue("adv/bitrate", self.adv_bitrate.value())
        self.settings.setValue("adv/bm", self.adv_bm.currentText())
        self.settings.setValue("adv/quality", self.adv_quality.currentText())
        self.settings.setValue("adv/keyint", self.adv_keyint.value())
        self.settings.setValue("adv/fm", self.adv_fm.currentText())
        self.settings.setValue("adv/frag_ms", self.adv_frag.value())
        self.settings.setValue("adv/tune", self.adv_tune.currentText())
        self.settings.setValue("adv/ab", self.adv_ab.value())
        self.settings.setValue("adv/stream_type", self.adv_stream.currentText())

    # ---------- device scan ----------

    def rescan(self):
        self.status.setText("Scanning for cast devices…")
        self.target.clear()
        self._scan = ScanThread()
        self._scan.done.connect(self._scan_done)
        self._scan.start()

    def _scan_done(self, devs):
        for name, ip, model in devs:
            self.target.addItem(f"{name}  — {model}" if model else name, (name, ip))
        if devs:
            last = self.settings.value("target")
            if last is not None:
                key = tuple(last) if isinstance(last, list) else last
                if (i := self.target.findData(key)) >= 0:
                    self.target.setCurrentIndex(i)
            self.status.setText(f"Found {len(devs)} device(s). Ready.")
        else:
            self.status.setText("No cast devices found. Try Rescan.")

    # ---------- casting ----------

    def start(self):
        data = self.target.currentData()
        if not data:
            self.status.setText("Pick a target device first.")
            return
        name, ip = data
        port = free_port()
        host_ip = local_ip_for(ip)

        if self.mode_screen.isChecked():
            cmd = ["python3", SCREEN_SERVER,
                   self.monitor.currentData(), str(port),
                   self.audio.currentData(), self.fps.currentText(),
                   "--bitrate", str(self.adv_bitrate.value()),
                   "--bm", self.adv_bm.currentText(),
                   "--quality", self.adv_quality.currentText(),
                   "--keyint", str(self.adv_keyint.value()),
                   "--fm", self.adv_fm.currentText(),
                   "--frag-ms", str(self.adv_frag.value()),
                   "--tune", self.adv_tune.currentText()]
            url = f"http://{host_ip}:{port}/screen.mp4"
            what = f"{self.monitor.currentData()} + audio"
        else:
            gid = self.audio.currentData()
            src = default_sink_monitor() if gid == "default_output" else gid
            cmd = ["python3", AUDIO_SERVER, src, str(port),
                   "--ab", str(self.adv_ab.value())]
            url = f"http://{host_ip}:{port}/audio.mp3"
            what = "audio"

        try:
            self.server = subprocess.Popen(cmd, start_new_session=True)
        except Exception as e:
            self.status.setText(f"Failed to start stream server: {e}")
            return
        subprocess.run([CATT, "-d", name, "cast",
                        "--stream-type", self.adv_stream.currentText(), url],
                       capture_output=True, text=True)
        self.current_url = url
        self.paused = False
        self._save()
        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.pause_btn.setText("Pause")
        self.stop_btn.setEnabled(True)
        self._set_inputs_enabled(False)
        self.status.setText(f"Casting {what} to {name}. (give it a few seconds)")

    def pause_toggle(self):
        d = self.target.currentData()
        if not d:
            return
        name = d[0]
        if not self.paused:
            # Pause ON the receiver -> TV freezes instantly.
            subprocess.run([CATT, "-d", name, "pause"], capture_output=True, text=True)
            self.paused = True
            self.pause_btn.setText("Resume")
            self.status.setText("Paused on the TV. Resume rejoins the live desktop.")
        else:
            # A mirror has no position to keep: resuming the frozen buffer would
            # permanently add the pause duration to the latency, so re-cast to
            # rejoin the live edge instead.
            subprocess.run([CATT, "-d", name, "stop"], capture_output=True, text=True)
            QtCore.QThread.msleep(800)
            subprocess.run([CATT, "-d", name, "cast",
                            "--stream-type", self.adv_stream.currentText(),
                            self.current_url],
                           capture_output=True, text=True)
            self.paused = False
            self.pause_btn.setText("Pause")
            self.status.setText("Resuming at the live desktop… (a few seconds)")

    def stop(self):
        d = self.target.currentData()
        if d:
            subprocess.run([CATT, "-d", d[0], "stop"], capture_output=True, text=True)
        QtCore.QThread.msleep(600)
        if self.server:
            try:
                os.killpg(os.getpgid(self.server.pid), signal.SIGTERM)
            except Exception:
                pass
            self.server = None
        for pat in ("screen_server.py", "audio_server.py", "gpu-screen-recorder -w"):
            subprocess.run(["pkill", "-f", pat], capture_output=True)
        self.paused = False
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("Pause")
        self.stop_btn.setEnabled(False)
        self._set_inputs_enabled(True)
        self.status.setText("Stopped.")

    def _set_inputs_enabled(self, on):
        for w in (self.target, self.mode_screen, self.mode_audio, self.audio):
            w.setEnabled(on)
        self.monitor.setEnabled(on and self.mode_screen.isChecked())
        self.fps.setEnabled(on and self.mode_screen.isChecked())
        self.tabs.widget(1).setEnabled(on)

    def closeEvent(self, e):
        if self.stop_btn.isEnabled():
            self.stop()
        e.accept()


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Cast to TV")
    w = CastApp()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
