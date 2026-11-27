"""景点顺序优化（开放环 / 闭环，距离 / 时间两种代价口径）。

路网最短路仍由 OsmService.plan_route 计算。本模块负责代价矩阵、
最近邻、非对称 2-opt 和 Held-Karp，再按得到的顺序调用已有规划接口恢复几何。

代价矩阵同时保存两份：
- network_m：按路段长度最短的路径距离；
- travel_s：按道路等级估速后的最快路径时间。

这样同一份缓存可以服务 P1（路网/直线距离）、P4（距离/时间口径对照）和
闭环/开放两种行程模型，不需要为每种口径重复建图。
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from itertools import permutations
from pathlib import Path
from typing import Any

import networkx as nx
import osmnx as ox

from .models import (
    ComponentStats,
    Coordinate,
    OptimizeRequest,
    OptimizeResult,
    OrderAlgorithmResult,
    PairRecord,
    RouteRequest,
    SnapRecord,
    StraightLineComparison,
    UnreachablePair,
)
from .osm_service import SPEED_PROFILE_ID, OsmService, get_osm_service


# 与答辩材料中的 n≤15 保持一致；13–15 个景点时 Held-Karp 可能需要数秒。
HELD_KARP_LIMIT = 15
MATRIX_VERSION = 2
_MATRIX_LOCK = threading.Lock()
_LABELS = {
    "given_order": "当前列表顺序",
    "nearest_neighbor": "最近邻",
    "nearest_neighbor_2opt": "最近邻 + 2-opt",
    "held_karp": "Held-Karp",
}


def open_cost(matrix: list[list[float]], order: list[int]) -> float:
    """固定起点、不返回起点的开放行程代价。order 是景点下标，不含起点。"""
    if not order:
        return 0.0
    total = matrix[0][order[0] + 1]
    for origin, destination in zip(order, order[1:]):
        total += matrix[origin + 1][destination + 1]
    return float(total)


def tour_cost(
    matrix: list[list[float]],
    order: list[int],
    closed_loop: bool = False,
) -> float:
    """开放行程或闭环行程的目标函数；闭环时加上最后一点回起点的边。"""
    total = open_cost(matrix, order)
    if closed_loop and order:
        total += _step(matrix, order[-1] + 1, 0)
    return float(total)


def assert_visit_order(order: list[int], attraction_count: int) -> None:
    if sorted(order) != list(range(attraction_count)):
        raise ValueError("访问顺序必须覆盖每个景点且不能重复，起点不计入景点")


def nearest_neighbor(
    matrix: list[list[float]],
    closed_loop: bool = False,
) -> tuple[list[int], float]:
    attraction_count = len(matrix) - 1
    remaining = set(range(attraction_count))
    current = 0
    order: list[int] = []
    while remaining:
        chosen = min(
            remaining,
            key=lambda attraction: (_step(matrix, current, attraction + 1), attraction),
        )
        if not math.isfinite(_step(matrix, current, chosen + 1)):
            raise ValueError("存在不可达景点，无法生成最近邻顺序")
        order.append(chosen)
        remaining.remove(chosen)
        current = chosen + 1
    assert_visit_order(order, attraction_count)
    return order, tour_cost(matrix, order, closed_loop)


def two_opt(
    matrix: list[list[float]],
    order: list[int],
    closed_loop: bool = False,
) -> tuple[list[int], float]:
    """反转访问子序列，并用完整目标函数接受改进。

    非对称路网反转后，片段内部边的方向会改变，不能套用对称 TSP 的两边增量。
    闭环时目标函数还包含最后一点回起点的边，同样完整重算。
    """
    attraction_count = len(matrix) - 1
    current = list(order)
    assert_visit_order(current, attraction_count)
    current_cost = tour_cost(matrix, current, closed_loop)
    improved = True
    while improved:
        improved = False
        for start in range(len(current)):
            for end in range(start + 1, len(current)):
                candidate = (
                    current[:start]
                    + list(reversed(current[start : end + 1]))
                    + current[end + 1 :]
                )
                candidate_cost = tour_cost(matrix, candidate, closed_loop)
                if candidate_cost + 1e-6 < current_cost:
                    current = candidate
                    current_cost = candidate_cost
                    improved = True
                    break
            if improved:
                break
    assert_visit_order(current, attraction_count)
    return current, current_cost


def held_karp(
    matrix: list[list[float]],
    closed_loop: bool = False,
) -> tuple[list[int], float]:
    attraction_count = len(matrix) - 1
    if attraction_count > HELD_KARP_LIMIT:
        raise ValueError(f"Held-Karp 仅用于不超过{HELD_KARP_LIMIT}个景点的实例")
    if attraction_count == 0:
        return [], 0.0

    size = 1 << attraction_count
    inf = math.inf
    dp = [[inf] * attraction_count for _ in range(size)]
    parent = [[-1] * attraction_count for _ in range(size)]
    for attraction in range(attraction_count):
        dp[1 << attraction][attraction] = _step(matrix, 0, attraction + 1)

    for mask in range(size):
        for ending in range(attraction_count):
            if (mask & (1 << ending)) == 0 or not math.isfinite(dp[mask][ending]):
                continue
            for nxt in range(attraction_count):
                if mask & (1 << nxt):
                    continue
                candidate = dp[mask][ending] + _step(matrix, ending + 1, nxt + 1)
                next_mask = mask | (1 << nxt)
                if candidate < dp[next_mask][nxt]:
                    dp[next_mask][nxt] = candidate
                    parent[next_mask][nxt] = ending

    full = size - 1
    if not any(math.isfinite(dp[full][ending]) for ending in range(attraction_count)):
        raise ValueError("存在不可达景点，无法求解访问顺序")

    if closed_loop:
        ending = min(
            range(attraction_count),
            key=lambda item: (dp[full][item] + _step(matrix, item + 1, 0), item),
        )
        expected = dp[full][ending] + _step(matrix, ending + 1, 0)
    else:
        ending = min(range(attraction_count), key=lambda item: (dp[full][item], item))
        expected = dp[full][ending]

    reversed_order: list[int] = []
    mask = full
    while ending != -1:
        reversed_order.append(ending)
        previous = parent[mask][ending]
        mask ^= 1 << ending
        ending = previous
    order = list(reversed(reversed_order))
    assert_visit_order(order, attraction_count)
    cost = tour_cost(matrix, order, closed_loop)
    if not math.isclose(cost, expected, rel_tol=1e-6, abs_tol=1e-4):
        raise RuntimeError("Held-Karp 回溯代价与状态值不一致")
    return order, cost


def brute_force_open(
    matrix: list[list[float]],
    closed_loop: bool = False,
) -> tuple[list[int], float]:
    attraction_count = len(matrix) - 1
    if attraction_count > 8:
        raise ValueError("全排列核对仅用于不超过8个景点的实例")
    best_order: list[int] | None = None
    best_cost = math.inf
    for perm in permutations(range(attraction_count)):
        order = list(perm)
        cost = tour_cost(matrix, order, closed_loop)
        if cost < best_cost:
            best_order = order
            best_cost = cost
    if best_order is None:
        raise ValueError("没有可枚举的访问顺序")
    return best_order, best_cost


def optimize_open_tour(
    request: OptimizeRequest,
    service: OsmService | None = None,
) -> OptimizeResult:
    service = service or get_osm_service()
    names = _attraction_names(request)
    built = _load_or_build_matrix(service, request, names)

    weight = request.weight
    closed_loop = request.closed_loop
    matrix = built["travel_s"] if weight == "time" else built["network_m"]
    attraction_count = len(request.attractions)
    _require_complete(matrix)

    started = time.perf_counter()
    given_order = list(range(attraction_count))
    given_cost = tour_cost(matrix, given_order, closed_loop)
    given_ms = (time.perf_counter() - started) * 1000

    nn_order, nn_cost, nn_ms = _timed(nearest_neighbor, matrix, closed_loop)
    two_order, two_cost, two_ms = _timed(two_opt, matrix, nn_order, closed_loop)
    exact_order, exact_cost, exact_ms = _timed(held_karp, matrix, closed_loop)
    _require_recomputed(matrix, nn_order, nn_cost, closed_loop, "最近邻")
    _require_recomputed(matrix, two_order, two_cost, closed_loop, "2-opt")
    _require_recomputed(matrix, exact_order, exact_cost, closed_loop, "Held-Karp")
    if two_cost > nn_cost + 1e-4:
        raise RuntimeError("2-opt 接受了使总代价增加的交换")

    improvement = _improvement_percent(nn_cost, two_cost)
    solutions = [
        ("given_order", given_order, given_cost, given_ms, None),
        ("nearest_neighbor", nn_order, nn_cost, nn_ms, None),
        ("nearest_neighbor_2opt", two_order, two_cost, two_ms, improvement),
        ("held_karp", exact_order, exact_cost, exact_ms, None),
    ]
    algorithms: list[OrderAlgorithmResult] = []
    for name, order, cost, elapsed_ms, improvement_percent in solutions:
        route = service.plan_route(
            _route_request(request, order, weight, closed_loop)
        )
        algorithms.append(
            OrderAlgorithmResult(
                algorithm=name,
                label=_LABELS[name],
                order=order,
                names=[names[index] for index in order],
                cost=round(cost, 3),
                cost_unit="s" if weight == "time" else "m",
                cost_m=route.distance_m,
                cost_s=round(route.estimated_duration_min * 60, 1),
                elapsed_ms=round(elapsed_ms, 3),
                gap_percent=_gap_percent(cost, exact_cost),
                improvement_percent=improvement_percent,
                route=route,
            )
        )

    all_names = [request.start_name, *names]
    return OptimizeResult(
        matrix_key=built["matrix_key"],
        network_cache_key=built["network_cache_key"],
        preferred_algorithm="held_karp",
        weight=weight,
        closed_loop=closed_loop,
        cache_hit=built["cache_hit"],
        matrix_elapsed_ms=round(float(built["matrix_elapsed_ms"]), 3),
        matrix_build_ms=round(float(built.get("matrix_build_ms", 0.0)), 3),
        matrix_lookup_ms=round(float(built.get("matrix_lookup_ms", 0.0)), 3),
        snap=[SnapRecord(**item) for item in built["snap"]],
        straight_line=StraightLineComparison(**built["straight_line"]),
        pairs=[PairRecord(**item) for item in built.get("pairs", [])],
        unreachable=[
            UnreachablePair(
                from_index=int(item["from"]),
                to_index=int(item["to"]),
                from_name=all_names[int(item["from"])],
                to_name=all_names[int(item["to"])],
            )
            for item in built.get("unreachable", [])
        ],
        component=(
            ComponentStats(**built["component"])
            if built.get("component")
            else None
        ),
        algorithms=algorithms,
    )


def _route_request(
    request: OptimizeRequest,
    order: list[int],
    weight: str,
    closed_loop: bool,
) -> RouteRequest:
    if closed_loop:
        return RouteRequest(
            start=request.start,
            end=request.start,
            waypoints=[request.attractions[index] for index in order],
            network_type=request.network_type,
            weight=weight,
            closed_loop=True,
            search_radius_m=request.search_radius_m,
        )
    return RouteRequest(
        start=request.start,
        end=request.attractions[order[-1]],
        waypoints=[request.attractions[index] for index in order[:-1]],
        network_type=request.network_type,
        weight=weight,
        closed_loop=False,
        search_radius_m=request.search_radius_m,
    )


def _timed(function, *args):
    started = time.perf_counter()
    order, cost = function(*args)
    return order, cost, (time.perf_counter() - started) * 1000


def _step(matrix: list[list[float]], origin: int, destination: int) -> float:
    value = matrix[origin][destination]
    if value is None:
        return math.inf
    return float(value)


def _require_complete(matrix: list[list[float]]) -> None:
    missing = [
        (origin, destination)
        for origin, row in enumerate(matrix)
        for destination, value in enumerate(row)
        if origin != destination and (value is None or not math.isfinite(value))
    ]
    if missing:
        pairs = "、".join(f"{origin}->{destination}" for origin, destination in missing[:8])
        raise ValueError(
            f"代价矩阵存在不可达点对：{pairs}。"
            "请确认地点位于同一最大强连通路网内，或缩小查询范围。"
        )


def _require_recomputed(
    matrix: list[list[float]],
    order: list[int],
    reported: float,
    closed_loop: bool,
    label: str,
) -> None:
    actual = tour_cost(matrix, order, closed_loop)
    if not math.isclose(actual, reported, rel_tol=1e-6, abs_tol=1e-4):
        raise RuntimeError(f"{label}报告的总代价与目标函数重算不一致")


def _gap_percent(cost: float, optimal: float) -> float | None:
    if not math.isfinite(optimal):
        return None
    if optimal <= 1e-6:
        return 0.0 if cost <= 1e-6 else None
    return round((cost - optimal) / optimal * 100, 2)


def _improvement_percent(before: float, after: float) -> float | None:
    if before <= 1e-6:
        return 0.0
    return round((before - after) / before * 100, 2)


def _attraction_names(request: OptimizeRequest) -> list[str]:
    if request.attraction_names:
        return list(request.attraction_names)
    return [f"景点{index + 1}" for index in range(len(request.attractions))]


def _load_or_build_matrix(
    service: OsmService,
    request: OptimizeRequest,
    names: list[str],
) -> dict[str, Any]:
    points = [request.start, *request.attractions]
    center, radius_m = _query_radius(service, points, request.search_radius_m)
    graph, network_cache_key = service.ensure_network(
        center,
        math.ceil(radius_m),
        request.network_type,
        coverage_points=points,
    )
    matrix_key = _matrix_key(network_cache_key, points, request.network_type)
    path = _matrix_path(service, matrix_key)
    with _MATRIX_LOCK:
        if path.is_file():
            lookup_started = time.perf_counter()
            cached = json.loads(path.read_text(encoding="utf-8"))
            lookup_ms = (time.perf_counter() - lookup_started) * 1000
            if _cache_is_current(cached, matrix_key):
                cached["cache_hit"] = True
                cached["matrix_lookup_ms"] = lookup_ms
                cached["matrix_build_ms"] = float(
                    cached.get("matrix_build_ms", cached.get("matrix_elapsed_ms", 0.0))
                )
                cached["matrix_elapsed_ms"] = lookup_ms
                cached["component"] = service.component_stats_for_key(network_cache_key)
                return cached
        started = time.perf_counter()
        payload = _build_matrix(
            graph,
            points,
            [request.start_name, *names],
            network_cache_key,
            matrix_key,
            request.network_type,
        )
        payload["matrix_build_ms"] = (time.perf_counter() - started) * 1000
        payload["matrix_lookup_ms"] = 0.0
        payload["matrix_elapsed_ms"] = payload["matrix_build_ms"]
        payload["cache_hit"] = False
        payload["component"] = service.component_stats_for_key(network_cache_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return payload


def _cache_is_current(cached: dict[str, Any], matrix_key: str) -> bool:
    return (
        cached.get("matrix_key") == matrix_key
        and cached.get("matrix_version") == MATRIX_VERSION
        and isinstance(cached.get("travel_s"), list)
        and isinstance(cached.get("network_m"), list)
    )


def _build_matrix(
    graph: nx.MultiDiGraph,
    points: list[Coordinate],
    names: list[str],
    network_cache_key: str,
    matrix_key: str,
    network_type: str,
) -> dict[str, Any]:
    nodes = [
        int(node)
        for node in ox.nearest_nodes(
            graph,
            X=[point.longitude for point in points],
            Y=[point.latitude for point in points],
        )
    ]
    length_maps = [
        nx.single_source_dijkstra_path_length(graph, node, weight="length")
        for node in nodes
    ]
    time_maps = [
        nx.single_source_dijkstra_path_length(graph, node, weight="travel_time_s")
        for node in nodes
    ]
    network: list[list[float | None]] = []
    travel: list[list[float | None]] = []
    straight: list[list[float]] = []
    unreachable: list[dict[str, int]] = []
    for origin, origin_node in enumerate(nodes):
        network_row: list[float | None] = []
        travel_row: list[float | None] = []
        straight_row: list[float] = []
        for destination, destination_node in enumerate(nodes):
            straight_row.append(round(_haversine_m(points[origin], points[destination]), 3))
            if origin == destination:
                network_row.append(0.0)
                travel_row.append(0.0)
                continue
            length_value = length_maps[origin].get(destination_node)
            time_value = time_maps[origin].get(destination_node)
            if (
                length_value is None
                or time_value is None
                or not math.isfinite(float(length_value))
                or not math.isfinite(float(time_value))
            ):
                network_row.append(None)
                travel_row.append(None)
                unreachable.append({"from": origin, "to": destination})
            else:
                network_row.append(round(float(length_value), 3))
                travel_row.append(round(float(time_value), 3))
        network.append(network_row)
        travel.append(travel_row)
        straight.append(straight_row)

    snap = []
    for index, (point, node, name) in enumerate(zip(points, nodes, names, strict=True)):
        snapped = Coordinate(
            latitude=float(graph.nodes[node]["y"]),
            longitude=float(graph.nodes[node]["x"]),
        )
        snap.append(
            {
                "index": index,
                "role": "start" if index == 0 else "attraction",
                "name": name,
                "latitude": point.latitude,
                "longitude": point.longitude,
                "node_id": node,
                "snap_distance_m": round(_haversine_m(point, snapped), 1),
            }
        )
    return {
        "matrix_key": matrix_key,
        "matrix_version": MATRIX_VERSION,
        "network_cache_key": network_cache_key,
        "network_type": network_type,
        "speed_profile": SPEED_PROFILE_ID,
        "weights": ["length", "time"],
        "network_m": network,
        "travel_s": travel,
        "straight_m": straight,
        "unreachable": unreachable,
        "pairs": _pair_records(network, travel, straight, names),
        "snap": snap,
        "straight_line": _straight_line_summary(network, straight),
    }


def _pair_records(
    network: list[list[float | None]],
    travel: list[list[float | None]],
    straight: list[list[float]],
    names: list[str],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for origin in range(len(network)):
        for destination in range(origin + 1, len(network)):
            network_m = network[origin][destination]
            baseline = straight[origin][destination]
            ratio = (
                round(float(network_m) / baseline, 4)
                if network_m is not None and baseline >= 1
                else None
            )
            records.append(
                {
                    "from_index": origin,
                    "to_index": destination,
                    "from_name": names[origin],
                    "to_name": names[destination],
                    "network_m": network_m,
                    "travel_s": travel[origin][destination],
                    "straight_m": baseline,
                    "ratio": ratio,
                }
            )
    return records


def _straight_line_summary(
    network: list[list[float | None]],
    straight: list[list[float]],
) -> dict[str, float | int | None]:
    ratios: list[float] = []
    for origin, row in enumerate(network):
        for destination, value in enumerate(row):
            if origin == destination or value is None:
                continue
            baseline = straight[origin][destination]
            if baseline < 1:
                continue
            ratios.append(float(value) / baseline)
    if not ratios:
        return {"pair_count": 0, "mean_ratio": None, "min_ratio": None, "max_ratio": None}
    return {
        "pair_count": len(ratios),
        "mean_ratio": round(sum(ratios) / len(ratios), 4),
        "min_ratio": round(min(ratios), 4),
        "max_ratio": round(max(ratios), 4),
    }


def _query_radius(
    service: OsmService,
    points: list[Coordinate],
    search_radius_m: int,
) -> tuple[Coordinate, float]:
    center = Coordinate(
        latitude=sum(point.latitude for point in points) / len(points),
        longitude=sum(point.longitude for point in points) / len(points),
    )
    required = max(_haversine_m(center, point) for point in points) + 750
    radius_m = max(float(search_radius_m), required)
    if radius_m > service.settings.max_query_radius_m:
        raise ValueError(
            f"路线跨度需要约{radius_m:.0f}米查询半径，超过上限"
            f"{service.settings.max_query_radius_m}米；请缩小区域或分段规划"
        )
    return center, radius_m


def _matrix_path(service: OsmService, matrix_key: str) -> Path:
    return service.datasets_dir / "runtime" / "matrices" / f"{matrix_key}.json"


def _matrix_key(
    network_cache_key: str | None,
    points: list[Coordinate],
    network_type: str,
) -> str:
    payload = {
        "matrix_version": MATRIX_VERSION,
        "network_cache_key": network_cache_key,
        "network_type": network_type,
        "speed_profile": SPEED_PROFILE_ID,
        "points": [
            [round(point.latitude, 6), round(point.longitude, 6)]
            for point in points
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:20]


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
