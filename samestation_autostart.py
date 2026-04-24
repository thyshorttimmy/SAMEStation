from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from samestation_runtime import ModeName
from samestation_distribution import ProductRole


AUTO_START_TASK_NAME = "SAMEStation Auto Start"
SERVER_AUTO_START_TASK_NAME = "SAMEStation Server Auto Start"
CLIENT_AUTO_START_TASK_NAME = "SAMEStation Client Auto Start"
DEFAULT_PORT = 8000
DEFAULT_SERVER_URL = f"http://127.0.0.1:{DEFAULT_PORT}"


def quote_windows_arg(value: str) -> str:
    escaped = str(value).replace('"', '\\"')
    return f'"{escaped}"'


def is_windows_auto_start_enabled() -> bool:
    command = [
        "schtasks",
        "/Query",
        "/TN",
        AUTO_START_TASK_NAME,
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    return result.returncode == 0


def auto_start_task_name_for_role(role: ProductRole | str) -> str:
    normalized = str(role).strip().lower()
    if normalized == "server":
        return SERVER_AUTO_START_TASK_NAME
    if normalized == "client":
        return CLIENT_AUTO_START_TASK_NAME
    raise ValueError("Auto-start role must be server or client.")


def is_product_auto_start_enabled(role: ProductRole | str) -> bool:
    command = [
        "schtasks",
        "/Query",
        "/TN",
        auto_start_task_name_for_role(role),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    return result.returncode == 0


def build_auto_start_command_args(
    *,
    mode: ModeName,
    server_url: str = DEFAULT_SERVER_URL,
    port: int = DEFAULT_PORT,
    auto_start_monitor: bool = False,
    auto_start_device_id: int | None = None,
    auto_start_pre_roll: int | None = None,
    auto_start_max_record: int | None = None,
) -> list[str]:
    args = [f"--{mode}"]
    if mode == "client":
        args.extend(["--server-url", server_url])
    if mode in {"server", "both"}:
        args.extend(["--port", str(port)])
        if auto_start_monitor:
            args.append("--auto-start-monitor")
        if auto_start_device_id is not None:
            args.extend(["--device-id", str(auto_start_device_id)])
        if auto_start_pre_roll is not None:
            args.extend(["--pre-roll", str(auto_start_pre_roll)])
        if auto_start_max_record is not None:
            args.extend(["--max-record", str(auto_start_max_record)])
    return args


def build_auto_start_command_line(
    *,
    mode: ModeName,
    server_url: str = DEFAULT_SERVER_URL,
    port: int = DEFAULT_PORT,
    auto_start_monitor: bool = False,
    auto_start_device_id: int | None = None,
    auto_start_pre_roll: int | None = None,
    auto_start_max_record: int | None = None,
) -> str:
    args = build_auto_start_command_args(
        mode=mode,
        server_url=server_url,
        port=port,
        auto_start_monitor=auto_start_monitor,
        auto_start_device_id=auto_start_device_id,
        auto_start_pre_roll=auto_start_pre_roll,
        auto_start_max_record=auto_start_max_record,
    )
    if getattr(sys, "frozen", False):
        executable = str(Path(sys.executable).resolve())
        parts = [quote_windows_arg(executable), *[quote_windows_arg(arg) for arg in args]]
    else:
        script = str((Path(__file__).resolve().parent / "samestation_launcher.py").resolve())
        python_executable = str(Path(sys.executable).resolve())
        parts = [quote_windows_arg(python_executable), quote_windows_arg(script), *[quote_windows_arg(arg) for arg in args]]
    return " ".join(parts)


def sync_windows_auto_start(
    *,
    enabled: bool,
    mode: ModeName,
    server_url: str = DEFAULT_SERVER_URL,
    port: int = DEFAULT_PORT,
    auto_start_monitor: bool = False,
    auto_start_device_id: int | None = None,
    auto_start_pre_roll: int | None = None,
    auto_start_max_record: int | None = None,
) -> None:
    if enabled:
        command_line = build_auto_start_command_line(
            mode=mode,
            server_url=server_url,
            port=port,
            auto_start_monitor=auto_start_monitor,
            auto_start_device_id=auto_start_device_id,
            auto_start_pre_roll=auto_start_pre_roll,
            auto_start_max_record=auto_start_max_record,
        )
        command = [
            "schtasks",
            "/Create",
            "/TN",
            AUTO_START_TASK_NAME,
            "/SC",
            "ONLOGON",
            "/RL",
            "LIMITED",
            "/TR",
            command_line,
            "/F",
        ]
    else:
        command = [
            "schtasks",
            "/Delete",
            "/TN",
            AUTO_START_TASK_NAME,
            "/F",
        ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if enabled and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Unable to create auto-start task.")
    if not enabled and result.returncode not in {0, 1}:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Unable to remove auto-start task.")


def sync_product_windows_auto_start(
    *,
    role: ProductRole | str,
    enabled: bool,
    executable_path: str | Path,
    server_url: str = DEFAULT_SERVER_URL,
    open_browser: bool = False,
    headless: bool = True,
) -> None:
    task_name = auto_start_task_name_for_role(role)
    target = Path(executable_path).resolve()
    if enabled:
        parts = [quote_windows_arg(str(target))]
        normalized_role = str(role).strip().lower()
        if normalized_role == "server":
            if headless:
                parts.append(quote_windows_arg("--headless"))
            if open_browser:
                parts.append(quote_windows_arg("--open-browser"))
        elif normalized_role == "client":
            if server_url:
                parts.append(quote_windows_arg("--server-url"))
                parts.append(quote_windows_arg(server_url))
        else:
            raise ValueError("Auto-start role must be server or client.")
        command = [
            "schtasks",
            "/Create",
            "/TN",
            task_name,
            "/SC",
            "ONLOGON",
            "/RL",
            "LIMITED",
            "/TR",
            " ".join(parts),
            "/F",
        ]
    else:
        command = [
            "schtasks",
            "/Delete",
            "/TN",
            task_name,
            "/F",
        ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if enabled and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Unable to create product auto-start task.")
    if not enabled and result.returncode not in {0, 1}:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Unable to remove product auto-start task.")
