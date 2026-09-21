#!/usr/bin/env python3
# Threaded HTTP server: streams a PulseAudio/PipeWire monitor (system audio)
# as live MP3, spawning a fresh ffmpeg per connection. A fresh encoder per
# request is what survives the Chromecast's probe-then-play pattern.
# Args: <pulse_monitor_source> <port>
import http.server, socketserver, subprocess, sys, os, signal

MON = sys.argv[1]
PORT = int(sys.argv[2])


class Handler(http.server.BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-Type', 'audio/mpeg')
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'audio/mpeg')
        self.end_headers()
        p = subprocess.Popen(
            ['ffmpeg', '-hide_banner', '-loglevel', 'fatal', '-f', 'pulse', '-i', MON,
             '-c:a', 'libmp3lame', '-b:a', '192k', '-f', 'mp3', '-'],
            stdout=subprocess.PIPE, preexec_fn=os.setsid)
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
