import json

from backend.app.agent_service import AgentArtifactCollector


def _event(event_type: str, data: dict) -> dict:
    return {"event": {"type": event_type, "data": data}}


def test_agent_route_tool_result_becomes_map_artifact() -> None:
    collector = AgentArtifactCollector()
    collector.ingest(
        "session.event",
        _event(
            "tool/call",
            {
                "callId": "route-1",
                "name": "mcp__zyourroad__plan_walking_route",
            },
        ),
    )
    route = {
        "distance_m": 1200.0,
        "estimated_duration_min": 15.0,
        "network_type": "walk",
        "visited_points": [
            {"latitude": 30.25, "longitude": 120.15},
            {"latitude": 30.24, "longitude": 120.14},
        ],
        "geometry": {
            "type": "LineString",
            "coordinates": [[120.15, 30.25], [120.14, 30.24]],
        },
        "segments": [],
        "attribution": "© OpenStreetMap contributors",
    }
    collector.ingest(
        "session.event",
        _event(
            "tool/result",
            {
                "message": {
                    "role": "tool",
                    "source": {"kind": "tool", "callId": "route-1"},
                    "content": [{"type": "text", "text": json.dumps(route)}],
                }
            },
        ),
    )

    assert collector.route is not None
    assert collector.route.distance_m == 1200.0
    assert collector.route.geometry["coordinates"][0] == [120.15, 30.25]


def test_only_published_itinerary_replaces_exploratory_routes() -> None:
    collector = AgentArtifactCollector()
    routes = [
        {
            "distance_m": 2300.0,
            "estimated_duration_min": 30.0,
            "network_type": "walk",
            "visited_points": [
                {"latitude": 31.2289, "longitude": 121.4880},
                {"latitude": 31.2320, "longitude": 121.4910},
                {"latitude": 31.2450, "longitude": 121.4900},
            ],
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [121.4880, 31.2289],
                    [121.4910, 31.2320],
                    [121.4900, 31.2450],
                ],
            },
            "segments": [],
        },
        {
            "distance_m": 1000.0,
            "estimated_duration_min": 13.0,
            "network_type": "walk",
            "visited_points": [
                {"latitude": 31.2390, "longitude": 121.5020},
                {"latitude": 31.2419, "longitude": 121.4953},
            ],
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [121.5020, 31.2390],
                    [121.4953, 31.2419],
                ],
            },
            "segments": [],
        },
    ]
    for index, route in enumerate(routes, start=1):
        call_id = f"route-{index}"
        collector.ingest(
            "session.event",
            _event(
                "tool/call",
                {
                    "callId": call_id,
                    "name": "mcp__zyourroad__plan_walking_route",
                },
            ),
        )
        collector.ingest(
            "session.event",
            _event(
                "tool/result",
                {
                    "message": {
                        "source": {"callId": call_id},
                        "content": [
                            {"type": "text", "text": json.dumps(route)}
                        ],
                    }
                },
            ),
        )

    exploratory = collector.route
    assert exploratory is not None
    assert exploratory.distance_m == 1000.0
    assert len(exploratory.visited_points) == 2

    committed = {
        "distance_m": 3300.0,
        "estimated_duration_min": 43.0,
        "network_type": "walk",
        "visited_points": [
            *routes[0]["visited_points"],
            *routes[1]["visited_points"],
        ],
        "geometry": {
            "type": "MultiLineString",
            "coordinates": [
                routes[0]["geometry"]["coordinates"],
                routes[1]["geometry"]["coordinates"],
            ],
        },
        "segments": [],
        "transfers": [
            {
                "start": routes[0]["visited_points"][-1],
                "end": routes[1]["visited_points"][0],
                "kind": "unrouted-transfer",
            }
        ],
    }
    collector.ingest(
        "session.event",
        _event(
            "tool/call",
            {
                "callId": "route-final",
                "name": "mcp__zyourroad__publish_tourism_itinerary",
            },
        ),
    )
    collector.ingest(
        "session.event",
        _event(
            "tool/result",
            {
                "message": {
                    "source": {"callId": "route-final"},
                    "content": [
                        {"type": "text", "text": json.dumps(committed)}
                    ],
                }
            },
        ),
    )

    published = collector.route
    assert published is not None
    assert published.distance_m == 3300.0
    assert len(published.visited_points) == 5
    assert published.geometry["type"] == "MultiLineString"
    assert len(published.geometry["coordinates"]) == 2
    assert len(published.transfers) == 1


def test_unrelated_tool_result_is_ignored() -> None:
    collector = AgentArtifactCollector()
    collector.ingest(
        "session.event",
        _event(
            "tool/call",
            {"callId": "other-1", "name": "mcp__zyourroad__geocode_location"},
        ),
    )
    collector.ingest(
        "session.event",
        _event(
            "tool/result",
            {
                "message": {
                    "source": {"callId": "other-1"},
                    "content": [{"type": "text", "text": '{"latitude": 30.2}'}],
                }
            },
        ),
    )

    assert collector.route is None
    assert collector.poi_result is None
