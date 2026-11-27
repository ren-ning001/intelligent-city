from fastapi.testclient import TestClient

from backend.app.main import _trace_from_notification, app


def test_health_does_not_expose_secrets() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "api_key" not in payload
    assert "DEEPSEEK_API_KEY" not in response.text


def test_poi_categories_are_validated() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/pois/search",
            json={
                "center": {"latitude": 30.2525, "longitude": 120.1552},
                "categories": ["not-a-real-category"],
            },
        )

    assert response.status_code == 400
    assert "未知POI类别" in response.json()["detail"]


def test_optimize_route_rejects_unknown_weight() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/routes/optimize",
            json={
                "start": {"latitude": 30.25, "longitude": 120.15},
                "attractions": [
                    {"latitude": 30.24, "longitude": 120.14},
                    {"latitude": 30.23, "longitude": 120.13},
                ],
                "weight": "crowding",
            },
        )

    assert response.status_code == 422


def test_optimize_route_requires_at_least_two_attractions() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/routes/optimize",
            json={
                "start": {"latitude": 30.25, "longitude": 120.15},
                "attractions": [{"latitude": 30.24, "longitude": 120.14}],
            },
        )

    assert response.status_code == 422


def test_matrix_export_rejects_path_traversal_key() -> None:
    with TestClient(app) as client:
        response = client.get("/api/routes/optimize/..%2F..%2Fetc/pairs.csv")

    assert response.status_code in (400, 404)


def test_location_search_returns_local_west_lake_candidates() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/geocode/search",
            json={"query": "断桥残雪", "limit": 5},
        )

    assert response.status_code == 200
    results = response.json()["results"]
    assert results
    assert any("断桥" in result["display_name"] for result in results)
    assert all(29.8 <= result["latitude"] <= 30.6 for result in results)


def test_tool_notifications_become_auditable_traces() -> None:
    names: dict[str, str] = {}
    started = _trace_from_notification(
        {
            "method": "session.event",
            "payload": {
                "event": {
                    "type": "tool/call",
                    "data": {
                        "callId": "call-1",
                        "name": "mcp__zyourroad__plan_walking_route",
                        "arguments": '{"waypoints": [{}, {}]}',
                    },
                }
            },
        },
        names,
    )
    completed = _trace_from_notification(
        {
            "method": "session.event",
            "payload": {
                "event": {
                    "type": "tool/result",
                    "data": {
                        "message": {
                            "source": {"callId": "call-1"},
                            "isError": False,
                        }
                    },
                }
            },
        },
        names,
    )

    assert started is not None
    assert started["status"] == "running"
    assert "2 个途经点" in started["detail"]
    assert completed is not None
    assert completed["status"] == "completed"


def test_order_optimizer_tool_has_auditable_detail() -> None:
    from backend.app.main import _tool_detail

    detail = _tool_detail(
        "optimize_itinerary_order",
        '{"attractions": [{}, {}, {}], "weight": "time", "closed_loop": true}',
    )
    assert "时间" in detail
    assert "闭环" in detail
    assert "3 个景点" in detail


def test_route_context_block_marks_interface_route_as_current() -> None:
    from backend.app.agent_service import _route_context_block
    from backend.app.models import (
        RouteContext,
        RouteContextSegment,
        RouteContextStop,
    )

    text = _route_context_block(
        RouteContext(
            distance_m=1020.0,
            estimated_duration_min=13.0,
            source="planner",
            stops=[
                RouteContextStop(
                    index=1,
                    name="断桥残雪",
                    latitude=30.2587,
                    longitude=120.1480,
                )
            ],
            segments=[
                RouteContextSegment(index=0, distance_m=300.0, duration_min=4.0)
            ],
        )
    )

    assert "当前界面路线" in text
    assert "断桥残雪" in text
    assert "1.02 km" in text
    assert "不要声称没有" in text


def test_plan_route_closed_loop_keeps_single_start_marker() -> None:
    start = {"latitude": 30.258, "longitude": 120.148}
    with TestClient(app) as client:
        response = client.post(
            "/api/routes/plan",
            json={
                "start": start,
                "end": start,
                "waypoints": [
                    {"latitude": 30.248, "longitude": 120.140},
                    {"latitude": 30.240, "longitude": 120.150},
                ],
                "closed_loop": True,
                "weight": "length",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["closed_loop"] is True
    assert len(payload["visited_points"]) == 3
    assert len(payload["segments"]) == 3
    assert payload["segments"][-1]["to"] == payload["visited_points"][0]
