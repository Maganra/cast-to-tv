#!/usr/bin/env python3
# Threaded HTTP server: streams a monitor + audio as live fragmented MP4
# (H.264/AAC) for a Chromecast. Per GET it runs, low-latency tuned:
#   gpu-screen-recorder (NVENC -> matroska) | ffmpeg (remux -> fMP4)
# Fragmented MP4 + a fresh pipeline per connection is what the Chromecast's
# probe-then-play pattern needs. HEAD is answered without spawning capture.
# Args: <monitor> <port> [audio_input=default_output] [fps=30]
import http.server, socketserver, subprocess, sys, os, signal

MON = sys.argv[1]
PORT = int(sys.argv[2])
AUD = sys.argv[3] if len(sys.argv) > 3 else "default_output"
FPS = sys.argv[4] if len(sys.argv) > 4 else "30"

CMD = (f'gpu-screen-recorder -w {MON} -f {FPS} -a {AUD} -k h264 -ac aac '
       f'-keyint 1 -c matroska -o /dev/stdout 2>/dev/null '
       f'| ffmpeg -hide_banner -loglevel fatal -fflags nobuffer -flags low_delay '
       f'-i pipe: -c copy -f mp4 '
       f'-movflags frag_keyframe+empty_moov+default_base_moof -frag_duration 500000 '
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
with socketserver.ThreadingTCPServer(('0.0.0.0', PORT), Handler) as srv:
    srv.serve_forever()
