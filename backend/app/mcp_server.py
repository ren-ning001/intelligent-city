from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .models import (
    Coordinate,
    ItineraryRequest,
    OptimizeRequest,
    PoiSearchRequest,
    PrepareRegionRequest,
    RouteRequest,
)
from .order_optimizer import optimize_open_tour
from .osm_service import get_osm_service


mcp = FastMCP(
    "zyourroad-osm",
    instructions=(
        "提供真实 OpenStreetMap 地理编码、旅游POI查询、按需路网缓存、路线规划和"
        "确定性景点顺序优化；北京、上海和浙江优先使用本地离线PBF。"
        "所有距离、坐标和路线必须来自这些工具；查询区域限制在10公里以内。"
    ),
)


@mcp.tool()
def geocode_location(query: str) -> dict[str, Any]:
    """将真实地名解析为WGS84经纬度。不要猜测用户地点坐标。"""
    return get_osm_service().geocode(query).model_dump()


@mcp.tool()
def search_tourism_pois(
    location: str = "",
    latitude: float | None = None,
    longitude: float | None = None,
    radius_m: int = 3000,
    categories: list[str] | None = None,
    exclude_categories: list[str] | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    """按业务类别查询旅游POI；支持 attraction、museum、hotel、park、history、arts。"""
    center = None
    if latitude is not None and longitude is not None:
        center = Coordinate(latitude=latitude, longitude=longitude)
    request = PoiSearchRequest(
        location=location.strip() or None,
        center=center,
        radius_m=radius_m,
        categories=categories or ["attraction", "history", "park"],
        exclude_categories=exclude_categories or [],
        limit=limit,
    )
    return get_osm_service().search_pois(request).model_dump()


@mcp.tool()
def plan_walking_route(
    start_latitude: float,
    start_longitude: float,
    end_latitude: float,
    end_longitude: float,
    waypoints: list[dict[str, float]] | None = None,
    weight: str = "length",
    network_type: str = "walk",
    search_radius_m: int = 5000,
) -> dict[str, Any]:
    """在OSM真实路网上规划起点、途经点和终点的有向路线；可选距离/时间权重。"""
    request = RouteRequest(
        start=Coordinate(latitude=start_latitude, longitude=start_longitude),
        end=Coordinate(latitude=end_latitude, longitude=end_longitude),
        waypoints=[Coordinate(**item) for item in (waypoints or [])],
        network_type=network_type,
        weight=weight,
        search_radius_m=search_radius_m,
    )
    return get_osm_service().plan_route(request).model_dump()


@mcp.tool()
def publish_tourism_itinerary(
    points: list[dict[str, float]],
    break_before_indexes: list[int] | None = None,
    weight: str = "length",
    network_type: str = "walk",
    search_radius_m: int = 5000,
) -> dict[str, Any]:
    """最终发布工具：按游览顺序一次提交全部地点；换乘前的地点索引写入break列表。"""
    request = ItineraryRequest(
        points=[Coordinate(**item) for item in points],
        break_before_indexes=break_before_indexes or [],
        network_type=network_type,
        weight=weight,
        search_radius_m=search_radius_m,
    )
    return get_osm_service().publish_itinerary(request).model_dump()


@mcp.tool()
def optimize_itinerary_order(
    start_latitude: float,
    start_longitude: float,
    attractions: list[dict[str, float]],
    attraction_names: list[str] | None = None,
    weight: str = "length",
    closed_loop: bool = False,
    network_type: str = "walk",
    search_radius_m: int = 5000,
) -> dict[str, Any]:
    """在真实路网上比较当前顺序、最近邻、2-opt 和 Held-Karp，返回可发布的确定性顺序。

    weight="length" 按路网距离优化，weight="time" 按道路等级估速后的时间优化。
    closed_loop=True 表示最后回到起点。景点数限制为 2–15。
    """
    request = OptimizeRequest(
        start=Coordinate(latitude=start_latitude, longitude=start_longitude),
        attractions=[Coordinate(**item) for item in attractions],
        attraction_names=attraction_names or [],
        weight=weight,
        closed_loop=closed_loop,
        network_type=network_type,
        search_radius_m=search_radius_m,
    )
    result = optimize_open_tour(request)
    preferred = next(
        item for item in result.algorithms if item.algorithm == result.preferred_algorithm
    )
    return {
        "matrix_key": result.matrix_key,
        "network_cache_key": result.network_cache_key,
        "weight": result.weight,
        "closed_loop": result.closed_loop,
        "preferred_algorithm": result.preferred_algorithm,
        "order": preferred.order,
        "names": preferred.names,
        "cost": preferred.cost,
        "cost_unit": preferred.cost_unit,
        "cost_m": preferred.cost_m,
        "cost_s": preferred.cost_s,
        "gap_percent": preferred.gap_percent,
        "comparison": [
            {
                "algorithm": item.algorithm,
                "label": item.label,
                "order": item.order,
                "names": item.names,
                "cost": item.cost,
                "cost_unit": item.cost_unit,
                "cost_m": item.cost_m,
                "cost_s": item.cost_s,
                "gap_percent": item.gap_percent,
                "improvement_percent": item.improvement_percent,
            }
            for item in result.algorithms
        ],
        "component": result.component.model_dump() if result.component else None,
    }


@mcp.tool()
def prepare_osm_region(
    latitude: float,
    longitude: float,
    radius_m: int = 3000,
    network_type: str = "walk",
    categories: list[str] | None = None,
) -> dict[str, Any]:
    """按需准备小区域路网和POI；优先读取本地城市PBF，不下载全国数据。"""
    request = PrepareRegionRequest(
        center=Coordinate(latitude=latitude, longitude=longitude),
        radius_m=radius_m,
        network_type=network_type,
        categories=categories or ["attraction", "history", "park"],
    )
    return get_osm_service().prepare_region(request)


if __name__ == "__main__":
    mcp.run(transport="stdio")
