export interface Coordinate {
  latitude: number
  longitude: number
}

export type NetworkType = 'walk' | 'bike' | 'drive'
export type WeightKind = 'length' | 'time'
export type CostUnit = 'm' | 's'

export interface HealthStatus {
  status: string
  service: string
  deepseek_configured: boolean
  dsh_profile: string
  dsh_model: string
  dsh_session_root: string
  dsh_session_files: number
  zyourroad_conversation_files: number
  zyourroad_event_files: number
  supported_categories: string[]
  offline_regions: Array<{
    id: string
    name: string
    available: boolean
  }>
}

export interface GeocodeResult extends Coordinate {
  query: string
  display_name: string
}

export interface LocationSearchResult {
  query: string
  results: GeocodeResult[]
}

export interface PoiFeature {
  osm_type: string
  osm_id: string
  name: string
  categories: Record<string, boolean>
  latitude: number
  longitude: number
}

export interface PoiSearchResult {
  center: Coordinate
  radius_m: number
  source: 'demo-cache' | 'offline-region' | 'query-cache' | 'openstreetmap'
  total: number
  pois: PoiFeature[]
  attribution: string
}

export interface RouteSegment {
  index: number
  distance_m: number
  duration_min?: number
  from: Coordinate
  to: Coordinate
}

export interface RouteResult {
  distance_m: number
  estimated_duration_min: number
  network_type: NetworkType
  weight: WeightKind
  closed_loop: boolean
  speed_profile: string
  visited_points: Coordinate[]
  geometry:
    | {
        type: 'LineString'
        coordinates: [number, number][]
      }
    | {
        type: 'MultiLineString'
        coordinates: [number, number][][]
      }
  segments: RouteSegment[]
  transfers: Array<{
    start: Coordinate
    end: Coordinate
    kind: 'unrouted-transfer'
  }>
  attribution: string
}

export interface ChatMessage {
  id: string
  role: 'agent' | 'user' | 'system'
  content: string
  pending?: boolean
}

export interface AgentTrace {
  id: string
  tool: string
  title: string
  detail: string
  status: 'running' | 'completed' | 'failed'
}

export interface ConversationSummary {
  session_id: string
  title: string
  message_count: number
  updated_at: string
}

export interface ConversationHistory {
  session_id: string
  messages: Array<{
    id: string
    role: 'user' | 'agent' | 'system'
    content: string
    created_at: string
  }>
  traces: AgentTrace[]
}

export interface ChatResponse {
  session_id: string
  answer: string
  finish_reason?: string | null
  route?: RouteResult | null
  poi_result?: PoiSearchResult | null
}

export type AlgorithmName =
  | 'given_order'
  | 'nearest_neighbor'
  | 'nearest_neighbor_2opt'
  | 'held_karp'

export interface OrderAlgorithmResult {
  algorithm: AlgorithmName
  label: string
  order: number[]
  names: string[]
  cost: number
  cost_unit: CostUnit
  cost_m: number
  cost_s: number
  elapsed_ms: number
  gap_percent: number | null
  improvement_percent: number | null
  route: RouteResult
}

export interface PairRecord {
  from_index: number
  to_index: number
  from_name: string
  to_name: string
  network_m: number | null
  travel_s: number | null
  straight_m: number
  ratio: number | null
}

export interface ComponentStats {
  method: string
  nodes_before: number
  nodes_after: number
  edges_before: number
  edges_after: number
  removed_nodes: number
  removed_edges: number
  strongly_connected: boolean
}

export interface UnreachablePair {
  from_index: number
  to_index: number
  from_name: string
  to_name: string
}

export interface RouteContextStop {
  index: number
  name: string
  latitude: number
  longitude: number
}

export interface RouteContextSegment {
  index: number
  distance_m: number
  duration_min: number
}

export interface RouteContext {
  distance_m: number
  estimated_duration_min: number
  network_type: NetworkType
  weight: WeightKind
  closed_loop: boolean
  source: string
  stops: RouteContextStop[]
  segments: RouteContextSegment[]
}

export interface OptimizeResult {
  matrix_key: string
  network_cache_key: string
  preferred_algorithm: AlgorithmName
  weight: WeightKind
  closed_loop: boolean
  cache_hit: boolean
  matrix_elapsed_ms: number
  matrix_build_ms: number
  matrix_lookup_ms: number
  pairs: PairRecord[]
  unreachable: UnreachablePair[]
  component: ComponentStats | null
  snap: Array<{
    index: number
    role: 'start' | 'attraction'
    name: string
    latitude: number
    longitude: number
    node_id: number
    snap_distance_m: number
  }>
  straight_line: {
    pair_count: number
    mean_ratio: number | null
    min_ratio: number | null
    max_ratio: number | null
  }
  algorithms: OrderAlgorithmResult[]
}
