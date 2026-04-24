from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from same_paths import app_root, resource_root


ProductRole = Literal["server", "client"]
ReleaseChannel = Literal["stable", "nightly"]

GITHUB_OWNER = "thyshorttimmy"
GITHUB_REPO = "SAMEStation"
PAYLOAD_REPO = os.environ.get("SAMESTATION_PAYLOAD_REPO", GITHUB_REPO)
PAYLOAD_OWNER = os.environ.get("SAMESTATION_PAYLOAD_OWNER", GITHUB_OWNER)
USER_AGENT = f"{GITHUB_REPO}-distribution/1.0"

RELEASE_CHANNELS: dict[ReleaseChannel, dict[str, object]] = {
    "stable": {
        "label": "Stable",
        "prerelease": False,
    },
    "nightly": {
        "label": "Nightly",
        "prerelease": True,
    },
}


@dataclass(frozen=True)
class ProductSpec:
    role: ProductRole
    label: str
    short_label: str
    app_exe_name: str
    installer_exe_name: str
    app_script_name: str
    installer_script_name: str
    install_manifest_name: str
    runtime_config_name: str
    local_payload_dir_name: str


PRODUCTS: dict[ProductRole, ProductSpec] = {
    "server": ProductSpec(
        role="server",
        label="SAMEStation Server",
        short_label="Server",
        app_exe_name="SAMEStation Server.exe",
        installer_exe_name="SAMEStation Server Installer.exe",
        app_script_name="samestation_server.py",
        installer_script_name="samestation_server_installer.py",
        install_manifest_name="samestation-server-install.json",
        runtime_config_name="samestation-server.json",
        local_payload_dir_name="server",
    ),
    "client": ProductSpec(
        role="client",
        label="SAMEStation Client",
        short_label="Client",
        app_exe_name="SAMEStation Client.exe",
        installer_exe_name="SAMEStation Client Installer.exe",
        app_script_name="samestation_client.py",
        installer_script_name="samestation_client_installer.py",
        install_manifest_name="samestation-client-install.json",
        runtime_config_name="samestation-client.json",
        local_payload_dir_name="client",
    ),
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


def normalize_role(raw_role: str | None) -> ProductRole:
    value = (raw_role or "").strip().lower()
    if value not in PRODUCTS:
        raise ValueError("Product role must be server or client.")
    return value  # type: ignore[return-value]


def normalize_channel(raw_channel: str | None) -> ReleaseChannel:
    value = (raw_channel or "stable").strip().lower()
    if value == "test":
        value = "nightly"
    if value not in RELEASE_CHANNELS:
        raise ValueError("Release channel must be stable or nightly.")
    return value  # type: ignore[return-value]


def product_spec(role: ProductRole | str) -> ProductSpec:
    return PRODUCTS[normalize_role(str(role))]


def public_release_repo() -> tuple[str, str]:
    build_info = read_build_info()
    owner = str(build_info.get("repoOwner") or GITHUB_OWNER).strip() or GITHUB_OWNER
    repo = str(build_info.get("repoName") or GITHUB_REPO).strip() or GITHUB_REPO
    return owner, repo


def payload_release_repo() -> tuple[str, str]:
    return PAYLOAD_OWNER, PAYLOAD_REPO


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


def read_build_info() -> dict[str, object]:
    for candidate in build_info_path_candidates():
        try:
            if candidate.exists():
                return json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
    info = read_git_build_info()
    return info if info is not None else {}


def build_info_path_candidates() -> list[Path]:
    return [
        resource_root() / "build_info.json",
        app_root() / "build_info.json",
        Path(__file__).resolve().parent / "build_info.json",
    ]


def read_git_build_info() -> dict[str, object] | None:
    repo_dir = Path(__file__).resolve().parent
    git_path = shutil.which("git")
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


def release_from_payload(channel: ReleaseChannel, payload: object) -> ReleaseInfo:
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


def fetch_latest_public_installer_release(channel: ReleaseChannel | str) -> ReleaseInfo:
    normalized_channel = normalize_channel(str(channel))
    owner, repo = public_release_repo()
    if normalized_channel == "stable":
        payload = github_request(f"https://api.github.com/repos/{owner}/{repo}/releases/latest")
        return release_from_payload(normalized_channel, payload)

    payload = github_request(f"https://api.github.com/repos/{owner}/{repo}/releases?per_page=20")
    if not isinstance(payload, list):
        raise RuntimeError("Unexpected GitHub release response.")
    for item in payload:
        if bool(item.get("prerelease")) and not bool(item.get("draft")):
            return release_from_payload(normalized_channel, item)
    raise RuntimeError("No nightly installer build is currently published.")


def payload_release_tag_prefixes(role: ProductRole, channel: ReleaseChannel) -> tuple[str, ...]:
    legacy_channel = "test" if channel == "nightly" else channel
    return (
        f"payload-{role}-{channel}-",
        f"payload-{role}-{legacy_channel}-",
        f"internal-{role}-{channel}-",
        f"internal-{role}-{legacy_channel}-",
    )


def fetch_latest_payload_release(role: ProductRole | str, channel: ReleaseChannel | str) -> ReleaseInfo:
    normalized_role = normalize_role(str(role))
    normalized_channel = normalize_channel(str(channel))
    owner, repo = payload_release_repo()
    payload = github_request(f"https://api.github.com/repos/{owner}/{repo}/releases?per_page=50")
    if not isinstance(payload, list):
        raise RuntimeError("Unexpected payload release response.")
    expected_asset = product_spec(normalized_role).app_exe_name
    prefixes = payload_release_tag_prefixes(normalized_role, normalized_channel)
    for item in payload:
        if bool(item.get("draft")):
            continue
        tag_name = str(item.get("tag_name") or "").strip()
        if not any(tag_name.startswith(prefix) for prefix in prefixes):
            continue
        release = release_from_payload(normalized_channel, item)
        if expected_asset in release.assets:
            return release
    raise RuntimeError(
        f"No internal payload release is currently published for {product_spec(normalized_role).label} ({normalized_channel})."
    )


def local_payload_asset(role: ProductRole | str, channel: ReleaseChannel | str) -> Path | None:
    spec = product_spec(str(role))
    normalized_channel = normalize_channel(str(channel))
    candidates = [
        app_root() / "dist" / "internal-payloads" / normalized_channel / spec.app_exe_name,
        app_root() / "dist" / spec.app_exe_name,
        app_root() / spec.app_exe_name,
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def download_release_asset(asset: ReleaseAsset, destination: Path) -> Path:
    request = urllib.request.Request(
        asset.download_url,
        headers={
            "User-Agent": USER_AGENT,
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


def default_install_dir(role: ProductRole | str) -> Path:
    spec = product_spec(str(role))
    if os.name == "nt":
        program_files = Path(os.environ.get("ProgramFiles") or r"C:\Program Files")
        return program_files / spec.label
    return Path.home() / f".{spec.label.lower().replace(' ', '-')}"


def default_server_misc_path(install_dir: Path | str) -> Path:
    return Path(install_dir) / "data"


def default_server_recordings_path() -> Path:
    return Path.home() / "Documents" / "SAMEStation Recordings"


def install_manifest_path(install_dir: Path | str, role: ProductRole | str) -> Path:
    return Path(install_dir) / product_spec(str(role)).install_manifest_name


def runtime_config_path(install_dir: Path | str, role: ProductRole | str) -> Path:
    return Path(install_dir) / product_spec(str(role)).runtime_config_name


def load_install_manifest(install_dir: Path | str, role: ProductRole | str) -> dict[str, Any]:
    path = install_manifest_path(install_dir, role)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save_install_manifest(install_dir: Path | str, role: ProductRole | str, payload: dict[str, Any]) -> Path:
    path = install_manifest_path(install_dir, role)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_runtime_config(role: ProductRole | str, base_dir: Path | None = None) -> dict[str, Any]:
    path = runtime_config_path(base_dir or app_root(), role)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save_runtime_config(install_dir: Path | str, role: ProductRole | str, payload: dict[str, Any]) -> Path:
    path = runtime_config_path(install_dir, role)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def installed_version_label(install_dir: Path | str, role: ProductRole | str) -> str:
    manifest = load_install_manifest(install_dir, role)
    version = str(manifest.get("installedVersion") or "").strip()
    return version or "Not installed"


def public_release_summary(channel: ReleaseChannel | str) -> str:
    normalized_channel = normalize_channel(str(channel))
    label = str(RELEASE_CHANNELS[normalized_channel]["label"])
    try:
        release = fetch_latest_public_installer_release(normalized_channel)
    except urllib.error.HTTPError as exc:
        return f"Unable to check {label} installer builds: HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return f"Unable to contact GitHub for {label} installer builds: {exc.reason}"
    except Exception as exc:  # noqa: BLE001
        return f"Unable to check {label} installer builds: {exc}"
    return release.tag_name or release.name or f"{label} installer build available"
