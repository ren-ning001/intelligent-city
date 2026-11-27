import math

import pytest

from backend.app.models import Coordinate, OptimizeRequest, PoiSearchRequest
from backend.app.order_optimizer import (
    brute_force_open,
    held_karp,
    nearest_neighbor,
    open_cost,
    optimize_open_tour,
    tour_cost,
    two_opt,
)
from backend.app.osm_service import OsmService


def _asymmetric_trap() -> list[list[float]]:
    # 最近邻会先走便宜的 A，再被迫走很长的下一段。
    # 反转 A-B 时内部边方向从 1 变成 100，完整重算必须拒绝这次交换。
    return [
        [0, 5, 4, 9],
        [9, 0, 1, 8],
        [9, 100, 0, 3],
        [9, 2, 7, 0],
    ]


def test_held_karp_matches_permutation_on_asymmetric_matrix() -> None:
    matrix = _asymmetric_trap()
    exact_order, exact_cost = held_karp(matrix)
    brute_order, brute_cost = brute_force_open(matrix)

    assert math.isclose(exact_cost, brute_cost)
    assert math.isclose(exact_cost, open_cost(matrix, exact_order))
    assert math.isclose(brute_cost, open_cost(matrix, brute_order))
    assert sorted(exact_order) == [0, 1, 2]


def test_held_karp_closed_matches_permutation() -> None:
    matrix = _asymmetric_trap()
    exact_order, exact_cost = held_karp(matrix, closed_loop=True)
    brute_order, brute_cost = brute_force_open(matrix, closed_loop=True)

    assert math.isclose(exact_cost, brute_cost)
    assert math.isclose(exact_cost, tour_cost(matrix, exact_order, True))
    assert math.isclose(brute_cost, tour_cost(matrix, brute_order, True))
    assert sorted(exact_order) == [0, 1, 2]
    assert tour_cost(matrix, exact_order, True) > open_cost(matrix, exact_order)


def test_closed_tour_adds_return_leg() -> None:
    matrix = _asymmetric_trap()
    order = [0, 1, 2]
    assert math.isclose(
        tour_cost(matrix, order, True) - open_cost(matrix, order),
        matrix[3][0],
    )


def test_two_opt_rejects_reversal_that_increases_directed_cost() -> None:
    matrix = _asymmetric_trap()
    start = [0, 1, 2]
    start_cost = open_cost(matrix, start)
    reversed_cost = open_cost(matrix, [1, 0, 2])
    assert reversed_cost > start_cost

    order, cost = two_opt(matrix, start)

    assert cost <= start_cost + 1e-6
    assert order != [1, 0, 2]
    assert math.isclose(cost, open_cost(matrix, order))


def test_two_opt_can_improve_nearest_neighbor_without_raising_cost() -> None:
    matrix = [
        [0, 1, 4, 8],
        [9, 0, 100, 3],
        [9, 1, 0, 1],
        [9, 4, 8, 0],
    ]
    nn_order, nn_cost = nearest_neighbor(matrix)
    improved, improved_cost = two_opt(matrix, nn_order)
    exact_order, exact_cost = held_karp(matrix)

    assert nn_order == [0, 2, 1]
    assert improved_cost <= nn_cost + 1e-6
    assert improved_cost < nn_cost
    assert math.isclose(improved_cost, exact_cost)
    assert sorted(improved) == [0, 1, 2]
    assert 0 not in improved or improved.count(0) == 1
    assert math.isclose(exact_cost, open_cost(matrix, exact_order))


def test_nearest_neighbor_does_not_count_start_as_attraction() -> None:
    matrix = [
        [0, 2, 5],
        [4, 0, 1],
        [4, 3, 0],
    ]
    order, cost = nearest_neighbor(matrix)

    assert order == [0, 1]
    assert math.isclose(cost, 3)
    assert math.isclose(cost, open_cost(matrix, order))


def test_open_tour_on_west_lake_demo_graph_is_comparable() -> None:
    service = OsmService()
    pois = service.search_pois(
        PoiSearchRequest(
            center=Coordinate(latitude=30.248, longitude=120.148),
            radius_m=1800,
            categories=["attraction", "history", "park"],
            limit=8,
        )
    )
    unique = []
    seen: set[str] = set()
    for poi in pois.pois:
        if poi.name in seen:
            continue
        seen.add(poi.name)
        unique.append(poi)
        if len(unique) == 4:
            break
    assert len(unique) == 4

    result = optimize_open_tour(
        OptimizeRequest(
            start=Coordinate(
                latitude=unique[0].latitude,
                longitude=unique[0].longitude,
            ),
            start_name=unique[0].name,
            attractions=[
                Coordinate(latitude=poi.latitude, longitude=poi.longitude)
                for poi in unique[1:]
            ],
            attraction_names=[poi.name for poi in unique[1:]],
        ),
        service,
    )

    by_name = {item.algorithm: item for item in result.algorithms}
    assert set(by_name) == {
        "given_order",
        "nearest_neighbor",
        "nearest_neighbor_2opt",
        "held_karp",
    }
    optimal = by_name["held_karp"].cost_m
    assert by_name["nearest_neighbor"].cost_m + 0.2 >= optimal
    assert by_name["nearest_neighbor_2opt"].cost_m + 0.2 >= optimal
    assert by_name["nearest_neighbor_2opt"].cost_m <= by_name["nearest_neighbor"].cost_m + 0.2
    assert result.straight_line.pair_count > 0
    assert result.straight_line.mean_ratio is not None
    assert result.straight_line.mean_ratio >= 1
    for item in result.algorithms:
        assert sorted(item.order) == [0, 1, 2]
        assert item.route.distance_m > 0
        assert len(item.route.segments) == 3
        assert abs(item.route.distance_m - item.cost_m) < 5
        assert item.cost_unit == "m"
    assert all(record.snap_distance_m >= 0 for record in result.snap)
    assert result.pairs
    assert result.component is not None
    assert result.component.strongly_connected is True

    time_result = optimize_open_tour(
        OptimizeRequest(
            start=Coordinate(
                latitude=unique[0].latitude,
                longitude=unique[0].longitude,
            ),
            start_name=unique[0].name,
            attractions=[
                Coordinate(latitude=poi.latitude, longitude=poi.longitude)
                for poi in unique[1:]
            ],
            attraction_names=[poi.name for poi in unique[1:]],
            weight="time",
            closed_loop=True,
        ),
        service,
    )
    assert time_result.weight == "time"
    assert time_result.closed_loop is True
    assert time_result.matrix_key == result.matrix_key
    assert all(item.cost_unit == "s" for item in time_result.algorithms)
    assert all(item.route.closed_loop for item in time_result.algorithms)
    assert all(len(item.route.segments) == 4 for item in time_result.algorithms)
    assert all(len(item.route.visited_points) == 4 for item in time_result.algorithms)


def test_unreachable_matrix_is_rejected() -> None:
    matrix = [
        [0, math.inf, 1],
        [math.inf, 0, math.inf],
        [1, math.inf, 0],
    ]
    with pytest.raises(ValueError, match="不可达"):
        nearest_neighbor(matrix)
