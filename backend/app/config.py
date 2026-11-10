from __future__ import annotations

import os
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

    def export_dsh_environment(self) -> None:
        """Expose only paths and non-secret prompt defaults to the DSH subprocess."""
        self.dsh_sessions_dir.mkdir(parents=True, exist_ok=True)
        os.environ["ZYOURROAD_ROOT"] = str(PROJECT_ROOT)
        os.environ["ZYOURROAD_PYTHON"] = sys.executable
        os.environ["ZYOURROAD_SESSION_ROOT"] = str(self.dsh_sessions_dir)
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
                "回答中必须明确非步行段的换乘方式。"
                "新城市先调用 prepare_osm_region 一次准备缓存；如果工具明确报告上游数据源"
                "暂时不可用，同一轮不要重复调用或缩放范围碰运气，直接简短说明并结束。"
            ),
        )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.datasets_dir.mkdir(parents=True, exist_ok=True)
    settings.dsh_home.mkdir(parents=True, exist_ok=True)
    settings.dsh_sessions_dir.mkdir(parents=True, exist_ok=True)
    return settings
