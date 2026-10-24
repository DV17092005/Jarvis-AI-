"""Local web interface and command API for Jarvis."""

import argparse
import json
import logging
import mimetypes
import os
import re
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import jarvis_brain


ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("jarvis")
STATE_LOCK = threading.Lock()
COMMAND_LOCK = threading.Lock()
STATE = {
    "state": "idle",
    "mode": "local" if not jarvis_brain.ready() else "hybrid",
    "note": "Ready",
    "last_you": "",
    "model": "Groq cloud + local actions" if jarvis_brain.ready() else "Local actions",
    "t_rec": 0.0,
    "t_think": 0.0,
    "last_tool": "Ready",
    "tools": 0,
    "facts": 0,
    "mail_age": None,
    "mail_status": "Not connected",
    "chat": [],
    "cards": [],
    "stocks": [],
    "sys": {},
    "mic": {"n": 0, "a": []},
}


def _add_message(kind, text):
    with STATE_LOCK:
        messages = STATE["chat"]
        messages.append({
            "i": messages[-1]["i"] + 1 if messages else 1,
            "k": kind,
            "x": text,
            "t": datetime.now().strftime("%H:%M:%S"),
        })
        del messages[:-80]


def _snapshot():
    result = {}
    with STATE_LOCK:
        result.update(STATE)
        result["chat"] = list(STATE["chat"])
        result["cards"] = list(STATE["cards"])
        result["stocks"] = list(STATE["stocks"])
        result["sys"] = dict(STATE["sys"])
        result["mic"] = {"n": STATE["mic"]["n"], "a": list(STATE["mic"]["a"])}
    cloud_ready = jarvis_brain.ready()
    result["mode"] = "hybrid" if cloud_ready else "local"
    result["model"] = "Groq cloud + local actions" if cloud_ready else "Local actions"
    try:
        import psutil

        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(str(Path.home().anchor or ROOT))
        boot_time = psutil.boot_time()
        result["sys"] = {
            "cpu": psutil.cpu_percent(interval=None),
            "ram": memory.percent,
            "disk": disk.percent,
            "free": round(disk.free / (1024 ** 3), 1),
            "up": max(0, int(time.time() - boot_time)),
        }
        battery = psutil.sensors_battery()
        if battery:
            result["sys"]["bat"] = round(battery.percent)
            result["sys"]["plug"] = battery.power_plugged
    except ImportError:
        pass
    return result


class JarvisHandler(BaseHTTPRequestHandler):
    server_version = "JarvisLocal/1.0"

    def log_message(self, fmt, *args):
        LOG.info("%s - %s", self.address_string(), fmt % args)

    def _json(self, status, value):
        payload = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _is_local_dashboard_origin(self, required=False):
        origin = self.headers.get("Origin")
        if origin is None:
            return not required
        return origin in {
            f"http://127.0.0.1:{self.server.server_port}",
            f"http://localhost:{self.server.server_port}",
        }

    def _read_json_body(self, maximum_length):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json(400, {"error": "Invalid request length"})
            return None
        if length < 1 or length > maximum_length:
            self._json(413, {"error": f"Request must be between 1 and {maximum_length} bytes"})
            return None
        try:
            body = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"error": "Request must contain valid JSON"})
            return None
        if not isinstance(body, dict):
            self._json(400, {"error": "Request must contain a JSON object"})
            return None
        return body

    def _ai_settings(self):
        status = jarvis_brain.api_key_status()
        return {
            **status,
            "provider": "Groq",
            "environment_override": bool(os.environ.get("GROQ_API_KEY", "").strip()),
            "connected": jarvis_brain.ready(),
            "model": jarvis_brain._preferred_model if jarvis_brain.ready() else None,
            "connection_error": jarvis_brain.connection_error(),
        }

    def _update_ai_state(self):
        cloud_ready = jarvis_brain.ready()
        with STATE_LOCK:
            STATE["mode"] = "hybrid" if cloud_ready else "local"
            STATE["model"] = "Groq cloud + local actions" if cloud_ready else "Local actions"

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/state":
            self._json(200, _snapshot())
            return
        if path == "/api/settings/ai":
            self._json(200, self._ai_settings())
            return
        if path in ("/", "/jarvis_workplace.html"):
            self._serve_dashboard()
            return
        self._json(404, {"error": "Not found"})

    def _serve_dashboard(self):
        dashboard = ROOT / "jarvis_workplace.html"
        if not dashboard.is_file():
            self._json(404, {"error": "Jarvis dashboard is missing"})
            return
        payload = dashboard.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(str(dashboard))[0] or "text/html")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/transcribe":
            self._transcribe_audio()
            return
        if path == "/api/settings/ai/test":
            if not self._is_local_dashboard_origin(required=True):
                self._json(403, {"error": "Connection tests are only allowed from the local Jarvis dashboard"})
                return
            try:
                with COMMAND_LOCK:
                    result = jarvis_brain.test_connection()
            except jarvis_brain.GroqConnectionError as error:
                status_code = error.status_code if error.status_code in (401, 403, 429) else 502
                self._json(status_code, {"connected": False, "error": str(error)})
                return
            self._update_ai_state()
            self._json(200, result)
            return
        if path == "/api/settings/ai":
            self._save_ai_settings()
            return
        if path != "/api/command":
            self._json(404, {"error": "Not found"})
            return
        if not self._is_local_dashboard_origin():
            self._json(403, {"error": "Commands are accepted only from the local Jarvis dashboard"})
            return
        body = self._read_json_body(8192)
        if body is None:
            return
        query = body.get("query")
        if not isinstance(query, str) or not query.strip() or len(query) > 2000:
            self._json(400, {"error": "Enter a command between 1 and 2000 characters"})
            return
        speech_latency = body.get("speech_latency", 0) if isinstance(body, dict) else 0
        if (
            isinstance(speech_latency, bool)
            or not isinstance(speech_latency, (int, float))
            or not 0 <= speech_latency <= 60
        ):
            self._json(400, {"error": "Invalid speech latency"})
            return

        query = query.strip()
        _add_message("you", query)
        with STATE_LOCK:
            STATE["state"] = "thinking"
            STATE["last_you"] = query
            STATE["note"] = "Processing your request"

        started = time.perf_counter()
        try:
            with COMMAND_LOCK:
                reply = jarvis_brain.think(query)
        except Exception:
            LOG.exception("Command processing failed")
            _add_message("sys", "Command failed; check the Jarvis server terminal for details.")
            with STATE_LOCK:
                STATE["state"] = "idle"
                STATE["note"] = "The command could not be processed"
            self._json(500, {"error": "Jarvis could not process that command. Check the server terminal for details."})
            return

        elapsed = round(time.perf_counter() - started, 2)
        _add_message("jarvis", reply)
        with STATE_LOCK:
            STATE["state"] = "idle"
            STATE["note"] = "Ready"
            STATE["t_rec"] = round(float(speech_latency), 2)
            STATE["t_think"] = elapsed
            STATE["tools"] += 1
            STATE["last_tool"] = "Local assistant"
            if any(word in query.lower() for word in ("email", "inbox", "mail")):
                STATE["cards"] = [{
                    "i": STATE["chat"][-1]["i"],
                    "title": "INBOX",
                    "t": datetime.now().strftime("%H:%M"),
                    "body": reply,
                }]
        self._json(200, {"reply": reply, "elapsed": elapsed})

    def _transcribe_audio(self):
        if not self._is_local_dashboard_origin(required=True):
            self._json(403, {"error": "Voice transcription is only allowed from the local Jarvis dashboard"})
            return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        supported_types = {
            "audio/webm",
            "audio/ogg",
            "audio/mp4",
            "audio/mpeg",
            "audio/wav",
            "audio/x-wav",
        }
        if content_type not in supported_types:
            self._json(415, {"error": "This browser's recording format is not supported. Try Chrome or Edge."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json(400, {"error": "Invalid audio length"})
            return
        maximum_audio_size = 10 * 1024 * 1024
        if length < 1 or length > maximum_audio_size:
            self._json(413, {"error": "Recording must be between 1 byte and 10 MB"})
            return
        language = self.headers.get("X-Speech-Language", "en").split("-", 1)[0].lower()
        if not re.fullmatch(r"[a-z]{2,3}", language):
            self._json(400, {"error": "Invalid speech language"})
            return

        audio_data = self.rfile.read(length)
        if len(audio_data) != length:
            self._json(400, {"error": "Incomplete audio upload"})
            return

        extension = {
            "audio/webm": "webm",
            "audio/ogg": "ogg",
            "audio/mp4": "m4a",
            "audio/mpeg": "mp3",
            "audio/wav": "wav",
            "audio/x-wav": "wav",
        }[content_type]
        with STATE_LOCK:
            STATE["state"] = "recognizing"
            STATE["note"] = "Transcribing audio with Groq"
        try:
            with COMMAND_LOCK:
                transcript = jarvis_brain.transcribe_audio(
                    audio_data,
                    f"jarvis-microphone.{extension}",
                    content_type,
                    language,
                )
        except jarvis_brain.GroqConnectionError as error:
            with STATE_LOCK:
                STATE["state"] = "idle"
                STATE["note"] = "Voice transcription failed"
            status_code = error.status_code if error.status_code in (401, 403, 429, 503) else 502
            self._json(status_code, {"error": str(error)})
            return
        except Exception:
            LOG.exception("Voice transcription failed")
            with STATE_LOCK:
                STATE["state"] = "idle"
                STATE["note"] = "Voice transcription failed"
            self._json(500, {"error": "Voice transcription failed. Check the Jarvis server terminal."})
            return

        with STATE_LOCK:
            STATE["state"] = "idle"
            STATE["note"] = "Ready"
        self._json(200, {"text": transcript})

    def do_DELETE(self):
        if urlparse(self.path).path != "/api/settings/ai":
            self._json(404, {"error": "Not found"})
            return
        if not self._is_local_dashboard_origin(required=True):
            self._json(403, {"error": "Key settings can only be changed from the local Jarvis dashboard"})
            return
        try:
            with COMMAND_LOCK:
                jarvis_brain.delete_api_key()
        except OSError:
            LOG.exception("Could not remove the local Groq API key")
            self._json(500, {"error": "Could not remove the saved key. Check the Jarvis server terminal."})
            return
        self._update_ai_state()
        self._json(200, self._ai_settings())

    def _save_ai_settings(self):
        if not self._is_local_dashboard_origin(required=True):
            self._json(403, {"error": "Key settings can only be changed from the local Jarvis dashboard"})
            return
        body = self._read_json_body(8192)
        if body is None:
            return
        api_key = body.get("api_key")
        if (
            not isinstance(api_key, str)
            or not api_key.strip()
            or len(api_key) > 4096
            or any(ord(character) < 32 for character in api_key.strip())
        ):
            self._json(400, {"error": "Enter a valid Groq API key"})
            return
        try:
            with COMMAND_LOCK:
                jarvis_brain.save_api_key(api_key.strip())
        except RuntimeError:
            self._json(
                409,
                {"error": "GROQ_API_KEY is already set in the environment and takes precedence over the saved key."},
            )
            return
        except OSError:
            LOG.exception("Could not save the local Groq API key")
            self._json(500, {"error": "Could not save the key locally. Check the Jarvis server terminal."})
            return
        self._update_ai_state()
        self._json(200, self._ai_settings())


def main():
    parser = argparse.ArgumentParser(description="Start the local Jarvis assistant dashboard.")
    parser.add_argument("--host", default="127.0.0.1", help="Interface to bind (default: localhost)")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the dashboard automatically")
    args = parser.parse_args()

    if args.host not in ("127.0.0.1", "localhost"):
        parser.error("Jarvis only supports a loopback host to keep the local command API private")
    try:
        server = ThreadingHTTPServer((args.host, args.port), JarvisHandler)
    except OSError as error:
        parser.error(f"Could not start Jarvis on {args.host}:{args.port}: {error}")

    url = f"http://127.0.0.1:{args.port}/"
    LOG.info("Jarvis is ready at %s", url)
    LOG.info("AI: %s", "Groq cloud enabled" if jarvis_brain.ready() else "local mode (set GROQ_API_KEY to enable cloud AI)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOG.info("Shutting down Jarvis")
    finally:
        server.server_close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
