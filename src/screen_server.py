#!/usr/bin/env python3
# Threaded HTTP server: streams a monitor + audio as live fragmented MP4
# (H.264/AAC) for a Chromecast. Per GET it runs, low-latency tuned:
#   gpu-screen-recorder (NVENC -> matroska) | ffmpeg (remux -> fMP4)
# Fragmented MP4 + a fresh pipeline per connection is what the Chromecast's
# probe-then-play pattern needs. HEAD is answered without spawning capture.
#
# Defaults are the measured lowest-stable-latency config (~2s on a stock
# Chromecast receiver): CBR + constant frame rate + 1s keyframes + 0.5s
# fragments. Bursty QP/VFR streams make the receiver hold extra buffer
# (2-5s wandering latency); more aggressive fragmentation also makes it
# WORSE, not better.
import argparse
import http.server, socketserver, subprocess, os, signal

ap = argparse.ArgumentParser(description="Screen+audio -> live fMP4 HTTP stream")
ap.add_argument("monitor")
ap.add_argument("port", type=int)
ap.add_argument("audio", nargs="?", default="default_output")
ap.add_argument("fps", nargs="?", default="30")
ap.add_argument("bitrate", nargs="?", default=None,
                help="video bitrate in kbps (CBR mode)")
ap.add_argument("--bitrate", dest="bitrate_flag", default=None)
ap.add_argument("--bm", default="cbr", choices=["cbr", "qp", "vbr"],
                help="bitrate mode (default cbr; steadiest stream = lowest latency)")
ap.add_argument("--quality", default="very_high",
                choices=["medium", "high", "very_high", "ultra"],
                help="quality preset used when --bm is qp/vbr")
ap.add_argument("--keyint", default="1", help="keyframe interval seconds")
ap.add_argument("--fm", default="cfr", choices=["cfr", "vfr", "content"],
                help="frame rate mode (default cfr)")
ap.add_argument("--frag-ms", default="500", help="MP4 fragment duration ms")
ap.add_argument("--tune", default="performance", choices=["performance", "quality"])
args = ap.parse_args()

BITRATE = args.bitrate_flag or args.bitrate or "6000"
QVAL = BITRATE if args.bm == "cbr" else args.quality
FRAG_US = int(float(args.frag_ms) * 1000)

CMD = (f'gpu-screen-recorder -w {args.monitor} -f {args.fps} -a {args.audio} '
       f'-k h264 -ac aac -keyint {args.keyint} -bm {args.bm} -q {QVAL} '
       f'-fm {args.fm} -tune {args.tune} -c matroska -o /dev/stdout 2>/dev/null '
       f'| ffmpeg -hide_banner -loglevel fatal -fflags nobuffer -flags low_delay '
       f'-i pipe: -c copy -f mp4 '
       f'-movflags frag_keyframe+empty_moov+default_base_moof '
       f'-frag_duration {FRAG_US} '
       f'-flush_packets 1 pipe: 2>/dev/null')


class Handler(http.server.BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-Type', 'video/mp4')
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'video/mp4')
        self.end_headers()
        p = subprocess.Popen(CMD, shell=True, stdout=subprocess.PIPE, preexec_fn=os.setsid)
        try:
            while True:
                d = p.stdout.read(16384)
                if not d:
                    break
                self.wfile.write(d)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            except Exception:
                pass

    def log_message(self, *a):
        pass


socketserver.ThreadingTCPServer.allow_reuse_address = True
with socketserver.ThreadingTCPServer(('0.0.0.0', args.port), Handler) as srv:
    srv.serve_forever()
