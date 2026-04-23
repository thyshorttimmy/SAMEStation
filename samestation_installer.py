from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import urllib.request
from pathlib import Path

from samestation_autostart import is_windows_auto_start_enabled, sync_windows_auto_start
from same_paths import app_root
from samestation_runtime import (
    ModeName,
    format_missing_dependencies,
    install_missing_dependencies_for_mode,
    missing_dependencies_for_mode,
)
from samestation_update import (
    APP_EXE_NAME,
    GITHUB_REPO,
    INSTALLER_EXE_NAME,
    UPDATE_CHANNELS,
    ReleaseAsset,
    ReleaseInfo,
    check_for_updates,
    current_version_label,
    normalize_update_channel,
)


LAUNCHER_SETTINGS_PATH = app_root() / "data" / "launcher-settings.json"


def normalize_mode(raw_mode: str) -> ModeName:
    value = (raw_mode or "").strip().lower()
    if value not in {"server", "client", "both"}:
        raise ValueError("Install profile must be server, client, or both.")
    return value


def ensure_launcher_settings_dir() -> None:
    LAUNCHER_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)


def load_launcher_settings() -> dict[str, object]:
    if not LAUNCHER_SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(LAUNCHER_SETTINGS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_install_preferences(*, mode: ModeName, channel: str, auto_start_with_windows: bool) -> None:
    ensure_launcher_settings_dir()
    settings = load_launcher_settings()
    settings["mode"] = mode
    settings["updateChannel"] = normalize_update_channel(channel)
    settings["autoStartWithWindows"] = bool(auto_start_with_windows)
    LAUNCHER_SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def dependency_status_for_mode(mode: ModeName) -> str:
    if getattr(sys, "frozen", False):
        return f"The packaged {GITHUB_REPO} build already includes the dependencies needed for {mode} mode."
    return format_missing_dependencies(missing_dependencies_for_mode(mode))


def maybe_install_dependencies(mode: ModeName, auto_install_dependencies: bool) -> list[str]:
    messages = [dependency_status_for_mode(mode)]
    if auto_install_dependencies:
        install_message = install_missing_dependencies_for_mode(mode)
        if install_message not in messages:
            messages.append(install_message)
    else:
        missing = missing_dependencies_for_mode(mode)
        if missing:
            raise RuntimeError(
                f"{format_missing_dependencies(missing)} Enable automatic dependency install or install them manually first."
            )
    return messages


def download_release_asset(asset: ReleaseAsset, destination: Path) -> Path:
    request = urllib.request.Request(
        asset.download_url,
        headers={
            "User-Agent": f"{GITHUB_REPO}-installer/1.0",
            "Accept": "application/octet-stream",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as file_handle:
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            file_handle.write(chunk)
    return destination


def queue_release_install(
    *,
    release: ReleaseInfo,
    install_dir: Path,
    wait_for_pids: list[int],
    start_app_after: bool,
) -> str:
    app_asset = release.assets.get(APP_EXE_NAME)
    if app_asset is None:
        raise RuntimeError(f"The selected release does not include {APP_EXE_NAME}.")
    installer_asset = release.assets.get(INSTALLER_EXE_NAME)

    staging_dir = Path(tempfile.mkdtemp(prefix="samestation-update-"))
    staged_app = download_release_asset(app_asset, staging_dir / APP_EXE_NAME)
    staged_installer = None
    if installer_asset is not None:
        staged_installer = download_release_asset(installer_asset, staging_dir / INSTALLER_EXE_NAME)

    script_path = staging_dir / "apply-update.ps1"
    launcher_path = install_dir / APP_EXE_NAME if start_app_after else None
    wait_values = [str(int(pid)) for pid in wait_for_pids if int(pid) > 0]
    wait_literal = ", ".join(f"'{value}'" for value in wait_values)
    installer_source = f"'{str(staged_installer)}'" if staged_installer is not None else "$null"
    installer_target = f"'{str(install_dir / INSTALLER_EXE_NAME)}'"
    launch_literal = f"'{str(launcher_path)}'" if launcher_path is not None else "$null"
    script_path.write_text(
        textwrap.dedent(
            f"""
            $ErrorActionPreference = 'Stop'
            $waitPids = @({wait_literal})
            foreach ($pidValue in $waitPids) {{
              if ([string]::IsNullOrWhiteSpace($pidValue)) {{
                continue
              }}
              $targetPid = [int]$pidValue
              while (Get-Process -Id $targetPid -ErrorAction SilentlyContinue) {{
                Start-Sleep -Milliseconds 400
              }}
            }}

            Copy-Item -LiteralPath '{str(staged_app)}' -Destination '{str(install_dir / APP_EXE_NAME)}' -Force

            if ({installer_source} -and (Test-Path -LiteralPath {installer_source})) {{
              Copy-Item -LiteralPath {installer_source} -Destination {installer_target} -Force
            }}

            if ({launch_literal}) {{
              Start-Process -FilePath {launch_literal}
            }}
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    creationflags = 0
    if sys.platform.startswith("win"):
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ],
        cwd=str(install_dir),
        creationflags=creationflags,
        close_fds=True,
    )
    return f"Queued {release.tag_name or release.name or release.channel} for installation."


def perform_install_or_update(
    *,
    channel: str,
    mode: ModeName,
    auto_install_dependencies: bool,
    auto_start_with_windows: bool,
    start_app_after: bool,
    wait_for_pids: list[int],
) -> str:
    normalized_channel = normalize_update_channel(channel)
    messages = maybe_install_dependencies(mode, auto_install_dependencies)
    save_install_preferences(mode=mode, channel=normalized_channel, auto_start_with_windows=auto_start_with_windows)
    if mode in {"server", "both"}:
        sync_windows_auto_start(
            enabled=bool(auto_start_with_windows),
            mode=mode,
        )
        if auto_start_with_windows:
            messages.append("Server launch at sign-in has been enabled for this install.")
        else:
            messages.append("Server launch at sign-in is disabled for this install.")
    else:
        sync_windows_auto_start(
            enabled=False,
            mode="server",
        )
        messages.append("Server launch at sign-in is disabled for this install.")
    update_check = check_for_updates(normalized_channel)
    messages.append(update_check.message)
    if update_check.release is None:
        if start_app_after and (app_root() / APP_EXE_NAME).exists():
            subprocess.Popen([str(app_root() / APP_EXE_NAME)], cwd=str(app_root()), close_fds=True)
        return "\n".join(messages)
    if not update_check.available:
        if start_app_after and (app_root() / APP_EXE_NAME).exists():
            subprocess.Popen([str(app_root() / APP_EXE_NAME)], cwd=str(app_root()), close_fds=True)
        return "\n".join(messages)
    queue_message = queue_release_install(
        release=update_check.release,
        install_dir=app_root(),
        wait_for_pids=wait_for_pids + [os.getpid()],
        start_app_after=start_app_after,
    )
    messages.append(queue_message)
    messages.append("Close this installer to let the file replacement finish.")
    return "\n".join(messages)


def show_installer_window(default_channel: str, default_mode: ModeName, auto_install_dependencies: bool) -> int:
    import tkinter as tk
    from tkinter import ttk

    auto_start_enabled = is_windows_auto_start_enabled()
    result = {
        "channel": default_channel,
        "mode": default_mode,
        "auto_install_dependencies": auto_install_dependencies,
        "auto_start_with_windows": auto_start_enabled if default_mode in {"server", "both"} else False,
        "start_app_after": True,
        "confirmed": False,
    }

    root = tk.Tk()
    root.title(f"Install {GITHUB_REPO}")
    root.geometry("700x720")
    root.minsize(660, 680)
    root.configure(bg="#f4f1e8")

    outer = ttk.Frame(root, padding=22)
    outer.pack(fill="both", expand=True)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    ttk.Label(outer, text=f"Install {GITHUB_REPO}", font=("Segoe UI", 18, "bold")).pack(anchor="w")
    ttk.Label(
        outer,
        text=f"Choose which branch channel to install, which profile this copy should default to, and whether dependencies should be checked automatically. Current build: {current_version_label()}",
        wraplength=600,
    ).pack(anchor="w", pady=(8, 16))

    channel_var = tk.StringVar(value=default_channel)
    mode_var = tk.StringVar(value=default_mode)
    auto_deps_var = tk.BooleanVar(value=auto_install_dependencies)
    auto_start_with_windows_var = tk.BooleanVar(value=bool(result["auto_start_with_windows"]))
    start_app_after_var = tk.BooleanVar(value=True)
    release_var = tk.StringVar(value="Press Check Latest Build to see what is available.")
    deps_var = tk.StringVar(value=dependency_status_for_mode(default_mode))
    error_var = tk.StringVar(value="")

    field = ttk.Frame(outer)
    field.pack(fill="x")
    ttk.Label(field, text="Install Branch").pack(anchor="w")
    channel_box = ttk.Combobox(
        field,
        textvariable=channel_var,
        state="readonly",
        values=[channel for channel in UPDATE_CHANNELS],
    )
    channel_box.pack(fill="x", pady=(6, 14))

    profile_frame = ttk.LabelFrame(outer, text="Install Profile", padding=14)
    profile_frame.pack(fill="x")
    for value, title, copy in (
        ("server", "Server", "Default this install to server mode and check the server-side dependencies."),
        ("client", "Client", "Default this install to client mode and check only the client-side dependencies."),
        ("both", "Both", "Default this install to both mode and check the full local bundle."),
    ):
        row = ttk.Frame(profile_frame)
        row.pack(fill="x", pady=4)
        ttk.Radiobutton(row, text=title, value=value, variable=mode_var).pack(anchor="w")
        ttk.Label(row, text=copy, wraplength=560).pack(anchor="w", padx=(24, 0))

    options_frame = ttk.Frame(outer)
    options_frame.pack(fill="x", pady=(16, 0))
    ttk.Checkbutton(
        options_frame,
        text="Automatically install missing dependencies for the selected profile",
        variable=auto_deps_var,
    ).pack(anchor="w")
    auto_start_checkbox = ttk.Checkbutton(
        options_frame,
        text="Install the server to launch automatically at sign-in",
        variable=auto_start_with_windows_var,
    )
    auto_start_checkbox.pack(anchor="w", pady=(8, 0))
    ttk.Checkbutton(
        options_frame,
        text=f"Reopen {GITHUB_REPO} when the install finishes",
        variable=start_app_after_var,
    ).pack(anchor="w", pady=(8, 0))

    status_frame = ttk.LabelFrame(outer, text="Status", padding=14)
    status_frame.pack(fill="x", pady=(18, 0))
    ttk.Label(status_frame, text="Dependencies").pack(anchor="w")
    ttk.Label(status_frame, textvariable=deps_var, wraplength=580).pack(anchor="w", pady=(4, 12))
    ttk.Label(status_frame, text="Latest Build").pack(anchor="w")
    ttk.Label(status_frame, textvariable=release_var, wraplength=580).pack(anchor="w", pady=(4, 0))

    def refresh_dependency_status(*_args) -> None:
        try:
            mode = normalize_mode(mode_var.get())
            deps_var.set(dependency_status_for_mode(mode))
            if mode == "client":
                auto_start_with_windows_var.set(False)
                auto_start_checkbox.configure(state="disabled")
            else:
                auto_start_checkbox.configure(state="normal")
        except ValueError as exc:
            deps_var.set(str(exc))

    def check_latest_build() -> None:
        error_var.set("")
        release_var.set("Checking GitHub for the selected branch channel...")
        root.update_idletasks()
        result_payload = check_for_updates(channel_var.get())
        release_var.set(result_payload.message)

    mode_var.trace_add("write", refresh_dependency_status)
    refresh_dependency_status()

    ttk.Label(outer, textvariable=error_var, foreground="#a32117", wraplength=600).pack(anchor="w", pady=(14, 0))

    actions = tk.Frame(root, bg="#efe5d4", padx=18, pady=14, highlightbackground="#d5c8af", highlightthickness=1)
    actions.pack(fill="x", side="bottom")

    def cancel() -> None:
        root.destroy()

    def install_now() -> None:
        try:
            result["channel"] = normalize_update_channel(channel_var.get())
            result["mode"] = normalize_mode(mode_var.get())
            result["auto_install_dependencies"] = bool(auto_deps_var.get())
            result["auto_start_with_windows"] = bool(auto_start_with_windows_var.get()) if result["mode"] in {"server", "both"} else False
            result["start_app_after"] = bool(start_app_after_var.get())
            release_var.set("Installing selected branch channel...")
            root.update_idletasks()
            message = perform_install_or_update(
                channel=result["channel"],
                mode=result["mode"],
                auto_install_dependencies=result["auto_install_dependencies"],
                auto_start_with_windows=result["auto_start_with_windows"],
                start_app_after=result["start_app_after"],
                wait_for_pids=[],
            )
            release_var.set(message)
            result["confirmed"] = True
            root.after(1200, root.destroy)
        except Exception as exc:  # noqa: BLE001
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
        text="Install / Update",
        command=install_now,
        width=18,
        padx=10,
        pady=6,
        bg="#b64926",
        fg="white",
        activebackground="#983c1e",
        activeforeground="white",
        relief="raised",
    ).pack(side="right", padx=(0, 10))
    ttk.Button(actions, text="Check Latest Build", command=check_latest_build).pack(side="left")

    root.protocol("WM_DELETE_WINDOW", cancel)
    root.mainloop()
    return 0 if result["confirmed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=f"Install or update {GITHUB_REPO}.")
    parser.add_argument("--channel", choices=tuple(UPDATE_CHANNELS), default="stable", help="Release channel to install.")
    parser.add_argument("--mode", choices=("server", "client", "both"), default="both", help="Default install profile to save.")
    parser.add_argument("--install-now", action="store_true", help="Install immediately without showing the installer window.")
    parser.add_argument("--check-only", action="store_true", help="Print the current update status and exit.")
    parser.add_argument("--auto-install-dependencies", action="store_true", help="Install missing dependencies before updating when running from source.")
    parser.add_argument("--auto-start-with-windows", action="store_true", help="Configure the installed server copy to launch automatically at sign-in.")
    parser.add_argument("--start-app-after", action="store_true", help=f"Start {GITHUB_REPO} again after the install finishes.")
    parser.add_argument("--wait-for-pid", action="append", type=int, default=[], help="Wait for the given process ID before replacing files.")
    args = parser.parse_args()

    channel = normalize_update_channel(args.channel)
    mode = normalize_mode(args.mode)

    if args.check_only:
        result = check_for_updates(channel)
        print(result.message)
        return 0

    if args.install_now:
        try:
            message = perform_install_or_update(
                channel=channel,
                mode=mode,
                auto_install_dependencies=bool(args.auto_install_dependencies),
                auto_start_with_windows=bool(args.auto_start_with_windows),
                start_app_after=bool(args.start_app_after),
                wait_for_pids=list(args.wait_for_pid),
            )
        except Exception as exc:  # noqa: BLE001
            print(exc, file=sys.stderr)
            return 1
        print(message)
        return 0

    return show_installer_window(channel, mode, bool(args.auto_install_dependencies))


if __name__ == "__main__":
    raise SystemExit(main())
