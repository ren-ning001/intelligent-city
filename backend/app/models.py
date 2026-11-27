from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


NetworkType = Literal["walk", "bike", "drive"]
WeightKind = Literal["length", "time"]
SpeedProfile = Literal["highway-speed-v1"]


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
    waypoints: list[Coordinate] = Field(default_factory=list, max_length=16)
    network_type: NetworkType = "walk"
    weight: WeightKind = "length"
    closed_loop: bool = False
    search_radius_m: int = Field(default=5000, ge=500, le=10_000)


class ItineraryRequest(BaseModel):
    points: list[Coordinate] = Field(min_length=2, max_length=15)
    break_before_indexes: list[int] = Field(default_factory=list, max_length=5)
    network_type: NetworkType = "walk"
    weight: WeightKind = "length"
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
    weight: WeightKind = "length"
    closed_loop: bool = False
    speed_profile: SpeedProfile = "highway-speed-v1"
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


class RouteContextStop(BaseModel):
    index: int = Field(ge=1)
    name: str = Field(max_length=120)
    latitude: float
    longitude: float


class RouteContextSegment(BaseModel):
    index: int = Field(ge=0)
    distance_m: float = Field(ge=0)
    duration_min: float = Field(default=0.0, ge=0)


class RouteContext(BaseModel):
    """A compact summary of the route currently displayed by the frontend."""

    distance_m: float = Field(ge=0)
    estimated_duration_min: float = Field(ge=0)
    network_type: NetworkType = "walk"
    weight: WeightKind = "length"
    closed_loop: bool = False
    source: str = Field(default="planner", max_length=40)
    stops: list[RouteContextStop] = Field(default_factory=list, max_length=20)
    segments: list[RouteContextSegment] = Field(default_factory=list, max_length=30)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str = Field(default="zyourroad-main", min_length=1, max_length=128)
    route_context: RouteContext | None = None


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


AlgorithmName = Literal[
    "given_order",
    "nearest_neighbor",
    "nearest_neighbor_2opt",
    "held_karp",
]


class OptimizeRequest(BaseModel):
    start: Coordinate
    start_name: str = Field(default="起点", max_length=80)
    attractions: list[Coordinate] = Field(min_length=2, max_length=15)
    attraction_names: list[str] = Field(default_factory=list, max_length=15)
    weight: WeightKind = "length"
    closed_loop: bool = False
    network_type: NetworkType = "walk"
    search_radius_m: int = Field(default=5000, ge=500, le=10_000)

    @model_validator(mode="after")
    def names_match_attractions(self) -> "OptimizeRequest":
        if self.attraction_names and len(self.attraction_names) != len(self.attractions):
            raise ValueError("景点名称数量必须与景点坐标一致")
        return self


class SnapRecord(BaseModel):
    index: int
    role: Literal["start", "attraction"]
    name: str
    latitude: float
    longitude: float
    node_id: int
    snap_distance_m: float


class StraightLineComparison(BaseModel):
    pair_count: int
    mean_ratio: float | None = None
    min_ratio: float | None = None
    max_ratio: float | None = None


class PairRecord(BaseModel):
    from_index: int
    to_index: int
    from_name: str
    to_name: str
    network_m: float | None = None
    travel_s: float | None = None
    straight_m: float
    ratio: float | None = None


class UnreachablePair(BaseModel):
    from_index: int
    to_index: int
    from_name: str
    to_name: str


class ComponentStats(BaseModel):
    method: str = "largest_strongly_connected"
    nodes_before: int
    nodes_after: int
    edges_before: int
    edges_after: int
    removed_nodes: int
    removed_edges: int
    strongly_connected: bool = True


class OrderAlgorithmResult(BaseModel):
    algorithm: AlgorithmName
    label: str
    order: list[int]
    names: list[str]
    cost: float
    cost_unit: Literal["m", "s"]
    cost_m: float
    cost_s: float
    elapsed_ms: float
    gap_percent: float | None = None
    improvement_percent: float | None = None
    route: RouteResult


class OptimizeResult(BaseModel):
    matrix_key: str
    network_cache_key: str
    preferred_algorithm: AlgorithmName = "held_karp"
    weight: WeightKind = "length"
    closed_loop: bool = False
    cache_hit: bool
    matrix_elapsed_ms: float
    matrix_build_ms: float = 0.0
    matrix_lookup_ms: float = 0.0
    snap: list[SnapRecord]
    straight_line: StraightLineComparison
    pairs: list[PairRecord] = Field(default_factory=list)
    unreachable: list[UnreachablePair] = Field(default_factory=list)
    component: ComponentStats | None = None
    algorithms: list[OrderAlgorithmResult]
