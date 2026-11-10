from __future__ import annotations

from typing import Any

from .models import Coordinate, RouteResult


def _same_coordinate(first: Coordinate, second: Coordinate) -> bool:
    return (
        abs(first.latitude - second.latitude) < 1e-7
        and abs(first.longitude - second.longitude) < 1e-7
    )


def _route_lines(route: RouteResult) -> list[list[list[float]]]:
    coordinates = route.geometry.get("coordinates", [])
    if route.geometry.get("type") == "MultiLineString":
        return coordinates if isinstance(coordinates, list) else []
    if route.geometry.get("type") == "LineString" and isinstance(coordinates, list):
        return [coordinates]
    return []


def merge_route_results(routes: list[RouteResult]) -> RouteResult | None:
    if not routes:
        return None
    if len(routes) == 1:
        return routes[0]

    lines: list[list[list[float]]] = []
    visited: list[Coordinate] = []
    segments: list[dict[str, Any]] = []
    transfers: list[dict[str, Any]] = []
    for route in routes:
        lines.extend(_route_lines(route))
        route_points = route.visited_points
        if visited and route_points:
            if _same_coordinate(visited[-1], route_points[0]):
                visited.extend(route_points[1:])
            else:
                transfers.append(
                    {
                        "start": visited[-1].model_dump(),
                        "end": route_points[0].model_dump(),
                        "kind": "unrouted-transfer",
                    }
                )
                visited.extend(route_points)
        elif route_points:
            visited.extend(route_points)
        for segment in route.segments:
            merged_segment = dict(segment)
            merged_segment["index"] = len(segments)
            segments.append(merged_segment)

    return RouteResult(
        distance_m=round(sum(route.distance_m for route in routes), 1),
        estimated_duration_min=round(
            sum(route.estimated_duration_min for route in routes),
            1,
        ),
        network_type=routes[0].network_type,
        visited_points=visited,
        geometry={
            "type": "MultiLineString",
            "coordinates": lines,
        },
        segments=segments,
        transfers=transfers,
        attribution=routes[0].attribution,
    )
