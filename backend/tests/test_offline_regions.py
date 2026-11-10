import json

import pytest

from backend.app.models import Coordinate
from backend.app.offline_regions import OfflineRegionCatalog


def _write_catalog(tmp_path) -> OfflineRegionCatalog:
    regions_dir = tmp_path / "regions"
    (regions_dir / "large" / "source").mkdir(parents=True)
    (regions_dir / "small" / "source").mkdir(parents=True)
    (regions_dir / "large" / "source" / "large.osm.pbf").write_bytes(b"pbf")
    (regions_dir / "small" / "source" / "small.osm.pbf").write_bytes(b"pbf")
    (regions_dir / "catalog.json").write_text(
        json.dumps(
            {
                "regions": [
                    {
                        "id": "large",
                        "name": "大区域",
                        "pbf": "large/source/large.osm.pbf",
                        "bounds": [120.0, 30.0, 123.0, 33.0],
                        "priority": 10,
                        "sample_center": [31.0, 121.0],
                    },
                    {
                        "id": "small",
                        "name": "小区域",
                        "pbf": "small/source/small.osm.pbf",
                        "bounds": [120.5, 30.5, 121.5, 31.5],
                        "priority": 100,
                        "sample_center": [31.0, 121.0],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return OfflineRegionCatalog(regions_dir)


def test_more_specific_offline_region_wins_by_priority(tmp_path) -> None:
    catalog = _write_catalog(tmp_path)

    region = catalog.find(
        Coordinate(latitude=31.0, longitude=121.0),
        radius_m=3000,
    )

    assert region is not None
    assert region.region_id == "small"


def test_query_circle_must_fit_inside_region_bounds(tmp_path) -> None:
    catalog = _write_catalog(tmp_path)

    region = catalog.find(
        Coordinate(latitude=30.51, longitude=120.51),
        radius_m=5000,
    )

    assert region is not None
    assert region.region_id == "large"


def test_catalog_rejects_path_traversal(tmp_path) -> None:
    regions_dir = tmp_path / "regions"
    regions_dir.mkdir()
    (regions_dir / "catalog.json").write_text(
        json.dumps(
            {
                "regions": [
                    {
                        "id": "bad",
                        "name": "错误区域",
                        "pbf": "../escape.osm.pbf",
                        "bounds": [120.0, 30.0, 121.0, 31.0],
                        "sample_center": [30.5, 120.5],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="路径不安全"):
        OfflineRegionCatalog(regions_dir)
