from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from queue import Empty, SimpleQueue

from samestation_autostart import is_windows_auto_start_enabled, sync_windows_auto_start
from same_paths import app_root
from samestation_runtime import ModeName, format_missing_dependencies, missing_dependencies_for_mode
from samestation_update import (
    UPDATE_CHANNELS,
    check_for_updates,
    current_version_label,
    launch_installer,
    normalize_update_channel,
)


WINDOW_TITLE = "SAMEStation"
CLIENT_WIDTH = 1360
CLIENT_HEIGHT = 920
CONSOLE_WIDTH = 900
CONSOLE_HEIGHT = 620
DEFAULT_PORT = 8000
DEFAULT_SERVER_URL = f"http://127.0.0.1:{DEFAULT_PORT}"
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"
LAUNCHER_SETTINGS_PATH = app_root() / "data" / "launcher-settings.json"

CONSOLE_HTML = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>SAMEStation Server Console</title>
    <style>
      :root {
        color-scheme: dark;
        --bg: #12171a;
        --panel: #1a2327;
        --border: #314247;
        --text: #e7f0f2;
        --muted: #a8babf;
        --accent: #d86b2b;
        --accent-soft: rgba(216, 107, 43, 0.16);
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        background:
          radial-gradient(circle at top right, rgba(216, 107, 43, 0.18), transparent 28%),
          linear-gradient(180deg, #151c1f 0%, var(--bg) 100%);
        color: var(--text);
        font-family: Consolas, "Courier New", monospace;
      }
      .layout {
        display: grid;
        grid-template-rows: auto 1fr auto;
        min-height: 100vh;
      }
      .topbar {
        padding: 18px 20px 10px;
      }
      .title {
        font-size: 26px;
        font-weight: 700;
        margin-bottom: 6px;
      }
      .subtitle {
        color: var(--muted);
        font-size: 14px;
        line-height: 1.5;
      }
      .console {
        margin: 0 20px 18px;
        border: 1px solid var(--border);
        border-radius: 14px;
        background: rgba(12, 17, 19, 0.92);
        overflow: hidden;
        display: grid;
        grid-template-rows: 1fr auto;
      }
      pre {
        margin: 0;
        padding: 16px;
        overflow: auto;
        white-space: pre-wrap;
        word-break: break-word;
        font-size: 13px;
        line-height: 1.45;
      }
      form {
        display: grid;
        grid-template-columns: 84px 1fr auto;
        gap: 10px;
        padding: 12px;
        border-top: 1px solid var(--border);
        background: var(--panel);
      }
      .prompt {
        align-self: center;
        color: #f9a76f;
        font-weight: 700;
      }
      input {
        width: 100%;
        border: 1px solid var(--border);
        background: #11181b;
        color: var(--text);
        border-radius: 10px;
        padding: 10px 12px;
        font: inherit;
      }
      button {
        border: 0;
        border-radius: 999px;
        padding: 10px 16px;
        font: inherit;
        cursor: pointer;
        background: var(--accent);
        color: white;
      }
      .help {
        padding: 0 20px 18px;
        color: var(--muted);
        font-size: 13px;
        line-height: 1.55;
      }
      code {
        background: var(--accent-soft);
        color: #ffbe8b;
        padding: 2px 6px;
        border-radius: 999px;
      }
    </style>
  </head>
  <body>
    <div class="layout">
      <div class="topbar">
        <div class="title">SAMEStation Server Console</div>
        <div class="subtitle" id="summary">Loading server details...</div>
      </div>
      <div class="console">
        <pre id="log"></pre>
        <form id="command-form">
          <div class="prompt">samestation&gt;</div>
          <input id="command" type="text" autocomplete="off" spellcheck="false" />
          <button type="submit">Run</button>
        </form>
      </div>
      <div class="help">Commands: <code>help</code> <code>status</code> <code>devices</code> <code>settings</code> <code>alerts 10</code> <code>start 3 10 180</code> <code>stop</code> <code>clear</code> <code>open</code> <code>shutdown</code></div>
    </div>
    <script>
      const logNode = document.getElementById("log");
      const form = document.getElementById("command-form");
      const commandInput = document.getElementById("command");
      const summaryNode = document.getElementById("summary");

      function appendLines(lines) {
        if (!Array.isArray(lines) || !lines.length) {
          return;
        }
        const stickToBottom = Math.abs(logNode.scrollHeight - logNode.clientHeight - logNode.scrollTop) < 32;
        const prefix = logNode.textContent ? "\\n" : "";
        logNode.textContent += prefix + lines.join("\\n");
        if (stickToBottom) {
          logNode.scrollTop = logNode.scrollHeight;
        }
      }

      async function refreshState() {
        const payload = await window.pywebview.api.read_console_state();
        if (payload.summary) {
          summaryNode.textContent = payload.summary;
        }
        appendLines(payload.lines || []);
      }

      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const rawCommand = commandInput.value.trim();
        if (!rawCommand) {
          return;
        }
        commandInput.value = "";
        await window.pywebview.api.submit_command(rawCommand);
        await refreshState();
      });

      setInterval(refreshState, 300);
      refreshState();
      commandInput.focus();
    </script>
  </body>
</html>
"""


@dataclass
class LaunchSelection:
    mode: ModeName
    server_url: str
    port: int
    auto_start_monitor: bool = False
    auto_start_device_id: int | None = None
    auto_start_pre_roll: int | None = None
    auto_start_max_record: int | None = None
    auto_start_with_windows: bool = False
    update_channel: str = "stable"
    check_updates_on_start: bool = True
    install_updates_on_start: bool = False


class BufferedLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self._queue: SimpleQueue[str] = SimpleQueue()
        self.setFormatter(logging.Formatter(LOG_FORMAT))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._queue.put_nowait(self.format(record))
        except Exception:
            pass

    def drain(self) -> list[str]:
        lines: list[str] = []
        while True:
            try:
                lines.append(self._queue.get_nowait())
            except Empty:
                return lines


class ServerConsoleApi:
    def __init__(self, cli: SAMEStationCli, log_handler: BufferedLogHandler, summary: str, on_shutdown_requested) -> None:
        self.cli = cli
        self.log_handler = log_handler
        self.summary = summary
        self.on_shutdown_requested = on_shutdown_requested

    def read_console_state(self) -> dict[str, object]:
        return {
            "summary": self.summary,
            "lines": self.log_handler.drain(),
        }

    def submit_command(self, raw_command: str) -> dict[str, object]:
        should_stop = self.cli.execute_command(raw_command)
        if should_stop:
            threading.Thread(target=self.on_shutdown_requested, name="samestation-ui-shutdown", daemon=True).start()
        return {"ok": True}


class DesktopRuntime:
    def __init__(self, selection: LaunchSelection) -> None:
        self.selection = selection
        self.context = None
        self.server_thread: threading.Thread | None = None
        self.console_cli = None
        self.console_window = None
        self.app_window = None
        self.log_handler: BufferedLogHandler | None = None
        self._shutdown_lock = threading.Lock()
        self._shutdown_started = False
        self._webview = None
        self._monitor = None
        self._samestation_cli_cls = None
        self._configure_logging = None
        self._create_server_context = None
        self._shutdown_server_context = None

    def prepare(self) -> None:
        self._load_runtime_components()
        self._configure_logging()
        if self.selection.mode in {"server", "both"}:
            self._start_local_server()
            if self.selection.auto_start_monitor:
                self._auto_start_server_monitor()
            self._create_console_window()
        if self.selection.mode == "client":
            self._create_app_window(self.selection.server_url, title=f"{WINDOW_TITLE} Client")
        if self.selection.mode == "both":
            self._create_app_window(self.local_server_url, title=WINDOW_TITLE)

    @property
    def local_server_url(self) -> str:
        if self.context is None:
            raise RuntimeError("Local server has not been started.")
        return f"http://127.0.0.1:{self.context.port}"

    def start_event_loop(self) -> None:
        self._load_runtime_components()
        self._webview.start(private_mode=False, storage_path=str(app_root() / "webview-storage"))

    def _load_runtime_components(self) -> None:
        if self._webview is not None:
            return
        import webview as webview_module

        from app import MONITOR, SAMEStationCli, configure_logging, create_server_context, shutdown_server_context

        self._webview = webview_module
        self._monitor = MONITOR
        self._samestation_cli_cls = SAMEStationCli
        self._configure_logging = configure_logging
        self._create_server_context = create_server_context
        self._shutdown_server_context = shutdown_server_context

    def _start_local_server(self) -> None:
        self.context = self._create_server_context(port=self.selection.port, enable_cli=False)
        self.server_thread = threading.Thread(
            target=self.context.server.serve_forever,
            name="samestation-http",
            daemon=True,
        )
        self.server_thread.start()
        logging.getLogger("samestation").info("SAMEStation listening on %s", self.local_server_url)

    def _auto_start_server_monitor(self) -> None:
        settings = self._monitor.get_settings()
        device_id = self.selection.auto_start_device_id
        if device_id is None:
            saved_device = settings.get("deviceId")
            device_id = int(saved_device) if saved_device is not None else None
        if device_id is None or int(device_id) < 0:
            raise RuntimeError("Auto-start monitor requested but no server audio device is configured.")

        pre_roll_seconds = (
            self.selection.auto_start_pre_roll
            if self.selection.auto_start_pre_roll is not None
            else int(settings.get("preRollSeconds") or 10)
        )
        max_record_seconds = (
            self.selection.auto_start_max_record
            if self.selection.auto_start_max_record is not None
            else int(settings.get("maxRecordSeconds") or 180)
        )

        self._monitor.start(
            int(device_id),
            pre_roll_seconds=int(pre_roll_seconds),
            max_record_seconds=int(max_record_seconds),
        )
        logging.getLogger("samestation").info(
            "Auto-started monitor on device=%s preRoll=%s maxRecord=%s",
            device_id,
            pre_roll_seconds,
            max_record_seconds,
        )

    def _create_console_window(self) -> None:
        if self.context is None:
            raise RuntimeError("Server context missing.")
        self.log_handler = BufferedLogHandler()
        logging.getLogger().addHandler(self.log_handler)
        self.console_cli = self._samestation_cli_cls(self.context.server, self._monitor, self.context.port)
        self.console_cli.execute_command("help")
        summary = f"Local server ready at {self.local_server_url}. Close this window or run shutdown to stop the server."
        api = ServerConsoleApi(self.console_cli, self.log_handler, summary, self.shutdown)
        self.console_window = self._webview.create_window(
            f"{WINDOW_TITLE} Server",
            html=CONSOLE_HTML,
            js_api=api,
            width=CONSOLE_WIDTH,
            height=CONSOLE_HEIGHT,
            min_size=(760, 460),
        )
        self.console_window.events.closed += lambda *_args: self.shutdown()

    def _create_app_window(self, url: str, *, title: str) -> None:
        self.app_window = self._webview.create_window(
            title,
            url,
            width=CLIENT_WIDTH,
            height=CLIENT_HEIGHT,
            min_size=(980, 720),
            text_select=True,
        )

    def shutdown(self) -> None:
        with self._shutdown_lock:
            if self._shutdown_started:
                return
            self._shutdown_started = True

        if self.console_window is not None:
            try:
                self.console_window.destroy()
            except Exception:
                pass

        if self.app_window is not None:
            try:
                self.app_window.destroy()
            except Exception:
                pass

        if self.context is not None:
            try:
                self._shutdown_server_context(self.context)
            except Exception:
                pass

        if self.log_handler is not None:
            try:
                logging.getLogger().removeHandler(self.log_handler)
            except Exception:
                pass


def normalize_mode(raw_mode: str) -> ModeName:
    value = (raw_mode or "").strip().lower()
    if value not in {"server", "client", "both"}:
        raise ValueError("Launch mode must be server, client, or both.")
    return value


def normalize_server_url(raw_url: str) -> str:
    value = (raw_url or "").strip()
    if not value:
        return DEFAULT_SERVER_URL
    if "://" not in value:
        value = f"http://{value}"
    return value.rstrip("/")


def ensure_launcher_settings_dir() -> None:
    LAUNCHER_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)


def load_launcher_settings() -> dict[str, object]:
    if not LAUNCHER_SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(LAUNCHER_SETTINGS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_launcher_settings(selection: LaunchSelection) -> None:
    ensure_launcher_settings_dir()
    payload = {
        "mode": selection.mode,
        "serverUrl": selection.server_url,
        "port": selection.port,
        "autoStartMonitor": selection.auto_start_monitor,
        "autoStartDeviceId": selection.auto_start_device_id,
        "autoStartPreRoll": selection.auto_start_pre_roll,
        "autoStartMaxRecord": selection.auto_start_max_record,
        "autoStartWithWindows": selection.auto_start_with_windows,
        "updateChannel": selection.update_channel,
        "checkUpdatesOnStart": selection.check_updates_on_start,
        "installUpdatesOnStart": selection.install_updates_on_start,
    }
    LAUNCHER_SETTINGS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_saved_selection() -> LaunchSelection:
    settings = load_launcher_settings()
    try:
        mode = normalize_mode(str(settings.get("mode") or "both"))
    except ValueError:
        mode = "both"
    selection = LaunchSelection(
        mode=mode,
        server_url=normalize_server_url(str(settings.get("serverUrl") or DEFAULT_SERVER_URL)),
        port=int(settings.get("port") or DEFAULT_PORT),
        auto_start_monitor=bool(settings.get("autoStartMonitor", False)),
        auto_start_device_id=(
            int(settings["autoStartDeviceId"])
            if settings.get("autoStartDeviceId") not in {None, ""}
            else None
        ),
        auto_start_pre_roll=(
            int(settings["autoStartPreRoll"])
            if settings.get("autoStartPreRoll") not in {None, ""}
            else None
        ),
        auto_start_max_record=(
            int(settings["autoStartMaxRecord"])
            if settings.get("autoStartMaxRecord") not in {None, ""}
            else None
        ),
        auto_start_with_windows=bool(settings.get("autoStartWithWindows", False)),
        update_channel=normalize_update_channel(str(settings.get("updateChannel") or "stable")),
        check_updates_on_start=bool(settings.get("checkUpdatesOnStart", True)),
        install_updates_on_start=bool(settings.get("installUpdatesOnStart", False)),
    )
    if selection.install_updates_on_start:
        selection.check_updates_on_start = True
    return selection


def choose_launch_selection(default_selection: LaunchSelection) -> LaunchSelection | None:
    import tkinter as tk
    from tkinter import ttk

    result: dict[str, str | bool] = {
        "mode": default_selection.mode,
        "server_url": default_selection.server_url,
        "auto_start_monitor": default_selection.auto_start_monitor,
        "auto_start_with_windows": default_selection.auto_start_with_windows,
        "update_channel": default_selection.update_channel,
        "check_updates_on_start": default_selection.check_updates_on_start,
        "install_updates_on_start": default_selection.install_updates_on_start,
        "confirmed": False,
    }
    update_state = {"running": False}

    root = tk.Tk()
    root.title("Launch SAMEStation")
    root.geometry("720x860")
    root.minsize(680, 780)
    root.configure(bg="#f4f1e8")
    root.resizable(True, True)

    outer = ttk.Frame(root, padding=22)
    outer.pack(fill="both", expand=True)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    ttk.Label(outer, text="Launch SAMEStation", font=("Segoe UI", 18, "bold")).pack(anchor="w")
    ttk.Label(
        outer,
        text=f"Pick whether this copy should act as the local server, a client against another SAMEStation server, or both at once. Installed build: {current_version_label()}",
        wraplength=620,
    ).pack(anchor="w", pady=(8, 16))

    mode_var = tk.StringVar(value=default_selection.mode)
    server_url_var = tk.StringVar(value=default_selection.server_url)
    auto_start_monitor_var = tk.BooleanVar(value=default_selection.auto_start_monitor)
    auto_start_with_windows_var = tk.BooleanVar(value=default_selection.auto_start_with_windows)
    update_channel_var = tk.StringVar(value=default_selection.update_channel)
    check_updates_on_start_var = tk.BooleanVar(value=default_selection.check_updates_on_start)
    install_updates_on_start_var = tk.BooleanVar(value=default_selection.install_updates_on_start)
    error_var = tk.StringVar(value="")
    update_var = tk.StringVar(value="Choose a branch channel, then check for updates or open the installer.")

    options = [
        ("server", "Server", "Run the local SAMEStation server and show the server console window only."),
        ("client", "Client", "Open the desktop web app against an existing SAMEStation server URL."),
        ("both", "Both", "Run the local server, show the server console, and open the SAMEStation client window."),
    ]

    cards = ttk.Frame(outer)
    cards.pack(fill="x")

    for value, title, copy in options:
        frame = ttk.Frame(cards, padding=(12, 10))
        frame.pack(fill="x", pady=4)
        ttk.Radiobutton(frame, text=title, value=value, variable=mode_var).pack(anchor="w")
        ttk.Label(frame, text=copy, wraplength=470).pack(anchor="w", padx=(24, 0), pady=(4, 0))

    field = ttk.Frame(outer)
    field.pack(fill="x", pady=(18, 0))
    ttk.Label(field, text="Client Server URL").pack(anchor="w")
    server_url_entry = ttk.Entry(field, textvariable=server_url_var)
    server_url_entry.pack(fill="x", pady=(6, 0))

    extras = ttk.Frame(outer)
    extras.pack(fill="x", pady=(16, 0))
    ttk.Checkbutton(
        extras,
        text="Auto-start the server monitor after launch",
        variable=auto_start_monitor_var,
    ).pack(anchor="w")
    ttk.Checkbutton(
        extras,
        text="Start SAMEStation automatically when you sign in",
        variable=auto_start_with_windows_var,
    ).pack(anchor="w", pady=(8, 0))

    update_frame = ttk.LabelFrame(outer, text="Updates", padding=14)
    update_frame.pack(fill="x", pady=(18, 0))
    ttk.Label(
        update_frame,
        text="Use the bundled installer to move between stable and test builds. The launcher can also check for updates each time it opens and hand off to the installer automatically.",
        wraplength=600,
    ).pack(anchor="w")
    channel_row = ttk.Frame(update_frame)
    channel_row.pack(fill="x", pady=(10, 0))
    ttk.Label(channel_row, text="Update Branch").pack(anchor="w")
    update_channel_box = ttk.Combobox(
        channel_row,
        textvariable=update_channel_var,
        state="readonly",
        values=[channel for channel in UPDATE_CHANNELS],
    )
    update_channel_box.pack(fill="x", pady=(6, 0))
    ttk.Checkbutton(
        update_frame,
        text="Check for updates when the launcher opens",
        variable=check_updates_on_start_var,
    ).pack(anchor="w", pady=(12, 0))
    ttk.Checkbutton(
        update_frame,
        text="Install updates automatically on launcher start",
        variable=install_updates_on_start_var,
    ).pack(anchor="w", pady=(8, 0))
    ttk.Label(update_frame, textvariable=update_var, wraplength=600, foreground="#39454a").pack(anchor="w", pady=(12, 0))
    update_actions = ttk.Frame(update_frame)
    update_actions.pack(anchor="w", pady=(12, 0))

    def sync_field_state(*_args) -> None:
        state = "normal" if mode_var.get() == "client" else "disabled"
        server_url_entry.configure(state=state)
        monitor_state = "disabled" if mode_var.get() == "client" else "normal"
        if mode_var.get() == "client":
            auto_start_monitor_var.set(False)
        for child in extras.winfo_children():
            label = str(child.cget("text"))
            if "server monitor" in label:
                child.configure(state=monitor_state)
        if install_updates_on_start_var.get():
            check_updates_on_start_var.set(True)

    def apply_update_check_result(message: str, *, auto_install: bool) -> None:
        update_state["running"] = False
        check_button.configure(state="normal")
        update_button.configure(state="normal")
        update_var.set(message)
        if auto_install:
            open_installer(install_now=True)

    def run_update_check(*, auto_install: bool = False) -> None:
        if update_state["running"]:
            return
        error_var.set("")
        update_state["running"] = True
        update_var.set("Checking GitHub for the selected branch channel...")
        check_button.configure(state="disabled")
        update_button.configure(state="disabled")
        channel = normalize_update_channel(update_channel_var.get())

        def worker() -> None:
            payload = check_for_updates(channel)

            def finish() -> None:
                try:
                    apply_update_check_result(payload.message, auto_install=auto_install and payload.available and payload.release is not None)
                except tk.TclError:
                    pass

            try:
                root.after(0, finish)
            except tk.TclError:
                pass

        threading.Thread(target=worker, name="samestation-update-check", daemon=True).start()

    def open_installer(*, install_now: bool) -> None:
        try:
            launch_installer(
                channel=normalize_update_channel(update_channel_var.get()),
                mode=normalize_mode(mode_var.get()),
                install_now=install_now,
                auto_install_dependencies=True,
                start_app_after=True,
                wait_for_pids=[os.getpid()],
            )
            root.destroy()
        except Exception as exc:  # noqa: BLE001
            update_state["running"] = False
            check_button.configure(state="normal")
            update_button.configure(state="normal")
            error_var.set(str(exc))

    def sync_update_toggles(*_args) -> None:
        if install_updates_on_start_var.get():
            check_updates_on_start_var.set(True)

    mode_var.trace_add("write", sync_field_state)
    install_updates_on_start_var.trace_add("write", sync_update_toggles)
    check_button = ttk.Button(update_actions, text="Check Now", command=lambda: run_update_check(auto_install=False))
    check_button.pack(side="left")
    update_button = ttk.Button(update_actions, text="Update", command=lambda: open_installer(install_now=False))
    update_button.pack(side="left", padx=(10, 0))
    sync_field_state()

    ttk.Label(outer, textvariable=error_var, foreground="#a32117", wraplength=620).pack(anchor="w", pady=(12, 0))

    ttk.Frame(outer).pack(fill="both", expand=True)

    actions = tk.Frame(root, bg="#efe5d4", padx=18, pady=14, highlightbackground="#d5c8af", highlightthickness=1)
    actions.pack(fill="x", side="bottom")

    def cancel() -> None:
        root.destroy()

    def launch() -> None:
        try:
            result["mode"] = normalize_mode(mode_var.get())
            result["server_url"] = normalize_server_url(server_url_var.get())
            result["auto_start_monitor"] = bool(auto_start_monitor_var.get())
            result["auto_start_with_windows"] = bool(auto_start_with_windows_var.get())
            result["update_channel"] = normalize_update_channel(update_channel_var.get())
            result["check_updates_on_start"] = bool(check_updates_on_start_var.get())
            result["install_updates_on_start"] = bool(install_updates_on_start_var.get())
            missing = missing_dependencies_for_mode(result["mode"])
            if missing:
                error_var.set(f"{format_missing_dependencies(missing)} Use Update to repair this install profile before launching.")
                return
            result["confirmed"] = True
            root.destroy()
        except ValueError as exc:
            error_var.set(str(exc))

    tk.Button(
        actions,
        text="Cancel",
        command=cancel,
        width=12,
        padx=10,
        pady=6,
        bg="#ddd2bf",
        activebackground="#d2c4ae",
        relief="raised",
    ).pack(side="right")
    tk.Button(
        actions,
        text="Start SAMEStation",
        command=launch,
        width=18,
        padx=10,
        pady=6,
        bg="#b64926",
        fg="white",
        activebackground="#983c1e",
        activeforeground="white",
        relief="raised",
    ).pack(side="right", padx=(0, 10))

    root.bind("<Return>", lambda _event: launch())

    root.protocol("WM_DELETE_WINDOW", cancel)
    if default_selection.check_updates_on_start:
        root.after(250, lambda: run_update_check(auto_install=bool(install_updates_on_start_var.get())))
    root.mainloop()

    if not result["confirmed"]:
        return None
    return LaunchSelection(
        mode=result["mode"],
        server_url=result["server_url"],
        port=default_selection.port,
        auto_start_monitor=bool(result["auto_start_monitor"]),
        auto_start_with_windows=bool(result["auto_start_with_windows"]),
        auto_start_device_id=default_selection.auto_start_device_id,
        auto_start_pre_roll=default_selection.auto_start_pre_roll,
        auto_start_max_record=default_selection.auto_start_max_record,
        update_channel=str(result["update_channel"]),
        check_updates_on_start=bool(result["check_updates_on_start"]),
        install_updates_on_start=bool(result["install_updates_on_start"]),
    )


def build_selection(args: argparse.Namespace) -> LaunchSelection | None:
    saved_selection = load_saved_selection()
    saved_selection.auto_start_with_windows = is_windows_auto_start_enabled()
    auto_start_monitor = saved_selection.auto_start_monitor

    flag_mode: ModeName | None = None
    if getattr(args, "server", False):
        flag_mode = "server"
    elif getattr(args, "client", False):
        flag_mode = "client"
    elif getattr(args, "both", False):
        flag_mode = "both"

    if flag_mode is not None and args.mode is not None:
        explicit_mode = normalize_mode(args.mode)
        if explicit_mode != flag_mode:
            raise ValueError("Do not mix --mode with conflicting --server/--client/--both flags.")

    mode = flag_mode or (normalize_mode(args.mode) if args.mode else None)

    if mode is None:
        selection = choose_launch_selection(saved_selection)
        if selection is None:
            return None
        selection.port = int(args.port)
        return selection

    if mode == "client" and args.auto_start_monitor:
        raise ValueError("Auto-start monitor is only available in --server or --both mode.")
    if mode == "client" and any(
        value is not None
        for value in (args.device_id, args.pre_roll, args.max_record)
    ):
        raise ValueError("Monitor options are only available in --server or --both mode.")

    if args.auto_start_monitor:
        auto_start_monitor = True
    elif mode == "client":
        auto_start_monitor = False

    return LaunchSelection(
        mode=mode,
        server_url=normalize_server_url(args.server_url),
        port=int(args.port),
        auto_start_monitor=auto_start_monitor,
        auto_start_device_id=args.device_id if args.device_id is not None else saved_selection.auto_start_device_id,
        auto_start_pre_roll=args.pre_roll if args.pre_roll is not None else saved_selection.auto_start_pre_roll,
        auto_start_max_record=args.max_record if args.max_record is not None else saved_selection.auto_start_max_record,
        auto_start_with_windows=saved_selection.auto_start_with_windows,
        update_channel=saved_selection.update_channel,
        check_updates_on_start=saved_selection.check_updates_on_start,
        install_updates_on_start=saved_selection.install_updates_on_start,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch the SAMEStation desktop app.")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--server", action="store_true", help="Launch the local SAMEStation server and server console only.")
    mode_group.add_argument("--client", action="store_true", help="Launch the SAMEStation client window against an existing server URL.")
    mode_group.add_argument("--both", action="store_true", help="Launch the local server, server console, and client window together.")
    parser.add_argument("--mode", choices=("server", "client", "both"), help="Legacy launch mode option. If omitted and no launch flag is provided, show the mode chooser.")
    parser.add_argument("--server-url", default=DEFAULT_SERVER_URL, help="Server URL for client mode.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Local port to bind in server or both mode.")
    parser.add_argument("--auto-start-monitor", action="store_true", help="Automatically start the server audio monitor in server or both mode.")
    parser.add_argument("--device-id", type=int, help="Audio input device ID to use when auto-starting the monitor. Defaults to the saved device.")
    parser.add_argument("--pre-roll", type=int, help="Pre-roll seconds for auto-start monitor. Defaults to the saved value.")
    parser.add_argument("--max-record", type=int, help="Maximum record seconds for auto-start monitor. Defaults to the saved value.")
    args = parser.parse_args()

    try:
        selection = build_selection(args)
    except ValueError as exc:
        parser.error(str(exc))
        return
    if selection is None:
        return

    missing = missing_dependencies_for_mode(selection.mode)
    if missing:
        parser.error(
            f"{format_missing_dependencies(missing)} Run the launcher without explicit mode flags to open the installer and repair this profile first."
        )
        return

    try:
        save_launcher_settings(selection)
        sync_windows_auto_start(
            enabled=bool(selection.auto_start_with_windows),
            mode=selection.mode,
            server_url=selection.server_url,
            port=selection.port,
            auto_start_monitor=selection.auto_start_monitor,
            auto_start_device_id=selection.auto_start_device_id,
            auto_start_pre_roll=selection.auto_start_pre_roll,
            auto_start_max_record=selection.auto_start_max_record,
        )
    except RuntimeError as exc:
        parser.error(str(exc))
        return

    runtime = DesktopRuntime(selection)
    runtime.prepare()
    try:
        runtime.start_event_loop()
    finally:
        runtime.shutdown()
        time.sleep(0.25)


if __name__ == "__main__":
    main()
