from __future__ import annotations

import argparse
import logging
import threading
import time
import tkinter as tk
from queue import Empty, SimpleQueue
from tkinter import ttk

WINDOW_TITLE = "SAMEStation Server"
WINDOW_WIDTH = 860
WINDOW_HEIGHT = 640
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"
DEFAULT_PORT = 8000
DEFAULT_BIND_HOST = "0.0.0.0"


def app_runtime():
    from app import MONITOR, build_access_urls, create_server_context, shutdown_server_context

    return MONITOR, build_access_urls, create_server_context, shutdown_server_context


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


class ServerHostWindow:
    def __init__(self, *, port: int, bind_host: str, open_browser: bool, auto_start_monitor: bool) -> None:
        self.port = port
        self.bind_host = bind_host
        self.open_browser = open_browser
        self.auto_start_monitor = auto_start_monitor
        self.context = None
        self.server_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.log_handler = BufferedLogHandler()
        self._browser_opened = False
        self.root = tk.Tk()
        self.root.title(WINDOW_TITLE)
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.minsize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.root.configure(bg="#f5f1e7")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.summary_var = tk.StringVar(value="Starting SAMEStation Server...")
        self.urls_var = tk.StringVar(value="")
        self._build_ui()
        self._attach_logging()

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text=WINDOW_TITLE, font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="The server keeps the current web console. Use the buttons below to open it, or leave this host running in the background.",
            wraplength=780,
        ).pack(anchor="w", pady=(8, 0))

        status_card = ttk.LabelFrame(outer, text="Status", padding=14)
        status_card.pack(fill="x", pady=(18, 0))
        ttk.Label(status_card, textvariable=self.summary_var, wraplength=760).pack(anchor="w")
        ttk.Label(status_card, textvariable=self.urls_var, wraplength=760, foreground="#30525e").pack(anchor="w", pady=(8, 0))

        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(16, 0))
        ttk.Button(controls, text="Open Web Console", command=self.open_console).pack(side="left")
        ttk.Button(controls, text="Stop Server", command=self.close).pack(side="left", padx=(10, 0))

        log_card = ttk.LabelFrame(outer, text="Server Log", padding=10)
        log_card.pack(fill="both", expand=True, pady=(18, 0))
        self.log_box = tk.Text(log_card, wrap="word", height=20, bg="#11181b", fg="#e7f0f2", insertbackground="#e7f0f2")
        self.log_box.pack(fill="both", expand=True)
        self.log_box.configure(state="disabled")

    def _attach_logging(self) -> None:
        logger = logging.getLogger("samestation")
        logger.setLevel(logging.INFO)
        logger.addHandler(self.log_handler)

    def _detach_logging(self) -> None:
        logger = logging.getLogger("samestation")
        logger.removeHandler(self.log_handler)

    def start(self) -> None:
        monitor, build_urls, create_context, _shutdown = app_runtime()
        self.context = create_context(port=self.port, bind_host=self.bind_host, enable_cli=False)
        self.server_thread = threading.Thread(
            target=self.context.server.serve_forever,
            name="samestation-server",
            daemon=True,
        )
        self.server_thread.start()
        urls = build_urls(self.context.port)
        self.summary_var.set("SAMEStation Server is running.")
        self.urls_var.set("Available URLs: " + " | ".join(urls))
        logging.getLogger("samestation").info("SAMEStation Server listening on %s", " | ".join(urls))
        if self.auto_start_monitor:
            self._try_auto_start_monitor(monitor)
        if self.open_browser and not self._browser_opened:
            self._browser_opened = True
            self.root.after(900, self.open_console)
        self.root.after(250, self._pump_logs)
        self.root.mainloop()

    def _try_auto_start_monitor(self, monitor) -> None:
        settings = monitor.get_settings()
        device_id = settings.get("deviceId")
        if device_id is None:
            logging.getLogger("samestation").warning("Auto-start monitor skipped because no server audio device is configured.")
            return
        try:
            monitor.start(
                int(device_id),
                pre_roll_seconds=int(settings.get("preRollSeconds") or 10),
                max_record_seconds=int(settings.get("maxRecordSeconds") or 180),
                source_mode=str(settings.get("sourceMode") or "device"),
                icecast_url=str(settings.get("icecastUrl") or ""),
            )
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("samestation").warning("Unable to auto-start monitor: %s", exc)

    def _pump_logs(self) -> None:
        lines = self.log_handler.drain()
        if lines:
            self.log_box.configure(state="normal")
            for line in lines:
                self.log_box.insert("end", line + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        if not self.stop_event.is_set():
            self.root.after(250, self._pump_logs)

    def open_console(self) -> None:
        if self.context is None:
            return
        import webbrowser

        webbrowser.open(f"http://127.0.0.1:{self.context.port}", new=1)

    def close(self) -> None:
        if self.stop_event.is_set():
            return
        self.stop_event.set()
        if self.context is not None:
            _monitor, _build_urls, _create_context, shutdown_context = app_runtime()
            shutdown_context(self.context)
        self._detach_logging()
        self.root.destroy()


def run_headless(*, port: int, bind_host: str, open_browser: bool, auto_start_monitor: bool) -> None:
    monitor, build_urls, create_context, shutdown_context = app_runtime()
    context = create_context(port=port, bind_host=bind_host, enable_cli=False)
    server_thread = threading.Thread(
        target=context.server.serve_forever,
        name="samestation-server",
        daemon=True,
    )
    server_thread.start()
    logger = logging.getLogger("samestation")
    urls = build_urls(context.port)
    logger.info("SAMEStation Server listening on %s", " | ".join(urls))
    if auto_start_monitor:
        settings = monitor.get_settings()
        device_id = settings.get("deviceId")
        if device_id is None:
            logger.warning("Auto-start monitor skipped because no server audio device is configured.")
        else:
            try:
                monitor.start(
                    int(device_id),
                    pre_roll_seconds=int(settings.get("preRollSeconds") or 10),
                    max_record_seconds=int(settings.get("maxRecordSeconds") or 180),
                    source_mode=str(settings.get("sourceMode") or "device"),
                    icecast_url=str(settings.get("icecastUrl") or ""),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Unable to auto-start monitor: %s", exc)
    if open_browser:
        import webbrowser

        time.sleep(1.0)
        webbrowser.open(f"http://127.0.0.1:{context.port}", new=1)
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        logger.info("Stopping SAMEStation Server.")
    finally:
        shutdown_context(context)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SAMEStation Server installed app.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind the local server on.")
    parser.add_argument("--bind", default=DEFAULT_BIND_HOST, help="Host or interface to bind the server on.")
    parser.add_argument("--open-browser", action="store_true", help="Open the web console after the server launches.")
    parser.add_argument("--headless", action="store_true", help="Run without the small server host window.")
    parser.add_argument("--auto-start-monitor", action="store_true", help="Auto-start the saved server monitor when the server launches.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

    if args.headless:
        run_headless(
            port=args.port,
            bind_host=args.bind,
            open_browser=args.open_browser,
            auto_start_monitor=args.auto_start_monitor,
        )
        return

    window = ServerHostWindow(
        port=args.port,
        bind_host=args.bind,
        open_browser=args.open_browser,
        auto_start_monitor=args.auto_start_monitor,
    )
    window.start()


if __name__ == "__main__":
    main()
