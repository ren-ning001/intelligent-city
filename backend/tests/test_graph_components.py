import networkx as nx
import pytest

from backend.app.osm_service import (
    annotate_travel_times,
    highway_speed_kmh,
    keep_largest_strong_component,
)


def _graph_with_islands() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    graph.add_edge(1, 2, length=10.0, highway="footway")
    graph.add_edge(2, 3, length=10.0, highway="footway")
    graph.add_edge(3, 1, length=10.0, highway="footway")
    graph.add_edge(4, 5, length=20.0, highway="path")
    graph.add_edge(5, 4, length=20.0, highway="path")
    graph.add_node(6)
    return graph


def test_keep_largest_strong_component_removes_islands() -> None:
    reduced, stats = keep_largest_strong_component(_graph_with_islands())

    assert set(reduced.nodes) == {1, 2, 3}
    assert nx.is_strongly_connected(reduced)
    assert stats["nodes_before"] == 6
    assert stats["nodes_after"] == 3
    assert stats["removed_nodes"] == 3
    assert stats["edges_before"] == 5
    assert stats["edges_after"] == 3
    assert stats["removed_edges"] == 2
    assert stats["strongly_connected"] is True


def test_keep_largest_strong_component_keeps_connected_graph() -> None:
    graph = nx.MultiDiGraph()
    graph.add_edge(1, 2, length=10.0)
    graph.add_edge(2, 1, length=10.0)

    reduced, stats = keep_largest_strong_component(graph)

    assert reduced is graph
    assert stats["removed_nodes"] == 0
    assert stats["removed_edges"] == 0


def test_annotate_travel_times_uses_highway_speed() -> None:
    graph = nx.MultiDiGraph()
    graph.add_edge(1, 2, length=100.0, highway="steps")
    graph.add_edge(2, 3, length=100.0, highway="footway")

    annotate_travel_times(graph, "walk")

    steps = graph[1][2][0]
    footway = graph[2][3][0]
    assert steps["speed_kmh"] == pytest.approx(2.5)
    assert footway["speed_kmh"] == pytest.approx(4.8)
    assert steps["travel_time_s"] > footway["travel_time_s"]
    assert steps["travel_time_s"] == pytest.approx(100.0 / (2.5 / 3.6), rel=1e-3)


def test_highway_speed_accepts_list_and_unknown_tags() -> None:
    assert highway_speed_kmh(["primary"], "drive") == pytest.approx(55.0)
    assert highway_speed_kmh("unknown-tag", "walk") == pytest.approx(4.8)
    assert highway_speed_kmh(None, "bike") == pytest.approx(15.0)
