export interface Coordinate {
  latitude: number
  longitude: number
}

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
  from: Coordinate
  to: Coordinate
}

export interface RouteResult {
  distance_m: number
  estimated_duration_min: number
  network_type: 'walk' | 'bike' | 'drive'
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
