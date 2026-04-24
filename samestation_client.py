from __future__ import annotations

import argparse
import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from samestation_distribution import load_runtime_config, save_runtime_config
from same_paths import app_root


WINDOW_TITLE = "SAMEStation Client"
WINDOW_WIDTH = 1360
WINDOW_HEIGHT = 920
DEFAULT_SERVER_URL = "http://127.0.0.1:8000"
CLIENT_CONFIG_DIR = app_root()


def client_user_config_dir() -> Path:
    local_app_data = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return local_app_data / "SAMEStation Client"

CLIENT_HTML = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>SAMEStation Client</title>
    <style>
      :root {
        color-scheme: light;
        --bg: #f5f1e7;
        --panel: #fffaf1;
        --panel-border: #d8cfbf;
        --text: #172026;
        --muted: #5d6d73;
        --accent: #b64926;
        --accent-dark: #93391c;
        --soft: #efe5d4;
        --ok: #245f45;
        --warn: #8b5d18;
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        font-family: "Segoe UI", Tahoma, sans-serif;
        background: linear-gradient(180deg, #f7f4ed 0%, var(--bg) 100%);
        color: var(--text);
      }
      .app {
        min-height: 100vh;
        display: grid;
        grid-template-rows: auto auto 1fr;
      }
      .hero {
        padding: 22px 24px 14px;
      }
      .hero h1 {
        margin: 0;
        font-size: 32px;
      }
      .hero p {
        margin: 8px 0 0;
        color: var(--muted);
      }
      .connect {
        margin: 0 24px 18px;
        background: var(--panel);
        border: 1px solid var(--panel-border);
        border-radius: 16px;
        padding: 16px;
        display: grid;
        gap: 12px;
      }
      .connect-row {
        display: grid;
        grid-template-columns: 1fr auto auto;
        gap: 10px;
      }
      input, button, select {
        font: inherit;
      }
      input {
        width: 100%;
        border: 1px solid #cfc3b0;
        border-radius: 10px;
        padding: 11px 12px;
        background: white;
      }
      button {
        border: 0;
        border-radius: 999px;
        padding: 11px 16px;
        background: var(--accent);
        color: white;
        cursor: pointer;
      }
      button.secondary {
        background: #d9ccba;
        color: var(--text);
      }
      .status-line {
        color: var(--muted);
        min-height: 20px;
      }
      .discovery {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
      }
      .chip {
        border: 1px solid #cbbda8;
        background: #f7f1e7;
        border-radius: 999px;
        padding: 8px 12px;
        cursor: pointer;
      }
      .dashboard {
        padding: 0 24px 24px;
        display: grid;
        grid-template-columns: 340px 1fr;
        gap: 18px;
      }
      .card {
        background: var(--panel);
        border: 1px solid var(--panel-border);
        border-radius: 16px;
        padding: 16px;
      }
      .card h2 {
        margin: 0 0 10px;
        font-size: 18px;
      }
      .stack {
        display: grid;
        gap: 18px;
        align-content: start;
      }
      .meta-grid {
        display: grid;
        grid-template-columns: 1fr;
        gap: 10px;
      }
      .meta-grid .label {
        color: var(--muted);
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
      }
      .pill {
        display: inline-flex;
        padding: 6px 10px;
        border-radius: 999px;
        background: #e6f0e8;
        color: var(--ok);
        font-size: 12px;
        font-weight: 600;
      }
      .pill.warn {
        background: #f3ead6;
        color: var(--warn);
      }
      .alerts {
        display: grid;
        gap: 14px;
      }
      .alert-card {
        border: 1px solid #dccfbf;
        border-radius: 14px;
        padding: 16px;
        background: white;
      }
      .alert-head {
        display: flex;
        justify-content: space-between;
        gap: 16px;
        align-items: start;
      }
      .alert-title {
        font-size: 19px;
        font-weight: 700;
      }
      .alert-meta {
        margin-top: 4px;
        color: var(--muted);
      }
      .alert-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 12px;
        margin-top: 14px;
      }
      .alert-grid span {
        display: block;
        color: var(--muted);
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        margin-bottom: 4px;
      }
      .recording-block {
        margin-top: 16px;
        padding-top: 14px;
        border-top: 1px solid #ede3d4;
      }
      audio {
        width: 100%;
        margin-top: 8px;
      }
      .empty {
        color: var(--muted);
      }
      @media (max-width: 980px) {
        .dashboard {
          grid-template-columns: 1fr;
        }
        .connect-row {
          grid-template-columns: 1fr;
        }
        .alert-grid {
          grid-template-columns: 1fr;
        }
      }
    </style>
  </head>
  <body>
    <div class="app">
      <div class="hero">
        <h1>SAMEStation Client</h1>
        <p>Native client for alerts, recordings, server health, RSS, and connection management.</p>
      </div>
      <div class="connect">
        <div class="connect-row">
          <input id="server-url" placeholder="http://127.0.0.1:8000" />
          <button id="connect">Connect</button>
          <button id="discover" class="secondary">Discover</button>
        </div>
        <div id="status-line" class="status-line">Ready.</div>
        <div id="discovery" class="discovery"></div>
      </div>
      <div class="dashboard">
        <div class="stack">
          <section class="card">
            <h2>Server Status</h2>
            <div class="meta-grid" id="server-status"></div>
          </section>
          <section class="card">
            <h2>Connection</h2>
            <div class="meta-grid" id="connection-status"></div>
          </section>
        </div>
        <section class="card">
          <h2>Decoded Alerts</h2>
          <div id="alerts" class="alerts"><div class="empty">Connect to a SAMEStation server to load alerts.</div></div>
        </section>
      </div>
    </div>
    <script>
      const elements = {
        serverUrl: document.getElementById("server-url"),
        connect: document.getElementById("connect"),
        discover: document.getElementById("discover"),
        statusLine: document.getElementById("status-line"),
        discovery: document.getElementById("discovery"),
        serverStatus: document.getElementById("server-status"),
        connectionStatus: document.getElementById("connection-status"),
        alerts: document.getElementById("alerts"),
      };

      const state = {
        serverUrl: "",
        refreshTimer: null,
      };

      function escapeHtml(value) {
        return String(value ?? "")
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;")
          .replace(/'/g, "&#39;");
      }

      function setStatus(text) {
        elements.statusLine.textContent = text;
      }

      function renderMeta(target, rows) {
        target.innerHTML = rows
          .map((row) => `<div><div class="label">${escapeHtml(row.label)}</div><div>${escapeHtml(row.value)}</div></div>`)
          .join("");
      }

      function renderAlerts(alerts) {
        if (!alerts.length) {
          elements.alerts.innerHTML = '<div class="empty">No alerts are currently available from this server.</div>';
          return;
        }
        elements.alerts.innerHTML = alerts
          .map((alert) => {
            const confidencePercent = `${Math.round(Number(alert.confidence || 0) * 100)}% confidence`;
            const locations = (alert.locations || [])
              .map((location) => {
                if (location.locationLabel) {
                  return `${location.partitionLabel}, ${location.locationLabel}`;
                }
                return location.code || "Unknown location";
              })
              .join("; ") || "No location codes parsed";
            const recordingMarkup = alert.recording?.absoluteUrl
              ? `
                  <div class="recording-block">
                    <div class="label">Recording</div>
                    <audio controls preload="none" src="${escapeHtml(alert.recording.absoluteUrl)}"></audio>
                  </div>
                `
              : alert.recording?.status === "recording"
                ? '<div class="recording-block"><div class="label">Recording</div><div>Capture in progress.</div></div>'
                : "";
            const statusClass = alert.recording?.status === "recording" ? "pill warn" : "pill";
            const statusLabel = alert.recording?.status === "recording"
              ? "Live capture"
              : `${alert.repeatCount || 1} repeat${Number(alert.repeatCount || 1) === 1 ? "" : "s"}`;
            return `
              <article class="alert-card">
                <div class="alert-head">
                  <div>
                    <div class="alert-title">${escapeHtml(alert.eventLabel || "Decoded header")} <span class="label">(${escapeHtml(alert.eventCode || "---")})</span></div>
                    <div class="alert-meta">${escapeHtml(alert.originatorLabel || "Unknown originator")} from ${escapeHtml(alert.sender || alert.sourceLabel || "Unknown source")}</div>
                  </div>
                  <div class="${statusClass}">${escapeHtml(statusLabel)} | ${escapeHtml(confidencePercent)}</div>
                </div>
                <div class="alert-grid">
                  <div><span>Issued</span>${escapeHtml(alert.issued?.display || alert.detectedAt || "Unknown")}</div>
                  <div><span>Sender</span>${escapeHtml(alert.sender || "Unknown")}</div>
                  <div><span>Detected Via</span>${escapeHtml(alert.detectionMethodLabel || "Unknown")}</div>
                  <div><span>Source</span>${escapeHtml(alert.sourceLabel || "Unknown")}</div>
                  <div><span>Duration</span>${escapeHtml(alert.durationText || "Unknown")}</div>
                  <div><span>Locations</span>${escapeHtml(locations)}</div>
                </div>
                ${recordingMarkup}
              </article>
            `;
          })
          .join("");
      }

      async function applySnapshot(snapshot) {
        state.serverUrl = snapshot.serverUrl || "";
        elements.serverUrl.value = state.serverUrl;
        renderMeta(elements.connectionStatus, [
          { label: "Server URL", value: snapshot.serverUrl || "Not set" },
          { label: "Reachable", value: snapshot.ok ? "Yes" : "No" },
          { label: "RSS Feed", value: snapshot.rssUrl || "Unavailable" },
          { label: "Message", value: snapshot.message || "Ready" },
        ]);
        renderMeta(elements.serverStatus, [
          { label: "Monitor Running", value: snapshot.status?.running ? "Yes" : "No" },
          { label: "Source", value: snapshot.status?.deviceName || snapshot.status?.icecastUrl || "Unknown" },
          { label: "Sample Rate", value: snapshot.status?.sampleRate ? `${snapshot.status.sampleRate} Hz` : "Unknown" },
          { label: "ntfy Alerts", value: snapshot.status?.settings?.ntfyEnabled ? "Enabled" : "Disabled" },
        ]);
        renderAlerts(snapshot.alerts || []);
        setStatus(snapshot.message || "Ready.");
      }

      async function refreshSnapshot() {
        const snapshot = await window.pywebview.api.refresh();
        await applySnapshot(snapshot);
      }

      async function connectToServer() {
        const target = elements.serverUrl.value.trim();
        const snapshot = await window.pywebview.api.connect(target);
        await applySnapshot(snapshot);
      }

      async function discoverServers() {
        setStatus("Scanning your LAN for SAMEStation servers...");
        const servers = await window.pywebview.api.discover_servers();
        if (!servers.length) {
          elements.discovery.innerHTML = '<div class="empty">No SAMEStation servers were found on the default port.</div>';
          setStatus("No SAMEStation servers were found on the default port.");
          return;
        }
        elements.discovery.innerHTML = servers
          .map((server) => `<button class="chip" data-url="${escapeHtml(server.url)}">${escapeHtml(server.label)}</button>`)
          .join("");
        elements.discovery.querySelectorAll("[data-url]").forEach((button) => {
          button.addEventListener("click", async () => {
            elements.serverUrl.value = button.getAttribute("data-url") || "";
            await connectToServer();
          });
        });
        setStatus(`Found ${servers.length} SAMEStation server${servers.length === 1 ? "" : "s"}.`);
      }

      elements.connect.addEventListener("click", connectToServer);
      elements.discover.addEventListener("click", discoverServers);

      window.addEventListener("DOMContentLoaded", async () => {
        const initialState = await window.pywebview.api.get_initial_state();
        await applySnapshot(initialState);
        if (state.refreshTimer) {
          clearInterval(state.refreshTimer);
        }
        state.refreshTimer = setInterval(refreshSnapshot, 3000);
      });
    </script>
  </body>
</html>
"""


def normalize_server_url(raw_url: str | None) -> str:
    value = str(raw_url or "").strip()
    if not value:
        return DEFAULT_SERVER_URL
    if "://" not in value:
        value = f"http://{value}"
    parsed = urllib.parse.urlparse(value)
    scheme = parsed.scheme or "http"
    netloc = parsed.netloc or parsed.path
    path = parsed.path if parsed.netloc else ""
    normalized = urllib.parse.urlunparse((scheme, netloc, path or "", "", "", ""))
    return normalized.rstrip("/")


def fetch_json(url: str, timeout: float = 3.0) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "SAMEStation-Client/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def load_client_config() -> dict[str, Any]:
    user_config = load_runtime_config("client", client_user_config_dir())
    if user_config:
        return user_config
    return load_runtime_config("client", CLIENT_CONFIG_DIR)


def save_client_config(payload: dict[str, Any]) -> None:
    save_runtime_config(client_user_config_dir(), "client", payload)


class ClientApi:
    def __init__(self, default_server_url: str) -> None:
        self.server_url = normalize_server_url(default_server_url)

    def get_initial_state(self) -> dict[str, Any]:
        return self.refresh()

    def connect(self, raw_server_url: str) -> dict[str, Any]:
        self.server_url = normalize_server_url(raw_server_url)
        save_client_config({"serverUrl": self.server_url})
        return self.refresh()

    def refresh(self) -> dict[str, Any]:
        snapshot = {
            "ok": False,
            "serverUrl": self.server_url,
            "message": "Not connected.",
            "alerts": [],
            "status": {},
            "rssUrl": "",
        }
        try:
            health = fetch_json(f"{self.server_url}/api/health")
            status = fetch_json(f"{self.server_url}/api/status")
        except urllib.error.URLError as exc:
            snapshot["message"] = f"Unable to reach {self.server_url}: {exc.reason}"
            return snapshot
        except Exception as exc:  # noqa: BLE001
            snapshot["message"] = f"Unable to load SAMEStation server data: {exc}"
            return snapshot

        alerts = []
        for alert in status.get("alerts") or []:
            normalized = dict(alert)
            recording = dict(normalized.get("recording") or {})
            if recording.get("url"):
                recording["absoluteUrl"] = f"{self.server_url}{recording['url']}"
            normalized["recording"] = recording
            alerts.append(normalized)

        snapshot.update(
            {
                "ok": bool(health.get("ok")),
                "message": "Connected.",
                "alerts": alerts,
                "status": status,
                "rssUrl": f"{self.server_url}/alerts.xml",
            }
        )
        return snapshot

    def discover_servers(self) -> list[dict[str, str]]:
        local_ips = discover_local_ipv4_addresses()
        candidates: list[str] = []
        seen: set[str] = set()
        for ip in local_ips:
            parts = ip.split(".")
            if len(parts) != 4:
                continue
            prefix = ".".join(parts[:3])
            for suffix in range(1, 255):
                candidate = f"{prefix}.{suffix}"
                if candidate in seen:
                    continue
                seen.add(candidate)
                candidates.append(candidate)

        found: list[dict[str, str]] = []
        with ThreadPoolExecutor(max_workers=32) as executor:
            future_map = {
                executor.submit(probe_candidate_server, candidate): candidate
                for candidate in candidates
            }
            for future in as_completed(future_map):
                result = future.result()
                if result is not None:
                    found.append(result)
        found.sort(key=lambda item: item["url"])
        return found


def discover_local_ipv4_addresses() -> list[str]:
    addresses = {"127.0.0.1"}
    try:
        hostname = socket.gethostname()
        infos = socket.getaddrinfo(hostname, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
    except Exception:
        infos = []
    for info in infos:
        address = str(info[4][0]).strip()
        if not address or address.startswith("127.") or address.startswith("169.254."):
            continue
        addresses.add(address)
    return sorted(addresses)


def probe_candidate_server(address: str) -> dict[str, str] | None:
    url = f"http://{address}:8000"
    try:
        payload = fetch_json(f"{url}/api/health", timeout=0.35)
    except Exception:
        return None
    if not payload.get("ok"):
        return None
    return {
        "url": url,
        "label": f"{address}:8000",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SAMEStation Client installed app.")
    parser.add_argument("--server-url", default="", help="Preferred SAMEStation server URL.")
    args = parser.parse_args()

    config = load_client_config()
    default_server_url = normalize_server_url(args.server_url or str(config.get("serverUrl") or DEFAULT_SERVER_URL))
    api = ClientApi(default_server_url)
    import webview

    window = webview.create_window(
        WINDOW_TITLE,
        html=CLIENT_HTML,
        js_api=api,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
    )
    webview.start(gui=None, private_mode=False, storage_path=str(app_root() / "webview-storage"))


if __name__ == "__main__":
    main()
