from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from same_paths import app_root, resource_root


GITHUB_OWNER = "thyshorttimmy"
GITHUB_REPO = "SAMEStation"
APP_EXE_NAME = "SAMEStation.exe"
INSTALLER_EXE_NAME = "SAMEStation Installer.exe"
USER_AGENT = f"{GITHUB_REPO}-updater/1.0"
UPDATE_CHANNELS = {
    "stable": {
        "label": "Stable",
        "prerelease": False,
    },
    "test": {
        "label": "Test",
        "prerelease": True,
    },
}


@dataclass
class ReleaseAsset:
    name: str
    download_url: str
    size: int


@dataclass
class ReleaseInfo:
    channel: str
    tag_name: str
    name: str
    prerelease: bool
    published_at: str
    html_url: str
    assets: dict[str, ReleaseAsset]


@dataclass
class UpdateCheckResult:
    channel: str
    current_version: str
    available: bool
    release: ReleaseInfo | None
    message: str


def normalize_update_channel(raw_channel: str | None) -> str:
    value = (raw_channel or "stable").strip().lower()
    if value not in UPDATE_CHANNELS:
        raise ValueError("Update channel must be stable or test.")
    return value


def build_info_path_candidates() -> list[Path]:
    return [
        resource_root() / "build_info.json",
        app_root() / "build_info.json",
        Path(__file__).resolve().parent / "build_info.json",
    ]


def read_build_info() -> dict[str, object]:
    for candidate in build_info_path_candidates():
        try:
            if candidate.exists():
                return json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
    info = read_git_build_info()
    return info if info is not None else {}


def read_git_build_info() -> dict[str, object] | None:
    repo_dir = Path(__file__).resolve().parent
    git_path = shutil_which("git")
    if git_path is None:
        return None
    commit = run_git_capture(git_path, repo_dir, "rev-parse", "HEAD")
    describe = run_git_capture(git_path, repo_dir, "describe", "--tags", "--always", "--dirty")
    branch = run_git_capture(git_path, repo_dir, "rev-parse", "--abbrev-ref", "HEAD")
    if commit is None and describe is None:
        return None
    return {
        "versionTag": describe or "local-source",
        "commit": commit,
        "sourceBranch": branch,
    }


def run_git_capture(git_path: str, repo_dir: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            [git_path, *args],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:  # noqa: BLE001
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def shutil_which(program: str) -> str | None:
    from shutil import which

    return which(program)


def current_version_label() -> str:
    build_info = read_build_info()
    version_tag = str(build_info.get("versionTag") or "").strip()
    commit = str(build_info.get("commit") or "").strip()
    if version_tag:
        return version_tag
    if commit:
        return commit[:7]
    return "unknown build"


def current_version_tag() -> str | None:
    build_info = read_build_info()
    value = str(build_info.get("versionTag") or "").strip()
    return value or None


def github_request(url: str) -> object:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_latest_release(channel: str) -> ReleaseInfo:
    normalized_channel = normalize_update_channel(channel)
    if normalized_channel == "stable":
        payload = github_request(f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest")
        return release_from_payload(normalized_channel, payload)

    payload = github_request(f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases?per_page=20")
    if not isinstance(payload, list):
        raise RuntimeError("Unexpected GitHub release response.")
    for item in payload:
        if bool(item.get("prerelease")) and not bool(item.get("draft")):
            return release_from_payload(normalized_channel, item)
    raise RuntimeError("No test build is currently published.")


def release_from_payload(channel: str, payload: object) -> ReleaseInfo:
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected GitHub release payload.")
    assets: dict[str, ReleaseAsset] = {}
    for asset_payload in payload.get("assets", []):
        name = str(asset_payload.get("name") or "").strip()
        download_url = str(asset_payload.get("browser_download_url") or "").strip()
        if not name or not download_url:
            continue
        assets[name] = ReleaseAsset(
            name=name,
            download_url=download_url,
            size=int(asset_payload.get("size") or 0),
        )
    return ReleaseInfo(
        channel=channel,
        tag_name=str(payload.get("tag_name") or "").strip(),
        name=str(payload.get("name") or "").strip(),
        prerelease=bool(payload.get("prerelease")),
        published_at=str(payload.get("published_at") or "").strip(),
        html_url=str(payload.get("html_url") or "").strip(),
        assets=assets,
    )


def check_for_updates(channel: str) -> UpdateCheckResult:
    normalized_channel = normalize_update_channel(channel)
    current_version = current_version_label()
    channel_label = UPDATE_CHANNELS[normalized_channel]["label"]
    try:
        release = fetch_latest_release(normalized_channel)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return UpdateCheckResult(
                channel=normalized_channel,
                current_version=current_version,
                available=False,
                release=None,
                message=f"No {channel_label.lower()} build is currently published.",
            )
        return UpdateCheckResult(
            channel=normalized_channel,
            current_version=current_version,
            available=False,
            release=None,
            message=f"Unable to check {channel_label} updates: HTTP {exc.code}",
        )
    except urllib.error.URLError as exc:
        return UpdateCheckResult(
            channel=normalized_channel,
            current_version=current_version,
            available=False,
            release=None,
            message=f"Unable to contact GitHub for {channel_label} updates: {exc.reason}",
        )
    except Exception as exc:  # noqa: BLE001
        return UpdateCheckResult(
            channel=normalized_channel,
            current_version=current_version,
            available=False,
            release=None,
            message=f"Unable to check {channel_label} updates: {exc}",
        )

    current_tag = current_version_tag()
    if current_tag and release.tag_name and current_tag == release.tag_name:
        return UpdateCheckResult(
            channel=normalized_channel,
            current_version=current_version,
            available=False,
            release=release,
            message=f"Installed build {current_version} is already on the latest {channel_label.lower()} release.",
        )

    return UpdateCheckResult(
        channel=normalized_channel,
        current_version=current_version,
        available=True,
        release=release,
        message=f"{channel_label} update available: {release.tag_name or release.name or 'new build'}",
    )


def installer_path() -> Path:
    if getattr(sys, "frozen", False):
        return app_root() / INSTALLER_EXE_NAME
    return Path(__file__).resolve().parent / "samestation_installer.py"


def build_installer_command(
    *,
    channel: str,
    mode: str | None = None,
    install_now: bool = False,
    auto_install_dependencies: bool = True,
    start_app_after: bool = False,
    wait_for_pids: list[int] | None = None,
) -> list[str]:
    normalized_channel = normalize_update_channel(channel)
    target = installer_path()
    command: list[str]
    if getattr(sys, "frozen", False):
        command = [str(target)]
    else:
        command = [str(Path(sys.executable).resolve()), str(target)]
    command.extend(["--channel", normalized_channel])
    if mode:
        command.extend(["--mode", mode])
    if install_now:
        command.append("--install-now")
    if auto_install_dependencies:
        command.append("--auto-install-dependencies")
    if start_app_after:
        command.append("--start-app-after")
    for pid in wait_for_pids or []:
        if int(pid) > 0:
            command.extend(["--wait-for-pid", str(int(pid))])
    return command


def launch_installer(
    *,
    channel: str,
    mode: str | None = None,
    install_now: bool = False,
    auto_install_dependencies: bool = True,
    start_app_after: bool = False,
    wait_for_pids: list[int] | None = None,
) -> subprocess.Popen[bytes]:
    command = build_installer_command(
        channel=channel,
        mode=mode,
        install_now=install_now,
        auto_install_dependencies=auto_install_dependencies,
        start_app_after=start_app_after,
        wait_for_pids=wait_for_pids,
    )
    creationflags = 0
    if sys.platform.startswith("win"):
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(
        command,
        cwd=str(app_root()),
        creationflags=creationflags,
        close_fds=True,
    )
