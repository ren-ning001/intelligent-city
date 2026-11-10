from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DATASETS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = DATASETS_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.config import get_settings  # noqa: E402
from backend.app.models import PrepareRegionRequest  # noqa: E402
from backend.app.offline_regions import OfflineRegionCatalog  # noqa: E402
from backend.app.osm_service import OsmService  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "校验北京、上海和浙江离线PBF，并为每个区域预热一份步行路网和旅游POI缓存。"
            "完整PBF始终保留，后续查询会按用户半径动态裁剪。"
        ),
    )
    parser.add_argument(
        "--region",
        action="append",
        default=[],
        help="只处理指定区域ID，可重复传入；默认处理全部区域。",
    )
    parser.add_argument(
        "--radius-m",
        type=int,
        default=3000,
        help="预热示例缓存的半径，默认3000米。",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="只检查目录、配置和PBF文件，不解析数据。",
    )
    return parser.parse_args()


def region_status(region: Any) -> dict[str, Any]:
    return {
        "id": region.region_id,
        "name": region.name,
        "pbf": str(region.pbf_path),
        "available": region.available,
        "size_mb": (
            round(region.pbf_path.stat().st_size / 1024 / 1024, 2)
            if region.available
            else 0
        ),
        "bounds": list(region.bounds),
        "sample_center": region.sample_center.model_dump(),
    }


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    args = parse_args()
    if not 500 <= args.radius_m <= 10_000:
        raise ValueError("--radius-m 必须在500到10000米之间")

    settings = get_settings()
    catalog = OfflineRegionCatalog(settings.datasets_dir / "regions")
    requested_ids = set(args.region)
    known_ids = {region.region_id for region in catalog.regions}
    unknown_ids = requested_ids - known_ids
    if unknown_ids:
        raise ValueError(f"未知离线区域：{', '.join(sorted(unknown_ids))}")

    selected = [
        region
        for region in catalog.regions
        if not requested_ids or region.region_id in requested_ids
    ]
    if not selected:
        raise RuntimeError("离线区域目录为空，请检查 regions/catalog.json")

    statuses = [region_status(region) for region in selected]
    missing = [item for item in statuses if not item["available"]]
    print(json.dumps(statuses, ensure_ascii=False, indent=2))
    if missing:
        names = "、".join(item["name"] for item in missing)
        raise FileNotFoundError(f"以下区域缺少PBF文件：{names}")
    if args.validate_only:
        print("离线区域配置和PBF文件检查通过。")
        return 0

    service = OsmService(settings)
    generated_at = datetime.now(UTC).isoformat()
    for region in selected:
        print(f"正在构建 {region.name} 的离线地点名称索引……")
        location_index = service.prepare_offline_location_index(
            region.region_id
        )
        print(
            f"地点索引完成：{location_index['location_count']}个有名称地点。"
        )
        print(f"正在预热 {region.name} 的离线路网与POI缓存……")
        prepared = service.prepare_region(
            PrepareRegionRequest(
                center=region.sample_center,
                radius_m=args.radius_m,
                network_type="walk",
                categories=[
                    "attraction",
                    "museum",
                    "park",
                    "history",
                    "arts",
                    "information",
                ],
            )
        )
        manifest = {
            "region_id": region.region_id,
            "name": region.name,
            "generated_at_utc": generated_at,
            "mode": "full-pbf-with-on-demand-spatial-cache",
            "pbf": region.pbf_path.relative_to(
                settings.datasets_dir
            ).as_posix(),
            "pbf_size_bytes": region.pbf_path.stat().st_size,
            "bounds": list(region.bounds),
            "sample_center": region.sample_center.model_dump(),
            "sample_radius_m": args.radius_m,
            "location_index": location_index,
            "sample_cache": prepared,
            "attribution": "© OpenStreetMap contributors",
        }
        manifest_path = region.pbf_path.parents[1] / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            f"{region.name}完成：{prepared['node_count']}个节点，"
            f"{prepared['poi_count']}个POI，来源={prepared['poi_source']}"
        )

    print("全部指定区域准备完成。后续查询将直接读取本地PBF并写入runtime缓存。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
