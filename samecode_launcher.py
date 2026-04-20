from __future__ import annotations

import argparse
import logging
import threading
import time
from dataclasses import dataclass
from queue import Empty, SimpleQueue
from typing import Literal

import webview

from app import DEFAULT_PORT, MONITOR, SAMECodeCli, configure_logging, create_server_context, shutdown_server_context
from same_paths import app_root


WINDOW_TITLE = "SAMECode"
CLIENT_WIDTH = 1360
CLIENT_HEIGHT = 920
CONSOLE_WIDTH = 900
CONSOLE_HEIGHT = 620
DEFAULT_SERVER_URL = f"http://127.0.0.1:{DEFAULT_PORT}"
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"
ModeName = Literal["server", "client", "both"]

CONSOLE_HTML = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>SAMECode Server Console</title>
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
        <div class="title">SAMECode Server Console</div>
        <div class="subtitle" id="summary">Loading server details...</div>
      </div>
      <div class="console">
        <pre id="log"></pre>
        <form id="command-form">
          <div class="prompt">samecode&gt;</div>
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
    def __init__(self, cli: SAMECodeCli, log_handler: BufferedLogHandler, summary: str, on_shutdown_requested) -> None:
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
            threading.Thread(target=self.on_shutdown_requested, name="samecode-ui-shutdown", daemon=True).start()
        return {"ok": True}


class DesktopRuntime:
    def __init__(self, selection: LaunchSelection) -> None:
        self.selection = selection
        self.context = None
        self.server_thread: threading.Thread | None = None
        self.console_cli: SAMECodeCli | None = None
        self.console_window: webview.Window | None = None
        self.app_window: webview.Window | None = None
        self.log_handler: BufferedLogHandler | None = None
        self._shutdown_lock = threading.Lock()
        self._shutdown_started = False

    def prepare(self) -> None:
        configure_logging()
        if self.selection.mode in {"server", "both"}:
            self._start_local_server()
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

    def _start_local_server(self) -> None:
        self.context = create_server_context(port=DEFAULT_PORT, enable_cli=False)
        self.server_thread = threading.Thread(
            target=self.context.server.serve_forever,
            name="samecode-http",
            daemon=True,
        )
        self.server_thread.start()
        logging.getLogger("samecode").info("SAMECode listening on %s", self.local_server_url)

    def _create_console_window(self) -> None:
        if self.context is None:
            raise RuntimeError("Server context missing.")
        self.log_handler = BufferedLogHandler()
        logging.getLogger().addHandler(self.log_handler)
        self.console_cli = SAMECodeCli(self.context.server, MONITOR, self.context.port)
        self.console_cli.execute_command("help")
        summary = f"Local server ready at {self.local_server_url}. Close this window or run shutdown to stop the server."
        api = ServerConsoleApi(self.console_cli, self.log_handler, summary, self.shutdown)
        self.console_window = webview.create_window(
            f"{WINDOW_TITLE} Server",
            html=CONSOLE_HTML,
            js_api=api,
            width=CONSOLE_WIDTH,
            height=CONSOLE_HEIGHT,
            min_size=(760, 460),
        )
        self.console_window.events.closed += lambda *_args: self.shutdown()

    def _create_app_window(self, url: str, *, title: str) -> None:
        self.app_window = webview.create_window(
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
                shutdown_server_context(self.context)
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


def choose_launch_selection(default_mode: ModeName, default_server_url: str) -> LaunchSelection | None:
    import tkinter as tk
    from tkinter import ttk

    result: dict[str, str | bool] = {
        "mode": default_mode,
        "server_url": default_server_url,
        "confirmed": False,
    }

    root = tk.Tk()
    root.title("Launch SAMECode")
    root.geometry("620x520")
    root.minsize(620, 520)
    root.configure(bg="#f4f1e8")
    root.resizable(False, False)

    outer = ttk.Frame(root, padding=22)
    outer.pack(fill="both", expand=True)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    ttk.Label(outer, text="Launch SAMECode", font=("Segoe UI", 18, "bold")).pack(anchor="w")
    ttk.Label(
        outer,
        text="Pick whether this copy should act as the local server, a client against another SAMECode server, or both at once.",
        wraplength=500,
    ).pack(anchor="w", pady=(8, 16))

    mode_var = tk.StringVar(value=default_mode)
    server_url_var = tk.StringVar(value=default_server_url)
    error_var = tk.StringVar(value="")

    options = [
        ("server", "Server", "Run the local SAMECode server and show the server console window only."),
        ("client", "Client", "Open the desktop web app against an existing SAMECode server URL."),
        ("both", "Both", "Run the local server, show the server console, and open the SAMECode client window."),
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

    def sync_field_state(*_args) -> None:
        state = "normal" if mode_var.get() == "client" else "disabled"
        server_url_entry.configure(state=state)

    mode_var.trace_add("write", sync_field_state)
    sync_field_state()

    ttk.Label(outer, textvariable=error_var, foreground="#a32117", wraplength=500).pack(anchor="w", pady=(12, 0))

    ttk.Frame(outer).pack(fill="both", expand=True)

    actions = tk.Frame(root, bg="#efe5d4", padx=18, pady=14, highlightbackground="#d5c8af", highlightthickness=1)
    actions.pack(fill="x", side="bottom")

    def cancel() -> None:
        root.destroy()

    def launch() -> None:
        try:
            result["mode"] = normalize_mode(mode_var.get())
            result["server_url"] = normalize_server_url(server_url_var.get())
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
        text="Start SAMECode",
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
    root.mainloop()

    if not result["confirmed"]:
        return None
    return LaunchSelection(mode=result["mode"], server_url=result["server_url"])


def build_selection(args: argparse.Namespace) -> LaunchSelection | None:
    if args.mode:
        return LaunchSelection(normalize_mode(args.mode), normalize_server_url(args.server_url))
    return choose_launch_selection("both", normalize_server_url(args.server_url))


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch the SAMECode desktop app.")
    parser.add_argument("--mode", choices=("server", "client", "both"), help="Launch mode. If omitted, show the mode chooser.")
    parser.add_argument("--server-url", default=DEFAULT_SERVER_URL, help="Server URL for client mode.")
    args = parser.parse_args()

    selection = build_selection(args)
    if selection is None:
        return

    runtime = DesktopRuntime(selection)
    runtime.prepare()
    try:
        webview.start(private_mode=False, storage_path=str(app_root() / "webview-storage"))
    finally:
        runtime.shutdown()
        time.sleep(0.25)


if __name__ == "__main__":
    main()
