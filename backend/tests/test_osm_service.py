import pytest
import requests

from backend.app.config import Settings
from backend.app.models import (
    Coordinate,
    GeocodeResult,
    PoiSearchRequest,
    RouteRequest,
)
from backend.app.osm_service import OsmService


def test_demo_data_can_include_hotels_dynamically() -> None:
    service = OsmService()
    result = service.search_pois(
        PoiSearchRequest(
            center=Coordinate(latitude=30.2525, longitude=120.1552),
            radius_m=2000,
            categories=["hotel"],
            limit=5,
        )
    )

    assert result.source == "demo-cache"
    assert result.total > 0
    assert all("hotel" in poi.categories for poi in result.pois)


def test_demo_graph_produces_real_route_geometry() -> None:
    service = OsmService()
    result = service.plan_route(
        RouteRequest(
            start=Coordinate(latitude=30.2426088, longitude=120.1662607),
            end=Coordinate(latitude=30.2399079, longitude=120.1409416),
        )
    )

    assert result.distance_m > 1000
    assert result.geometry["type"] == "LineString"
    assert len(result.geometry["coordinates"]) > 2


def test_overpass_failure_tries_fallbacks_then_opens_circuit() -> None:
    service = OsmService(
        Settings(
            overpass_endpoints="https://one.invalid/api,https://two.invalid/api",
            overpass_failure_cooldown_seconds=60,
        )
    )
    attempts = 0

    def fail() -> None:
        nonlocal attempts
        attempts += 1
        raise requests.exceptions.SSLError("test certificate failure")

    with pytest.raises(RuntimeError, match="已依次尝试2个"):
        service._run_overpass(fail, "测试查询")
    assert attempts == 2

    with pytest.raises(RuntimeError, match="冷却期"):
        service._run_overpass(fail, "测试查询")
    assert attempts == 2


def test_city_prefixed_geocode_query_is_rewritten_for_nominatim() -> None:
    assert OsmService._nominatim_query("上海豫园") == "豫园, 上海市, 中国"
    assert (
        OsmService._nominatim_query("杭州西湖")
        == "西湖, 杭州市, 浙江省, 中国"
    )


def test_obviously_mismatched_city_cache_is_ignored() -> None:
    wrong = GeocodeResult(
        query="上海豫园",
        display_name="上海体育大学",
        latitude=31.313664,
        longitude=121.5218896,
    )
    correct = GeocodeResult(
        query="上海豫园",
        display_name="豫园, 上海市",
        latitude=31.2289274,
        longitude=121.4879752,
    )

    assert not OsmService._cached_geocode_matches_query("上海豫园", wrong)
    assert OsmService._cached_geocode_matches_query("上海豫园", correct)


def test_offline_location_index_resolves_city_prefixed_name() -> None:
    service = OsmService()
    service._offline_location_index = [
        {
            "display_name": "豫园",
            "names": ["豫园", "yuyuan garden"],
            "latitude": 31.2289274,
            "longitude": 121.4879752,
            "region_name": "上海市",
        }
    ]

    results = service._search_offline_locations("上海豫园", limit=5)

    assert len(results) == 1
    assert results[0].display_name.startswith("豫园")
    assert results[0].latitude == pytest.approx(31.2289274)
