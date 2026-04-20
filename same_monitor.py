from __future__ import annotations

import json
import queue
import threading
import time
import urllib.parse
import urllib.request
import uuid
import wave
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import numpy as np
import sounddevice as sd

from same_decoder import HEADER_REPEAT_TARGET, SAMEStreamDecoder, parse_same_header

EOM_REPEAT_TARGET = 3
EOM_TIMEOUT_SECONDS = 5.0
NTFY_DEFAULT_BASE_URL = "https://ntfy.sh"
NTFY_DEFAULT_PRIORITY = "high"
NTFY_DEFAULT_TAGS = "warning,radio"
TRANSCRIPTION_DEFAULT_MODEL = "small.en"
TRANSCRIPTION_ALLOWED_MODELS = ("tiny.en", "base.en", "small.en", "medium.en")
TRANSCRIPTION_INITIAL_PROMPT = (
    "National Weather Service NOAA Weather Radio severe thunderstorm warning tornado warning "
    "tornado watch severe thunderstorm watch advisory statement radar indicated rotation "
    "quarter size hail Central Daylight Time county Texas take cover now moving east miles per hour"
)


class ServerAudioMonitor:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.data_dir = root_dir / "data"
        self.recordings_dir = self.data_dir / "recordings"
        self.alerts_path = self.data_dir / "alerts.json"
        self.settings_path = self.data_dir / "settings.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.recordings_dir.mkdir(parents=True, exist_ok=True)

        self.lock = threading.RLock()
        self.running = False
        self.stream: sd.InputStream | None = None
        self.device_id: int | None = None
        self.device_name = "None"
        self.sample_rate = 0
        self.pre_roll_seconds = 10
        self.max_record_seconds = 180
        self.auto_live_playback_on_alert = False
        self.ntfy_enabled = False
        self.ntfy_base_url = NTFY_DEFAULT_BASE_URL
        self.ntfy_topic = ""
        self.ntfy_priority_warning = "urgent"
        self.ntfy_priority_watch = "high"
        self.ntfy_priority_advisory = "default"
        self.ntfy_priority_test = "min"
        self.ntfy_priority_other = NTFY_DEFAULT_PRIORITY
        self.ntfy_tags = NTFY_DEFAULT_TAGS
        self.ntfy_click_url_detected = ""
        self.ntfy_click_url_completed = ""
        self.ntfy_completed_direct_recording_link = True
        self.ntfy_notify_on_detected = True
        self.ntfy_notify_on_completed = False
        self.transcription_enabled = True
        self.transcription_model = TRANSCRIPTION_DEFAULT_MODEL
        self.decoder = SAMEStreamDecoder({"maxWindowSeconds": 30, "minRepeats": 1})
        self.pre_roll_chunks: deque[np.ndarray] = deque()
        self.pre_roll_samples = 0
        self.current_recording: dict[str, Any] | None = None
        self.alerts = self._load_alerts()
        self.activity: list[dict[str, str]] = []
        self.live_listeners: dict[str, queue.Queue[bytes | None]] = {}
        self.event_listeners: dict[str, queue.Queue[dict[str, Any] | None]] = {}
        self.notification_queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self.transcription_queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self.activity_callback: Any | None = None
        self._transcriber: Any | None = None
        self._transcriber_model_name: str | None = None
        self._load_settings()
        self.notification_thread = threading.Thread(
            target=self._run_notification_worker,
            name="samecode-ntfy",
            daemon=True,
        )
        self.notification_thread.start()
        self.transcription_thread = threading.Thread(
            target=self._run_transcription_worker,
            name="samecode-transcript",
            daemon=True,
        )
        self.transcription_thread.start()

    def set_activity_callback(self, callback: Any | None) -> None:
        with self.lock:
            self.activity_callback = callback

    def list_input_devices(self) -> list[dict[str, Any]]:
        hostapis = sd.query_hostapis()
        devices = []
        for device in sd.query_devices():
            if int(device["max_input_channels"]) <= 0:
                continue
            hostapi_index = int(device["hostapi"])
            devices.append(
                {
                    "id": int(device["index"]),
                    "name": str(device["name"]),
                    "hostapi": hostapis[hostapi_index]["name"],
                    "maxInputChannels": int(device["max_input_channels"]),
                    "defaultSampleRate": int(round(float(device["default_samplerate"]))),
                    "defaultLowInputLatency": float(device["default_low_input_latency"]),
                }
            )
        return devices

    def start(self, device_id: int, pre_roll_seconds: int = 10, max_record_seconds: int = 180) -> None:
        with self.lock:
            if self.running:
                self.stop("restarted")

            device = sd.query_devices(device_id, "input")
            self.device_id = int(device_id)
            self.device_name = str(device["name"])
            self.pre_roll_seconds = max(0, int(pre_roll_seconds))
            self.max_record_seconds = max(15, int(max_record_seconds))
            self._persist_settings()
            self.decoder.reset()
            self.pre_roll_chunks.clear()
            self.pre_roll_samples = 0
            self.current_recording = None
            self.running = False

            stream, opened_rate, open_detail = self._open_input_stream(device)
            self.stream = stream
            self.sample_rate = opened_rate
            self.running = True
            self.stream.start()
            self._add_activity("Server monitor started", f"{self.device_name} @ {self.sample_rate} Hz")
            self._add_activity("Input stream config", open_detail)

    def stop(self, reason: str = "stopped") -> None:
        with self.lock:
            self.running = False
            if self.current_recording is not None:
                self._finalize_recording(reason if reason != "stopped" else "monitor_stopped")

            if self.stream is not None:
                try:
                    self.stream.stop()
                finally:
                    self.stream.close()
                self.stream = None

            for listener_queue in list(self.live_listeners.values()):
                try:
                    listener_queue.put_nowait(None)
                except queue.Full:
                    pass

            self._add_activity("Server monitor stopped", reason.replace("_", " "))

    def get_status(self) -> dict[str, Any]:
        with self.lock:
            return {
                "running": self.running,
                "deviceId": self.device_id,
                "deviceName": self.device_name,
                "sampleRate": self.sample_rate,
                "preRollSeconds": self.pre_roll_seconds,
                "maxRecordSeconds": self.max_record_seconds,
                "alerts": self.alerts[:25],
                "activity": self.activity[:20],
                "currentRecording": self._current_recording_status(),
                "settings": self.get_settings(),
            }

    def get_settings(self) -> dict[str, Any]:
        with self.lock:
            return {
                "deviceId": self.device_id,
                "deviceName": self.device_name,
                "preRollSeconds": self.pre_roll_seconds,
                "maxRecordSeconds": self.max_record_seconds,
                "autoLivePlaybackOnAlert": self.auto_live_playback_on_alert,
                "ntfyEnabled": self.ntfy_enabled,
                "ntfyBaseUrl": self.ntfy_base_url,
                "ntfyTopic": self.ntfy_topic,
                "ntfyPriorityWarning": self.ntfy_priority_warning,
                "ntfyPriorityWatch": self.ntfy_priority_watch,
                "ntfyPriorityAdvisory": self.ntfy_priority_advisory,
                "ntfyPriorityTest": self.ntfy_priority_test,
                "ntfyPriorityOther": self.ntfy_priority_other,
                "ntfyTags": self.ntfy_tags,
                "ntfyClickUrlDetected": self.ntfy_click_url_detected,
                "ntfyClickUrlCompleted": self.ntfy_click_url_completed,
                "ntfyCompletedDirectRecordingLink": self.ntfy_completed_direct_recording_link,
                "ntfyNotifyOnDetected": self.ntfy_notify_on_detected,
                "ntfyNotifyOnCompleted": self.ntfy_notify_on_completed,
                "transcriptionEnabled": self.transcription_enabled,
                "transcriptionModel": self.transcription_model,
            }

    def update_settings(
        self,
        *,
        device_id: int | None = None,
        pre_roll_seconds: int | None = None,
        max_record_seconds: int | None = None,
        auto_live_playback_on_alert: bool | None = None,
        ntfy_enabled: bool | None = None,
        ntfy_base_url: str | None = None,
        ntfy_topic: str | None = None,
        ntfy_priority_warning: str | None = None,
        ntfy_priority_watch: str | None = None,
        ntfy_priority_advisory: str | None = None,
        ntfy_priority_test: str | None = None,
        ntfy_priority_other: str | None = None,
        ntfy_tags: str | None = None,
        ntfy_click_url_detected: str | None = None,
        ntfy_click_url_completed: str | None = None,
        ntfy_completed_direct_recording_link: bool | None = None,
        ntfy_notify_on_detected: bool | None = None,
        ntfy_notify_on_completed: bool | None = None,
        transcription_enabled: bool | None = None,
        transcription_model: str | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            if device_id is not None:
                self.device_id = int(device_id)
                self.device_name = self._lookup_device_name(self.device_id)
            if pre_roll_seconds is not None:
                self.pre_roll_seconds = max(0, int(pre_roll_seconds))
            if max_record_seconds is not None:
                self.max_record_seconds = max(15, int(max_record_seconds))
            if auto_live_playback_on_alert is not None:
                self.auto_live_playback_on_alert = bool(auto_live_playback_on_alert)
            if ntfy_enabled is not None:
                self.ntfy_enabled = bool(ntfy_enabled)
            if ntfy_base_url is not None:
                self.ntfy_base_url = sanitize_base_url(ntfy_base_url) or NTFY_DEFAULT_BASE_URL
            if ntfy_topic is not None:
                self.ntfy_topic = str(ntfy_topic).strip()
            if ntfy_priority_warning is not None:
                self.ntfy_priority_warning = sanitize_ntfy_priority(ntfy_priority_warning)
            if ntfy_priority_watch is not None:
                self.ntfy_priority_watch = sanitize_ntfy_priority(ntfy_priority_watch)
            if ntfy_priority_advisory is not None:
                self.ntfy_priority_advisory = sanitize_ntfy_priority(ntfy_priority_advisory)
            if ntfy_priority_test is not None:
                self.ntfy_priority_test = sanitize_ntfy_priority(ntfy_priority_test)
            if ntfy_priority_other is not None:
                self.ntfy_priority_other = sanitize_ntfy_priority(ntfy_priority_other)
            if ntfy_tags is not None:
                self.ntfy_tags = str(ntfy_tags).strip()
            if ntfy_click_url_detected is not None:
                self.ntfy_click_url_detected = str(ntfy_click_url_detected).strip()
            if ntfy_click_url_completed is not None:
                self.ntfy_click_url_completed = str(ntfy_click_url_completed).strip()
            if ntfy_completed_direct_recording_link is not None:
                self.ntfy_completed_direct_recording_link = bool(ntfy_completed_direct_recording_link)
            if ntfy_notify_on_detected is not None:
                self.ntfy_notify_on_detected = bool(ntfy_notify_on_detected)
            if ntfy_notify_on_completed is not None:
                self.ntfy_notify_on_completed = bool(ntfy_notify_on_completed)
            if transcription_enabled is not None:
                self.transcription_enabled = bool(transcription_enabled)
            if transcription_model is not None:
                self.transcription_model = sanitize_transcription_model(transcription_model)
                self._transcriber = None
                self._transcriber_model_name = None
            self._persist_settings()
            self._emit_event("settings-updated")
            return self.get_settings()

    def clear_alerts(self) -> None:
        with self.lock:
            for alert in self.alerts:
                recording_url = alert.get("recording", {}).get("url")
                if not recording_url:
                    continue
                file_name = Path(str(recording_url)).name
                target = (self.recordings_dir / file_name).resolve()
                if target.exists() and target.is_file() and self.recordings_dir.resolve() in target.parents:
                    target.unlink(missing_ok=True)
            self.alerts = []
            self._persist_alerts()
            self._add_activity("Alerts cleared", "Stored alerts and saved recordings were removed.")

    def request_retranscription(self, record_id: str) -> dict[str, Any]:
        with self.lock:
            target_alert = next((alert for alert in self.alerts if alert.get("recordId") == record_id), None)
            if target_alert is None:
                raise KeyError(f"Alert {record_id} was not found.")

            recording = target_alert.get("recording") or {}
            if recording.get("status") != "complete":
                raise RuntimeError("Only completed alert recordings can be retranscribed.")

            file_name = str(recording.get("fileName") or "").strip()
            if not file_name:
                recording_url = str(recording.get("url") or "").strip()
                file_name = Path(recording_url).name if recording_url else ""
            if not file_name:
                raise RuntimeError("This alert does not have a saved recording file.")

            file_path = (self.recordings_dir / file_name).resolve()
            if self.recordings_dir.resolve() not in file_path.parents or not file_path.exists():
                raise FileNotFoundError(f"Saved recording not found for alert {record_id}.")

            target_alert["transcript"] = build_transcript_state("pending", model=self.transcription_model)
            self._persist_alerts()
            self._emit_event("transcript-requeued")

        self._queue_transcription(target_alert, file_path)
        self._add_activity("Transcript requeued", file_name)
        return json.loads(json.dumps(target_alert))

    def open_live_listener(self) -> tuple[str, queue.Queue[bytes | None]]:
        with self.lock:
            listener_id = uuid.uuid4().hex
            listener_queue: queue.Queue[bytes | None] = queue.Queue(maxsize=32)
            self.live_listeners[listener_id] = listener_queue
            return listener_id, listener_queue

    def close_live_listener(self, listener_id: str) -> None:
        with self.lock:
            self.live_listeners.pop(listener_id, None)

    def open_event_listener(self) -> tuple[str, queue.Queue[dict[str, Any] | None]]:
        with self.lock:
            listener_id = uuid.uuid4().hex
            listener_queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=32)
            self.event_listeners[listener_id] = listener_queue
            listener_queue.put_nowait({"type": "snapshot", "status": self.get_status()})
            return listener_id, listener_queue

    def close_event_listener(self, listener_id: str) -> None:
        with self.lock:
            self.event_listeners.pop(listener_id, None)

    def build_rss(self, base_url: str) -> bytes:
        items = []
        for alert in self.alerts[:50]:
            title = escape(f"{alert['eventLabel']} from {alert['sender']}")
            recording_url = f"{base_url}{alert['recording']['url']}" if alert.get("recording", {}).get("url") else ""
            recording_state = alert.get("recording", {}).get("status", "complete")
            guid = escape(alert["recordId"])
            pub_date = escape(alert.get("detectedPubDate") or datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000"))
            escaped_recording_url = escape(recording_url) if recording_url else ""
            length = str(alert.get("recording", {}).get("sizeBytes", 0))
            issue_display = escape(alert.get("issued", {}).get("display") or alert.get("detectedAt") or "Unknown")
            duration_text = escape(alert.get("durationText") or "Unknown")
            source_label = escape(alert.get("sourceLabel") or "Server audio device")
            raw_header = escape(format_raw_bursts(alert))
            originator_label = escape(alert.get("originatorLabel") or "Unknown originator")
            sender = escape(alert.get("sender") or source_label)
            event_label = escape(alert.get("eventLabel") or "Decoded header")
            event_code = escape(alert.get("eventCode") or "---")
            confidence_percent = f"{round(float(alert.get('confidence', 0.0)) * 100)}%"
            repeat_count = int(alert.get("repeatCount", 1))
            repeat_text = f"{repeat_count} repeat" if repeat_count == 1 else f"{repeat_count} repeats"

            locations = alert.get("locations") or []
            if locations:
                location_parts = []
                for location in locations:
                    label = location.get("locationLabel") or (
                        f"{location.get('stateLabel', 'Unknown state')}, county {location.get('countyCode', '---')}"
                    )
                    location_parts.append(
                        escape(f"{location.get('partitionLabel', 'Unknown area')}, {label}")
                    )
                location_summary = "<br />".join(location_parts)
            else:
                location_summary = "No location codes parsed"

            recording_markup = (
                f"<div class=\"recording-block\">"
                f"<span>Recording</span>"
                f"<audio controls preload=\"none\" src=\"{escaped_recording_url}\"></audio>"
                f"<div class=\"muted\">{escape(alert['recording']['durationText'])} | Ended by {escape(alert['recording']['endReason'])}</div>"
                f"</div>"
                if recording_state == "complete" and escaped_recording_url
                else "<div class=\"recording-block\"><span>Recording</span><div class=\"recording-status\">Capture in progress. This alert will update when the file is finalized.</div></div>"
            )
            transcript_markup = build_transcript_markup(alert.get("transcript"))

            description = (
                "<![CDATA["
                f"<article class=\"alert-card\">"
                f"<div class=\"alert-head\">"
                f"<div>"
                f"<div class=\"alert-title\">{event_label} <span class=\"muted\">({event_code})</span></div>"
                f"<div class=\"alert-meta\">{originator_label} from {sender}</div>"
                f"</div>"
                f"<div class=\"pill{' warn' if recording_state == 'recording' or repeat_count < 3 else ''}\">{escape('live capture' if recording_state == 'recording' else repeat_text)} | {confidence_percent}</div>"
                f"</div>"
                f"<div class=\"alert-grid\">"
                f"<div><span>Issued</span>{issue_display}</div>"
                f"<div><span>Valid For</span>{duration_text}</div>"
                f"<div><span>Source</span>{source_label}</div>"
                f"<div><span>Locations</span>{location_summary}</div>"
                f"</div>"
                f"{recording_markup}"
                f"{transcript_markup}"
                f"<div class=\"raw-header\">{raw_header}</div>"
                f"</article>"
                "]]>"
            )
            items.append(
                "\n".join(
                    [
                        "    <item>",
                        f"      <title>{title}</title>",
                        f"      <guid>{guid}</guid>",
                        f"      <pubDate>{pub_date}</pubDate>",
                        f"      <link>{escape(base_url)}/</link>",
                        f"      <description>{description}</description>",
                        *(
                            [f'      <enclosure url="{escaped_recording_url}" length="{length}" type="audio/wav" />']
                            if escaped_recording_url
                            else []
                        ),
                        "    </item>",
                    ]
                )
            )

        xml = "\n".join(
            [
                '<?xml version="1.0" encoding="UTF-8"?>',
                '<?xml-stylesheet type="text/xsl" href="/alerts.xsl"?>',
                '<rss version="2.0">',
                "  <channel>",
                "    <title>SAMECode Alerts</title>",
                f"    <link>{escape(base_url)}/</link>",
                "    <description>Recorded SAME alerts captured by the server-side audio monitor.</description>",
                *items,
                "  </channel>",
                "</rss>",
                "",
            ]
        )
        return xml.encode("utf-8")

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        mono = np.asarray(indata[:, 0], dtype=np.float32).copy()
        with self.lock:
            if not self.running:
                return

            if status:
                self._add_activity("Audio callback status", str(status))

            self._broadcast_live_audio(mono)
            self._append_pre_roll(mono)
            if self.current_recording is not None:
                self.current_recording["chunks"].append(mono.copy())

            ready = self.decoder.append_pcm(mono, self.sample_rate)
            if ready:
                result = self.decoder.scan()
                self._process_new_bursts(result["newBursts"])
                self._update_recording_from_alerts(result["alerts"])

            if self.current_recording is not None:
                recorded_samples = int(sum(chunk.size for chunk in self.current_recording["chunks"]))
                if recorded_samples / max(1, self.sample_rate) >= self.max_record_seconds:
                    self._finalize_recording("timeout")
                elif self._should_finalize_due_to_eom_timeout():
                    self._add_activity(
                        "EOM timeout reached",
                        f"No additional EOM burst arrived within {int(EOM_TIMEOUT_SECONDS)} seconds.",
                    )
                    self._finalize_recording("eom_timeout")

    def _append_pre_roll(self, chunk: np.ndarray) -> None:
        if self.pre_roll_seconds <= 0:
            return

        self.pre_roll_chunks.append(chunk.copy())
        self.pre_roll_samples += int(chunk.size)
        max_samples = int(self.sample_rate * self.pre_roll_seconds)
        while self.pre_roll_samples > max_samples and self.pre_roll_chunks:
            removed = self.pre_roll_chunks.popleft()
            self.pre_roll_samples -= int(removed.size)

    def _process_new_bursts(self, bursts: list[dict[str, Any]]) -> None:
        for burst in bursts:
            if burst["kind"] == "header":
                parsed = parse_same_header(burst["rawText"])
                if parsed is None:
                    continue
                if self.current_recording is None:
                    self._start_recording(parsed, burst)
                elif self.current_recording["rawHeader"] == burst["rawText"]:
                    if int(self.current_recording.get("headerCount", 1)) >= HEADER_REPEAT_TARGET:
                        continue
                    self.current_recording["headerCount"] = int(self.current_recording.get("headerCount", 1)) + 1
                    self.current_recording["repeatCount"] = max(
                        int(self.current_recording.get("repeatCount", 1)),
                        int(self.current_recording["headerCount"]),
                    )
                    self.current_recording["lastHeaderAt"] = now_iso()
                    self.current_recording["rawBursts"].append(self._serialize_burst(burst))
                    self._update_pending_alert()
            elif burst["kind"] == "eom" and self.current_recording is not None:
                self.current_recording["rawBursts"].append(self._serialize_burst(burst))
                self.current_recording["eomCount"] = int(self.current_recording.get("eomCount", 0)) + 1
                self.current_recording["lastEomAt"] = now_iso()
                self.current_recording["lastEomMonotonic"] = time.monotonic()
                self._update_pending_alert()
                self._add_activity(
                    "EOM burst detected",
                    f"{self.current_recording['eomCount']} of {EOM_REPEAT_TARGET} received.",
                )
                if self.current_recording["eomCount"] >= EOM_REPEAT_TARGET:
                    self._finalize_recording("eom")

    def _update_recording_from_alerts(self, alerts: list[dict[str, Any]]) -> None:
        if self.current_recording is None:
            return
        for alert in alerts:
            if alert["rawHeader"] == self.current_recording["rawHeader"]:
                previous_repeat_count = int(self.current_recording.get("repeatCount", 1))
                previous_confidence = float(self.current_recording.get("confidence", 0.0))
                self.current_recording["repeatCount"] = max(
                    previous_repeat_count,
                    int(alert.get("repeatCount", 1)),
                )
                self.current_recording["confidence"] = max(
                    previous_confidence,
                    float(alert.get("confidence", 0.0)),
                )
                if (
                    int(self.current_recording.get("repeatCount", 1)) != previous_repeat_count
                    or float(self.current_recording.get("confidence", 0.0)) != previous_confidence
                ):
                    self._emit_event("recording-updated")

    def _start_recording(self, parsed: dict[str, Any], burst: dict[str, Any]) -> None:
        chunks = [chunk.copy() for chunk in self.pre_roll_chunks]
        record_id = uuid.uuid4().hex
        self.current_recording = {
            "recordId": record_id,
            "rawHeader": parsed["rawHeader"],
            "parsed": parsed,
            "startedAt": now_iso(),
            "detectedPubDate": parsed.get("issued", {}).get("pubDate"),
            "repeatCount": 1,
            "headerCount": 1,
            "confidence": float(burst.get("confidence", 0.0)),
            "chunks": chunks,
            "lastHeaderAt": now_iso(),
            "eomCount": 0,
            "lastEomAt": None,
            "lastEomMonotonic": None,
            "rawBursts": [self._serialize_burst(burst)],
        }
        pending_alert = {
            **parsed,
            "id": parsed.get("id"),
            "recordId": record_id,
            "confidence": float(burst.get("confidence", 0.0)),
            "repeatCount": 1,
            "sourceKind": "server-device",
            "sourceLabel": self.device_name,
            "detectedAt": self.current_recording["startedAt"],
            "detectedPubDate": self.current_recording.get("detectedPubDate"),
            "completedAt": None,
            "rawBursts": list(self.current_recording["rawBursts"]),
            "recording": {
                "url": None,
                "fileName": None,
                "durationSeconds": None,
                "durationText": "Recording in progress",
                "sampleRate": self.sample_rate,
                "endReason": None,
                "preRollSeconds": self.pre_roll_seconds,
                "sizeBytes": 0,
                "status": "recording",
            },
            "transcript": build_transcript_state("waiting", model=self.transcription_model),
        }
        self.alerts.insert(0, pending_alert)
        self.alerts = self.alerts[:200]
        self._persist_alerts()
        self._add_activity("Recording started", parsed["rawHeader"])
        self._queue_ntfy_notification(pending_alert, "detected")

    def _finalize_recording(self, end_reason: str) -> None:
        if self.current_recording is None:
            return

        recording = self.current_recording
        self.current_recording = None
        samples = np.concatenate(recording["chunks"]) if recording["chunks"] else np.zeros(0, dtype=np.float32)
        if samples.size == 0:
            self._add_activity("Recording discarded", "No samples were captured.")
            return

        file_name = build_recording_name(recording["parsed"], recording["recordId"])
        file_path = self.recordings_dir / file_name
        write_wav(file_path, samples, self.sample_rate)
        duration_seconds = samples.size / max(1, self.sample_rate)
        file_size = file_path.stat().st_size

        alert_record = {
            **recording["parsed"],
            "id": recording["parsed"]["id"] if "id" in recording["parsed"] else None,
            "recordId": recording["recordId"],
            "confidence": float(recording.get("confidence", 0.0)),
            "repeatCount": int(recording.get("repeatCount", 1)),
            "sourceKind": "server-device",
            "sourceLabel": self.device_name,
            "detectedAt": recording["startedAt"],
            "detectedPubDate": recording.get("detectedPubDate"),
            "completedAt": now_iso(),
            "rawBursts": list(recording.get("rawBursts", [])),
            "recording": {
                "url": f"/recordings/{file_name}",
                "fileName": file_name,
                "durationSeconds": round(duration_seconds, 2),
                "durationText": format_seconds(duration_seconds),
                "sampleRate": self.sample_rate,
                "endReason": end_reason,
                "preRollSeconds": self.pre_roll_seconds,
                "sizeBytes": file_size,
                "status": "complete",
            },
            "transcript": build_transcript_state(
                "pending" if self.transcription_enabled else "disabled",
                model=self.transcription_model,
            ),
        }
        self._replace_alert(alert_record)
        self._persist_alerts()
        self._add_activity("Recording saved", f"{file_name} ({alert_record['recording']['durationText']})")
        if self.transcription_enabled:
            self._queue_transcription(alert_record, file_path)
        self._queue_ntfy_notification(alert_record, "completed")

    def _current_recording_status(self) -> dict[str, Any] | None:
        if self.current_recording is None:
            return None
        duration_samples = int(sum(chunk.size for chunk in self.current_recording["chunks"]))
        return {
            "recordId": self.current_recording["recordId"],
            "rawHeader": self.current_recording["rawHeader"],
            "startedAt": self.current_recording["startedAt"],
            "durationSeconds": round(duration_samples / max(1, self.sample_rate), 2),
            "eomCount": int(self.current_recording.get("eomCount", 0)),
        }

    def _load_alerts(self) -> list[dict[str, Any]]:
        if not self.alerts_path.exists():
            return []
        try:
            return json.loads(self.alerts_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

    def _load_settings(self) -> None:
        if self.settings_path.exists():
            try:
                settings = json.loads(self.settings_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                settings = {}
        else:
            settings = {}

        saved_device_id = settings.get("deviceId")
        if saved_device_id is not None:
            try:
                self.device_id = int(saved_device_id)
                self.device_name = self._lookup_device_name(self.device_id)
            except Exception:  # noqa: BLE001
                self.device_name = f"Saved device #{saved_device_id}"
        self.pre_roll_seconds = max(0, int(settings.get("preRollSeconds", self.pre_roll_seconds)))
        self.max_record_seconds = max(15, int(settings.get("maxRecordSeconds", self.max_record_seconds)))
        self.auto_live_playback_on_alert = bool(settings.get("autoLivePlaybackOnAlert", self.auto_live_playback_on_alert))
        self.ntfy_enabled = bool(settings.get("ntfyEnabled", self.ntfy_enabled))
        self.ntfy_base_url = sanitize_base_url(str(settings.get("ntfyBaseUrl", self.ntfy_base_url))) or NTFY_DEFAULT_BASE_URL
        self.ntfy_topic = str(settings.get("ntfyTopic", self.ntfy_topic)).strip()
        legacy_priority = str(settings.get("ntfyPriority", self.ntfy_priority_other))
        self.ntfy_priority_warning = sanitize_ntfy_priority(str(settings.get("ntfyPriorityWarning", self.ntfy_priority_warning)))
        self.ntfy_priority_watch = sanitize_ntfy_priority(str(settings.get("ntfyPriorityWatch", self.ntfy_priority_watch)))
        self.ntfy_priority_advisory = sanitize_ntfy_priority(str(settings.get("ntfyPriorityAdvisory", self.ntfy_priority_advisory)))
        self.ntfy_priority_test = sanitize_ntfy_priority(str(settings.get("ntfyPriorityTest", self.ntfy_priority_test)))
        self.ntfy_priority_other = sanitize_ntfy_priority(str(settings.get("ntfyPriorityOther", legacy_priority)))
        self.ntfy_tags = str(settings.get("ntfyTags", self.ntfy_tags)).strip()
        legacy_click_url = str(settings.get("ntfyClickUrl", "")).strip()
        self.ntfy_click_url_detected = str(settings.get("ntfyClickUrlDetected", legacy_click_url or self.ntfy_click_url_detected)).strip()
        self.ntfy_click_url_completed = str(settings.get("ntfyClickUrlCompleted", legacy_click_url or self.ntfy_click_url_completed)).strip()
        self.ntfy_completed_direct_recording_link = bool(
            settings.get("ntfyCompletedDirectRecordingLink", self.ntfy_completed_direct_recording_link)
        )
        self.ntfy_notify_on_detected = bool(settings.get("ntfyNotifyOnDetected", self.ntfy_notify_on_detected))
        self.ntfy_notify_on_completed = bool(settings.get("ntfyNotifyOnCompleted", self.ntfy_notify_on_completed))
        self.transcription_enabled = bool(settings.get("transcriptionEnabled", self.transcription_enabled))
        self.transcription_model = sanitize_transcription_model(
            str(settings.get("transcriptionModel", self.transcription_model))
        )
        self._persist_settings()

    def _persist_alerts(self) -> None:
        self.alerts_path.write_text(json.dumps(self.alerts, indent=2), encoding="utf-8")

    def _persist_settings(self) -> None:
        payload = {
            "deviceId": self.device_id,
            "deviceName": self.device_name,
            "preRollSeconds": self.pre_roll_seconds,
            "maxRecordSeconds": self.max_record_seconds,
            "autoLivePlaybackOnAlert": self.auto_live_playback_on_alert,
            "ntfyEnabled": self.ntfy_enabled,
            "ntfyBaseUrl": self.ntfy_base_url,
            "ntfyTopic": self.ntfy_topic,
            "ntfyPriorityWarning": self.ntfy_priority_warning,
            "ntfyPriorityWatch": self.ntfy_priority_watch,
            "ntfyPriorityAdvisory": self.ntfy_priority_advisory,
            "ntfyPriorityTest": self.ntfy_priority_test,
            "ntfyPriorityOther": self.ntfy_priority_other,
            "ntfyTags": self.ntfy_tags,
            "ntfyClickUrlDetected": self.ntfy_click_url_detected,
            "ntfyClickUrlCompleted": self.ntfy_click_url_completed,
            "ntfyCompletedDirectRecordingLink": self.ntfy_completed_direct_recording_link,
            "ntfyNotifyOnDetected": self.ntfy_notify_on_detected,
            "ntfyNotifyOnCompleted": self.ntfy_notify_on_completed,
            "transcriptionEnabled": self.transcription_enabled,
            "transcriptionModel": self.transcription_model,
        }
        self.settings_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _add_activity(self, title: str, detail: str) -> None:
        self.activity.insert(0, {"title": title, "detail": detail, "timestamp": now_iso()})
        self.activity = self.activity[:50]
        callback = self.activity_callback
        if callback is not None:
            try:
                callback(title, detail)
            except Exception:
                pass
        self._emit_event("activity", activity=self.activity[0])

    def _replace_alert(self, replacement: dict[str, Any]) -> None:
        for index, alert in enumerate(self.alerts):
            if alert.get("recordId") == replacement.get("recordId"):
                self.alerts[index] = replacement
                return
        self.alerts.insert(0, replacement)
        self.alerts = self.alerts[:200]

    def _update_pending_alert(self) -> None:
        if self.current_recording is None:
            return
        for alert in self.alerts:
            if alert.get("recordId") == self.current_recording["recordId"]:
                alert["rawBursts"] = list(self.current_recording.get("rawBursts", []))
                alert["repeatCount"] = int(self.current_recording.get("repeatCount", 1))
                alert["confidence"] = float(self.current_recording.get("confidence", 0.0))
                self._persist_alerts()
                self._emit_event("recording-updated")
                return

    def _serialize_burst(self, burst: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": str(burst.get("kind") or "header"),
            "rawText": str(burst.get("rawText") or ""),
            "confidence": float(burst.get("confidence", 0.0)),
            "startSample": int(burst.get("startSample", 0)),
            "endSample": int(burst.get("endSample", 0)),
        }

    def _should_finalize_due_to_eom_timeout(self) -> bool:
        if self.current_recording is None:
            return False
        eom_count = int(self.current_recording.get("eomCount", 0))
        last_eom_monotonic = self.current_recording.get("lastEomMonotonic")
        if eom_count <= 0 or last_eom_monotonic is None:
            return False
        return (time.monotonic() - float(last_eom_monotonic)) >= EOM_TIMEOUT_SECONDS

    def _lookup_device_name(self, device_id: int) -> str:
        try:
            device = sd.query_devices(device_id, "input")
        except Exception:  # noqa: BLE001
            return f"Saved device #{device_id}"
        return str(device["name"])

    def _open_input_stream(self, device: dict[str, Any]) -> tuple[sd.InputStream, int, str]:
        channels = 1
        default_rate = int(round(float(device["default_samplerate"])))
        candidate_rates = unique_ints(
            [
                default_rate,
                48000,
                44100,
                32000,
                22050,
            ]
        )
        candidate_configs = [
            {"blocksize": 0, "latency": "low"},
            {"blocksize": 0, "latency": "high"},
            {"blocksize": 4096, "latency": "high"},
            {"blocksize": 4096, "latency": "low"},
            {"blocksize": None, "latency": None},
        ]

        errors: list[str] = []
        for sample_rate in candidate_rates:
            for config in candidate_configs:
                try:
                    check_kwargs = {
                        "device": self.device_id,
                        "samplerate": sample_rate,
                        "channels": channels,
                        "dtype": "float32",
                    }
                    if config["latency"] is not None:
                        check_kwargs["latency"] = config["latency"]
                    sd.check_input_settings(**check_kwargs)

                    stream_kwargs = {
                        "device": self.device_id,
                        "samplerate": sample_rate,
                        "channels": channels,
                        "dtype": "float32",
                        "callback": self._audio_callback,
                    }
                    if config["blocksize"] is not None:
                        stream_kwargs["blocksize"] = config["blocksize"]
                    if config["latency"] is not None:
                        stream_kwargs["latency"] = config["latency"]
                    stream = sd.InputStream(**stream_kwargs)
                    detail = f"sampleRate={sample_rate}, blocksize={config['blocksize']}, latency={config['latency']}"
                    return stream, sample_rate, detail
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        f"sampleRate={sample_rate}, blocksize={config['blocksize']}, latency={config['latency']}: {exc}"
                    )

        joined_errors = " | ".join(errors[:6])
        raise RuntimeError(
            f"Could not open input stream for {self.device_name}. Tried multiple sample rate and latency combinations. {joined_errors}"
        )

    def _broadcast_live_audio(self, samples: np.ndarray) -> None:
        if not self.live_listeners:
            return
        stale_ids: list[str] = []
        pcm_bytes = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
        for listener_id, listener_queue in self.live_listeners.items():
            try:
                listener_queue.put_nowait(pcm_bytes)
            except queue.Full:
                try:
                    listener_queue.get_nowait()
                    listener_queue.put_nowait(pcm_bytes)
                except Exception:  # noqa: BLE001
                    stale_ids.append(listener_id)
        for listener_id in stale_ids:
            self.live_listeners.pop(listener_id, None)

    def _emit_event(self, event_type: str, **payload: Any) -> None:
        if not self.event_listeners:
            return
        snapshot = {"type": event_type, "status": self.get_status(), **payload}
        stale_ids: list[str] = []
        for listener_id, listener_queue in self.event_listeners.items():
            try:
                listener_queue.put_nowait(snapshot)
            except queue.Full:
                try:
                    listener_queue.get_nowait()
                    listener_queue.put_nowait(snapshot)
                except Exception:  # noqa: BLE001
                    stale_ids.append(listener_id)
        for listener_id in stale_ids:
            self.event_listeners.pop(listener_id, None)

    def _queue_ntfy_notification(self, alert: dict[str, Any], stage: str) -> None:
        if not self.ntfy_enabled or not self.ntfy_topic:
            return
        if stage == "detected" and not self.ntfy_notify_on_detected:
            return
        if stage == "completed" and not self.ntfy_notify_on_completed:
            return
        self.notification_queue.put(
            {
                "kind": "ntfy",
                "stage": stage,
                "alert": json.loads(json.dumps(alert)),
            }
        )

    def _queue_transcription(self, alert: dict[str, Any], file_path: Path) -> None:
        self.transcription_queue.put(
            {
                "recordId": str(alert.get("recordId") or ""),
                "recordingPath": str(file_path),
                "model": self.transcription_model,
            }
        )
        self._add_activity("Transcript queued", file_path.name)

    def _run_notification_worker(self) -> None:
        while True:
            task = self.notification_queue.get()
            if task is None:
                return
            try:
                if task.get("kind") == "ntfy":
                    self._send_ntfy_notification(task["alert"], str(task.get("stage") or "detected"))
            except Exception as exc:  # noqa: BLE001
                self._add_activity("Notification failed", str(exc))

    def _run_transcription_worker(self) -> None:
        while True:
            task = self.transcription_queue.get()
            if task is None:
                return
            record_id = str(task.get("recordId") or "")
            recording_path = Path(str(task.get("recordingPath") or ""))
            model_name = sanitize_transcription_model(str(task.get("model") or self.transcription_model))
            try:
                if not recording_path.exists():
                    raise FileNotFoundError(f"Recording not found: {recording_path.name}")
                self._add_activity("Transcript started", f"{recording_path.name} using {model_name}")
                transcript = self._transcribe_recording(recording_path, model_name)
                self._update_alert_transcript(
                    record_id,
                    build_transcript_state(
                        "complete",
                        model=model_name,
                        text=transcript["text"],
                        language=transcript.get("language"),
                    ),
                )
                self._add_activity("Transcript finished", recording_path.name)
            except Exception as exc:  # noqa: BLE001
                self._update_alert_transcript(
                    record_id,
                    build_transcript_state("error", model=model_name, error=str(exc)),
                )
                self._add_activity("Transcript failed", str(exc))

    def _transcribe_recording(self, file_path: Path, model_name: str) -> dict[str, Any]:
        transcriber = self._get_transcriber(model_name)
        segments, info = transcriber.transcribe(
            str(file_path),
            language="en",
            beam_size=5,
            best_of=5,
            temperature=0.0,
            vad_filter=True,
            condition_on_previous_text=True,
            initial_prompt=TRANSCRIPTION_INITIAL_PROMPT,
        )
        text_parts: list[str] = []
        for segment in segments:
            piece = str(getattr(segment, "text", "") or "").strip()
            if piece:
                text_parts.append(piece)
        transcript_text = " ".join(text_parts).strip()
        if not transcript_text:
            transcript_text = "No spoken transcript could be recognized."
        return {
            "text": transcript_text,
            "language": str(getattr(info, "language", "en") or "en"),
        }

    def _get_transcriber(self, model_name: str) -> Any:
        if self._transcriber is not None and self._transcriber_model_name == model_name:
            return self._transcriber
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "Alert transcription requires faster-whisper. Install the dependency bundle again to enable transcripts."
            ) from exc

        errors: list[str] = []
        for compute_type in ("int8", "int8_float32", "float32"):
            try:
                self._transcriber = WhisperModel(model_name, device="cpu", compute_type=compute_type)
                self._transcriber_model_name = model_name
                return self._transcriber
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{compute_type}: {exc}")
        raise RuntimeError(f"Unable to load transcription model {model_name}. {' | '.join(errors[:3])}")

    def _update_alert_transcript(self, record_id: str, transcript: dict[str, Any]) -> None:
        if not record_id:
            return
        with self.lock:
            for alert in self.alerts:
                if alert.get("recordId") != record_id:
                    continue
                alert["transcript"] = transcript
                self._persist_alerts()
                self._emit_event("transcript-updated")
                return

    def _send_ntfy_notification(self, alert: dict[str, Any], stage: str) -> None:
        base_url = sanitize_base_url(self.ntfy_base_url) or NTFY_DEFAULT_BASE_URL
        topic = str(self.ntfy_topic).strip()
        if not topic:
            return

        publish_url = f"{base_url}/{urllib.parse.quote(topic, safe='')}"
        title = build_ntfy_title(alert, stage)
        message = build_ntfy_message(alert, stage)
        headers = {
            "Title": title,
            "Priority": self._priority_for_alert(alert),
        }
        tags = normalize_tag_list(self.ntfy_tags)
        if tags:
            headers["Tags"] = ",".join(tags)
        click_url = build_ntfy_click_url(
            alert,
            self.ntfy_click_url_detected if stage == "detected" else self.ntfy_click_url_completed,
            stage,
            prefer_recording_link=self.ntfy_completed_direct_recording_link,
        )
        if click_url:
            headers["Click"] = click_url

        request = urllib.request.Request(
            publish_url,
            data=message.encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            status = getattr(response, "status", 200)
            if int(status) >= 400:
                raise RuntimeError(f"ntfy returned HTTP {status}")
        self._add_activity("ntfy sent", f"{title} -> {topic}")

    def _priority_for_alert(self, alert: dict[str, Any]) -> str:
        category = classify_ntfy_alert_type(alert)
        if category == "warning":
            return self.ntfy_priority_warning
        if category == "watch":
            return self.ntfy_priority_watch
        if category == "advisory":
            return self.ntfy_priority_advisory
        if category == "test":
            return self.ntfy_priority_test
        return self.ntfy_priority_other


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_recording_name(parsed: dict[str, Any], record_id: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    event_code = sanitize_part(parsed.get("eventCode", "evt"))
    sender = sanitize_part(parsed.get("sender", "sender"))
    return f"{timestamp}-{event_code}-{sender}-{record_id[:8]}.wav"


def build_transcript_state(
    status: str,
    *,
    model: str,
    text: str = "",
    language: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "text": text,
        "language": language,
        "model": sanitize_transcription_model(model),
        "error": error,
        "updatedAt": now_iso(),
    }


def build_transcript_markup(transcript: dict[str, Any] | None) -> str:
    if not transcript:
        return ""

    status = str(transcript.get("status") or "")
    text = escape(str(transcript.get("text") or ""))
    model = escape(str(transcript.get("model") or TRANSCRIPTION_DEFAULT_MODEL))
    language = escape(str(transcript.get("language") or "en"))
    error_text = escape(str(transcript.get("error") or ""))

    if status == "disabled":
        body = "<div class=\"recording-status\">Transcript capture is disabled for this server.</div>"
    elif status == "waiting":
        body = "<div class=\"recording-status\">Transcript will start after the recording is finalized.</div>"
    elif status == "pending":
        body = f"<div class=\"recording-status\">Transcribing recording with {model}. This alert will update when the transcript is ready.</div>"
    elif status == "error":
        body = f"<div class=\"recording-status\">Transcript failed: {error_text or 'Unknown error'}</div>"
    else:
        body = (
            f"<div class=\"transcript-text\">{text or 'No spoken transcript could be recognized.'}</div>"
            f"<div class=\"muted\">Language {language} | Model {model}</div>"
        )

    return f"<div class=\"recording-block\"><span>Transcript</span>{body}</div>"


def sanitize_part(value: str) -> str:
    return "".join(char if char.isalnum() else "-" for char in value).strip("-")[:32] or "item"


def sanitize_transcription_model(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in TRANSCRIPTION_ALLOWED_MODELS:
        return normalized
    return TRANSCRIPTION_DEFAULT_MODEL


def unique_ints(values: list[int]) -> list[int]:
    seen: set[int] = set()
    ordered: list[int] = []
    for value in values:
        if value <= 0 or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def sanitize_base_url(value: str) -> str:
    candidate = str(value).strip().rstrip("/")
    if not candidate:
        return ""
    parsed = urllib.parse.urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return candidate


def sanitize_ntfy_priority(value: str) -> str:
    normalized = str(value).strip().lower()
    if normalized in {"max", "urgent"}:
        return "urgent"
    if normalized in {"high", "default", "low", "min"}:
        return normalized
    return NTFY_DEFAULT_PRIORITY


def normalize_tag_list(value: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw_tag in str(value).replace(";", ",").split(","):
        tag = raw_tag.strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        ordered.append(tag)
    return ordered


def classify_ntfy_alert_type(alert: dict[str, Any]) -> str:
    event_code = str(alert.get("eventCode") or "").upper()
    event_label = str(alert.get("eventLabel") or "").strip().lower()

    if event_code in {"RWT", "RMT", "NPT", "DMO", "EAN", "EAT"} or "test" in event_label or "demo" in event_label:
        return "test"
    if "warning" in event_label:
        return "warning"
    if "watch" in event_label:
        return "watch"
    if "advisory" in event_label or "statement" in event_label:
        return "advisory"
    return "other"


def build_ntfy_title(alert: dict[str, Any], stage: str) -> str:
    event_label = str(alert.get("eventLabel") or "SAME Alert")
    stage_label = "Detected" if stage == "detected" else "Recording Saved"
    return f"{stage_label}: {event_label}"


def build_ntfy_message(alert: dict[str, Any], stage: str) -> str:
    lines = [
        str(alert.get("rawHeader") or ""),
        f"Event: {alert.get('eventLabel') or alert.get('eventCode') or 'Unknown'}",
        f"Sender: {alert.get('sender') or alert.get('sourceLabel') or 'Unknown'}",
    ]
    locations = format_ntfy_locations(alert.get("locations") or [])
    if locations:
        lines.append(f"Locations: {locations}")
    issued = alert.get("issued", {}).get("display") or alert.get("detectedAt") or "Unknown"
    lines.append(f"Issued: {issued}")
    lines.append(f"Valid For: {alert.get('durationText') or 'Unknown'}")
    lines.append(f"Stage: {'Alert detected, recording in progress' if stage == 'detected' else 'Recording completed'}")
    recording = alert.get("recording") or {}
    if stage == "completed" and recording.get("url"):
        lines.append(f"Recording: {recording.get('durationText') or 'saved'} ({recording.get('endReason') or 'complete'})")
    return "\n".join(line for line in lines if line)


def format_ntfy_locations(locations: list[dict[str, Any]]) -> str:
    labels = []
    for location in locations[:6]:
        label = location.get("locationLabel")
        if label:
            labels.append(f"{location.get('partitionLabel', 'Area')}, {label}")
        else:
            labels.append(
                f"{location.get('partitionLabel', 'Area')}, {location.get('stateLabel', 'Unknown state')}, county {location.get('countyCode', '---')}"
            )
    if len(locations) > 6:
        labels.append(f"+{len(locations) - 6} more")
    return "; ".join(labels)


def build_ntfy_click_url(
    alert: dict[str, Any],
    click_base_url: str,
    stage: str,
    *,
    prefer_recording_link: bool,
) -> str:
    base_url = sanitize_base_url(click_base_url)
    if not base_url:
        return ""
    recording = alert.get("recording") or {}
    recording_url = recording.get("url")
    if stage == "completed" and prefer_recording_link and recording_url:
        return f"{base_url}{recording_url}"
    return f"{base_url}/"


def write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())


def format_seconds(total_seconds: float) -> str:
    seconds = int(round(total_seconds))
    minutes, seconds = divmod(seconds, 60)
    if minutes == 0:
        return f"{seconds}s"
    return f"{minutes}m {seconds:02d}s"


def build_live_wav_header(sample_rate: int) -> bytes:
    data_size = 0x7FFFFFFF
    byte_rate = sample_rate * 2
    block_align = 2
    riff_size = min(0x7FFFFFFF, 36 + data_size)
    return (
        b"RIFF"
        + riff_size.to_bytes(4, "little", signed=False)
        + b"WAVE"
        + b"fmt "
        + (16).to_bytes(4, "little", signed=False)
        + (1).to_bytes(2, "little", signed=False)
        + (1).to_bytes(2, "little", signed=False)
        + sample_rate.to_bytes(4, "little", signed=False)
        + byte_rate.to_bytes(4, "little", signed=False)
        + block_align.to_bytes(2, "little", signed=False)
        + (16).to_bytes(2, "little", signed=False)
        + b"data"
        + data_size.to_bytes(4, "little", signed=False)
    )


def format_raw_bursts(alert: dict[str, Any]) -> str:
    bursts = alert.get("rawBursts") or []
    if not bursts:
        return str(alert.get("rawHeader") or "")
    return "\n".join(
        f"{index + 1}. {str(burst.get('kind') or 'burst').upper()}: {str(burst.get('rawText') or '')}"
        for index, burst in enumerate(bursts)
    )
