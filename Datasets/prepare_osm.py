from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DATASET_DIR = Path(__file__).resolve().parent
REQUIRED_CONFIG_KEYS = {
    "dataset_name",
    "center_point",
    "radius_m",
    "network_type",
    "poi_tags",
}
SUPPORTED_NETWORK_TYPES = {"all", "all_public", "bike", "drive", "drive_service", "walk"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="下载并整理 ZYourRoad 使用的 OSM 路网和旅游 POI 数据。",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DATASET_DIR / "config.example.json",
        help="JSON 配置文件路径。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DATASET_DIR,
        help="raw 和 processed 目录所在位置。",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="只检查配置，不下载数据。",
    )
    return parser.parse_args()


def load_and_validate_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"配置文件不存在：{path}")

    with path.open("r", encoding="utf-8") as file:
        config = json.load(file)

    missing = REQUIRED_CONFIG_KEYS - config.keys()
    if missing:
        raise ValueError(f"配置缺少字段：{', '.join(sorted(missing))}")

    center = config["center_point"]
    if (
        not isinstance(center, list)
        or len(center) != 2
        or not all(isinstance(value, (int, float)) for value in center)
    ):
        raise ValueError("center_point 必须是 [纬度, 经度] 数值数组。")

    latitude, longitude = center
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("center_point 的经纬度超出合法范围。")

    radius = config["radius_m"]
    if not isinstance(radius, (int, float)) or not 100 <= radius <= 50_000:
        raise ValueError("radius_m 必须在 100 到 50000 米之间。")

    network_type = config["network_type"]
    if network_type not in SUPPORTED_NETWORK_TYPES:
        choices = ", ".join(sorted(SUPPORTED_NETWORK_TYPES))
        raise ValueError(f"network_type 必须是以下值之一：{choices}")

    poi_tags = config["poi_tags"]
    if not isinstance(poi_tags, dict) or not poi_tags:
        raise ValueError("poi_tags 必须是非空对象。")

    return config


def json_safe_value(value: Any) -> Any:
    if isinstance(value, (list, tuple, set, dict)):
        return json.dumps(value, ensure_ascii=False, default=str)

    try:
        import pandas as pd

        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    if hasattr(value, "item"):
        return value.item()
    return value


def sanitize_geodataframe(geodataframe: Any) -> Any:
    result = geodataframe.copy()
    for column in result.columns:
        if column != result.geometry.name:
            result[column] = result[column].map(json_safe_value)
    return result


def build_poi_table(
    features: Any,
    poi_tags: dict[str, Any],
    exclusions: dict[str, list[str]],
    require_name: bool,
) -> Any:
    import pandas as pd

    features = features[
        features.geometry.notna() & ~features.geometry.is_empty
    ].copy()
    if features.empty:
        return pd.DataFrame(
            columns=["osm_type", "osm_id", "name", "categories", "latitude", "longitude"]
        )

    indexed = features.reset_index()
    projected = indexed.to_crs(indexed.estimate_utm_crs())
    projected["geometry"] = projected.geometry.representative_point()
    points = projected.to_crs(epsg=4326)

    name_columns = ["name:zh", "name", "official_name", "alt_name"]
    records: list[dict[str, Any]] = []

    for _, row in points.iterrows():
        is_excluded = any(
            str(row.get(key, "")) in excluded_values
            for key, excluded_values in exclusions.items()
        )
        if is_excluded:
            continue

        name = next(
            (
                str(row[column])
                for column in name_columns
                if column in row and pd.notna(row[column]) and str(row[column]).strip()
            ),
            "",
        )
        categories = {
            key: json_safe_value(row[key])
            for key in poi_tags
            if key in row and pd.notna(row[key])
        }
        geometry = row.geometry
        records.append(
            {
                "osm_type": row.get("element_type", row.get("element", "")),
                "osm_id": row.get("osmid", row.get("id", "")),
                "name": name,
                "categories": json.dumps(categories, ensure_ascii=False),
                "latitude": round(float(geometry.y), 7),
                "longitude": round(float(geometry.x), 7),
            }
        )

    table = pd.DataFrame.from_records(records)
    if require_name and not table.empty:
        table = table[table["name"].str.strip().ne("")]
    return table.drop_duplicates(subset=["osm_type", "osm_id"]).reset_index(drop=True)


def prepare_dataset(config: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    try:
        import osmnx as ox
    except ImportError as error:
        raise RuntimeError(
            "缺少 osmnx，请先执行：python -m pip install -r Datasets/requirements.txt"
        ) from error

    output_dir = output_dir.resolve()
    raw_dir = output_dir / "raw"
    processed_dir = output_dir / "processed"
    cache_dir = output_dir / "cache"
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    ox.settings.use_cache = True
    ox.settings.cache_folder = cache_dir
    ox.settings.log_console = True
    ox.settings.requests_timeout = 180

    center = tuple(config["center_point"])
    radius = float(config["radius_m"])
    network_type = config["network_type"]
    poi_tags = config["poi_tags"]
    exclusions = config.get("poi_exclusions", {})
    require_name = bool(config.get("require_poi_name", True))

    print("1/4 正在下载并构建 OSM 有向道路图……")
    graph = ox.graph_from_point(
        center,
        dist=radius,
        network_type=network_type,
        simplify=True,
        retain_all=False,
    )

    graphml_path = raw_dir / "osm_graph.graphml"
    network_gpkg_path = processed_dir / "network.gpkg"
    ox.save_graphml(graph, filepath=graphml_path)
    if network_gpkg_path.exists():
        network_gpkg_path.unlink()
    ox.save_graph_geopackage(graph, filepath=network_gpkg_path, directed=True)

    print("2/4 正在下载旅游 POI……")
    features = ox.features_from_point(center, tags=poi_tags, dist=radius)
    features = features[
        features.geometry.notna() & ~features.geometry.is_empty
    ].copy()

    features_gpkg_path = raw_dir / "osm_features.gpkg"
    if features_gpkg_path.exists():
        features_gpkg_path.unlink()
    sanitize_geodataframe(features.reset_index()).to_file(
        features_gpkg_path,
        layer="pois",
        driver="GPKG",
        index=False,
    )

    print("3/4 正在生成候选 POI 表……")
    poi_table = build_poi_table(features, poi_tags, exclusions, require_name)
    poi_csv_path = processed_dir / "poi_candidates.csv"
    poi_table.to_csv(poi_csv_path, index=False, encoding="utf-8-sig")

    manifest = {
        "dataset_name": config["dataset_name"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "OpenStreetMap",
        "license": "ODbL",
        "attribution": "© OpenStreetMap contributors",
        "center_point": config["center_point"],
        "radius_m": radius,
        "network_type": network_type,
        "poi_tags": poi_tags,
        "poi_exclusions": exclusions,
        "require_poi_name": require_name,
        "node_count": int(graph.number_of_nodes()),
        "edge_count": int(graph.number_of_edges()),
        "raw_feature_count": int(len(features)),
        "poi_count": int(len(poi_table)),
        "files": {
            "graphml": graphml_path.relative_to(output_dir).as_posix(),
            "network_geopackage": network_gpkg_path.relative_to(
                output_dir
            ).as_posix(),
            "features_geopackage": features_gpkg_path.relative_to(
                output_dir
            ).as_posix(),
            "poi_csv": poi_csv_path.relative_to(output_dir).as_posix(),
        },
    }

    manifest_path = processed_dir / "manifest.json"
    with manifest_path.open("w", encoding="utf-8") as file:
        json.dump(manifest, file, ensure_ascii=False, indent=2)

    print("4/4 数据准备完成。")
    return manifest


def main() -> None:
    args = parse_args()
    config = load_and_validate_config(args.config.resolve())

    if args.validate_only:
        print("配置检查通过：")
        print(json.dumps(config, ensure_ascii=False, indent=2))
        return

    manifest = prepare_dataset(config, args.output_dir)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
