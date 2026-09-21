# Cast to TV

Cast a monitor (screen + audio) or just system audio from a Linux desktop to a
Chromecast / Google TV / Chromecast-built-in TV. Qt GUI plus CLI commands.

Built for Wayland + NVIDIA (uses `gpu-screen-recorder` for capture), works on
X11 too. Latency is ~2s (Chromecast buffering), so it's for **passive viewing**,
not real-time/interactive use.

## How it works

`gpu-screen-recorder` captures the screen (hardware-encoded H.264) plus audio →
`ffmpeg` remuxes to live fragmented MP4 (or MP3 for audio-only) → a tiny HTTP
server serves it → [`catt`](https://github.com/skorokithakis/catt) tells the
Chromecast to play it as a **live** stream.

## Dependencies

- `python` (3.10+), `python-pyqt6`
- `ffmpeg`, `gpu-screen-recorder`, `catt`
- `libpulse` (`pactl`), `iproute2` (`ip`), `procps-ng` (`pkill`)

On Arch/CachyOS: `python-pyqt6`, `ffmpeg` are in the repos;
`gpu-screen-recorder` and `catt` are in the AUR
(`paru -S gpu-screen-recorder catt`), or install `catt` with `pipx install catt`.

## Install

### Arch / CachyOS (recommended)

```bash
paru -S gpu-screen-recorder catt      # AUR deps
makepkg -si                           # builds & installs this package
```

### Any distro (per-user, ~/.local)

```bash
./install.sh
```

## Usage

- Launch **Cast to TV** from your app menu, or run `cast-to-tv`.
- Pick a **target device**, **mode** (Screen+Audio / Audio only), **monitor**,
  and **audio output**, then **Start**. It remembers your last choices.
- The **Advanced tab** exposes the encoder/stream knobs: bitrate & bitrate
  mode (CBR/QP/VBR), quality preset, keyframe interval, frame-rate mode,
  MP4 fragment duration, encoder tune, audio bitrate, and cast stream type
  (live/buffered). Defaults are the lowest-stable-latency config (~2s);
  "Reset to defaults" restores them. Note: steadier streams buffer less —
  overly aggressive values can *increase* latency.

### CLI

```bash
cast-screen                 # first monitor + audio to first cast device
CAST_DEVICE="My TV" CAST_MONITOR=DP-2 CAST_FPS=30 CAST_BITRATE=6000 cast-screen
cast-audio                  # system audio to first cast device
```

## Firewall

Screen mirroring needs the Chromecast to connect back to your PC. If you run a
firewall, allow it:

```bash
sudo ufw allow from <chromecast-ip>   # the TV
sudo ufw allow 5353/udp               # mDNS discovery
```

## Notes / limits

- ~2s latency is the Chromecast default receiver's buffer floor.
- Screen capture on Wayland uses `gpu-screen-recorder` (portal/KMS); plain
  ffmpeg `x11grab` misses Wayland windows.
- HDR monitors are auto tone-mapped to SDR by `gpu-screen-recorder`.
