from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path
from typing import Literal


ModeName = Literal["server", "client", "both"]
DependencySpec = tuple[str, str, str, set[ModeName]]

RUNTIME_DEPENDENCIES: tuple[DependencySpec, ...] = (
    ("webview", "pywebview[winforms]", "pywebview", {"client", "server", "both"}),
    ("numpy", "numpy", "numpy", {"server", "both"}),
    ("sounddevice", "sounddevice", "sounddevice", {"server", "both"}),
    ("yt_dlp", "yt-dlp", "yt-dlp", {"server", "both"}),
    ("imageio_ffmpeg", "imageio-ffmpeg", "imageio-ffmpeg", {"server", "both"}),
)


def dependency_specs_for_mode(mode: ModeName) -> list[DependencySpec]:
    return [spec for spec in RUNTIME_DEPENDENCIES if mode in spec[3]]


def missing_dependencies_for_mode(mode: ModeName) -> list[DependencySpec]:
    missing: list[DependencySpec] = []
    for spec in dependency_specs_for_mode(mode):
        module_name = spec[0]
        try:
            importlib.import_module(module_name)
        except Exception:  # noqa: BLE001
            missing.append(spec)
    return missing


def format_missing_dependencies(missing: list[DependencySpec]) -> str:
    labels = [spec[2] for spec in missing]
    if not labels:
        return "All required dependencies are ready for this profile."
    return f"Missing dependencies: {', '.join(labels)}."


def install_missing_dependencies_for_mode(mode: ModeName) -> str:
    if getattr(sys, "frozen", False):
        return "The packaged build already includes its required dependencies."
    missing = missing_dependencies_for_mode(mode)
    if not missing:
        return "All required dependencies are already installed."
    package_specs: list[str] = []
    seen: set[str] = set()
    for _module_name, package_name, _label, _modes in missing:
        if package_name in seen:
            continue
        seen.add(package_name)
        package_specs.append(package_name)
    command = [str(Path(sys.executable).resolve()), "-m", "pip", "install", *package_specs]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Unable to install missing dependencies.")
    return f"Installed: {', '.join(package_specs)}"
