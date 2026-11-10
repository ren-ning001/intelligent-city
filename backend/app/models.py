from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


NetworkType = Literal["walk", "bike", "drive"]


class Coordinate(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class GeocodeRequest(BaseModel):
    query: str = Field(min_length=2, max_length=200)


class GeocodeResult(Coordinate):
    query: str
    display_name: str


class LocationSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    limit: int = Field(default=8, ge=1, le=12)


class LocationSearchResult(BaseModel):
    query: str
    results: list[GeocodeResult]


class PoiSearchRequest(BaseModel):
    location: str | None = Field(default=None, min_length=2, max_length=200)
    center: Coordinate | None = None
    radius_m: int = Field(default=3000, ge=100, le=10_000)
    categories: list[str] = Field(default_factory=lambda: ["attraction", "history", "park"])
    exclude_categories: list[str] = Field(default_factory=list)
    require_name: bool = True
    limit: int = Field(default=40, ge=1, le=100)

    @model_validator(mode="after")
    def require_search_origin(self) -> "PoiSearchRequest":
        if self.location is None and self.center is None:
            raise ValueError("location 和 center 至少提供一个")
        return self


class PoiFeature(BaseModel):
    osm_type: str
    osm_id: str
    name: str
    categories: dict[str, Any]
    latitude: float
    longitude: float


class PoiSearchResult(BaseModel):
    center: Coordinate
    radius_m: int
    source: Literal[
        "demo-cache",
        "offline-region",
        "query-cache",
        "openstreetmap",
    ]
    total: int
    pois: list[PoiFeature]
    attribution: str = "© OpenStreetMap contributors"


class RouteRequest(BaseModel):
    start: Coordinate
    end: Coordinate
    waypoints: list[Coordinate] = Field(default_factory=list, max_length=12)
    network_type: NetworkType = "walk"
    search_radius_m: int = Field(default=5000, ge=500, le=10_000)


class ItineraryRequest(BaseModel):
    points: list[Coordinate] = Field(min_length=2, max_length=12)
    break_before_indexes: list[int] = Field(default_factory=list, max_length=5)
    network_type: NetworkType = "walk"
    search_radius_m: int = Field(default=5000, ge=500, le=10_000)

    @model_validator(mode="after")
    def validate_breaks(self) -> "ItineraryRequest":
        breaks = sorted(set(self.break_before_indexes))
        if breaks != self.break_before_indexes:
            raise ValueError("break_before_indexes 必须严格递增且不能重复")
        boundaries = [0, *breaks, len(self.points)]
        if any(
            end - start < 2
            for start, end in zip(boundaries[:-1], boundaries[1:], strict=True)
        ):
            raise ValueError("每个连续步行段至少需要两个地点")
        return self


class RouteResult(BaseModel):
    distance_m: float
    estimated_duration_min: float
    network_type: NetworkType
    visited_points: list[Coordinate]
    geometry: dict[str, Any]
    segments: list[dict[str, Any]]
    transfers: list[dict[str, Any]] = Field(default_factory=list)
    attribution: str = "© OpenStreetMap contributors"


class PrepareRegionRequest(BaseModel):
    center: Coordinate
    radius_m: int = Field(default=3000, ge=500, le=10_000)
    network_type: NetworkType = "walk"
    categories: list[str] = Field(default_factory=lambda: ["attraction", "history", "park"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str = Field(default="zyourroad-main", min_length=1, max_length=128)


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    finish_reason: str | None = None
    route: RouteResult | None = None
    poi_result: PoiSearchResult | None = None


class ConversationMessage(BaseModel):
    id: str
    role: Literal["user", "agent", "system"]
    content: str
    created_at: str


class ConversationSummary(BaseModel):
    session_id: str
    title: str
    message_count: int
    updated_at: str


class ConversationList(BaseModel):
    sessions: list[ConversationSummary]


class ConversationTrace(BaseModel):
    id: str
    tool: str
    title: str
    detail: str
    status: Literal["running", "completed", "failed"]


class ConversationHistory(BaseModel):
    session_id: str
    messages: list[ConversationMessage]
    traces: list[ConversationTrace] = Field(default_factory=list)


class ToolEventRecord(BaseModel):
    id: str
    method: str
    payload: dict[str, Any]
    created_at: str


class ToolEventHistory(BaseModel):
    session_id: str
    events: list[ToolEventRecord]
