from __future__ import annotations

import asyncio
import csv
import io
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from .agent_service import get_agent_service
from .config import get_settings
from .conversation_store import get_conversation_store
from .models import (
    ChatRequest,
    ChatResponse,
    ConversationHistory,
    ConversationList,
    GeocodeRequest,
    GeocodeResult,
    LocationSearchRequest,
    LocationSearchResult,
    OptimizeRequest,
    OptimizeResult,
    PoiSearchRequest,
    PoiSearchResult,
    PrepareRegionRequest,
    RouteRequest,
    RouteResult,
    ToolEventHistory,
)
from .order_optimizer import optimize_open_tour
from .osm_service import get_osm_service


settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    get_agent_service().close()


app = FastAPI(
    title="ZYourRoad API",
    version="0.1.0",
    description="OSM、路径规划与 DeepSeek Harness Agent 后端。",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _bad_request(error: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(error))


@app.get("/api/health")
def health() -> dict[str, Any]:
    osm_service = get_osm_service()
    return {
        "status": "ok",
        "service": settings.app_name,
        "deepseek_configured": settings.deepseek_configured,
        "dsh_profile": settings.dsh_profile,
        "dsh_model": settings.dsh_model,
        "dsh_session_root": str(settings.dsh_sessions_dir),
        "dsh_session_files": sum(
            1 for path in settings.dsh_sessions_dir.rglob("session*.jsonl*")
            if path.is_file()
        ),
        "zyourroad_conversation_files": sum(
            1 for path in settings.dsh_sessions_dir.rglob("zyourroad-chat.jsonl")
            if path.is_file()
        ),
        "zyourroad_event_files": sum(
            1 for path in settings.dsh_sessions_dir.rglob("zyourroad-events.jsonl")
            if path.is_file()
        ),
        "supported_categories": osm_service.supported_categories(),
        "offline_regions": [
            {
                "id": region.region_id,
                "name": region.name,
                "available": region.available,
            }
            for region in osm_service.offline_regions.regions
        ],
    }


@app.post("/api/geocode", response_model=GeocodeResult)
async def geocode(request: GeocodeRequest) -> GeocodeResult:
    try:
        return await run_in_threadpool(get_osm_service().geocode, request.query)
    except Exception as error:
        raise _bad_request(error) from error


@app.post("/api/geocode/search", response_model=LocationSearchResult)
async def search_locations(request: LocationSearchRequest) -> LocationSearchResult:
    try:
        return await run_in_threadpool(
            get_osm_service().search_locations,
            request.query,
            request.limit,
        )
    except Exception as error:
        raise _bad_request(error) from error


@app.post("/api/pois/search", response_model=PoiSearchResult)
async def search_pois(request: PoiSearchRequest) -> PoiSearchResult:
    try:
        return await run_in_threadpool(get_osm_service().search_pois, request)
    except Exception as error:
        raise _bad_request(error) from error


@app.post("/api/routes/plan", response_model=RouteResult)
async def plan_route(request: RouteRequest) -> RouteResult:
    try:
        return await run_in_threadpool(get_osm_service().plan_route, request)
    except Exception as error:
        raise _bad_request(error) from error


@app.post("/api/regions/prepare")
async def prepare_region(request: PrepareRegionRequest) -> dict[str, Any]:
    try:
        return await run_in_threadpool(get_osm_service().prepare_region, request)
    except Exception as error:
        raise _bad_request(error) from error


@app.post("/api/agent/chat", response_model=ChatResponse)
async def agent_chat(request: ChatRequest) -> ChatResponse:
    try:
        return await run_in_threadpool(
            get_agent_service().chat,
            request.message,
            request.session_id,
            None,
            request.route_context,
        )
    except Exception as error:
        raise _bad_request(error) from error


@app.get("/api/agent/sessions", response_model=ConversationList)
async def list_agent_sessions() -> ConversationList:
    sessions = await run_in_threadpool(get_conversation_store().list_sessions)
    return ConversationList(sessions=sessions)


@app.get(
    "/api/agent/sessions/{session_id}",
    response_model=ConversationHistory,
)
async def get_agent_session(session_id: str) -> ConversationHistory:
    try:
        store = get_conversation_store()
        messages, events = await asyncio.gather(
            run_in_threadpool(store.messages, session_id),
            run_in_threadpool(store.events, session_id),
        )
        return ConversationHistory(
            session_id=session_id,
            messages=messages,
            traces=_stored_traces(events),
        )
    except Exception as error:
        raise _bad_request(error) from error


@app.get(
    "/api/agent/sessions/{session_id}/events",
    response_model=ToolEventHistory,
)
async def get_agent_session_events(session_id: str) -> ToolEventHistory:
    try:
        events = await run_in_threadpool(
            get_conversation_store().events,
            session_id,
        )
        return ToolEventHistory(session_id=session_id, events=events)
    except Exception as error:
        raise _bad_request(error) from error


def _sse(event: str, payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {data}\n\n"


TOOL_LABELS = {
    "geocode_location": "解析地点",
    "search_tourism_pois": "检索旅游POI",
    "prepare_osm_region": "准备区域地图数据",
    "plan_walking_route": "计算真实步行路线",
    "optimize_itinerary_order": "优化景点访问顺序",
    "publish_tourism_itinerary": "发布最终游览路线",
    "list_mcp_resources": "列出 MCP 资源",
    "list_mcp_resource_templates": "列出 MCP 资源模板",
    "pwsh": "执行 PowerShell",
    "bash": "执行 Shell",
    "read_file": "读取本地文件",
}


def _tool_name(public_name: str) -> str:
    return public_name.rsplit("__", maxsplit=1)[-1]


def _tool_detail(name: str, raw_arguments: Any) -> str:
    try:
        arguments = (
            json.loads(raw_arguments)
            if isinstance(raw_arguments, str)
            else raw_arguments
        )
    except json.JSONDecodeError:
        arguments = {}
    if not isinstance(arguments, dict):
        return "正在执行受约束的地图工具"
    if name == "geocode_location":
        return f"查找“{arguments.get('query', '用户指定地点')}”的真实坐标"
    if name == "search_tourism_pois":
        categories = arguments.get("categories") or ["默认旅游类别"]
        return f"查询 {', '.join(map(str, categories))}，半径 {arguments.get('radius_m', 3000)} 米"
    if name == "prepare_osm_region":
        return f"下载或读取半径 {arguments.get('radius_m', 3000)} 米的小区域缓存"
    if name == "plan_walking_route":
        waypoints = arguments.get("waypoints") or []
        return f"在真实路网上连接起终点与 {len(waypoints)} 个途经点"
    if name == "optimize_itinerary_order":
        attractions = arguments.get("attractions") or []
        weight = "时间" if arguments.get("weight") == "time" else "距离"
        loop = "闭环" if arguments.get("closed_loop") else "开放"
        return f"按{weight}权重比较 {len(attractions)} 个景点的{loop}顺序"
    if name == "publish_tourism_itinerary":
        points = arguments.get("points") or []
        breaks = arguments.get("break_before_indexes") or []
        return f"发布 {len(points)} 个地点，包含 {len(breaks)} 处非步行衔接"
    if name in {"list_mcp_resources", "list_mcp_resource_templates"}:
        server = arguments.get("server") or "全部 MCP 服务"
        kind = "资源模板" if name.endswith("templates") else "资源清单"
        return f"查询 {server} 的{kind}（用于探查，不是路线数据）"
    if name in {"pwsh", "bash"}:
        command = str(arguments.get("command") or "").strip().replace("\n", " ")
        label = "PowerShell" if name == "pwsh" else "Shell"
        return f"执行{label}命令：{command[:150]}"
    if name == "read_file":
        path = str(arguments.get("path") or arguments.get("target_file") or "")
        return f"读取 {path[:150]}"
    return "正在执行受约束的地图工具"


def _tool_error_text(message: dict[str, Any]) -> str | None:
    content = message.get("content")
    if not isinstance(content, list):
        return None
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "text":
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        first = next((line.strip() for line in text.splitlines() if line.strip()), "")
        return first[:180] or None
    return None


def _trace_from_notification(
    notification: dict[str, Any],
    call_names: dict[str, str],
    call_details: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    if notification.get("method") != "session.event":
        return None
    payload = notification.get("payload")
    event = payload.get("event") if isinstance(payload, dict) else None
    if not isinstance(event, dict):
        return None
    data = event.get("data")
    if not isinstance(data, dict):
        return None

    if event.get("type") == "tool/call":
        call_id = data.get("callId")
        public_name = data.get("name")
        if not isinstance(call_id, str) or not isinstance(public_name, str):
            return None
        name = _tool_name(public_name)
        call_names[call_id] = name
        detail = _tool_detail(name, data.get("arguments"))
        if call_details is not None:
            call_details[call_id] = detail
        return {
            "id": call_id,
            "tool": name,
            "title": TOOL_LABELS.get(name, "调用工具"),
            "detail": detail,
            "status": "running",
        }

    if event.get("type") != "tool/result":
        return None
    message = data.get("message")
    if not isinstance(message, dict):
        return None
    source = message.get("source")
    call_id = source.get("callId") if isinstance(source, dict) else None
    if not isinstance(call_id, str):
        call_id = message.get("toolCallId")
    if not isinstance(call_id, str):
        return None
    name = call_names.get(call_id, "tool")
    failed = message.get("isError") is True
    error = data.get("error")
    reason = error.get("reason") if isinstance(error, dict) else None
    base = (call_details or {}).get(call_id)
    if failed:
        error_text = str(reason) if reason else _tool_error_text(message)
        detail = (
            f"{base}；失败：{error_text}" if base and error_text
            else base or (f"失败：{error_text}" if error_text else "调用失败，Agent将停止无效重试")
        )
    else:
        detail = f"{base}；已完成" if base else "已获得可验证的数据"
    return {
        "id": call_id,
        "tool": name,
        "title": TOOL_LABELS.get(name, "调用工具"),
        "detail": detail[:260],
        "status": "failed" if failed else "completed",
    }


def _stored_traces(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    call_names: dict[str, str] = {}
    call_details: dict[str, str] = {}
    traces: list[dict[str, Any]] = []
    indexes: dict[str, int] = {}
    for record in records:
        trace = _trace_from_notification(
            {
                "method": record.get("method"),
                "payload": record.get("payload"),
            },
            call_names,
            call_details,
        )
        if trace is None:
            continue
        trace_id = str(trace["id"])
        index = indexes.get(trace_id)
        if index is None:
            indexes[trace_id] = len(traces)
            traces.append(trace)
        else:
            traces[index] = trace
    return traces


@app.post("/api/agent/chat/stream")
async def agent_chat_stream(request: ChatRequest) -> StreamingResponse:
    async def generate() -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        notifications: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        call_names: dict[str, str] = {}
        call_details: dict[str, str] = {}

        def on_notification(notification: dict[str, Any]) -> None:
            loop.call_soon_threadsafe(notifications.put_nowait, notification)

        yield _sse("status", {"stage": "thinking", "message": "Agent正在理解并规划…"})
        task = asyncio.create_task(
            asyncio.to_thread(
                get_agent_service().chat,
                request.message,
                request.session_id,
                on_notification,
                request.route_context,
            )
        )

        while not task.done() or not notifications.empty():
            try:
                notification = await asyncio.wait_for(notifications.get(), timeout=0.25)
            except TimeoutError:
                continue
            method = str(notification.get("method", "notification"))
            if method in {"session.event", "session.status", "session.query.completed"}:
                yield _sse("notification", notification)
            trace = _trace_from_notification(
                notification,
                call_names,
                call_details,
            )
            if trace is not None:
                yield _sse("trace", trace)

        try:
            response = await task
            yield _sse("message", response.model_dump())
            yield _sse("done", {"session_id": response.session_id})
        except Exception as error:
            yield _sse("error", {"message": str(error)})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/routes/optimize", response_model=OptimizeResult)
async def optimize_route(request: OptimizeRequest) -> OptimizeResult:
    try:
        return await run_in_threadpool(optimize_open_tour, request)
    except Exception as error:
        raise _bad_request(error) from error


_MATRIX_KEY_PATTERN = re.compile(r"^[a-f0-9]{20}$")


@app.get("/api/routes/optimize/{matrix_key}/pairs.csv")
async def export_matrix_pairs(matrix_key: str) -> Response:
    """导出已缓存矩阵的逐对距离，便于报告绘图和复核。"""
    if not _MATRIX_KEY_PATTERN.fullmatch(matrix_key):
        raise HTTPException(status_code=400, detail="matrix_key 格式不正确")
    path = settings.datasets_dir / "runtime" / "matrices" / f"{matrix_key}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="没有找到该矩阵缓存")
    payload = json.loads(path.read_text(encoding="utf-8"))
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "from_index",
            "from_name",
            "to_index",
            "to_name",
            "network_m",
            "travel_s",
            "straight_m",
            "ratio",
        ]
    )
    for pair in payload.get("pairs", []):
        writer.writerow(
            [
                pair.get("from_index"),
                pair.get("from_name"),
                pair.get("to_index"),
                pair.get("to_name"),
                pair.get("network_m"),
                pair.get("travel_s"),
                pair.get("straight_m"),
                pair.get("ratio"),
            ]
        )
    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="zyourroad-pairs-{matrix_key}.csv"'
            )
        },
    )
