from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, ttk
from pathlib import Path


APP_TITLE = "SAMEStation Server Installer"
WINDOW_WIDTH = 920
WINDOW_HEIGHT = 760
SETUP_COLUMN_WIDTH = 398
SETUP_CARD_HEIGHT_TOP = 136
SETUP_CARD_HEIGHT_MID = 178
SETUP_CARD_HEIGHT_BOTTOM = 126
CONTENT_PANEL_WIDTH = 872
CONTENT_PANEL_HEIGHT = 495
SETUP_PANEL_HEIGHT = 530
MOCK_PROCESS_MARKERS = {
    "samestation_server_installer_mock.py",
    "SAMEStation Server Installer Mock.exe",
}

RELEASE_NOTES = {
    "Stable": [
        "Recommended for normal use.",
        "Focuses on predictable installs and fewer surprises.",
        "Best choice for a machine that should stay on watch.",
    ],
    "Nightly": [
        "Includes newer installer and server changes first.",
        "May change more often before the next stable build.",
        "Best for trying upcoming features before public release.",
    ],
}


class ServerInstallerMock:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
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

        self.steps = [
            "Welcome",
            "Setup",
            "Review",
            "Install",
        ]
        self.current_step = 0
        self.installing = False

        self.channel_var = tk.StringVar(value="Stable")
        self.version_var = tk.StringVar(value="v0.2.0-alpha.mock")
        self.install_path_var = tk.StringVar(value=r"C:\Program Files\SAMEStation Server")
        self.launch_at_login_var = tk.BooleanVar(value=True)
        self.open_browser_var = tk.BooleanVar(value=True)
        self.start_after_install_var = tk.BooleanVar(value=True)
        self.auto_start_monitor_var = tk.BooleanVar(value=False)
        self.misc_path_var = tk.StringVar()
        self.recordings_path_var = tk.StringVar()
        self.release_notes_var = tk.StringVar(value=self._release_notes_text())
        self.progress_var = tk.DoubleVar(value=0.0)
        self.status_var = tk.StringVar(value="Ready to simulate installation.")
        self.log_var = tk.StringVar(value="")

        self._sync_storage_paths()
        self._build_shell()
        self._show_step()

    def _build_shell(self) -> None:
        self.outer = ttk.Frame(self.root, padding=16)
        self.outer.pack(fill="both", expand=True)

        header = ttk.Frame(self.outer)
        header.pack(fill="x")
        ttk.Label(header, text=APP_TITLE, font=("Segoe UI", 20, "bold"), anchor="center", justify="center").pack()
        ttk.Label(
            header,
            text="Barebones UI prototype for the future SAMEStation Server installer flow. This mock does not install or modify anything.",
            wraplength=800,
            anchor="center",
            justify="center",
        ).pack(anchor="w", pady=(8, 0))

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

    def _clear_content(self) -> None:
        for child in self.content.winfo_children():
            child.destroy()

    def _mount_panel(self, title: str | None = None, *, padding: int = 12, height: int | None = None) -> ttk.Frame:
        panel_height = height or CONTENT_PANEL_HEIGHT
        host = ttk.Frame(self.content, width=CONTENT_PANEL_WIDTH, height=panel_height)
        host.place(
            relx=0.5,
            rely=0.0,
            anchor="n",
            width=CONTENT_PANEL_WIDTH,
            height=panel_height,
        )
        if title:
            panel = ttk.LabelFrame(host, text=title, padding=padding)
        else:
            panel = ttk.Frame(host, padding=padding)
        panel.pack(fill="both", expand=True)
        return panel

    def _show_step(self) -> None:
        self._clear_content()
        step_name = self.steps[self.current_step]
        self.step_label.configure(text=f"Step {self.current_step + 1} of {len(self.steps)}: {step_name}")

        if step_name == "Welcome":
            self._render_welcome()
        elif step_name == "Setup":
            self._render_setup()
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
            else:
                self.next_button.configure(text="Finish", state="normal")
        else:
            self.next_button.configure(text="Continue", state="normal")

    def _render_welcome(self) -> None:
        box = self._mount_panel(padding=12)
        ttk.Label(box, text="Install SAMEStation Server", font=("Segoe UI", 18, "bold"), anchor="center", justify="center").pack()
        ttk.Label(
            box,
            text="This prototype shows the future server installer flow for branch selection, install path, startup behavior, and storage options.",
            wraplength=720,
            anchor="center",
            justify="center",
        ).pack(pady=(10, 0))
        ttk.Label(
            box,
            text="Nothing here performs a real install. It is only a barebones UI mock for flow and layout.",
            wraplength=720,
            anchor="center",
            justify="center",
        ).pack(pady=(10, 0))

    def _render_setup(self) -> None:
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
        branch_box = ttk.Combobox(
            build_card,
            textvariable=self.channel_var,
            state="readonly",
            values=["Stable", "Nightly"],
            width=16,
        )
        branch_box.pack(anchor="w", pady=(4, 8))
        branch_box.bind("<<ComboboxSelected>>", lambda _event: self.release_notes_var.set(self._release_notes_text()))
        ttk.Label(build_card, text="Published Version").pack(anchor="w")
        ttk.Entry(build_card, textvariable=self.version_var, state="readonly", width=24).pack(anchor="w", pady=(6, 0))

        location_card = ttk.LabelFrame(right_column, text="Install Location", padding=10, width=SETUP_COLUMN_WIDTH, height=SETUP_CARD_HEIGHT_TOP)
        location_card.pack(fill="x", pady=(0, 8))
        location_card.pack_propagate(False)
        ttk.Label(location_card, text="Choose where the server build should live.").pack(anchor="w")
        row = ttk.Frame(location_card)
        row.pack(fill="x", pady=(6, 0))
        ttk.Entry(row, textvariable=self.install_path_var, width=32).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse", command=self._choose_folder).pack(side="left", padx=(8, 0))

        startup_card = ttk.LabelFrame(left_column, text="Startup", padding=10, width=SETUP_COLUMN_WIDTH, height=SETUP_CARD_HEIGHT_MID)
        startup_card.pack(fill="x", pady=(0, 8))
        startup_card.pack_propagate(False)
        ttk.Checkbutton(
            startup_card,
            text="Launch server when I sign in",
            variable=self.launch_at_login_var,
        ).pack(anchor="w")
        ttk.Checkbutton(
            startup_card,
            text="Open the web console after launch",
            variable=self.open_browser_var,
        ).pack(anchor="w", pady=(6, 0))
        ttk.Checkbutton(
            startup_card,
            text="Start the server after install",
            variable=self.start_after_install_var,
        ).pack(anchor="w", pady=(6, 0))
        ttk.Checkbutton(
            startup_card,
            text="Auto-start the monitor",
            variable=self.auto_start_monitor_var,
        ).pack(anchor="w", pady=(6, 0))

        notes_card = ttk.LabelFrame(right_column, text="Release Notes", padding=10, width=SETUP_COLUMN_WIDTH, height=SETUP_CARD_HEIGHT_MID)
        notes_card.pack(fill="x", pady=(0, 8))
        notes_card.pack_propagate(False)
        notes_label = ttk.Label(notes_card, text=self._release_notes_text(), wraplength=340, justify="left")
        notes_label.pack(anchor="w")

        def sync_notes(*_args) -> None:
            notes_label.configure(text=self._release_notes_text())

        self.channel_var.trace_add("write", sync_notes)

        misc_card = ttk.LabelFrame(left_column, text="Misc Data", padding=10, width=SETUP_COLUMN_WIDTH, height=SETUP_CARD_HEIGHT_BOTTOM)
        misc_card.pack(fill="x")
        misc_card.pack_propagate(False)
        ttk.Label(misc_card, text="General app data path").pack(anchor="w")
        misc_path_row = ttk.Frame(misc_card)
        misc_path_row.pack(fill="x", pady=(6, 0))
        misc_path_entry = ttk.Entry(misc_path_row, textvariable=self.misc_path_var, width=32)
        misc_path_entry.pack(side="left", fill="x", expand=True)
        misc_browse = ttk.Button(misc_path_row, text="Browse", command=lambda: self._choose_storage_folder("misc"))
        misc_browse.pack(side="left", padx=(8, 0))
        ttk.Label(
            misc_card,
            text="Default: inside the app folder.",
            wraplength=340,
        ).pack(anchor="w", pady=(8, 0))

        recordings_card = ttk.LabelFrame(right_column, text="Recordings", padding=10, width=SETUP_COLUMN_WIDTH, height=SETUP_CARD_HEIGHT_BOTTOM)
        recordings_card.pack(fill="x")
        recordings_card.pack_propagate(False)
        ttk.Label(recordings_card, text="Alert recordings path").pack(anchor="w")
        recordings_path_row = ttk.Frame(recordings_card)
        recordings_path_row.pack(fill="x", pady=(6, 0))
        recordings_path_entry = ttk.Entry(recordings_path_row, textvariable=self.recordings_path_var, width=32)
        recordings_path_entry.pack(side="left", fill="x", expand=True)
        recordings_browse = ttk.Button(recordings_path_row, text="Browse", command=lambda: self._choose_storage_folder("recordings"))
        recordings_browse.pack(side="left", padx=(8, 0))
        ttk.Label(
            recordings_card,
            text="Default: Documents\\SAMEStation Recordings.",
            wraplength=340,
        ).pack(anchor="w", pady=(8, 0))

    def _render_review(self) -> None:
        box = self._mount_panel("Ready To Install", padding=18)

        summary_lines = [
            f"Build channel: {self.channel_var.get()}",
            f"Published version: {self.version_var.get()}",
            f"Install path: {self.install_path_var.get()}",
            f"Launch at sign-in: {'On' if self.launch_at_login_var.get() else 'Off'}",
            f"Open browser after launch: {'On' if self.open_browser_var.get() else 'Off'}",
            f"Start server after install: {'On' if self.start_after_install_var.get() else 'Off'}",
            f"Auto-start monitor: {'On' if self.auto_start_monitor_var.get() else 'Off'}",
            f"Misc storage path: {self.misc_path_var.get()}",
            f"Recordings storage path: {self.recordings_path_var.get()}",
        ]
        ttk.Label(box, text="Review the mock installer choices below.", anchor="center", justify="center").pack()
        review = tk.Text(box, height=13, width=78, wrap="word")
        review.pack(pady=(12, 0))
        review.insert("1.0", "\n".join(summary_lines))
        review.configure(state="disabled")

    def _render_install(self) -> None:
        box = self._mount_panel("Installing SAMEStation Server", padding=18)

        if self.installing:
            ttk.Label(box, textvariable=self.status_var, wraplength=720, anchor="center", justify="center").pack()
            ttk.Progressbar(box, maximum=100, variable=self.progress_var).pack(fill="x", pady=(12, 12))

            log = tk.Text(box, height=14, width=78, wrap="word")
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
            return

        ttk.Label(box, text="SAMEStation Server Is Ready", font=("Segoe UI", 16, "bold"), anchor="center", justify="center").pack()
        ttk.Label(
            box,
            text="This is the finish screen for the condensed installer mock.",
            wraplength=720,
            anchor="center",
            justify="center",
        ).pack(pady=(10, 0))
        ttk.Label(
            box,
            text="Pretend server URL: http://127.0.0.1:8000",
            wraplength=720,
            anchor="center",
            justify="center",
        ).pack(pady=(12, 0))
        ttk.Label(
            box,
            text="A real build would offer launch and open-console actions here.",
            wraplength=720,
            anchor="center",
            justify="center",
        ).pack(pady=(10, 0))

    def _release_notes_text(self) -> str:
        notes = RELEASE_NOTES.get(self.channel_var.get(), RELEASE_NOTES["Stable"])
        return "\n".join(f"- {line}" for line in notes)

    def _choose_folder(self) -> None:
        folder = filedialog.askdirectory(title="Choose Install Folder")
        if folder:
            self.install_path_var.set(folder)
            self._sync_storage_paths()

    def _default_misc_path(self) -> str:
        return str(Path(self.install_path_var.get()) / "data")

    def _default_recordings_path(self) -> str:
        return str(Path.home() / "Documents" / "SAMEStation Recordings")

    def _sync_storage_paths(self) -> None:
        if not self.misc_path_var.get():
            self.misc_path_var.set(self._default_misc_path())
        if not self.recordings_path_var.get():
            self.recordings_path_var.set(self._default_recordings_path())

    def _choose_storage_folder(self, kind: str) -> None:
        title = "Choose Misc Data Folder" if kind == "misc" else "Choose Recordings Folder"
        folder = filedialog.askdirectory(title=title)
        if not folder:
            return
        if kind == "misc":
            self.misc_path_var.set(folder)
        else:
            self.recordings_path_var.set(folder)

    def _previous_step(self) -> None:
        if self.installing or self.current_step <= 0:
            return
        self.current_step -= 1
        self._show_step()

    def _next_step(self) -> None:
        step_name = self.steps[self.current_step]
        if step_name == "Review":
            self.current_step = self.steps.index("Install")
            self._show_step()
            self._start_fake_install()
            return
        if step_name == "Install":
            if not self.installing:
                self.root.destroy()
            return
        if self.current_step < len(self.steps) - 1:
            self.current_step += 1
            self._show_step()

    def _start_fake_install(self) -> None:
        self.installing = True
        self.progress_var.set(0)
        self.status_var.set("Preparing mock install...")
        self.log_var.set("")
        self._refresh_next_button()

        steps = [
            (10, "Checking selected branch channel...", "Resolved installer channel and mock version information."),
            (28, "Preparing server package...", "Prepared the SAMEStation Server package layout."),
            (46, "Checking install path...", "Verified the selected install folder layout."),
            (64, "Configuring startup options...", "Applied login-start and browser-launch mock settings."),
            (82, "Saving storage preferences...", "Captured the selected misc and recordings storage settings."),
            (100, "Finishing install...", "Installation mock complete. SAMEStation Server is ready."),
        ]

        def advance(index: int = 0) -> None:
            if index >= len(steps):
                self.installing = False
                self.status_var.set("Installation mock complete.")
                self._show_step()
                return
            progress, status, line = steps[index]
            self.progress_var.set(progress)
            self.status_var.set(status)
            current_log = self.log_var.get()
            self.log_var.set(f"{current_log}{line}\n" if current_log else f"{line}\n")
            self.root.after(450, lambda: advance(index + 1))

        advance()

    def run(self) -> None:
        self.root.mainloop()


def auto_clean_previous_instances() -> None:
    current_pid = os.getpid()
    marker_checks = " -or ".join([f"$cmd -like '*{marker}*'" for marker in MOCK_PROCESS_MARKERS])
    command = f"""
$ErrorActionPreference = 'SilentlyContinue'
$currentPid = {current_pid}
Get-CimInstance Win32_Process |
  Where-Object {{ $_.ProcessId -ne $currentPid }} |
  ForEach-Object {{
    $cmd = $_.CommandLine
    if ({marker_checks}) {{
      Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }}
  }}
"""
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
        creationflags=creationflags,
    )


def main() -> None:
    auto_clean_previous_instances()
    ServerInstallerMock().run()


if __name__ == "__main__":
    main()
