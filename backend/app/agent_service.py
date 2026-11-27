from __future__ import annotations

import json
import threading
from collections.abc import Callable
from typing import Any

from deepseek_harness import DeepSeekHarness
from deepseek_harness.errors import JsonRpcError

from .config import Settings, get_settings
from .conversation_store import ConversationStore, get_conversation_store
from .models import ChatResponse, PoiSearchResult, RouteContext, RouteResult


NotificationCallback = Callable[[dict[str, Any]], None]


def _route_context_block(context: RouteContext) -> str:
    """Render the route currently shown by the frontend for the next turn."""
    network = {"walk": "步行", "bike": "骑行", "drive": "驾车"}.get(
        context.network_type,
        context.network_type,
    )
    weight = "最短时间" if context.weight == "time" else "最短距离"
    loop = "闭环（最后回到起点）" if context.closed_loop else "开放路线"
    lines = [
        "【当前界面路线（规划器已显示）】",
        "说明：这是用户界面上正在显示的路线，不是本轮 MCP 工具的历史记录。",
        "用户问“解释当前路线/为什么这样走”时必须以此为准，不要声称没有"
        "已规划或已发布的路线；若用户要改路线，再调用工具重新规划。",
        "上下文没有给出的算法细节不要编造；来源不是 optimize/agent 时，"
        "不要声称做过 TSP、2-opt 或算法对比。",
        f"- 出行方式：{network}；优化口径：{weight}；{loop}",
        (
            f"- 总距离：{context.distance_m / 1000:.2f} km；"
            f"预计时间：{context.estimated_duration_min:.1f} 分钟；"
            f"来源：{context.source}"
        ),
    ]
    if context.stops:
        lines.append(
            "- 访问顺序："
            + " -> ".join(
                f"{stop.index}.{stop.name}({stop.latitude:.5f},{stop.longitude:.5f})"
                for stop in context.stops
            )
        )
    if context.segments:
        lines.append(
            "- 分段："
            + "；".join(
                f"第{segment.index + 1}段 {segment.distance_m / 1000:.2f} km"
                f"/{segment.duration_min:.0f} min"
                for segment in context.segments
            )
        )
    return "\n".join(lines)


def _content_texts(value: Any) -> list[str]:
    if isinstance(value, list):
        return [text for item in value for text in _content_texts(item)]
    if not isinstance(value, dict):
        return []
    texts: list[str] = []
    if value.get("type") == "text" and isinstance(value.get("text"), str):
        texts.append(value["text"])
    for key, child in value.items():
        if key not in {"text", "type"}:
            texts.extend(_content_texts(child))
    return texts


def _decode_tool_payload(message: dict[str, Any]) -> dict[str, Any] | None:
    for text in _content_texts(message.get("content")):
        candidate = text.strip()
        if candidate.startswith("```") and candidate.endswith("```"):
            candidate = candidate.split("\n", maxsplit=1)[-1].rsplit("```", maxsplit=1)[0]
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


class AgentArtifactCollector:
    """Collect structured GIS results from one DSH run's durable tool events."""

    def __init__(self) -> None:
        self._tool_names: dict[str, str] = {}
        self._exploratory_routes: list[RouteResult] = []
        self._committed_route: RouteResult | None = None
        self.poi_result: PoiSearchResult | None = None

    @property
    def route(self) -> RouteResult | None:
        if self._committed_route is not None:
            return self._committed_route
        return (
            self._exploratory_routes[-1]
            if self._exploratory_routes
            else None
        )

    def ingest(self, method: str, payload: dict[str, Any]) -> None:
        if method != "session.event":
            return
        event = payload.get("event")
        if not isinstance(event, dict):
            return
        data = event.get("data")
        if not isinstance(data, dict):
            return

        if event.get("type") == "tool/call":
            call_id = data.get("callId")
            name = data.get("name")
            if isinstance(call_id, str) and isinstance(name, str):
                self._tool_names[call_id] = name
            return

        if event.get("type") != "tool/result":
            return
        message = data.get("message")
        if not isinstance(message, dict) or message.get("isError") is True:
            return
        source = message.get("source")
        call_id = source.get("callId") if isinstance(source, dict) else None
        if not isinstance(call_id, str):
            call_id = message.get("toolCallId")
        if not isinstance(call_id, str):
            return
        name = self._tool_names.get(call_id, "")
        result = _decode_tool_payload(message)
        if result is None:
            return

        try:
            if name.endswith("__publish_tourism_itinerary"):
                self._committed_route = RouteResult.model_validate(result)
            elif name.endswith("__plan_walking_route"):
                route = RouteResult.model_validate(result)
                signature = tuple(
                    (
                        round(point.latitude, 7),
                        round(point.longitude, 7),
                    )
                    for point in route.visited_points
                )
                known_signatures = {
                    tuple(
                        (
                            round(point.latitude, 7),
                            round(point.longitude, 7),
                        )
                        for point in existing.visited_points
                    )
                    for existing in self._exploratory_routes
                }
                if signature not in known_signatures:
                    self._exploratory_routes.append(route)
            elif name.endswith("__search_tourism_pois"):
                self.poi_result = PoiSearchResult.model_validate(result)
        except ValueError:
            return


class AgentService:
    """Own one reusable DSH SDK process and expose serialized chat turns."""

    def __init__(
        self,
        settings: Settings | None = None,
        conversations: ConversationStore | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.conversations = conversations or get_conversation_store()
        self._harness: DeepSeekHarness | None = None
        self._lock = threading.RLock()
        self._active_sessions: set[str] = set()

    def _get_harness(self) -> DeepSeekHarness:
        api_key = self.settings.deepseek_api_key
        if api_key is None or not api_key.get_secret_value().strip():
            raise RuntimeError(
                "尚未设置 DEEPSEEK_API_KEY。请在启动后端前通过环境变量注入，"
                "不要把密钥写入源码或提交到Git。"
            )
        if not self.settings.dsh_patch.is_file():
            raise RuntimeError(f"DSH插件Patch不存在：{self.settings.dsh_patch}")

        if self._harness is None:
            self.settings.export_dsh_environment()
            self._harness = DeepSeekHarness(
                provider=self.settings.dsh_provider,
                model=self.settings.dsh_model,
                max_tokens=self.settings.dsh_max_tokens,
                api_key=api_key.get_secret_value(),
                cwd=str(self.settings.datasets_dir.parent),
                dsh_home=str(self.settings.dsh_home),
                profile=self.settings.dsh_profile,
                patches=(str(self.settings.dsh_patch),),
            )
        return self._harness

    def _get_session(
        self,
        harness: DeepSeekHarness,
        session_id: str,
    ) -> tuple[Any, bool]:
        if session_id in self._active_sessions:
            return harness.start_session(session_id), True
        try:
            session = harness.resume_session(session_id)
            resumed = True
        except JsonRpcError as error:
            if "not found" not in error.message.casefold():
                raise
            session = harness.start_session(session_id)
            resumed = False
        self._active_sessions.add(session_id)
        return session, resumed

    def chat(
        self,
        message: str,
        session_id: str,
        on_notification: NotificationCallback | None = None,
        route_context: RouteContext | None = None,
    ) -> ChatResponse:
        with self._lock:
            stored_context = self.conversations.context(session_id)
            self.conversations.append(session_id, "user", message)
            try:
                harness = self._get_harness()
                active_before = session_id in self._active_sessions
                native_transcript = any(
                    path.is_file()
                    for path in self.conversations.session_dir(session_id).glob(
                        "session*.jsonl*"
                    )
                )
                session, resumed = self._get_session(harness, session_id)
                artifacts = AgentArtifactCollector()

                def callback(notification: Any) -> None:
                    self.conversations.append_tool_notification(
                        session_id,
                        notification.method,
                        notification.payload,
                    )
                    artifacts.ingest(notification.method, notification.payload)
                    if on_notification is not None:
                        on_notification(
                            {
                                "method": notification.method,
                                "payload": notification.payload,
                            }
                        )

                input_message = message
                route_block = (
                    _route_context_block(route_context) if route_context else ""
                )
                native_context_available = active_before or (
                    resumed and native_transcript
                )
                if stored_context and not native_context_available:
                    input_message = (
                        "后端刚恢复，但原生DSH会话日志不可用。以下是本应用可靠保存的"
                        "先前对话，请据此无缝继续，不要逐字复述：\n\n"
                        f"{stored_context}"
                    )
                    if route_block:
                        input_message += f"\n\n{route_block}"
                    input_message += f"\n\n当前用户消息：{message}"
                elif route_block:
                    input_message = f"{route_block}\n\n当前用户消息：{message}"
                result = session.run(
                    input_message,
                    on_notification=callback,
                )
                response = ChatResponse(
                    session_id=result.session_id,
                    answer=result.final_response,
                    finish_reason=result.finish_reason,
                    route=artifacts.route,
                    poi_result=artifacts.poi_result,
                )
                self.conversations.append(
                    session_id,
                    "agent",
                    response.answer or "Agent已完成处理，但没有返回文本。",
                )
                return response
            except Exception as error:
                self.conversations.append(
                    session_id,
                    "system",
                    f"请求失败：{type(error).__name__}",
                )
                raise

    def close(self) -> None:
        with self._lock:
            if self._harness is not None:
                self._harness.close()
                self._harness = None
            self._active_sessions.clear()


_agent_service: AgentService | None = None


def get_agent_service() -> AgentService:
    global _agent_service
    if _agent_service is None:
        _agent_service = AgentService()
    return _agent_service
