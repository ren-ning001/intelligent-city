from __future__ import annotations

import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime configuration. Secrets remain in process environment only."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ZYourRoad"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    frontend_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    datasets_dir: Path = PROJECT_ROOT / "Datasets"
    dsh_home: Path = PROJECT_ROOT / ".dsh-home"
    dsh_profile: str = "sdk-minimal"
    dsh_provider: str = "deepseek-official"
    dsh_model: str = Field(
        default="deepseek-v4-flash",
        validation_alias="ZYOURROAD_DSH_MODEL",
    )
    dsh_max_tokens: int = 8192
    dsh_patch: Path = PROJECT_ROOT / "plugins" / "zyourroad-osm" / "cordis.patch.yml"
    deepseek_api_key: SecretStr | None = Field(default=None, alias="DEEPSEEK_API_KEY")

    max_query_radius_m: int = 10_000
    default_query_radius_m: int = 3_000
    overpass_timeout_seconds: int = 35
    overpass_failure_cooldown_seconds: int = 90
    overpass_endpoints: str = (
        "https://overpass-api.de/api,"
        "https://overpass.kumi.systems/api,"
        "https://overpass.nchc.org.tw/api"
    )

    def _export_koffi_sidecar(self) -> None:
        """Route the bundled runtime's broken koffi resolution to a real sidecar.

        Some Windows `deepseek-harness-runtime-bin` builds embed the build-time
        path `F:\\snapshot\\node\\...` for @koromix/koffi. The setup script
        downloads the locked koffi packages; the preload patches
        Module._resolveFilename and process.dlopen to use them. Without the
        sidecar the runtime still starts, but every turn ends with a native
        module error and the UI shows the empty-response fallback.
        """
        sidecar = self._dsh_office_sidecar()
        if sidecar is None:
            return
        entry = sidecar / "node_modules" / "koffi" / "index.js"
        platform_binary = (
            sidecar
            / "node_modules"
            / "@koromix"
            / "koffi-win32-x64"
            / "win32_x64"
            / "koffi.node"
        )
        loader = PROJECT_ROOT / "scripts" / "dsh_koffi_loader.cjs"
        if not loader.is_file():
            return
        os.environ["DSH_OFFICE_SIDECAR"] = str(sidecar)
        os.environ["DSH_KOFFI_ENTRY"] = entry.as_posix()
        os.environ["DSH_KOFFI_PLATFORM"] = platform_binary.as_posix()
        require_flag = f'--require "{loader.as_posix()}"'
        node_options = os.environ.get("NODE_OPTIONS", "").strip()
        if require_flag not in node_options:
            os.environ["NODE_OPTIONS"] = f"{node_options} {require_flag}".strip()

    def _export_node_pty(self) -> None:
        """Expose the real node-pty prebuild so the pwsh tool can spawn.

        The same single-file packaging problem also leaves `node-pty` without
        `prebuilds/win32-x64/conpty.node`. `scripts/prepare_dsh_runtime.py`
        installs the matching npm package; the preload redirects both the
        `node-pty` package and its native binary.
        """
        root = (
            PROJECT_ROOT
            / "Datasets"
            / "runtime"
            / "dsh-resources"
            / "node-pty"
            / "node_modules"
            / "node-pty"
        )
        entry = root / "lib" / "index.js"
        prebuild = root / "prebuilds" / "win32-x64"
        if not (entry.is_file() and (prebuild / "conpty.node").is_file()):
            return
        os.environ["DSH_NODE_PTY_ENTRY"] = entry.as_posix()
        os.environ["DSH_NODE_PTY_PREBUILD_DIR"] = prebuild.as_posix()
        # node-pty's useConptyDll mode loads conpty.dll/OpenConsole.exe from its
        # prebuild directory; make that directory visible even when the wrapper
        # itself came from the packaged snapshot.
        conpty_dir = (prebuild / "conpty").as_posix()
        path_parts = os.environ.get("PATH", "").split(os.pathsep)
        if conpty_dir not in path_parts:
            os.environ["PATH"] = os.pathsep.join([conpty_dir, *path_parts])

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]

    @property
    def deepseek_configured(self) -> bool:
        return bool(
            self.deepseek_api_key
            and self.deepseek_api_key.get_secret_value().strip()
        )

    @property
    def overpass_endpoint_list(self) -> list[str]:
        return [
            endpoint.strip().rstrip("/")
            for endpoint in self.overpass_endpoints.split(",")
            if endpoint.strip()
        ]

    @property
    def dsh_sessions_dir(self) -> Path:
        return self.dsh_home / "sessions"

    def _dsh_office_sidecar(self) -> Path | None:
        """Return a usable koffi/office sidecar prepared by the setup script."""
        root = PROJECT_ROOT / "Datasets" / "runtime" / "dsh-resources"
        if not root.is_dir():
            return None
        for entry in sorted(root.glob("*/office/node_modules/koffi/index.js")):
            office = entry.parents[2]
            platform_binary = (
                office
                / "node_modules"
                / "@koromix"
                / "koffi-win32-x64"
                / "win32_x64"
                / "koffi.node"
            )
            if (
                entry.is_file()
                and platform_binary.is_file()
                and (office / "complete").is_file()
            ):
                return office
        return None

    def export_dsh_environment(self) -> None:
        """Expose only paths and non-secret prompt defaults to the DSH subprocess."""
        self.dsh_sessions_dir.mkdir(parents=True, exist_ok=True)
        os.environ["ZYOURROAD_ROOT"] = str(PROJECT_ROOT)
        os.environ["ZYOURROAD_PYTHON"] = sys.executable
        os.environ["ZYOURROAD_SESSION_ROOT"] = str(self.dsh_sessions_dir)
        pwsh = (
            os.environ.get("ZYOURROAD_PWSH_PATH")
            or shutil.which("pwsh")
            or shutil.which("powershell")
            or str(
                Path(os.environ.get("SystemRoot", r"C:\Windows"))
                / "System32"
                / "WindowsPowerShell"
                / "v1.0"
                / "powershell.exe"
            )
        )
        if pwsh:
            os.environ["ZYOURROAD_PWSH_PATH"] = pwsh
        self._export_koffi_sidecar()
        self._export_node_pty()
        os.environ.setdefault(
            "DSH_SYSTEM_PROMPT",
            (
                "你是 ZYourRoad 城市旅游路径规划 Agent。必须优先调用 zyourroad MCP 工具"
                "获取真实地点、POI、路网和路线；不得编造距离、坐标或景点。先确认约束，"
                "再查询数据、规划、验证。选定最终地点后，必须且只能调用一次"
                "publish_tourism_itinerary：points按最终游览顺序包含全部地点；遇到轮渡、"
                "地铁等非步行衔接时，把后一段首个地点的零基索引放入"
                "break_before_indexes。不要用多次plan_walking_route发布最终路线。"
                "最终回答使用简洁中文，重点给出地点顺序、总距离、预计时间"
                "和一条必要提示；除非异常会阻断规划，不要展示坐标、缓存名、工具调用过程"
                "或内部调试信息。用户没有指定起终点但给了多个想去的地点时，可按合理顺序"
                "连接这些地点，不要强迫用户补起终点；只有关键约束确实缺失时才追问一次。"
                "同一轮最多查询一次同类POI，避免为同一地点反复地理编码或尝试大量候选路线；"
                "当待排序景点达到2个（含起点至少3个点）且需要比较游览顺序时，"
                "先调用一次 optimize_itinerary_order 获取确定性顺序，再按返回的 names 顺序发布；"
                "距离口径用 weight=length，用户明确优先时间时用 weight=time；"
                "顺序优化用了哪种 weight，发布时也必须传同一种 weight，保证路线几何与排序口径一致；"
                "用户要求回到起点时用 closed_loop=true。回答中必须明确非步行段的换乘方式。"
                "新城市先调用 prepare_osm_region 一次准备缓存；如果工具明确报告上游数据源"
                "暂时不可用，同一轮不要重复调用或缩放范围碰运气，直接简短说明并结束。"
                "不要用 list_mcp_resources、list_mcp_resource_templates 或 pwsh 去探测"
                "可用工具/路网：zyourroad 的地理工具已直接可用；只有用户明确要求检查"
                "本地文件时才使用 pwsh。"
            ),
        )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.datasets_dir.mkdir(parents=True, exist_ok=True)
    settings.dsh_home.mkdir(parents=True, exist_ok=True)
    settings.dsh_sessions_dir.mkdir(parents=True, exist_ok=True)
    return settings
