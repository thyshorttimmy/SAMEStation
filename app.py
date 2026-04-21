from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import socket
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from shlex import split as shell_split
from typing import NamedTuple

from same_decoder import SAME_CODE_MAP
from same_monitor import ServerAudioMonitor, build_live_wav_header
from same_paths import app_root, resource_root


ROOT_DIR = app_root()
RESOURCE_DIR = resource_root()
WEB_DIR = RESOURCE_DIR / "web"
DEFAULT_PORT = 8000
DEFAULT_BIND_HOST = "0.0.0.0"
USER_AGENT = "SAMECode/1.0 (+https://weather.gov/)"
FORWARDED_HEADERS = {
    "accept-ranges",
    "content-length",
    "content-range",
    "content-type",
    "icy-br",
    "icy-description",
    "icy-genre",
    "icy-metaint",
    "icy-name",
}
MONITOR = ServerAudioMonitor(ROOT_DIR)
LOGGER = logging.getLogger("samecode")
YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}
YTDLP_AUDIO_FORMAT = "bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]/bestaudio/best"


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


class SAMECodeHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json({"ok": True, "monitor": MONITOR.get_status()})
            return
        if parsed.path == "/api/status":
            self._send_json(MONITOR.get_status())
            return
        if parsed.path == "/api/devices":
            self._send_json({"devices": MONITOR.list_input_devices()})
            return
        if parsed.path == "/api/settings":
            self._send_json({"settings": MONITOR.get_settings()})
            return
        if parsed.path == "/api/same-codes":
            self._send_json({"codes": SAME_CODE_MAP})
            return
        if parsed.path == "/api/alerts":
            self._send_json({"alerts": MONITOR.get_status()["alerts"]})
            return
        if parsed.path == "/api/events":
            self._serve_event_stream()
            return
        if parsed.path == "/api/monitor/live.wav":
            self._serve_live_monitor_audio(parsed)
            return
        if parsed.path == "/api/proxy":
            self._handle_proxy(parsed, head_only=False)
            return
        if parsed.path == "/alerts.xml":
            self._handle_rss()
            return
        if parsed.path == "/alerts.xsl":
            self._serve_support_file(RESOURCE_DIR / "web" / "alerts.xsl", "text/xsl; charset=utf-8")
            return
        if parsed.path.startswith("/recordings/"):
            self._serve_recording(parsed.path)
            return
        super().do_GET()

    def do_HEAD(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/proxy":
            self._handle_proxy(parsed, head_only=True)
            return
        if parsed.path == "/api/monitor/live.wav":
            self._serve_live_monitor_audio(parsed, head_only=True)
            return
        if parsed.path == "/alerts.xsl":
            self._serve_support_file(RESOURCE_DIR / "web" / "alerts.xsl", "text/xsl; charset=utf-8", head_only=True)
            return
        if parsed.path.startswith("/recordings/"):
            self._serve_recording(parsed.path, head_only=True)
            return
        super().do_HEAD()

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/monitor/start":
            self._handle_monitor_start()
            return
        if parsed.path == "/api/monitor/stop":
            self._handle_monitor_stop()
            return
        if parsed.path == "/api/settings":
            self._handle_settings_update()
            return
        if parsed.path == "/api/alerts/import":
            self._handle_import_alerts()
            return
        if parsed.path == "/api/alerts/clear":
            self._handle_clear_alerts()
            return
        self.send_error_json(HTTPStatus.NOT_FOUND, "Unknown API endpoint.")

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:
        LOGGER.info("HTTP %s - %s", self.address_string(), format % args)

    def guess_type(self, path: str) -> str:
        guessed = super().guess_type(path)
        if guessed == "text/plain" and Path(path).suffix in {".js", ".mjs"}:
            return "application/javascript"
        return guessed

    def send_error_json(self, status: HTTPStatus, message: str) -> None:
        payload = json.dumps({"error": message}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _send_json(self, payload: dict[str, object]) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(encoded)

    def _read_json_body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw_body = self.rfile.read(length)
        if not raw_body:
            return {}
        return json.loads(raw_body.decode("utf-8"))

    def _handle_monitor_start(self) -> None:
        try:
            payload = self._read_json_body()
            device_id = int(payload.get("deviceId", -1))
            pre_roll_seconds = int(payload.get("preRollSeconds", 10))
            max_record_seconds = int(payload.get("maxRecordSeconds", 180))
            MONITOR.start(device_id, pre_roll_seconds=pre_roll_seconds, max_record_seconds=max_record_seconds)
            self._send_json({"ok": True, "monitor": MONITOR.get_status()})
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, f"Invalid monitor request: {exc}")
        except Exception as exc:  # noqa: BLE001
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, f"Unable to start monitor: {exc}")

    def _handle_monitor_stop(self) -> None:
        MONITOR.stop("stopped")
        self._send_json({"ok": True, "monitor": MONITOR.get_status()})

    def _handle_settings_update(self) -> None:
        try:
            payload = self._read_json_body()
            device_id = payload.get("deviceId")
            pre_roll_seconds = payload.get("preRollSeconds")
            max_record_seconds = payload.get("maxRecordSeconds")
            auto_live_playback_on_alert = payload.get("autoLivePlaybackOnAlert")
            ntfy_enabled = payload.get("ntfyEnabled")
            ntfy_base_url = payload.get("ntfyBaseUrl")
            ntfy_topic = payload.get("ntfyTopic")
            ntfy_priority_warning = payload.get("ntfyPriorityWarning")
            ntfy_priority_watch = payload.get("ntfyPriorityWatch")
            ntfy_priority_advisory = payload.get("ntfyPriorityAdvisory")
            ntfy_priority_test = payload.get("ntfyPriorityTest")
            ntfy_priority_other = payload.get("ntfyPriorityOther")
            ntfy_tags = payload.get("ntfyTags")
            ntfy_click_url_detected = payload.get("ntfyClickUrlDetected")
            ntfy_click_url_completed = payload.get("ntfyClickUrlCompleted")
            ntfy_completed_direct_recording_link = payload.get("ntfyCompletedDirectRecordingLink")
            ntfy_notify_on_detected = payload.get("ntfyNotifyOnDetected")
            ntfy_notify_on_completed = payload.get("ntfyNotifyOnCompleted")
            settings = MONITOR.update_settings(
                device_id=int(device_id) if device_id is not None else None,
                pre_roll_seconds=int(pre_roll_seconds) if pre_roll_seconds is not None else None,
                max_record_seconds=int(max_record_seconds) if max_record_seconds is not None else None,
                auto_live_playback_on_alert=bool(auto_live_playback_on_alert) if auto_live_playback_on_alert is not None else None,
                ntfy_enabled=bool(ntfy_enabled) if ntfy_enabled is not None else None,
                ntfy_base_url=str(ntfy_base_url) if ntfy_base_url is not None else None,
                ntfy_topic=str(ntfy_topic) if ntfy_topic is not None else None,
                ntfy_priority_warning=str(ntfy_priority_warning) if ntfy_priority_warning is not None else None,
                ntfy_priority_watch=str(ntfy_priority_watch) if ntfy_priority_watch is not None else None,
                ntfy_priority_advisory=str(ntfy_priority_advisory) if ntfy_priority_advisory is not None else None,
                ntfy_priority_test=str(ntfy_priority_test) if ntfy_priority_test is not None else None,
                ntfy_priority_other=str(ntfy_priority_other) if ntfy_priority_other is not None else None,
                ntfy_tags=str(ntfy_tags) if ntfy_tags is not None else None,
                ntfy_click_url_detected=str(ntfy_click_url_detected) if ntfy_click_url_detected is not None else None,
                ntfy_click_url_completed=str(ntfy_click_url_completed) if ntfy_click_url_completed is not None else None,
                ntfy_completed_direct_recording_link=bool(ntfy_completed_direct_recording_link) if ntfy_completed_direct_recording_link is not None else None,
                ntfy_notify_on_detected=bool(ntfy_notify_on_detected) if ntfy_notify_on_detected is not None else None,
                ntfy_notify_on_completed=bool(ntfy_notify_on_completed) if ntfy_notify_on_completed is not None else None,
            )
            self._send_json({"ok": True, "settings": settings})
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, f"Invalid settings request: {exc}")
        except Exception as exc:  # noqa: BLE001
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, f"Unable to update settings: {exc}")

    def _handle_clear_alerts(self) -> None:
        try:
            MONITOR.clear_alerts()
            self._send_json({"ok": True, "monitor": MONITOR.get_status()})
        except Exception as exc:  # noqa: BLE001
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, f"Unable to clear alerts: {exc}")

    def _handle_import_alerts(self) -> None:
        try:
            payload = self._read_json_body()
            alerts = payload.get("alerts")
            if not isinstance(alerts, list):
                self.send_error_json(HTTPStatus.BAD_REQUEST, "Expected alerts to be an array.")
                return
            imported = MONITOR.import_external_alerts(alerts)
            self._send_json({"ok": True, "imported": imported, "monitor": MONITOR.get_status()})
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, f"Invalid alert import request: {exc}")
        except Exception as exc:  # noqa: BLE001
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, f"Unable to import alerts: {exc}")

    def _handle_rss(self) -> None:
        xml = MONITOR.build_rss(self._base_url())
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/rss+xml; charset=utf-8")
        self.send_header("Content-Length", str(len(xml)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(xml)

    def _serve_recording(self, request_path: str, head_only: bool = False) -> None:
        relative_name = request_path.removeprefix("/recordings/").strip("/")
        recordings_dir = MONITOR.recordings_dir.resolve()
        target = (recordings_dir / relative_name).resolve()
        if recordings_dir not in target.parents and target != recordings_dir:
            self.send_error_json(HTTPStatus.FORBIDDEN, "Invalid recording path.")
            return
        if not target.exists() or not target.is_file():
            self.send_error_json(HTTPStatus.NOT_FOUND, "Recording not found.")
            return

        content = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(str(target))[0] or "audio/wav")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        if not head_only:
            self.wfile.write(content)

    def _serve_support_file(self, target: Path, content_type: str, head_only: bool = False) -> None:
        if not target.exists() or not target.is_file():
            self.send_error_json(HTTPStatus.NOT_FOUND, "Support file not found.")
            return
        content = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        if not head_only:
            self.wfile.write(content)

    def _serve_live_monitor_audio(self, parsed: urllib.parse.ParseResult, head_only: bool = False) -> None:
        status = MONITOR.get_status()
        if not status["running"] or status["sampleRate"] <= 0:
            self.send_error_json(HTTPStatus.SERVICE_UNAVAILABLE, "Server audio monitor is not running.")
            return

        listener_id, listener_queue = MONITOR.open_live_listener()
        wav_header = build_live_wav_header(int(status["sampleRate"]))

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Connection", "close")
        self.end_headers()
        if head_only:
            MONITOR.close_live_listener(listener_id)
            return

        try:
            self.wfile.write(wav_header)
            self.wfile.flush()
            while True:
                chunk = listener_queue.get(timeout=15)
                if chunk is None:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except Exception:
            pass
        finally:
            MONITOR.close_live_listener(listener_id)

    def _serve_event_stream(self) -> None:
        listener_id, listener_queue = MONITOR.open_event_listener()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        try:
            while True:
                try:
                    payload = listener_queue.get(timeout=15)
                except Exception:
                    payload = {"type": "keepalive", "timestamp": time.time()}

                if payload is None:
                    break

                encoded = json.dumps(payload)
                self.wfile.write(f"data: {encoded}\n\n".encode("utf-8"))
                self.wfile.flush()
        except Exception:
            pass
        finally:
            MONITOR.close_event_listener(listener_id)

    def _base_url(self) -> str:
        host = self.headers.get("Host", f"127.0.0.1:{self.server.server_port}")
        return f"http://{host}"

    def _handle_proxy(self, parsed: urllib.parse.ParseResult, head_only: bool) -> None:
        params = urllib.parse.parse_qs(parsed.query)
        raw_url = (params.get("url") or [""])[0].strip()
        if not raw_url:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Missing url query parameter.")
            return

        target = urllib.parse.urlparse(raw_url)
        if target.scheme not in {"http", "https"}:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Only http and https URLs are supported.")
            return

        try:
            resolved_target = resolve_proxy_target(raw_url)
        except Exception as exc:  # noqa: BLE001
            self.send_error_json(HTTPStatus.BAD_GATEWAY, f"Unable to resolve remote audio URL: {exc}")
            return

        request = urllib.request.Request(
            resolved_target.url,
            method="HEAD" if head_only else "GET",
            headers=resolved_target.request_headers or {"User-Agent": USER_AGENT},
        )

        if range_header := self.headers.get("Range"):
            request.add_header("Range", range_header)
        if accept_header := self.headers.get("Accept"):
            request.add_header("Accept", accept_header)
        if self.headers.get("Icy-Metadata"):
            request.add_header("Icy-Metadata", self.headers["Icy-Metadata"])

        try:
            with urllib.request.urlopen(request, timeout=20) as upstream:
                status = getattr(upstream, "status", HTTPStatus.OK)
                self.send_response(status)

                content_type = upstream.headers.get_content_type()
                mime_type, _ = mimetypes.guess_type(raw_url)
                resolved_mime_type, _ = mimetypes.guess_type(resolved_target.url)
                final_type = (
                    upstream.headers.get("Content-Type")
                    or resolved_target.content_type_hint
                    or resolved_mime_type
                    or mime_type
                    or content_type
                    or "application/octet-stream"
                )
                self.send_header("Content-Type", final_type)

                for key, value in upstream.headers.items():
                    lower = key.lower()
                    if lower in FORWARDED_HEADERS and lower != "content-type":
                        self.send_header(key, value)

                self.end_headers()

                if not head_only:
                    shutil.copyfileobj(upstream, self.wfile, length=64 * 1024)

        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:200]
            message = f"Remote server returned {exc.code} {exc.reason}."
            if body:
                message = f"{message} {body}"
            self.send_error_json(HTTPStatus(exc.code), message)
        except urllib.error.URLError as exc:
            self.send_error_json(HTTPStatus.BAD_GATEWAY, f"Unable to fetch remote audio URL: {exc.reason}")


class ResolvedProxyTarget(NamedTuple):
    url: str
    request_headers: dict[str, str]
    content_type_hint: str | None


def resolve_proxy_target(raw_url: str) -> ResolvedProxyTarget:
    if not is_youtube_url(raw_url):
        return ResolvedProxyTarget(
            url=raw_url,
            request_headers={"User-Agent": USER_AGENT},
            content_type_hint=None,
        )

    try:
        from yt_dlp import YoutubeDL
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("YouTube URL support requires yt-dlp to be installed.") from exc

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "extract_flat": False,
        "format": YTDLP_AUDIO_FORMAT,
    }
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(raw_url, download=False)

    if info is None:
        raise RuntimeError("yt-dlp did not return any media information.")

    if isinstance(info, dict) and info.get("entries"):
        first_entry = next((entry for entry in info["entries"] if entry), None)
        if first_entry:
            info = first_entry

    media_url = str(info.get("url") or "").strip() if isinstance(info, dict) else ""
    if not media_url:
        raise RuntimeError("No playable audio stream URL was returned for this YouTube link.")

    request_headers = normalize_request_headers(info.get("http_headers") if isinstance(info, dict) else {})
    content_type_hint = guess_content_type_hint(str(info.get("ext") or "")) if isinstance(info, dict) else None
    if "User-Agent" not in request_headers:
        request_headers["User-Agent"] = USER_AGENT
    return ResolvedProxyTarget(
        url=media_url,
        request_headers=request_headers,
        content_type_hint=content_type_hint,
    )


def is_youtube_url(raw_url: str) -> bool:
    parsed = urllib.parse.urlparse(str(raw_url).strip())
    hostname = parsed.netloc.lower().split(":")[0]
    return hostname in YOUTUBE_HOSTS


def normalize_request_headers(headers: object) -> dict[str, str]:
    if not isinstance(headers, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, value in headers.items():
        header_name = str(key).strip()
        header_value = str(value).strip()
        if not header_name or not header_value:
            continue
        if header_name.lower() == "host":
            continue
        normalized[header_name] = header_value
    return normalized


def guess_content_type_hint(extension: str) -> str | None:
    normalized = str(extension).strip().lower().lstrip(".")
    if normalized == "m4a":
        return "audio/mp4"
    if normalized == "webm":
        return "audio/webm"
    if normalized == "mp3":
        return "audio/mpeg"
    if normalized == "ogg":
        return "audio/ogg"
    return None


class SAMECodeCli:
    def __init__(self, server: ThreadingHTTPServer, monitor: ServerAudioMonitor, port: int) -> None:
        self.server = server
        self.monitor = monitor
        self.port = port
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if sys.stdin is None or sys.stdin.closed:
            LOGGER.info("CLI disabled because stdin is unavailable.")
            return
        self.thread = threading.Thread(target=self._run, name="samecode-cli", daemon=True)
        self.thread.start()
        LOGGER.info("CLI ready. Type 'help' for commands.")

    def stop(self) -> None:
        self.stop_event.set()

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                raw_command = input("samecode> ").strip()
            except EOFError:
                LOGGER.info("CLI stdin closed.")
                return
            except Exception as exc:  # noqa: BLE001
                LOGGER.error("CLI input failed: %s", exc)
                return

            if not raw_command:
                continue

            should_stop = self.execute_command(raw_command)
            if should_stop:
                return

    def execute_command(self, raw_command: str) -> bool:
        raw_command = raw_command.strip()
        if not raw_command:
            return False
        return self._handle_command(raw_command)

    def _handle_command(self, raw_command: str) -> bool:
        try:
            parts = shell_split(raw_command)
        except ValueError as exc:
            LOGGER.error("Unable to parse command: %s", exc)
            return False

        command = parts[0].lower()
        args = parts[1:]

        try:
            if command in {"help", "?"}:
                self._log_help()
                return False
            if command == "status":
                self._log_status()
                return False
            if command == "devices":
                self._log_devices()
                return False
            if command == "settings":
                LOGGER.info("Settings: %s", json.dumps(self.monitor.get_settings()))
                return False
            if command == "alerts":
                self._log_alerts(args)
                return False
            if command == "start":
                self._start_monitor(args)
                return False
            if command == "stop":
                self.monitor.stop("cli_stop")
                return False
            if command == "clear":
                self.monitor.clear_alerts()
                return False
            if command in {"open", "url"}:
                for url in build_access_urls(self.port):
                    LOGGER.info("Console: %s", url)
                return False
            if command in {"quit", "exit", "shutdown"}:
                LOGGER.info("Shutting down SAMECode from CLI command.")
                self.stop_event.set()
                threading.Thread(target=self.server.shutdown, name="samecode-shutdown", daemon=True).start()
                return True
            LOGGER.warning("Unknown command '%s'. Type 'help' for commands.", command)
            return False
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("Command '%s' failed: %s", raw_command, exc)
            return False

    def _log_help(self) -> None:
        LOGGER.info("Commands: help, status, devices, settings, alerts [count], start <deviceId> [preRoll] [maxRecord], stop, clear, open, shutdown")

    def _log_status(self) -> None:
        status = self.monitor.get_status()
        recording = status.get("currentRecording")
        summary = {
            "running": status.get("running"),
            "deviceId": status.get("deviceId"),
            "deviceName": status.get("deviceName"),
            "sampleRate": status.get("sampleRate"),
            "preRollSeconds": status.get("preRollSeconds"),
            "maxRecordSeconds": status.get("maxRecordSeconds"),
            "alerts": len(status.get("alerts") or []),
            "currentRecording": recording["rawHeader"] if recording else None,
        }
        LOGGER.info("Status: %s", json.dumps(summary))

    def _log_devices(self) -> None:
        devices = self.monitor.list_input_devices()
        if not devices:
            LOGGER.info("No input devices found.")
            return
        for device in devices:
            LOGGER.info(
                "Device %s | %s | host=%s | channels=%s | rate=%s",
                device["id"],
                device["name"],
                device["hostapi"],
                device["maxInputChannels"],
                device["defaultSampleRate"],
            )

    def _log_alerts(self, args: list[str]) -> None:
        limit = 5
        if args:
            limit = max(1, int(args[0]))
        alerts = self.monitor.get_status().get("alerts") or []
        if not alerts:
            LOGGER.info("No alerts captured.")
            return
        for alert in alerts[:limit]:
            LOGGER.info(
                "Alert %s | %s | sender=%s | repeats=%s | recording=%s",
                alert.get("recordId"),
                alert.get("eventLabel"),
                alert.get("sender"),
                alert.get("repeatCount"),
                alert.get("recording", {}).get("status"),
            )

    def _start_monitor(self, args: list[str]) -> None:
        if not args:
            raise ValueError("start requires: start <deviceId> [preRoll] [maxRecord]")
        device_id = int(args[0])
        settings = self.monitor.get_settings()
        pre_roll_seconds = int(args[1]) if len(args) >= 2 else int(settings.get("preRollSeconds") or 10)
        max_record_seconds = int(args[2]) if len(args) >= 3 else int(settings.get("maxRecordSeconds") or 180)
        self.monitor.start(
            device_id,
            pre_roll_seconds=pre_roll_seconds,
            max_record_seconds=max_record_seconds,
        )
        LOGGER.info(
            "Monitor start requested from CLI: device=%s preRoll=%s maxRecord=%s",
            device_id,
            pre_roll_seconds,
            max_record_seconds,
        )


class ServerContext(NamedTuple):
    server: ThreadingHTTPServer
    cli: SAMECodeCli | None
    port: int
    bind_host: str


def create_server_context(*, port: int = DEFAULT_PORT, bind_host: str = DEFAULT_BIND_HOST, enable_cli: bool = True) -> ServerContext:
    server = ThreadingHTTPServer((bind_host, port), SAMECodeHandler)
    resolved_port = int(server.server_port)
    MONITOR.set_activity_callback(lambda title, detail: LOGGER.info("Monitor | %s | %s", title, detail))
    cli = SAMECodeCli(server, MONITOR, resolved_port) if enable_cli else None
    return ServerContext(server=server, cli=cli, port=resolved_port, bind_host=bind_host)


def shutdown_server_context(context: ServerContext) -> None:
    if context.cli is not None:
        context.cli.stop()
    MONITOR.stop("server_shutdown")
    context.server.shutdown()
    context.server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SAMECode local web server.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind the local server on.")
    parser.add_argument("--bind", default=DEFAULT_BIND_HOST, help="Host or interface to bind the server on. Use 0.0.0.0 for LAN access.")
    parser.add_argument("--open-browser", action="store_true", help="Open the SAMECode web console in the default browser.")
    args = parser.parse_args()

    run_server(port=args.port, bind_host=args.bind, open_browser=args.open_browser)


def run_server(*, port: int = DEFAULT_PORT, bind_host: str = DEFAULT_BIND_HOST, open_browser: bool = False) -> None:
    configure_logging()
    context = create_server_context(port=port, bind_host=bind_host, enable_cli=True)
    for url in build_access_urls(context.port):
        LOGGER.info("SAMECode listening on %s", url)
    if context.cli is not None:
        context.cli.start()
    if open_browser:
        threading.Thread(
            target=lambda: _open_browser(f"http://127.0.0.1:{context.port}"),
            name="samecode-browser",
            daemon=True,
        ).start()
    try:
        context.server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Shutting down.")
    finally:
        if context.cli is not None:
            context.cli.stop()
        MONITOR.stop("server_shutdown")
        context.server.server_close()


def _open_browser(url: str) -> None:
    time.sleep(1.0)
    try:
        webbrowser.open(url, new=1)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Unable to open browser automatically: %s", exc)


def build_access_urls(port: int) -> list[str]:
    urls = [f"http://127.0.0.1:{port}"]
    seen = {"127.0.0.1"}
    try:
        hostname = socket.gethostname()
        infos = socket.getaddrinfo(hostname, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
    except Exception:
        infos = []

    for info in infos:
        address = str(info[4][0]).strip()
        if not address or address in seen:
            continue
        if address.startswith("127.") or address.startswith("169.254."):
            continue
        seen.add(address)
        urls.append(f"http://{address}:{port}")
    return urls


if __name__ == "__main__":
    main()
