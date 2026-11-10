import pytest
from fastapi.testclient import TestClient

from backend.app import main as main_module
from backend.app.agent_service import AgentService
from backend.app.config import Settings
from backend.app.conversation_store import ConversationStore


@pytest.fixture
def conversation_store(tmp_path) -> ConversationStore:
    settings = Settings(dsh_home=tmp_path / ".dsh-home")
    return ConversationStore(settings)


def test_conversation_store_persists_utf8_jsonl(
    conversation_store: ConversationStore,
) -> None:
    conversation_store.append("session-test", "user", "规划一条西湖路线")
    conversation_store.append("session-test", "agent", "路线已规划。")

    path = conversation_store.transcript_path("session-test")
    assert path.is_file()
    assert "规划一条西湖路线" in path.read_text(encoding="utf-8")
    assert [item["role"] for item in conversation_store.messages("session-test")] == [
        "user",
        "agent",
    ]

    sessions = conversation_store.list_sessions()
    assert sessions[0]["session_id"] == "session-test"
    assert sessions[0]["title"] == "规划一条西湖路线"
    assert sessions[0]["message_count"] == 2


def test_tool_calls_and_full_results_are_persisted(
    conversation_store: ConversationStore,
) -> None:
    conversation_store.append_tool_notification(
        "session-tools",
        "session.event",
        {
            "event": {
                "type": "tool/call",
                "data": {
                    "callId": "call-1",
                    "name": "mcp__zyourroad__search_tourism_pois",
                    "arguments": '{"categories":["park"]}',
                },
            }
        },
    )
    conversation_store.append_tool_notification(
        "session-tools",
        "session.event",
        {
            "event": {
                "type": "tool/result",
                "data": {
                    "message": {
                        "source": {"callId": "call-1"},
                        "content": [
                            {
                                "type": "text",
                                "text": '{"total":1,"pois":[{"name":"公园"}]}',
                            }
                        ],
                    }
                },
            }
        },
    )

    events = conversation_store.events("session-tools")
    assert len(events) == 2
    assert conversation_store.events_path("session-tools").is_file()
    result_text = events[1]["payload"]["event"]["data"]["message"]["content"][0]["text"]
    assert '"公园"' in result_text


def test_conversation_store_rejects_path_traversal(
    conversation_store: ConversationStore,
) -> None:
    with pytest.raises(ValueError, match="无效的会话ID"):
        conversation_store.append("../escape", "user", "不应写入")


def test_agent_startup_failure_is_still_saved(
    conversation_store: ConversationStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = AgentService(
        settings=conversation_store.settings,
        conversations=conversation_store,
    )

    def fail_to_start():
        raise RuntimeError("runtime unavailable")

    monkeypatch.setattr(service, "_get_harness", fail_to_start)

    with pytest.raises(RuntimeError, match="runtime unavailable"):
        service.chat("请规划路线", "session-failed")

    assert [
        item["role"] for item in conversation_store.messages("session-failed")
    ] == ["user", "system"]


def test_conversation_history_api(
    conversation_store: ConversationStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_store.append("session-api", "user", "上海路线")
    conversation_store.append("session-api", "agent", "已收到。")
    conversation_store.append_tool_notification(
        "session-api",
        "session.event",
        {
            "event": {
                "type": "tool/call",
                "data": {
                    "callId": "route-final",
                    "name": "mcp__zyourroad__publish_tourism_itinerary",
                    "arguments": '{"points":[{},{}]}',
                },
            }
        },
    )
    conversation_store.append_tool_notification(
        "session-api",
        "session.event",
        {
            "event": {
                "type": "tool/result",
                "data": {
                    "message": {
                        "source": {"callId": "route-final"},
                        "isError": False,
                    }
                },
            }
        },
    )
    monkeypatch.setattr(
        main_module,
        "get_conversation_store",
        lambda: conversation_store,
    )

    with TestClient(main_module.app) as client:
        sessions_response = client.get("/api/agent/sessions")
        history_response = client.get("/api/agent/sessions/session-api")
        events_response = client.get(
            "/api/agent/sessions/session-api/events"
        )

    assert sessions_response.status_code == 200
    assert sessions_response.json()["sessions"][0]["title"] == "上海路线"
    assert history_response.status_code == 200
    assert [item["content"] for item in history_response.json()["messages"]] == [
        "上海路线",
        "已收到。",
    ]
    assert history_response.json()["traces"][0]["status"] == "completed"
    assert events_response.status_code == 200
    assert len(events_response.json()["events"]) == 2
