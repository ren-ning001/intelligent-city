"""Prepare the DSH koffi sidecar needed by the bundled Windows runtime.

Some `deepseek-harness-runtime-bin` wheels embed the build-time path
``F:\\snapshot\\node\\...`` for ``@koromix/koffi``. The runtime then starts but
every Agent turn ends with ``turn/end: error`` and the UI shows the empty
response fallback. This script downloads the locked Office/koffi sidecar into
``Datasets/runtime/dsh-resources`` (inside the project, not the home cache).

If the runtime's Windows cache publish step fails after downloading all
archives, the script reconstructs the expected sidecar layout from those
archives. Rerunning is safe: a complete sidecar is reused.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = PROJECT_ROOT / "Datasets" / "runtime" / "dsh-resources"
NODE_PTY_VERSION = "1.2.0-beta.15"
NODE_PTY_URL = (
    "https://registry.npmjs.org/node-pty/-/node-pty-"
    f"{NODE_PTY_VERSION}.tgz"
)
NODE_PTY_ROOT = CACHE_ROOT / "node-pty"
NODE_PTY_TARGET = NODE_PTY_ROOT / "node_modules" / "node-pty"


def _node_pty_valid() -> bool:
    return (
        (NODE_PTY_TARGET / "lib" / "index.js").is_file()
        and (NODE_PTY_TARGET / "prebuilds" / "win32-x64" / "conpty.node").is_file()
    )


def _ensure_node_pty() -> Path:
    """Install the matching node-pty package used by the bundled pwsh tool."""
    if _node_pty_valid():
        return NODE_PTY_TARGET
    NODE_PTY_ROOT.mkdir(parents=True, exist_ok=True)
    archive = NODE_PTY_ROOT / f"node-pty-{NODE_PTY_VERSION}.tgz"
    if not archive.is_file():
        print(f"  下载 node-pty {NODE_PTY_VERSION}（用于 pwsh 的 conpty）")
        urllib.request.urlretrieve(NODE_PTY_URL, archive)
    NODE_PTY_TARGET.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as handle:
        for member in handle.getmembers():
            if not member.name.startswith("package/"):
                continue
            member.name = member.name[len("package/") :]
            if not member.name:
                continue
            try:
                handle.extract(member, NODE_PTY_TARGET, filter="data")
            except TypeError:
                handle.extract(member, NODE_PTY_TARGET)
    if not _node_pty_valid():
        raise RuntimeError(f"node-pty 安装不完整：{NODE_PTY_TARGET}")
    return NODE_PTY_TARGET


def _manifest() -> dict:
    from deepseek_harness_runtime import bundled_package_dir

    path = bundled_package_dir() / "runtime" / "win-x64" / "downloads.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _valid(office: Path) -> bool:
    return (
        (office / "complete").is_file()
        and (office / "node_modules" / "koffi" / "index.js").is_file()
        and (
            office
            / "node_modules"
            / "@koromix"
            / "koffi-win32-x64"
            / "win32_x64"
            / "koffi.node"
        ).is_file()
        and (office / "node" / "bin" / "node.exe").is_file()
    )


def _package_name(archive: Path) -> str | None:
    try:
        if tarfile.is_tarfile(archive):
            with tarfile.open(archive) as handle:
                member = handle.extractfile("package/package.json")
                return json.load(member)["name"] if member else None
        with zipfile.ZipFile(archive) as handle:
            return json.loads(handle.read("package/package.json"))["name"]
    except (KeyError, json.JSONDecodeError, OSError, tarfile.TarError, zipfile.BadZipFile):
        return None


def _extract_package(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    if tarfile.is_tarfile(archive):
        with tarfile.open(archive) as handle:
            for member in handle.getmembers():
                if not member.name.startswith("package/"):
                    continue
                member.name = member.name[len("package/") :]
                if not member.name:
                    continue
                try:
                    handle.extract(member, destination, filter="data")
                except TypeError:
                    handle.extract(member, destination)
        return
    with zipfile.ZipFile(archive) as handle:
        for name in handle.namelist():
            if not name.startswith("package/"):
                continue
            target = destination / name[len("package/") :]
            if name.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with handle.open(name) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _extract_node_runtime(archive: Path, office: Path) -> None:
    node_dir = office / "node"
    with zipfile.ZipFile(archive) as handle:
        for name in handle.namelist():
            parts = name.split("/", 1)
            if len(parts) != 2 or not parts[1]:
                continue
            target = node_dir / parts[1]
            if name.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with handle.open(name) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
    node_exe = node_dir / "node.exe"
    bin_dir = node_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    if node_exe.is_file() and not (bin_dir / "node.exe").is_file():
        shutil.copy2(node_exe, bin_dir / "node.exe")


def _rebuild_from_archives(identity: str) -> Path:
    root = CACHE_ROOT / identity
    archives = root / "archives"
    office = root / "office"
    if not archives.is_dir():
        raise FileNotFoundError(
            f"没有可用的 DSH 归档缓存：{archives}。请联网后重新运行本脚本。"
        )
    modules = office / "node_modules"
    modules.mkdir(parents=True, exist_ok=True)
    node_archive: Path | None = None
    for archive in sorted(archives.iterdir()):
        if not archive.is_file():
            continue
        name = _package_name(archive)
        if name:
            print(f"  解包 {name}")
            _extract_package(archive, modules / name)
        elif zipfile.is_zipfile(archive):
            node_archive = archive
    if node_archive is not None:
        print("  解包 Node 运行时")
        _extract_node_runtime(node_archive, office)
    (office / "complete").write_text(identity, encoding="utf-8")
    return office


def main() -> int:
    if sys.platform != "win32":
        print("该兼容处理只用于 Windows 的捆绑 DSH 运行时。")
        return 0
    try:
        pty = _ensure_node_pty()
        print(f"node-pty sidecar 已就绪：{pty}")
    except Exception as error:  # noqa: BLE001 - pwsh is optional for GIS tools
        print(f"node-pty sidecar 准备失败（{type(error).__name__}: {error}）")
        print("Agent 的地理工具仍可工作，但 pwsh 工具可能失败。")

    manifest = _manifest()
    identity = manifest["identity"]
    office = CACHE_ROOT / identity / "office"
    if _valid(office):
        print(f"DSH koffi sidecar 已就绪：{office}")
        return 0

    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    os.environ["DSH_RESOURCE_CACHE"] = str(CACHE_ROOT)
    try:
        from deepseek_harness_runtime import download_office

        downloaded = download_office()
        if _valid(Path(downloaded)):
            print(f"DSH koffi sidecar 已下载：{downloaded}")
            return 0
    except Exception as error:  # noqa: BLE001 - fall back to cached archives
        print(f"download_office 未完成（{type(error).__name__}: {error}）")
        print("尝试从已下载归档重建 sidecar…")

    office = _rebuild_from_archives(identity)
    if not _valid(office):
        print(f"sidecar 仍不完整：{office}")
        return 1
    print(f"DSH koffi sidecar 已重建：{office}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
