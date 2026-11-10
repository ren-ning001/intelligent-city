from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Coordinate


EARTH_METERS_PER_DEGREE = 111_320.0


@dataclass(frozen=True)
class OfflineRegion:
    region_id: str
    name: str
    pbf_path: Path
    bounds: tuple[float, float, float, float]
    priority: int
    sample_center: Coordinate

    @property
    def available(self) -> bool:
        return self.pbf_path.is_file() and self.pbf_path.stat().st_size > 0

    def contains_circle(self, center: Coordinate, radius_m: float) -> bool:
        min_lon, min_lat, max_lon, max_lat = self.bounds
        latitude_delta = radius_m / EARTH_METERS_PER_DEGREE
        longitude_scale = max(
            math.cos(math.radians(center.latitude)),
            0.1,
        )
        longitude_delta = radius_m / (
            EARTH_METERS_PER_DEGREE * longitude_scale
        )
        return (
            center.longitude - longitude_delta >= min_lon
            and center.longitude + longitude_delta <= max_lon
            and center.latitude - latitude_delta >= min_lat
            and center.latitude + latitude_delta <= max_lat
        )


class OfflineRegionCatalog:
    def __init__(self, regions_dir: Path) -> None:
        self.regions_dir = regions_dir
        self.catalog_path = regions_dir / "catalog.json"
        self.regions = self._load()

    def _load(self) -> list[OfflineRegion]:
        if not self.catalog_path.is_file():
            return []
        with self.catalog_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        items = payload.get("regions", [])
        if not isinstance(items, list):
            raise ValueError("离线区域目录中的 regions 必须是数组")

        regions: list[OfflineRegion] = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("离线区域配置项必须是对象")
            regions.append(self._parse_region(item))
        regions.sort(key=lambda region: region.priority, reverse=True)
        return regions

    def _parse_region(self, item: dict[str, Any]) -> OfflineRegion:
        region_id = str(item["id"]).strip()
        name = str(item["name"]).strip()
        relative_pbf = Path(str(item["pbf"]))
        bounds_raw = item["bounds"]
        sample_raw = item["sample_center"]
        if not region_id or not name:
            raise ValueError("离线区域 id 和 name 不能为空")
        if relative_pbf.is_absolute() or ".." in relative_pbf.parts:
            raise ValueError(f"离线区域 {region_id} 的PBF路径不安全")
        if (
            not isinstance(bounds_raw, list)
            or len(bounds_raw) != 4
            or not all(isinstance(value, (int, float)) for value in bounds_raw)
        ):
            raise ValueError(f"离线区域 {region_id} 的 bounds 必须包含4个数值")
        if (
            not isinstance(sample_raw, list)
            or len(sample_raw) != 2
            or not all(isinstance(value, (int, float)) for value in sample_raw)
        ):
            raise ValueError(
                f"离线区域 {region_id} 的 sample_center 必须为[纬度, 经度]"
            )
        bounds = tuple(float(value) for value in bounds_raw)
        min_lon, min_lat, max_lon, max_lat = bounds
        if min_lon >= max_lon or min_lat >= max_lat:
            raise ValueError(f"离线区域 {region_id} 的 bounds 顺序错误")

        return OfflineRegion(
            region_id=region_id,
            name=name,
            pbf_path=(self.regions_dir / relative_pbf).resolve(),
            bounds=bounds,
            priority=int(item.get("priority", 0)),
            sample_center=Coordinate(
                latitude=float(sample_raw[0]),
                longitude=float(sample_raw[1]),
            ),
        )

    def find(
        self,
        center: Coordinate,
        radius_m: float,
    ) -> OfflineRegion | None:
        return next(
            (
                region
                for region in self.regions
                if region.available and region.contains_circle(center, radius_m)
            ),
            None,
        )

    def get(self, region_id: str) -> OfflineRegion | None:
        return next(
            (region for region in self.regions if region.region_id == region_id),
            None,
        )
