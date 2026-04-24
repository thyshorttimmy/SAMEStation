from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any

from samestation_autostart import is_product_auto_start_enabled, sync_product_windows_auto_start
from samestation_distribution import (
    ProductRole,
    current_version_label,
    default_install_dir,
    default_server_misc_path,
    default_server_recordings_path,
    download_release_asset,
    fetch_latest_payload_release,
    installed_version_label,
    local_payload_asset,
    normalize_channel,
    normalize_role,
    product_spec,
    save_install_manifest,
    save_runtime_config,
)
from samestation_runtime import install_missing_dependencies_for_mode


WINDOW_WIDTH = 920
WINDOW_HEIGHT = 825
CONTENT_PANEL_WIDTH = 872
CONTENT_PANEL_HEIGHT = 590
SETUP_COLUMN_WIDTH = 398
SETUP_CARD_HEIGHT_TOP = 224
SETUP_CARD_HEIGHT_MID = 186
SETUP_CARD_HEIGHT_BOTTOM = 126
SETUP_PANEL_HEIGHT = 630
CLIENT_SETUP_PANEL_HEIGHT = 580
CLIENT_DEFAULT_SERVER_URL = "http://127.0.0.1:8000"

SERVER_RELEASE_NOTES = {
    "Stable": [
        "Recommended for normal use.",
        "Focuses on predictable installs and fewer surprises.",
        "Best choice for a machine that should stay on watch.",
    ],
    "Nightly": [
        "Includes newer server and installer changes first.",
        "Updates more often before the next stable release.",
        "Best for trying upcoming server features early.",
    ],
}

CLIENT_RELEASE_NOTES = {
    "Stable": [
        "Recommended for normal day-to-day client use.",
        "Focuses on a dependable alerts dashboard connection.",
        "Best for viewers who want the cleanest client experience.",
    ],
    "Nightly": [
        "Includes newer client connection and dashboard changes first.",
        "Updates more often before the next stable release.",
        "Best for trying upcoming client improvements early.",
    ],
}


def wait_for_pid(pid_value: int, timeout_seconds: float = 30.0) -> None:
    if pid_value <= 0:
        return
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"Get-Process -Id {pid_value} -ErrorAction SilentlyContinue"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return
        time.sleep(0.4)


class ProductInstallerApp:
    def __init__(
        self,
        *,
        role: ProductRole,
        initial_channel: str = "stable",
        install_now: bool = False,
        wait_for_pids: list[int] | None = None,
    ) -> None:
        self.role = normalize_role(role)
        self.spec = product_spec(self.role)
        self.install_now = install_now
        self.wait_for_pids = [int(pid) for pid in (wait_for_pids or []) if int(pid) > 0]
        self.root = tk.Tk()
        self.root.title(self.spec.installer_exe_name.replace(".exe", ""))
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.minsize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.root.maxsize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.root.resizable(False, False)
        self.root.configure(bg="#f5f1e7")

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        self.steps = ["Welcome", "Setup", "Review", "Install"]
        self.current_step = 0
        self.installing = False
        self.install_complete = False
        self.install_failed = False

        self.channel_var = tk.StringVar(value="Stable" if normalize_channel(initial_channel) == "stable" else "Nightly")
        initial_install_dir = Path(default_install_dir(self.role))
        self.available_version_var = tk.StringVar(value="Checking...")
        self.installed_version_var = tk.StringVar(value=installed_version_label(initial_install_dir, self.role))
        self.release_notes_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Ready.")
        self.log_var = tk.StringVar(value="")
        self.progress_var = tk.DoubleVar(value=0.0)

        self.install_path_var = tk.StringVar(value=str(initial_install_dir))
        default_launch_at_login = True if self.role == "server" else False
        try:
            default_launch_at_login = is_product_auto_start_enabled(self.role) or default_launch_at_login
        except Exception:
            pass
        self.launch_at_login_var = tk.BooleanVar(value=default_launch_at_login)
        self.start_after_install_var = tk.BooleanVar(value=False if self.role == "server" else True)
        self.open_browser_var = tk.BooleanVar(value=False)
        self.auto_start_monitor_var = tk.BooleanVar(value=False)
        self.misc_path_var = tk.StringVar(value=str(default_server_misc_path(self.install_path_var.get())) if self.role == "server" else "")
        self.recordings_path_var = tk.StringVar(value=str(default_server_recordings_path()) if self.role == "server" else "")
        self.server_url_var = tk.StringVar(value=CLIENT_DEFAULT_SERVER_URL)

        self._build_shell()
        self._refresh_dynamic_copy()
        self._show_step()
        self._schedule_release_refresh()
        if self.install_now:
            self.current_step = 3
            self._show_step()
            self.root.after(120, self._begin_install)

    def _build_shell(self) -> None:
        self.outer = ttk.Frame(self.root, padding=16)
        self.outer.pack(fill="both", expand=True)

        header = ttk.Frame(self.outer)
        header.pack(fill="x")
        ttk.Label(header, text=self.spec.installer_exe_name.replace(".exe", ""), font=("Segoe UI", 20, "bold"), anchor="center", justify="center").pack()
        subtitle = (
            f"Installer-first setup for {self.spec.label}. Public releases should expose only the installer, while this tool resolves the installed app payload separately."
        )
        ttk.Label(header, text=subtitle, wraplength=800, anchor="center", justify="center").pack(anchor="w", pady=(8, 0))

        self.step_label = ttk.Label(self.outer, font=("Segoe UI", 11, "bold"), anchor="center", justify="center")
        self.step_label.pack(pady=(14, 8))

        self.content = ttk.Frame(self.outer)
        self.content.pack(fill="both", expand=True)

        self.action_bar = tk.Frame(
            self.root,
            bg="#efe5d4",
            padx=18,
            pady=14,
            highlightbackground="#d5c8af",
            highlightthickness=1,
        )
        self.action_bar.pack(fill="x", side="bottom")

        self.cancel_button = tk.Button(
            self.action_bar,
            text="Close",
            command=self.root.destroy,
            width=12,
            padx=10,
            pady=6,
            bg="#ddd2bf",
            activebackground="#d2c4ae",
            relief="raised",
        )
        self.cancel_button.pack(side="right")

        self.next_button = tk.Button(
            self.action_bar,
            text="Continue",
            command=self._next_step,
            width=16,
            padx=10,
            pady=6,
            bg="#b64926",
            fg="white",
            activebackground="#983c1e",
            activeforeground="white",
            relief="raised",
        )
        self.next_button.pack(side="right", padx=(0, 10))

        self.back_button = tk.Button(
            self.action_bar,
            text="Back",
            command=self._previous_step,
            width=12,
            padx=10,
            pady=6,
            bg="#ddd2bf",
            activebackground="#d2c4ae",
            relief="raised",
        )
        self.back_button.pack(side="right", padx=(0, 10))

    def _mount_panel(self, title: str | None = None, *, padding: int = 12, height: int | None = None) -> ttk.Frame:
        panel_height = height or CONTENT_PANEL_HEIGHT
        host = ttk.Frame(self.content, width=CONTENT_PANEL_WIDTH, height=panel_height)
        host.place(relx=0.5, rely=0.0, anchor="n", width=CONTENT_PANEL_WIDTH, height=panel_height)
        if title:
            panel = ttk.LabelFrame(host, text=title, padding=padding)
        else:
            panel = ttk.Frame(host, padding=padding)
        panel.pack(fill="both", expand=True)
        return panel

    def _build_value_box(self, parent: tk.Misc, variable: tk.StringVar) -> tuple[tk.Frame, tk.Label]:
        box = tk.Frame(
            parent,
            height=36,
            background="#ffffff",
            highlightbackground="#a9a9a9",
            highlightthickness=1,
            bd=0,
        )
        box.pack_propagate(False)
        label = tk.Label(
            box,
            textvariable=variable,
            background="#ffffff",
            anchor="w",
            justify="left",
            padx=6,
            pady=4,
        )
        label.pack(fill="both", expand=True)
        return box, label

    def _clear_content(self) -> None:
        for child in self.content.winfo_children():
            child.destroy()

    def _show_step(self) -> None:
        self._clear_content()
        step_name = self.steps[self.current_step]
        self.step_label.configure(text=f"Step {self.current_step + 1} of {len(self.steps)}: {step_name}")
        if step_name == "Welcome":
            self._render_welcome()
        elif step_name == "Setup":
            if self.role == "server":
                self._render_server_setup()
            else:
                self._render_client_setup()
        elif step_name == "Review":
            self._render_review()
        elif step_name == "Install":
            self._render_install()

        self.back_button.configure(state="normal" if self.current_step > 0 and not self.installing else "disabled")
        self._refresh_next_button()

    def _refresh_next_button(self) -> None:
        step_name = self.steps[self.current_step]
        if step_name == "Review":
            self.next_button.configure(text="Install", state="normal")
        elif step_name == "Install":
            if self.installing:
                self.next_button.configure(text="Installing...", state="disabled")
            elif self.install_complete:
                self.next_button.configure(text="Finish", state="normal")
            else:
                self.next_button.configure(text="Install", state="normal")
        else:
            self.next_button.configure(text="Continue", state="normal")

    def _schedule_release_refresh(self) -> None:
        threading.Thread(target=self._refresh_release_info, name=f"{self.role}-release-check", daemon=True).start()

    def _refresh_release_info(self) -> None:
        install_dir = Path(self.install_path_var.get())
        installed_label = installed_version_label(install_dir, self.role)
        try:
            release = fetch_latest_payload_release(self.role, normalize_channel(self.channel_var.get().lower()))
            available = release.tag_name or release.name or "Available"
        except Exception as exc:  # noqa: BLE001
            local_asset = local_payload_asset(self.role, normalize_channel(self.channel_var.get().lower()))
            available = f"Local payload: {local_asset.name}" if local_asset is not None else f"Unavailable: {exc}"
        self.root.after(0, lambda: self._apply_release_info(installed_label, available))

    def _apply_release_info(self, installed_label: str, available_label: str) -> None:
        self.installed_version_var.set(installed_label)
        self.available_version_var.set(available_label)
        self._refresh_dynamic_copy()

    def _refresh_dynamic_copy(self) -> None:
        self.release_notes_var.set(self._release_notes_text())

    def _release_notes_text(self) -> str:
        notes = SERVER_RELEASE_NOTES if self.role == "server" else CLIENT_RELEASE_NOTES
        selected = notes.get(self.channel_var.get(), notes["Stable"])
        dynamic_lines = [
            f"Installed here: {self.installed_version_var.get() or 'Checking...'}",
            f"Available payload: {self.available_version_var.get() or 'Checking...'}",
        ]
        return "\n".join([*(f"- {line}" for line in selected), *(f"- {line}" for line in dynamic_lines)])

    def _render_welcome(self) -> None:
        box = self._mount_panel(padding=12)
        ttk.Label(box, text=f"Install {self.spec.label}", font=("Segoe UI", 18, "bold"), anchor="center", justify="center").pack()
        intro = (
            "This installer sets up the machine that captures and serves alerts."
            if self.role == "server"
            else "This installer sets up the native client that connects to an existing SAMEStation server."
        )
        ttk.Label(box, text=intro, wraplength=720, anchor="center", justify="center").pack(pady=(10, 0))
        ttk.Label(
            box,
            text="Public releases should ship only the installers. The installed app payload is resolved separately from the selected internal channel.",
            wraplength=720,
            anchor="center",
            justify="center",
        ).pack(pady=(10, 0))

    def _render_server_setup(self) -> None:
        box = self._mount_panel("Server Setup", padding=12, height=SETUP_PANEL_HEIGHT)
        grid = ttk.Frame(box)
        grid.pack(anchor="center", pady=(4, 0))
        left_column = ttk.Frame(grid, width=SETUP_COLUMN_WIDTH)
        right_column = ttk.Frame(grid, width=SETUP_COLUMN_WIDTH)
        left_column.grid(row=0, column=0, sticky="ns", padx=(0, 8))
        right_column.grid(row=0, column=1, sticky="ns")
        left_column.grid_propagate(False)
        right_column.grid_propagate(False)

        build_card = ttk.LabelFrame(left_column, text="Build", padding=10, width=SETUP_COLUMN_WIDTH, height=SETUP_CARD_HEIGHT_TOP)
        build_card.pack(fill="x", pady=(0, 8))
        build_card.pack_propagate(False)
        ttk.Label(build_card, text="Branch Channel").pack(anchor="w")
        branch_box = ttk.Combobox(build_card, textvariable=self.channel_var, state="readonly", values=["Stable", "Nightly"], width=16)
        branch_box.pack(anchor="w", pady=(4, 8))
        branch_box.bind("<<ComboboxSelected>>", self._handle_channel_changed)
        ttk.Label(build_card, text="Available Payload").pack(anchor="w")
        available_box, _available_label = self._build_value_box(build_card, self.available_version_var)
        available_box.pack(anchor="w", pady=(6, 4), fill="x")
        ttk.Label(build_card, text="Installed Here").pack(anchor="w")
        installed_box, installed_label = self._build_value_box(build_card, self.installed_version_var)
        installed_label.configure(text=self.installed_version_var.get())
        self.installed_version_var.trace_add("write", lambda *_args, label=installed_label: label.configure(text=self.installed_version_var.get()))
        installed_box.pack(anchor="w", pady=(6, 0), fill="x")

        location_card = ttk.LabelFrame(right_column, text="Install Location", padding=10, width=SETUP_COLUMN_WIDTH, height=SETUP_CARD_HEIGHT_TOP)
        location_card.pack(fill="x", pady=(0, 8))
        location_card.pack_propagate(False)
        ttk.Label(location_card, text="Choose where the server app should live.").pack(anchor="w")
        row = ttk.Frame(location_card)
        row.pack(fill="x", pady=(6, 0))
        ttk.Entry(row, textvariable=self.install_path_var, width=32).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse", command=self._choose_install_folder).pack(side="left", padx=(8, 0))

        startup_card = ttk.LabelFrame(left_column, text="Startup", padding=10, width=SETUP_COLUMN_WIDTH, height=SETUP_CARD_HEIGHT_MID)
        startup_card.pack(fill="x", pady=(0, 8))
        startup_card.pack_propagate(False)
        ttk.Checkbutton(startup_card, text="Launch server when I sign in", variable=self.launch_at_login_var).pack(anchor="w")
        ttk.Checkbutton(startup_card, text="Open the web console after launch", variable=self.open_browser_var).pack(anchor="w", pady=(6, 0))
        ttk.Checkbutton(startup_card, text="Start the server after install", variable=self.start_after_install_var).pack(anchor="w", pady=(6, 0))
        ttk.Checkbutton(startup_card, text="Auto-start the monitor", variable=self.auto_start_monitor_var).pack(anchor="w", pady=(6, 0))

        notes_card = ttk.LabelFrame(right_column, text="Release Notes", padding=10, width=SETUP_COLUMN_WIDTH, height=SETUP_CARD_HEIGHT_MID)
        notes_card.pack(fill="x", pady=(0, 8))
        notes_card.pack_propagate(False)
        ttk.Label(notes_card, textvariable=self.release_notes_var, wraplength=340, justify="left").pack(anchor="w")

        misc_card = ttk.LabelFrame(left_column, text="Misc Data", padding=10, width=SETUP_COLUMN_WIDTH, height=SETUP_CARD_HEIGHT_BOTTOM)
        misc_card.pack(fill="x")
        misc_card.pack_propagate(False)
        ttk.Label(misc_card, text="General app data path").pack(anchor="w")
        misc_row = ttk.Frame(misc_card)
        misc_row.pack(fill="x", pady=(6, 0))
        ttk.Entry(misc_row, textvariable=self.misc_path_var, width=32).pack(side="left", fill="x", expand=True)
        ttk.Button(misc_row, text="Browse", command=lambda: self._choose_storage_folder("misc")).pack(side="left", padx=(8, 0))
        ttk.Label(misc_card, text="Default: inside the app folder.", wraplength=340).pack(anchor="w", pady=(8, 0))

        recordings_card = ttk.LabelFrame(right_column, text="Recordings", padding=10, width=SETUP_COLUMN_WIDTH, height=SETUP_CARD_HEIGHT_BOTTOM)
        recordings_card.pack(fill="x")
        recordings_card.pack_propagate(False)
        ttk.Label(recordings_card, text="Alert recordings path").pack(anchor="w")
        recordings_row = ttk.Frame(recordings_card)
        recordings_row.pack(fill="x", pady=(6, 0))
        ttk.Entry(recordings_row, textvariable=self.recordings_path_var, width=32).pack(side="left", fill="x", expand=True)
        ttk.Button(recordings_row, text="Browse", command=lambda: self._choose_storage_folder("recordings")).pack(side="left", padx=(8, 0))
        ttk.Label(recordings_card, text="Default: Documents\\SAMEStation Recordings.", wraplength=340).pack(anchor="w", pady=(8, 0))

    def _render_client_setup(self) -> None:
        box = self._mount_panel("Client Setup", padding=12, height=CLIENT_SETUP_PANEL_HEIGHT)
        grid = ttk.Frame(box)
        grid.pack(anchor="center", pady=(4, 0))
        left_column = ttk.Frame(grid, width=SETUP_COLUMN_WIDTH)
        right_column = ttk.Frame(grid, width=SETUP_COLUMN_WIDTH)
        left_column.grid(row=0, column=0, sticky="ns", padx=(0, 8))
        right_column.grid(row=0, column=1, sticky="ns")
        left_column.grid_propagate(False)
        right_column.grid_propagate(False)

        build_card = ttk.LabelFrame(left_column, text="Build", padding=10, width=SETUP_COLUMN_WIDTH, height=SETUP_CARD_HEIGHT_TOP)
        build_card.pack(fill="x", pady=(0, 8))
        build_card.pack_propagate(False)
        ttk.Label(build_card, text="Branch Channel").pack(anchor="w")
        branch_box = ttk.Combobox(build_card, textvariable=self.channel_var, state="readonly", values=["Stable", "Nightly"], width=16)
        branch_box.pack(anchor="w", pady=(4, 8))
        branch_box.bind("<<ComboboxSelected>>", self._handle_channel_changed)
        ttk.Label(build_card, text="Available Payload").pack(anchor="w")
        available_box, _available_label = self._build_value_box(build_card, self.available_version_var)
        available_box.pack(anchor="w", pady=(6, 4), fill="x")
        ttk.Label(build_card, text="Installed Here").pack(anchor="w")
        installed_box, installed_label = self._build_value_box(build_card, self.installed_version_var)
        installed_label.configure(text=self.installed_version_var.get())
        self.installed_version_var.trace_add("write", lambda *_args, label=installed_label: label.configure(text=self.installed_version_var.get()))
        installed_box.pack(anchor="w", pady=(6, 0), fill="x")

        location_card = ttk.LabelFrame(right_column, text="Install Location", padding=10, width=SETUP_COLUMN_WIDTH, height=SETUP_CARD_HEIGHT_TOP)
        location_card.pack(fill="x", pady=(0, 8))
        location_card.pack_propagate(False)
        ttk.Label(location_card, text="Choose where the client app should live.").pack(anchor="w")
        row = ttk.Frame(location_card)
        row.pack(fill="x", pady=(6, 0))
        ttk.Entry(row, textvariable=self.install_path_var, width=32).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse", command=self._choose_install_folder).pack(side="left", padx=(8, 0))

        connection_card = ttk.LabelFrame(left_column, text="Server Connection", padding=10, width=SETUP_COLUMN_WIDTH, height=SETUP_CARD_HEIGHT_MID)
        connection_card.pack(fill="x", pady=(0, 8))
        connection_card.pack_propagate(False)
        ttk.Label(connection_card, text="Preferred SAMEStation server URL").pack(anchor="w")
        ttk.Entry(connection_card, textvariable=self.server_url_var, width=36).pack(anchor="w", fill="x", pady=(6, 8))
        ttk.Label(
            connection_card,
            text="The client supports LAN discovery later, but this saved URL gives it a manual fallback right away.",
            wraplength=340,
            justify="left",
        ).pack(anchor="w")

        options_card = ttk.LabelFrame(right_column, text="Startup", padding=10, width=SETUP_COLUMN_WIDTH, height=SETUP_CARD_HEIGHT_MID)
        options_card.pack(fill="x", pady=(0, 8))
        options_card.pack_propagate(False)
        ttk.Checkbutton(options_card, text="Launch client when I sign in", variable=self.launch_at_login_var).pack(anchor="w")
        ttk.Checkbutton(options_card, text="Start the client after install", variable=self.start_after_install_var).pack(anchor="w", pady=(6, 0))
        ttk.Label(options_card, text="The client never installs server-side monitoring or decoding components.", wraplength=340, justify="left").pack(anchor="w", pady=(10, 0))

        notes_card = ttk.LabelFrame(box, text="Release Notes", padding=10)
        notes_card.pack(fill="x", pady=(4, 0))
        ttk.Label(notes_card, textvariable=self.release_notes_var, wraplength=760, justify="left").pack(anchor="w")

    def _render_review(self) -> None:
        box = self._mount_panel("Ready To Install", padding=18)
        summary_lines = [
            f"Product: {self.spec.label}",
            f"Branch channel: {self.channel_var.get()}",
            f"Available payload: {self.available_version_var.get()}",
            f"Installed here now: {self.installed_version_var.get()}",
            f"Install path: {self.install_path_var.get()}",
        ]
        if self.role == "server":
            summary_lines.extend(
                [
                    f"Launch at sign-in: {'On' if self.launch_at_login_var.get() else 'Off'}",
                    f"Open web console after launch: {'On' if self.open_browser_var.get() else 'Off'}",
                    f"Start server after install: {'On' if self.start_after_install_var.get() else 'Off'}",
                    f"Auto-start monitor: {'On' if self.auto_start_monitor_var.get() else 'Off'}",
                    f"Misc data path: {self.misc_path_var.get()}",
                    f"Recordings path: {self.recordings_path_var.get()}",
                ]
            )
        else:
            summary_lines.extend(
                [
                    f"Launch at sign-in: {'On' if self.launch_at_login_var.get() else 'Off'}",
                    f"Start client after install: {'On' if self.start_after_install_var.get() else 'Off'}",
                    f"Preferred server URL: {self.server_url_var.get()}",
                ]
            )
        ttk.Label(box, text="Review the install choices below before continuing.", anchor="center", justify="center").pack()
        review = tk.Text(box, height=16, width=78, wrap="word")
        review.pack(pady=(12, 0))
        review.insert("1.0", "\n".join(summary_lines))
        review.configure(state="disabled")

    def _render_install(self) -> None:
        box = self._mount_panel(f"Installing {self.spec.label}", padding=18)
        if self.install_complete:
            ttk.Label(box, text=f"{self.spec.label} Is Ready", font=("Segoe UI", 16, "bold"), anchor="center", justify="center").pack()
            ttk.Label(box, textvariable=self.status_var, wraplength=720, anchor="center", justify="center").pack(pady=(12, 0))
            return

        ttk.Label(box, textvariable=self.status_var, wraplength=720, anchor="center", justify="center").pack()
        ttk.Progressbar(box, maximum=100, variable=self.progress_var).pack(fill="x", pady=(12, 12))
        log = tk.Text(box, height=16, width=78, wrap="word")
        log.pack()
        log.insert("1.0", self.log_var.get())
        log.configure(state="disabled")

        def sync_log(*_args) -> None:
            log.configure(state="normal")
            log.delete("1.0", "end")
            log.insert("1.0", self.log_var.get())
            log.configure(state="disabled")
            log.see("end")

        self.log_var.trace_add("write", sync_log)

    def _handle_channel_changed(self, _event=None) -> None:
        self._refresh_dynamic_copy()
        self.available_version_var.set("Checking...")
        self._schedule_release_refresh()

    def _choose_install_folder(self) -> None:
        folder = filedialog.askdirectory(title=f"Choose {self.spec.short_label} Install Folder")
        if folder:
            self.install_path_var.set(folder)
            if self.role == "server":
                self.misc_path_var.set(str(default_server_misc_path(folder)))
            self.installed_version_var.set(installed_version_label(folder, self.role))
            self._schedule_release_refresh()

    def _choose_storage_folder(self, kind: str) -> None:
        title = "Choose Misc Data Folder" if kind == "misc" else "Choose Recordings Folder"
        folder = filedialog.askdirectory(title=title)
        if not folder:
            return
        if kind == "misc":
            self.misc_path_var.set(folder)
        else:
            self.recordings_path_var.set(folder)

    def _next_step(self) -> None:
        if self.current_step == len(self.steps) - 1:
            if self.install_complete:
                self.root.destroy()
                return
            if not self.installing:
                self._begin_install()
            return
        self.current_step += 1
        self._show_step()

    def _previous_step(self) -> None:
        if self.current_step <= 0 or self.installing:
            return
        self.current_step -= 1
        self._show_step()

    def _append_log(self, line: str) -> None:
        current = self.log_var.get()
        next_value = f"{current}\n{line}" if current else line
        self.root.after(0, lambda: self.log_var.set(next_value))

    def _set_status(self, text: str) -> None:
        self.root.after(0, lambda: self.status_var.set(text))

    def _set_progress(self, value: float) -> None:
        self.root.after(0, lambda: self.progress_var.set(value))

    def _begin_install(self) -> None:
        if self.installing:
            return
        self.installing = True
        self.install_complete = False
        self.install_failed = False
        self.log_var.set("")
        self.progress_var.set(0.0)
        self.status_var.set(f"Installing {self.spec.label}...")
        self._show_step()
        threading.Thread(target=self._run_install, name=f"{self.role}-install", daemon=True).start()

    def _run_install(self) -> None:
        try:
            self._install_payload()
        except Exception as exc:  # noqa: BLE001
            self.install_failed = True
            self._append_log(f"Install failed: {exc}")
            self._set_status(f"Install failed: {exc}")
        else:
            self.install_complete = True
            self._set_status(f"{self.spec.label} is installed and ready.")
        finally:
            self.installing = False
            self.root.after(0, self._show_step)

    def _install_payload(self) -> None:
        channel = normalize_channel(self.channel_var.get().lower())
        install_dir = Path(self.install_path_var.get()).expanduser().resolve()
        install_dir.mkdir(parents=True, exist_ok=True)

        self._set_progress(6)
        self._append_log(f"Preparing {self.spec.label} install in {install_dir}")
        self._append_log(install_missing_dependencies_for_mode(self.role))

        self._set_progress(12)
        for pid_value in self.wait_for_pids:
            self._append_log(f"Waiting for process {pid_value} to exit...")
            wait_for_pid(pid_value)

        self._set_progress(18)
        staged_dir = Path(tempfile.mkdtemp(prefix=f"samestation-{self.role}-"))
        staged_app = staged_dir / self.spec.app_exe_name
        release_tag = current_version_label()
        try:
            release = fetch_latest_payload_release(self.role, channel)
            asset = release.assets[self.spec.app_exe_name]
            self._append_log(f"Resolved internal payload {release.tag_name or release.name}")
            self._set_progress(35)
            download_release_asset(asset, staged_app)
            release_tag = release.tag_name or release.name or current_version_label()
        except Exception as exc:  # noqa: BLE001
            local_asset = local_payload_asset(self.role, channel)
            if local_asset is None:
                raise RuntimeError(f"Unable to resolve an internal payload for {self.spec.label}: {exc}") from exc
            self._append_log(f"GitHub payload lookup failed, using local payload {local_asset.name}")
            self._set_progress(35)
            shutil.copy2(local_asset, staged_app)

        self._set_progress(58)
        installed_app = install_dir / self.spec.app_exe_name
        shutil.copy2(staged_app, installed_app)
        self._append_log(f"Installed app payload to {installed_app}")

        if getattr(sys, "frozen", False):
            self._set_progress(66)
            shutil.copy2(Path(sys.executable).resolve(), install_dir / self.spec.installer_exe_name)
            self._append_log(f"Installed updater companion to {install_dir / self.spec.installer_exe_name}")

        self._set_progress(76)
        runtime_payload: dict[str, Any]
        if self.role == "server":
            runtime_payload = {
                "miscDataPath": self.misc_path_var.get().strip(),
                "recordingsPath": self.recordings_path_var.get().strip(),
                "defaultPort": 8000,
            }
        else:
            runtime_payload = {
                "serverUrl": self.server_url_var.get().strip() or CLIENT_DEFAULT_SERVER_URL,
            }
        save_runtime_config(install_dir, self.role, runtime_payload)
        self._append_log(f"Saved runtime config for {self.spec.short_label.lower()} product.")

        self._set_progress(84)
        manifest_payload: dict[str, Any] = {
            "role": self.role,
            "channel": channel,
            "installedVersion": release_tag,
            "installedByVersion": current_version_label(),
            "installPath": str(install_dir),
            "appExecutable": str(installed_app),
            "updatedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if self.role == "server":
            manifest_payload.update(
                {
                    "launchAtLogin": bool(self.launch_at_login_var.get()),
                    "openBrowserAfterLaunch": bool(self.open_browser_var.get()),
                    "startAfterInstall": bool(self.start_after_install_var.get()),
                    "autoStartMonitor": bool(self.auto_start_monitor_var.get()),
                    "miscDataPath": self.misc_path_var.get().strip(),
                    "recordingsPath": self.recordings_path_var.get().strip(),
                }
            )
        else:
            manifest_payload.update(
                {
                    "launchAtLogin": bool(self.launch_at_login_var.get()),
                    "startAfterInstall": bool(self.start_after_install_var.get()),
                    "serverUrl": self.server_url_var.get().strip() or CLIENT_DEFAULT_SERVER_URL,
                }
            )
        save_install_manifest(install_dir, self.role, manifest_payload)
        self._append_log(f"Saved install manifest to {install_dir}")

        self._set_progress(90)
        sync_product_windows_auto_start(
            role=self.role,
            enabled=bool(self.launch_at_login_var.get()),
            executable_path=installed_app,
            server_url=self.server_url_var.get().strip() or CLIENT_DEFAULT_SERVER_URL,
            open_browser=False,
            headless=True,
        )
        if self.launch_at_login_var.get():
            self._append_log("Configured launch at sign-in.")
        else:
            self._append_log("Launch at sign-in is disabled.")

        self._set_progress(97)
        if self.start_after_install_var.get():
            command = [str(installed_app)]
            if self.role == "server":
                if self.open_browser_var.get():
                    command.append("--open-browser")
                if self.auto_start_monitor_var.get():
                    command.append("--auto-start-monitor")
            else:
                server_url = self.server_url_var.get().strip() or CLIENT_DEFAULT_SERVER_URL
                command.extend(["--server-url", server_url])
            subprocess.Popen(command, cwd=str(install_dir), close_fds=True)
            self._append_log("Started installed app.")
        else:
            self._append_log("Install finished without auto-starting the app.")

        self._set_progress(100)
        self.installed_version_var.set(release_tag)

    def run(self) -> int:
        self.root.mainloop()
        return 0


def build_argument_parser(role: ProductRole) -> argparse.ArgumentParser:
    spec = product_spec(role)
    parser = argparse.ArgumentParser(description=f"Install or update {spec.label}.")
    parser.add_argument(
        "--channel",
        default="stable",
        type=normalize_channel,
        metavar="{stable,nightly}",
        help="Release channel to install from. Legacy 'test' is still accepted.",
    )
    parser.add_argument("--install-now", action="store_true", help="Open directly to the install step and begin immediately.")
    parser.add_argument("--wait-for-pid", action="append", default=[], help="Optional running process id to wait for before copying files.")
    return parser


def main_for_role(role: ProductRole) -> None:
    parser = build_argument_parser(role)
    args = parser.parse_args()
    app = ProductInstallerApp(
        role=role,
        initial_channel=args.channel,
        install_now=bool(args.install_now),
        wait_for_pids=[int(value) for value in args.wait_for_pid],
    )
    raise SystemExit(app.run())
