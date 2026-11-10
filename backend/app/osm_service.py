from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Iterable, TypeVar

import geopandas as gpd
import networkx as nx
import osmnx as ox
import pandas as pd
import requests
from osmnx._errors import InsufficientResponseError, ResponseStatusCodeError
from shapely.geometry import LineString, Point

from .config import Settings, get_settings
from .offline_regions import OfflineRegion, OfflineRegionCatalog
from .models import (
    Coordinate,
    GeocodeResult,
    ItineraryRequest,
    LocationSearchResult,
    PoiFeature,
    PoiSearchRequest,
    PoiSearchResult,
    PrepareRegionRequest,
    RouteRequest,
    RouteResult,
)
from .route_utils import merge_route_results


CATEGORY_TAGS: dict[str, dict[str, bool | list[str]]] = {
    "attraction": {"tourism": ["attraction", "viewpoint"]},
    "museum": {"tourism": ["museum", "gallery"]},
    "hotel": {"tourism": ["hotel", "guest_house", "hostel", "apartment", "motel"]},
    "park": {"leisure": ["park", "garden", "nature_reserve"]},
    "history": {"historic": True},
    "arts": {"amenity": ["arts_centre", "theatre"]},
    "information": {"tourism": ["information"]},
}
OFFLINE_LOCATION_TAGS: dict[str, bool | list[str]] = {
    "tourism": True,
    "historic": True,
    "leisure": True,
    "amenity": True,
    "railway": ["station", "halt", "subway_entrance"],
    "public_transport": True,
}
NAME_COLUMNS = ("name:zh", "name", "official_name", "alt_name")
SPEED_KMH = {"walk": 4.8, "bike": 15.0, "drive": 30.0}
CITY_QUERY_PREFIXES = {
    "北京市": "北京市",
    "北京": "北京市",
    "上海市": "上海市",
    "上海": "上海市",
    "浙江省": "浙江省",
    "浙江": "浙江省",
    "杭州市": "杭州市, 浙江省",
    "杭州": "杭州市, 浙江省",
    "宁波市": "宁波市, 浙江省",
    "宁波": "宁波市, 浙江省",
}
ResultT = TypeVar("ResultT")


def _haversine_m(first: Coordinate, second: Coordinate) -> float:
    radius = 6_371_009.0
    lat1, lat2 = math.radians(first.latitude), math.radians(second.latitude)
    d_lat = lat2 - lat1
    d_lon = math.radians(second.longitude - first.longitude)
    value = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(value))


def _stable_key(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:20]


def _scalar(value: Any) -> Any:
    if isinstance(value, (list, tuple, set, dict)):
        return json.dumps(value, ensure_ascii=False, default=str)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        return value.item()
    return value


class OsmService:
    """Validated, cached OSM access shared by REST and the DSH MCP plugin."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.datasets_dir = self.settings.datasets_dir
        self.runtime_dir = self.datasets_dir / "runtime"
        self.network_dir = self.runtime_dir / "networks"
        self.poi_dir = self.runtime_dir / "pois"
        self.geocode_path = self.runtime_dir / "geocode.json"
        self.offline_regions = OfflineRegionCatalog(
            self.datasets_dir / "regions"
        )
        for directory in (self.network_dir, self.poi_dir):
            directory.mkdir(parents=True, exist_ok=True)

        ox.settings.use_cache = True
        ox.settings.cache_folder = self.datasets_dir / "cache"
        ox.settings.log_console = False
        ox.settings.requests_timeout = self.settings.overpass_timeout_seconds
        ox.settings.overpass_rate_limit = False
        ox.settings.http_accept_language = "zh-CN,zh,en"

        self._lock = threading.RLock()
        self._download_lock = threading.RLock()
        self._graphs: dict[str, nx.MultiDiGraph] = {}
        self._demo_manifest = self._read_json(self.datasets_dir / "processed" / "manifest.json")
        self._geocode_cache = self._read_json(self.geocode_path)
        self._demo_location_index: list[dict[str, Any]] | None = None
        self._offline_location_index: list[dict[str, Any]] | None = None
        self._overpass_unavailable_until = 0.0
        self._overpass_last_error = ""

    @staticmethod
    def supported_categories() -> list[str]:
        return sorted(CATEGORY_TAGS)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _save_geocode_cache(self) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        with self.geocode_path.open("w", encoding="utf-8") as file:
            json.dump(self._geocode_cache, file, ensure_ascii=False, indent=2)

    def _run_overpass(
        self,
        operation: Callable[[], ResultT],
        purpose: str,
    ) -> ResultT:
        with self._download_lock:
            remaining = self._overpass_unavailable_until - time.monotonic()
            if remaining > 0:
                raise RuntimeError(
                    f"OSM实时数据源处于{math.ceil(remaining)}秒冷却期："
                    f"{self._overpass_last_error}。本轮请勿重复调用。"
                )

            errors: list[str] = []
            for endpoint in self.settings.overpass_endpoint_list:
                ox.settings.overpass_url = endpoint
                try:
                    result = operation()
                    self._overpass_unavailable_until = 0.0
                    self._overpass_last_error = ""
                    return result
                except (
                    requests.RequestException,
                    InsufficientResponseError,
                    ResponseStatusCodeError,
                ) as error:
                    errors.append(f"{endpoint}: {type(error).__name__}")

            summary = "；".join(errors) or "没有可用的Overpass端点"
            self._overpass_last_error = summary
            self._overpass_unavailable_until = (
                time.monotonic() + self.settings.overpass_failure_cooldown_seconds
            )
            raise RuntimeError(
                f"{purpose}失败，已依次尝试{len(errors)}个OSM Overpass端点："
                f"{summary}。现有缓存不受影响，本轮请勿重复调用。"
            )

    def _load_demo_location_index(self) -> list[dict[str, Any]]:
        if self._demo_location_index is not None:
            return self._demo_location_index
        path = self.datasets_dir / "raw" / "osm_features.gpkg"
        if not path.is_file():
            self._demo_location_index = []
            return self._demo_location_index
        features = gpd.read_file(path, layer="pois")
        if features.empty:
            self._demo_location_index = []
            return self._demo_location_index
        projected = features.to_crs(features.estimate_utm_crs())
        points = projected.geometry.representative_point()
        point_series = gpd.GeoSeries(points, crs=projected.crs).to_crs(epsg=4326)
        index: list[dict[str, Any]] = []
        for _, row in features.iterrows():
            names = list(
                dict.fromkeys(
                    str(row[column]).strip()
                    for column in NAME_COLUMNS
                    if column in row and pd.notna(row[column]) and str(row[column]).strip()
                )
            )
            if not names:
                continue
            point = point_series.loc[row.name]
            index.append(
                {
                    "display_name": names[0],
                    "names": [name.casefold() for name in names],
                    "latitude": float(point.y),
                    "longitude": float(point.x),
                }
            )
        self._demo_location_index = index
        return index

    @staticmethod
    def _offline_location_path(region: OfflineRegion) -> Path:
        return region.pbf_path.parents[1] / "processed" / "locations.csv"

    def prepare_offline_location_index(
        self,
        region_id: str,
    ) -> dict[str, Any]:
        region = self.offline_regions.get(region_id)
        if region is None:
            raise ValueError(f"未知离线区域：{region_id}")
        if not region.available:
            raise FileNotFoundError(f"{region.name}的离线PBF不存在")

        osm_class = self._pyrosm_class()
        osm = osm_class(
            str(region.pbf_path),
            keep_metadata=False,
            engine="out_of_core",
        )
        features = osm.get_pois(
            custom_filter=OFFLINE_LOCATION_TAGS,
            tags_to_keep=list(NAME_COLUMNS),
        )
        records: list[dict[str, Any]] = []
        if features is not None and not features.empty:
            if features.crs is None:
                features = features.set_crs(epsg=4326)
            features = features[
                features.geometry.notna() & ~features.geometry.is_empty
            ].copy()
            projected = features.to_crs(features.estimate_utm_crs())
            projected["geometry"] = projected.geometry.representative_point()
            points = projected.to_crs(epsg=4326)
            for _, row in points.iterrows():
                names = list(
                    dict.fromkeys(
                        str(row[column]).strip()
                        for column in NAME_COLUMNS
                        if (
                            column in row
                            and pd.notna(row[column])
                            and str(row[column]).strip()
                        )
                    )
                )
                if not names:
                    continue
                records.append(
                    {
                        "display_name": names[0],
                        "search_names": json.dumps(
                            names,
                            ensure_ascii=False,
                        ),
                        "latitude": round(float(row.geometry.y), 7),
                        "longitude": round(float(row.geometry.x), 7),
                        "region_id": region.region_id,
                        "region_name": region.name,
                    }
                )

        frame = pd.DataFrame.from_records(
            records,
            columns=[
                "display_name",
                "search_names",
                "latitude",
                "longitude",
                "region_id",
                "region_name",
            ],
        ).drop_duplicates(
            subset=["display_name", "latitude", "longitude"]
        )
        path = self._offline_location_path(region)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False, encoding="utf-8-sig")
        self._offline_location_index = None
        return {
            "path": path.relative_to(self.datasets_dir).as_posix(),
            "location_count": len(frame),
            "region_id": region.region_id,
        }

    def _load_offline_location_index(self) -> list[dict[str, Any]]:
        if self._offline_location_index is not None:
            return self._offline_location_index
        index: list[dict[str, Any]] = []
        for region in self.offline_regions.regions:
            path = self._offline_location_path(region)
            if not path.is_file():
                continue
            frame = pd.read_csv(path, encoding="utf-8-sig")
            for item in frame.to_dict(orient="records"):
                try:
                    names = json.loads(str(item["search_names"]))
                    latitude = float(item["latitude"])
                    longitude = float(item["longitude"])
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    continue
                if not isinstance(names, list):
                    continue
                index.append(
                    {
                        "display_name": str(item["display_name"]),
                        "names": [
                            str(name).casefold()
                            for name in names
                            if str(name).strip()
                        ],
                        "latitude": latitude,
                        "longitude": longitude,
                        "region_name": str(item.get("region_name", "")),
                    }
                )
        self._offline_location_index = index
        return index

    @staticmethod
    def _local_search_terms(query: str) -> list[str]:
        primary = query.split(",", maxsplit=1)[0].strip().casefold()
        simplified = primary
        for prefix in sorted(CITY_QUERY_PREFIXES, key=len, reverse=True):
            if simplified.startswith(prefix.casefold()):
                simplified = simplified[len(prefix):].strip()
                break
        return list(dict.fromkeys(term for term in (primary, simplified) if term))

    def _search_demo_locations(self, query: str, limit: int) -> list[GeocodeResult]:
        terms = self._local_search_terms(query)
        ranked: list[tuple[int, str, dict[str, Any]]] = []
        for item in self._load_demo_location_index():
            scores = [
                0 if term in item["names"] else
                1 if any(name.startswith(term) for name in item["names"]) else
                2 if any(term in name for name in item["names"]) else
                99
                for term in terms
            ]
            score = min(scores, default=99)
            if score < 99:
                ranked.append((score, item["display_name"], item))
        ranked.sort(key=lambda value: (value[0], len(value[1]), value[1]))
        return [
            GeocodeResult(
                query=query,
                display_name=item["display_name"],
                latitude=item["latitude"],
                longitude=item["longitude"],
            )
            for _, _, item in ranked[:limit]
        ]

    def _search_offline_locations(
        self,
        query: str,
        limit: int,
    ) -> list[GeocodeResult]:
        terms = self._local_search_terms(query)
        ranked: list[tuple[int, str, dict[str, Any]]] = []
        for item in self._load_offline_location_index():
            scores = [
                0 if term in item["names"] else
                1 if any(name.startswith(term) for name in item["names"]) else
                2 if any(term in name for name in item["names"]) else
                99
                for term in terms
            ]
            score = min(scores, default=99)
            if score < 99:
                ranked.append((score, item["display_name"], item))
        ranked.sort(key=lambda value: (value[0], len(value[1]), value[1]))
        return [
            GeocodeResult(
                query=query,
                display_name=(
                    f"{item['display_name']}（{item['region_name']}离线数据）"
                ),
                latitude=item["latitude"],
                longitude=item["longitude"],
            )
            for _, _, item in ranked[:limit]
        ]

    @staticmethod
    def _nominatim_query(query: str) -> str:
        if "," in query or "，" in query:
            return query
        for prefix in sorted(CITY_QUERY_PREFIXES, key=len, reverse=True):
            if query.startswith(prefix):
                place = query[len(prefix):].strip()
                if place:
                    return f"{place}, {CITY_QUERY_PREFIXES[prefix]}, 中国"
        return query

    @staticmethod
    def _cached_geocode_matches_query(
        query: str,
        result: GeocodeResult,
    ) -> bool:
        for prefix in sorted(CITY_QUERY_PREFIXES, key=len, reverse=True):
            if query.startswith(prefix):
                place = query[len(prefix):].strip(" ,，")
                return not place or place.casefold() in result.display_name.casefold()
        return True

    @staticmethod
    def _search_nominatim(query: str, limit: int) -> list[GeocodeResult]:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": OsmService._nominatim_query(query),
                "format": "jsonv2",
                "addressdetails": 1,
                "limit": limit,
                "countrycodes": "cn",
                "accept-language": "zh-CN,zh,en",
            },
            headers={"User-Agent": "ZYourRoad/0.1 smart-city-course-project"},
            timeout=20,
        )
        response.raise_for_status()
        results: list[GeocodeResult] = []
        for item in response.json():
            try:
                results.append(
                    GeocodeResult(
                        query=query,
                        display_name=str(item["display_name"]),
                        latitude=float(item["lat"]),
                        longitude=float(item["lon"]),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return results

    def search_locations(self, query: str, limit: int = 8) -> LocationSearchResult:
        normalized = " ".join(query.split())
        local = [
            *self._search_demo_locations(normalized, limit),
            *self._search_offline_locations(normalized, limit),
        ]
        remote: list[GeocodeResult] = []
        if not local:
            try:
                remote = self._search_nominatim(normalized, limit)
            except requests.RequestException:
                remote = []
        unique: dict[tuple[str, float, float], GeocodeResult] = {}
        for result in [*local, *remote]:
            key = (
                result.display_name.casefold(),
                round(result.latitude, 5),
                round(result.longitude, 5),
            )
            unique.setdefault(key, result)
        return LocationSearchResult(
            query=normalized,
            results=list(unique.values())[:limit],
        )

    def geocode(self, query: str) -> GeocodeResult:
        normalized = " ".join(query.split())
        cache_key = normalized.casefold()
        cached = self._geocode_cache.get(cache_key)
        if cached:
            result = GeocodeResult(**cached)
            if self._cached_geocode_matches_query(normalized, result):
                return result

        candidates = self.search_locations(normalized, limit=8).results
        if not candidates:
            raise ValueError(f"未找到地点“{normalized}”，请换一个更具体的名称")
        result = candidates[0]
        with self._lock:
            self._geocode_cache[cache_key] = result.model_dump()
            self._save_geocode_cache()
        return result

    def _resolve_center(self, request: PoiSearchRequest) -> Coordinate:
        if request.center is not None:
            return request.center
        if request.location is None:
            raise ValueError("缺少查询中心")
        result = self.geocode(request.location)
        return Coordinate(latitude=result.latitude, longitude=result.longitude)

    def _validate_categories(self, categories: Iterable[str]) -> list[str]:
        normalized = list(dict.fromkeys(category.strip().lower() for category in categories))
        unknown = sorted(set(normalized) - CATEGORY_TAGS.keys())
        if unknown:
            supported = ", ".join(self.supported_categories())
            raise ValueError(f"未知POI类别：{', '.join(unknown)}；支持：{supported}")
        return normalized

    @staticmethod
    def _merge_query_tags(categories: Iterable[str]) -> dict[str, bool | list[str]]:
        merged: dict[str, bool | list[str]] = {}
        for category in categories:
            for key, requested in CATEGORY_TAGS[category].items():
                current = merged.get(key)
                if current is True or requested is True:
                    merged[key] = True
                    continue
                values = set(current or [])
                values.update(requested)
                merged[key] = sorted(values)
        return merged

    @staticmethod
    def _query_bounds(
        center: Coordinate,
        radius_m: float,
    ) -> list[float]:
        latitude_delta = radius_m / 111_320.0
        longitude_scale = max(
            math.cos(math.radians(center.latitude)),
            0.1,
        )
        longitude_delta = radius_m / (111_320.0 * longitude_scale)
        return [
            center.longitude - longitude_delta,
            center.latitude - latitude_delta,
            center.longitude + longitude_delta,
            center.latitude + latitude_delta,
        ]

    @staticmethod
    def _pyrosm_class() -> Any:
        try:
            from pyrosm import OSM
        except ImportError as error:
            raise RuntimeError(
                "检测到可用的离线城市PBF，但尚未安装pyrosm。请在zyourroad "
                "Conda环境中重新安装 backend/requirements.txt。"
            ) from error
        return OSM

    def _offline_pois(
        self,
        region: OfflineRegion,
        center: Coordinate,
        radius_m: int,
        tags: dict[str, bool | list[str]],
    ) -> gpd.GeoDataFrame:
        osm_class = self._pyrosm_class()
        osm = osm_class(
            str(region.pbf_path),
            bounding_box=self._query_bounds(center, radius_m),
            keep_metadata=False,
            engine="out_of_core",
        )
        columns = list(dict.fromkeys([*NAME_COLUMNS, *tags.keys()]))
        features = osm.get_pois(
            custom_filter=tags,
            tags_to_keep=columns,
        )
        if features is None or features.empty:
            return gpd.GeoDataFrame(
                {"geometry": []},
                geometry="geometry",
                crs="EPSG:4326",
            )
        if features.crs is None:
            features = features.set_crs(epsg=4326)
        features = features[
            features.geometry.notna() & ~features.geometry.is_empty
        ].copy()
        features["offline_region"] = region.region_id
        return features

    @staticmethod
    def _matches(row: pd.Series, category: str) -> bool:
        for key, expected in CATEGORY_TAGS[category].items():
            value = row.get(key)
            if value is None:
                continue
            try:
                if pd.isna(value):
                    continue
            except (TypeError, ValueError):
                pass
            if expected is True or str(value) in expected:
                return True
        return False

    def _demo_contains(self, center: Coordinate, radius_m: int) -> bool:
        if not self._demo_manifest:
            return False
        demo_center_raw = self._demo_manifest.get("center_point", [])
        if len(demo_center_raw) != 2:
            return False
        demo_center = Coordinate(
            latitude=float(demo_center_raw[0]),
            longitude=float(demo_center_raw[1]),
        )
        demo_radius = float(self._demo_manifest.get("radius_m", 0))
        return _haversine_m(center, demo_center) + radius_m <= demo_radius

    def _query_pois(
        self,
        center: Coordinate,
        radius_m: int,
        categories: list[str],
    ) -> tuple[gpd.GeoDataFrame, str]:
        if self._demo_contains(center, radius_m):
            path = self.datasets_dir / "raw" / "osm_features.gpkg"
            if path.is_file():
                return gpd.read_file(path, layer="pois"), "demo-cache"

        tags = self._merge_query_tags(categories)
        offline_region = self.offline_regions.find(center, radius_m)
        key = _stable_key(
            {
                "latitude": round(center.latitude, 5),
                "longitude": round(center.longitude, 5),
                "radius_m": radius_m,
                "tags": tags,
                "offline_region": (
                    offline_region.region_id if offline_region else None
                ),
            }
        )
        cache_path = self.poi_dir / f"{key}.gpkg"
        if cache_path.is_file():
            source = "offline-region" if offline_region else "query-cache"
            return gpd.read_file(cache_path, layer="pois"), source

        if offline_region is not None:
            features = self._offline_pois(
                offline_region,
                center,
                radius_m,
                tags,
            )
            safe = features.copy()
            for column in safe.columns:
                if column != safe.geometry.name:
                    safe[column] = safe[column].map(_scalar)
            if not safe.empty:
                safe.to_file(
                    cache_path,
                    layer="pois",
                    driver="GPKG",
                    index=False,
                )
            return safe, "offline-region"

        features = self._run_overpass(
            lambda: ox.features_from_point(
                (center.latitude, center.longitude),
                tags=tags,
                dist=radius_m,
            ),
            "获取区域POI",
        )
        features = features[
            features.geometry.notna() & ~features.geometry.is_empty
        ].reset_index()
        safe = features.copy()
        for column in safe.columns:
            if column != safe.geometry.name:
                safe[column] = safe[column].map(_scalar)
        safe.to_file(cache_path, layer="pois", driver="GPKG", index=False)
        return safe, "openstreetmap"

    @staticmethod
    def _within_radius(
        features: gpd.GeoDataFrame,
        center: Coordinate,
        radius_m: int,
    ) -> gpd.GeoDataFrame:
        if features.empty:
            return features
        if features.crs is None:
            features = features.set_crs(epsg=4326)
        projected = features.to_crs(features.estimate_utm_crs())
        center_series = gpd.GeoSeries(
            [Point(center.longitude, center.latitude)],
            crs="EPSG:4326",
        ).to_crs(projected.crs)
        return features.loc[projected.geometry.distance(center_series.iloc[0]) <= radius_m].copy()

    def search_pois(self, request: PoiSearchRequest) -> PoiSearchResult:
        center = self._resolve_center(request)
        include = self._validate_categories(request.categories)
        exclude = self._validate_categories(request.exclude_categories)
        if not include:
            raise ValueError("至少需要一个POI类别")

        features, source = self._query_pois(center, request.radius_m, include)
        features = self._within_radius(features, center, request.radius_m)
        if not isinstance(features.index, pd.RangeIndex):
            features = features.reset_index()

        if features.empty:
            return PoiSearchResult(
                center=center,
                radius_m=request.radius_m,
                source=source,
                total=0,
                pois=[],
            )

        projected = features.to_crs(features.estimate_utm_crs())
        projected["geometry"] = projected.geometry.representative_point()
        points = projected.to_crs(epsg=4326)

        pois: list[PoiFeature] = []
        for _, row in points.iterrows():
            if not any(self._matches(row, category) for category in include):
                continue
            if any(self._matches(row, category) for category in exclude):
                continue
            name = next(
                (
                    str(row[column]).strip()
                    for column in NAME_COLUMNS
                    if column in row and pd.notna(row[column]) and str(row[column]).strip()
                ),
                "",
            )
            if request.require_name and not name:
                continue
            matched = {
                category: True
                for category in include
                if self._matches(row, category)
            }
            geometry = row.geometry
            osm_type = row.get(
                "osm_type",
                row.get("element_type", row.get("element", "")),
            )
            osm_id = row.get("osmid", row.get("id", ""))
            pois.append(
                PoiFeature(
                    osm_type=str(osm_type),
                    osm_id=str(osm_id),
                    name=name or f"OSM {osm_type} {osm_id}",
                    categories=matched,
                    latitude=round(float(geometry.y), 7),
                    longitude=round(float(geometry.x), 7),
                )
            )

        unique = {(poi.osm_type, poi.osm_id): poi for poi in pois}
        limited = list(unique.values())[: request.limit]
        return PoiSearchResult(
            center=center,
            radius_m=request.radius_m,
            source=source,
            total=len(unique),
            pois=limited,
        )

    def _network_cache_key(
        self,
        center: Coordinate,
        radius_m: int,
        network_type: str,
    ) -> str:
        if network_type == "walk" and self._demo_manifest:
            demo_center_raw = self._demo_manifest.get("center_point", [])
            demo_radius = float(self._demo_manifest.get("radius_m", 0))
            if len(demo_center_raw) == 2:
                demo_center = Coordinate(
                    latitude=float(demo_center_raw[0]),
                    longitude=float(demo_center_raw[1]),
                )
                if (
                    radius_m <= demo_radius
                    and _haversine_m(center, demo_center) <= demo_radius
                ):
                    return "demo-west-lake-walk"
        offline_region = self.offline_regions.find(center, radius_m)
        return _stable_key(
            {
                "latitude": round(center.latitude, 5),
                "longitude": round(center.longitude, 5),
                "radius_m": radius_m,
                "network_type": network_type,
                "offline_region": (
                    offline_region.region_id if offline_region else None
                ),
            }
        )

    def _offline_network(
        self,
        region: OfflineRegion,
        center: Coordinate,
        radius_m: int,
        network_type: str,
    ) -> nx.MultiDiGraph:
        osm_class = self._pyrosm_class()
        osm = osm_class(
            str(region.pbf_path),
            bounding_box=self._query_bounds(center, radius_m),
            keep_metadata=False,
            engine="out_of_core",
        )
        pyrosm_network_type = {
            "walk": "walking",
            "bike": "cycling",
            "drive": "driving",
        }[network_type]
        nodes, edges = osm.get_network(
            network_type=pyrosm_network_type,
            nodes=True,
        )
        if nodes is None or edges is None or nodes.empty or edges.empty:
            raise RuntimeError(
                f"{region.name}离线数据中没有找到可用的{network_type}路网"
            )
        graph = osm_class.to_graph(
            nodes,
            edges,
            graph_type="networkx",
            network_type=pyrosm_network_type,
            retain_all=False,
            osmnx_compatible=True,
            simplify=True,
        )
        graph.graph["offline_region"] = region.region_id
        graph.graph["data_source"] = "offline-pbf"
        return graph

    def ensure_network(
        self,
        center: Coordinate,
        radius_m: int,
        network_type: str,
    ) -> tuple[nx.MultiDiGraph, str]:
        key = self._network_cache_key(center, radius_m, network_type)
        with self._lock:
            if key in self._graphs:
                return self._graphs[key], key

            if key == "demo-west-lake-walk":
                path = self.datasets_dir / "raw" / "osm_graph.graphml"
            else:
                path = self.network_dir / f"{key}.graphml"

            if path.is_file():
                graph = ox.load_graphml(path)
            else:
                offline_region = self.offline_regions.find(center, radius_m)
                if offline_region is not None:
                    graph = self._offline_network(
                        offline_region,
                        center,
                        radius_m,
                        network_type,
                    )
                else:
                    graph = self._run_overpass(
                        lambda: ox.graph_from_point(
                            (center.latitude, center.longitude),
                            dist=radius_m,
                            network_type=network_type,
                            simplify=True,
                            retain_all=False,
                        ),
                        "获取区域路网",
                    )
                ox.save_graphml(graph, filepath=path)
            self._graphs[key] = graph
            return graph, key

    @staticmethod
    def _edge_coordinates(
        graph: nx.MultiDiGraph,
        first: int,
        second: int,
    ) -> tuple[list[list[float]], float]:
        edges = graph.get_edge_data(first, second)
        if not edges:
            raise nx.NetworkXNoPath(f"道路边不存在：{first} → {second}")
        edge = min(edges.values(), key=lambda item: float(item.get("length", math.inf)))
        geometry = edge.get("geometry")
        if geometry is None:
            coordinates = [
                [float(graph.nodes[first]["x"]), float(graph.nodes[first]["y"])],
                [float(graph.nodes[second]["x"]), float(graph.nodes[second]["y"])],
            ]
        else:
            coordinates = [[float(x), float(y)] for x, y in geometry.coords]
            first_xy = (float(graph.nodes[first]["x"]), float(graph.nodes[first]["y"]))
            forward_error = (
                (coordinates[0][0] - first_xy[0]) ** 2
                + (coordinates[0][1] - first_xy[1]) ** 2
            )
            reverse_error = (
                (coordinates[-1][0] - first_xy[0]) ** 2
                + (coordinates[-1][1] - first_xy[1]) ** 2
            )
            if reverse_error < forward_error:
                coordinates.reverse()
        return coordinates, float(edge.get("length", 0.0))

    def plan_route(self, request: RouteRequest) -> RouteResult:
        points = [request.start, *request.waypoints, request.end]
        center = Coordinate(
            latitude=sum(point.latitude for point in points) / len(points),
            longitude=sum(point.longitude for point in points) / len(points),
        )
        required_radius = max(_haversine_m(center, point) for point in points) + 750
        radius_m = max(float(request.search_radius_m), required_radius)
        if radius_m > self.settings.max_query_radius_m:
            raise ValueError(
                f"路线跨度需要约{radius_m:.0f}米查询半径，超过上限"
                f"{self.settings.max_query_radius_m}米；请缩小区域或分段规划"
            )

        graph, _ = self.ensure_network(center, math.ceil(radius_m), request.network_type)
        nodes = ox.nearest_nodes(
            graph,
            X=[point.longitude for point in points],
            Y=[point.latitude for point in points],
        )

        all_coordinates: list[list[float]] = []
        segments: list[dict[str, Any]] = []
        total_distance = 0.0
        for index, (origin, destination) in enumerate(
            zip(nodes[:-1], nodes[1:], strict=True)
        ):
            route = nx.shortest_path(graph, origin, destination, weight="length")
            segment_coordinates: list[list[float]] = []
            segment_distance = 0.0
            for first, second in zip(route[:-1], route[1:], strict=True):
                coordinates, distance = self._edge_coordinates(graph, first, second)
                if segment_coordinates and coordinates:
                    coordinates = coordinates[1:]
                segment_coordinates.extend(coordinates)
                segment_distance += distance

            if all_coordinates and segment_coordinates:
                segment_coordinates = segment_coordinates[1:]
            all_coordinates.extend(segment_coordinates)
            total_distance += segment_distance
            segments.append(
                {
                    "index": index,
                    "distance_m": round(segment_distance, 1),
                    "from": points[index].model_dump(),
                    "to": points[index + 1].model_dump(),
                }
            )

        duration_min = total_distance / 1000 / SPEED_KMH[request.network_type] * 60
        return RouteResult(
            distance_m=round(total_distance, 1),
            estimated_duration_min=round(duration_min, 1),
            network_type=request.network_type,
            visited_points=points,
            geometry={
                "type": "LineString",
                "coordinates": all_coordinates,
            },
            segments=segments,
        )

    def publish_itinerary(self, request: ItineraryRequest) -> RouteResult:
        boundaries = [
            0,
            *request.break_before_indexes,
            len(request.points),
        ]
        routes = []
        for start_index, end_index in zip(
            boundaries[:-1],
            boundaries[1:],
            strict=True,
        ):
            points = request.points[start_index:end_index]
            routes.append(
                self.plan_route(
                    RouteRequest(
                        start=points[0],
                        end=points[-1],
                        waypoints=points[1:-1],
                        network_type=request.network_type,
                        search_radius_m=request.search_radius_m,
                    )
                )
            )
        merged = merge_route_results(routes)
        if merged is None:
            raise RuntimeError("最终行程没有生成任何可渲染路线")
        return merged

    def prepare_region(self, request: PrepareRegionRequest) -> dict[str, Any]:
        categories = self._validate_categories(request.categories)
        graph, cache_key = self.ensure_network(
            request.center,
            request.radius_m,
            request.network_type,
        )
        pois = self.search_pois(
            PoiSearchRequest(
                center=request.center,
                radius_m=request.radius_m,
                categories=categories,
                limit=100,
            )
        )
        return {
            "cache_key": cache_key,
            "network_type": request.network_type,
            "node_count": graph.number_of_nodes(),
            "edge_count": graph.number_of_edges(),
            "poi_count": pois.total,
            "poi_source": pois.source,
            "attribution": "© OpenStreetMap contributors",
        }


_service: OsmService | None = None


def get_osm_service() -> OsmService:
    global _service
    if _service is None:
        _service = OsmService()
    return _service
