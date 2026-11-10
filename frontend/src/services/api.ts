import type {
  AgentTrace,
  ChatResponse,
  Coordinate,
  ConversationHistory,
  ConversationSummary,
  GeocodeResult,
  HealthStatus,
  LocationSearchResult,
  PoiSearchResult,
  RouteResult,
} from '../types'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail ?? '请求失败')
  }
  return response.json() as Promise<T>
}

export const getHealth = () => request<HealthStatus>('/api/health')

export const getAgentSessions = async () =>
  (await request<{ sessions: ConversationSummary[] }>('/api/agent/sessions')).sessions

export const getAgentSession = (sessionId: string) =>
  request<ConversationHistory>(`/api/agent/sessions/${encodeURIComponent(sessionId)}`)

export const geocode = (query: string) =>
  request<GeocodeResult>('/api/geocode', {
    method: 'POST',
    body: JSON.stringify({ query }),
  })

export const searchLocations = (query: string, limit = 8, signal?: AbortSignal) =>
  request<LocationSearchResult>('/api/geocode/search', {
    method: 'POST',
    body: JSON.stringify({ query, limit }),
    signal,
  })

export const searchPois = (
  center: Coordinate,
  categories = ['attraction', 'history', 'park'],
  radiusM = 3000,
) =>
  request<PoiSearchResult>('/api/pois/search', {
    method: 'POST',
    body: JSON.stringify({
      center,
      categories,
      radius_m: radiusM,
      limit: 60,
    }),
  })

export const planRoute = (
  start: Coordinate,
  end: Coordinate,
  waypoints: Coordinate[] = [],
) =>
  request<RouteResult>('/api/routes/plan', {
    method: 'POST',
    body: JSON.stringify({
      start,
      end,
      waypoints,
      network_type: 'walk',
      search_radius_m: 5000,
    }),
  })

interface StreamCallbacks {
  onStatus?: (message: string) => void
  onTrace?: (trace: AgentTrace) => void
  onMessage: (response: ChatResponse) => void
  onError: (message: string) => void
}

export async function streamAgentChat(
  message: string,
  sessionId: string,
  callbacks: StreamCallbacks,
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/agent/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId }),
  })
  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(payload.detail ?? 'Agent连接失败')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const consume = (block: string) => {
    const lines = block.split('\n')
    const event = lines.find((line) => line.startsWith('event:'))?.slice(6).trim()
    const dataText = lines.find((line) => line.startsWith('data:'))?.slice(5).trim()
    if (!event || !dataText) return
    const data = JSON.parse(dataText)
    if (event === 'status') callbacks.onStatus?.(data.message)
    if (event === 'trace') callbacks.onTrace?.(data)
    if (event === 'message') callbacks.onMessage(data)
    if (event === 'error') callbacks.onError(data.message)
  }

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() ?? ''
    blocks.forEach(consume)
    if (done) break
  }
  if (buffer.trim()) consume(buffer)
}
