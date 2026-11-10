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
