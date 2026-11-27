<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Activity, Bot, Layers3, Map, PanelLeftOpen, Plus, X } from 'lucide-vue-next'
import AgentPanel from './components/AgentPanel.vue'
import FloatingPanel from './components/FloatingPanel.vue'
import MapCanvas from './components/MapCanvas.vue'
import PlannerPanel from './components/PlannerPanel.vue'
import {
  getAgentSession,
  getAgentSessions,
  getHealth,
  optimizeRoute,
  planRoute,
  searchPois,
  streamAgentChat,
} from './services/api'
import type {
  AgentTrace,
  AlgorithmName,
  ChatMessage,
  ConversationSummary,
  GeocodeResult,
  HealthStatus,
  OptimizeResult,
  PoiFeature,
  PoiSearchResult,
  RouteContext,
  RouteResult,
  WeightKind,
} from './types'

const WEST_LAKE = { latitude: 30.2525, longitude: 120.1552 }
const health = ref<HealthStatus | null>(null)
const route = ref<RouteResult | null>(null)
const priorRoutes = ref<RouteResult[]>([])
const pois = ref<PoiFeature[]>([])
const poiLoaded = ref(false)
const dataSource = ref('')
const planning = ref(false)
const optimizing = ref(false)
const optimizeResult = ref<OptimizeResult | null>(null)
const selectedAlgorithm = ref<AlgorithmName | ''>('')
const agentThinking = ref(false)
const agentSteps = ref<AgentTrace[]>([])
const plannerOpen = ref(true)
const agentOpen = ref(true)
const agentSessions = ref<ConversationSummary[]>([])
const plannerPanel = ref<InstanceType<typeof PlannerPanel> | null>(null)
const selectedPoi = ref<PoiFeature | null>(null)
const toast = ref('')
const storedSessionId = window.localStorage.getItem('zyourroad.session-id')
const sessionId = ref(storedSessionId || `session-${crypto.randomUUID()}`)
window.localStorage.setItem('zyourroad.session-id', sessionId.value)
const welcomeMessage: ChatMessage = {
  id: 'welcome',
  role: 'agent',
  content:
    '你好，我是 YourRoad。告诉我你想去哪里、偏好什么、最多走多远，我会调用真实OSM工具完成规划与验证。',
}
const messages = ref<ChatMessage[]>([
  {
    ...welcomeMessage,
  },
])
let healthTimer: number | undefined

const mapContext = computed(() => {
  const point = route.value?.visited_points[0] ?? pois.value[0]
  if (!point) return '城市旅游路径规划'
  const { latitude, longitude } = point
  if (
    latitude >= 30.6 && latitude <= 31.9
    && longitude >= 120.84 && longitude <= 122.2
  ) return '上海 · 离线城市包'
  if (
    latitude >= 39.4 && latitude <= 41.1
    && longitude >= 115.4 && longitude <= 117.6
  ) return '北京 · 离线城市包'
  if (
    latitude >= 29.8 && latitude <= 30.6
    && longitude >= 119.8 && longitude <= 120.6
  ) return '杭州 · 西湖实验区'
  if (
    latitude >= 27 && latitude <= 31.3
    && longitude >= 118 && longitude <= 123
  ) return '浙江 · 离线城市包'
  return '自定义城市区域'
})

function poiSourceLabel(source: PoiSearchResult['source'], agent = false) {
  const prefix = agent ? 'Agent · ' : ''
  if (source === 'demo-cache') return `${prefix}西湖演示缓存`
  if (source === 'offline-region') return `${prefix}离线城市数据包`
  if (source === 'query-cache') return `${prefix}OSM查询缓存`
  return `${prefix}OSM实时查询`
}

function showToast(message: string) {
  toast.value = message
  window.setTimeout(() => {
    if (toast.value === message) toast.value = ''
  }, 3600)
}

async function loadHealth() {
  try {
    health.value = await getHealth()
  } catch {
    health.value = null
  }
}

async function loadDemoPois() {
  try {
    const result = await searchPois(WEST_LAKE, ['attraction', 'history', 'park'], 3000)
    pois.value = result.pois
    poiLoaded.value = true
    dataSource.value = poiSourceLabel(result.source)
  } catch (error) {
    showToast(error instanceof Error ? error.message : 'POI加载失败')
  }
}

async function handlePlan(payload: {
  points: GeocodeResult[]
  categories: string[]
  weight: WeightKind
}) {
  if (payload.points.length < 2) return
  planning.value = true
  priorRoutes.value = []
  optimizeResult.value = null
  selectedAlgorithm.value = ''
  selectedPoi.value = null
  try {
    const start = payload.points[0]!
    const end = payload.points[payload.points.length - 1]!
    const waypoints = payload.points.slice(1, -1)
    const center = {
      latitude:
        payload.points.reduce((sum, point) => sum + point.latitude, 0)
        / payload.points.length,
      longitude:
        payload.points.reduce((sum, point) => sum + point.longitude, 0)
        / payload.points.length,
    }
    const [routeResult, poiResult] = await Promise.all([
      planRoute(start, end, waypoints, { weight: payload.weight }),
      searchPois(center, payload.categories, 3000),
    ])
    route.value = routeResult
    pois.value = poiResult.pois
    poiLoaded.value = true
    dataSource.value = poiSourceLabel(poiResult.source)
  } catch (error) {
    showToast(error instanceof Error ? error.message : '路线规划失败')
  } finally {
    planning.value = false
  }
}

async function handleOptimize(payload: {
  start: GeocodeResult
  attractions: GeocodeResult[]
  categories: string[]
  weight: WeightKind
  closedLoop: boolean
}) {
  if (payload.attractions.length < 2) return
  optimizing.value = true
  selectedPoi.value = null
  try {
    const points = [payload.start, ...payload.attractions]
    const center = {
      latitude: points.reduce((sum, point) => sum + point.latitude, 0) / points.length,
      longitude: points.reduce((sum, point) => sum + point.longitude, 0) / points.length,
    }
    const [result, poiResult] = await Promise.all([
      optimizeRoute(
        payload.start,
        payload.attractions,
        payload.start.display_name.split(',')[0] ?? '起点',
        payload.attractions.map((point) => point.display_name.split(',')[0] ?? '景点'),
        { weight: payload.weight, closedLoop: payload.closedLoop },
      ),
      searchPois(center, payload.categories, 3000),
    ])
    optimizeResult.value = result
    priorRoutes.value = []
    const preferred = result.algorithms.find(
      (item) => item.algorithm === result.preferred_algorithm,
    ) ?? result.algorithms[0]
    selectedAlgorithm.value = preferred?.algorithm ?? ''
    if (preferred) route.value = preferred.route
    pois.value = poiResult.pois
    poiLoaded.value = true
    dataSource.value = poiSourceLabel(poiResult.source)
  } catch (error) {
    showToast(error instanceof Error ? error.message : '顺序优化失败')
  } finally {
    optimizing.value = false
  }
}

async function handleReplan(payload: {
  points: GeocodeResult[]
  categories: string[]
  weight: WeightKind
  closedLoop: boolean
}) {
  if (payload.points.length < 2) return
  const previous = route.value
  planning.value = true
  selectedPoi.value = null
  try {
    const first = payload.points[0]!
    const last = payload.points[payload.points.length - 1]!
    const start = first
    const end = payload.closedLoop ? first : last
    const waypoints = payload.closedLoop
      ? payload.points.slice(1)
      : payload.points.slice(1, -1)
    const center = {
      latitude:
        payload.points.reduce((sum, point) => sum + point.latitude, 0)
        / payload.points.length,
      longitude:
        payload.points.reduce((sum, point) => sum + point.longitude, 0)
        / payload.points.length,
    }
    const [routeResult, poiResult] = await Promise.all([
      planRoute(start, end, waypoints, {
        weight: payload.weight,
        closedLoop: payload.closedLoop,
      }),
      searchPois(center, payload.categories, 3000),
    ])
    optimizeResult.value = null
    selectedAlgorithm.value = ''
    if (previous) {
      priorRoutes.value = [...priorRoutes.value, previous].slice(-5)
    }
    route.value = routeResult
    pois.value = poiResult.pois
    poiLoaded.value = true
    dataSource.value = poiSourceLabel(poiResult.source)
  } catch (error) {
    showToast(error instanceof Error ? error.message : '仅保留地点规划失败')
  } finally {
    planning.value = false
  }
}

function handleSelectAlgorithm(algorithm: AlgorithmName) {
  const selected = optimizeResult.value?.algorithms.find((item) => item.algorithm === algorithm)
  if (!selected) return
  priorRoutes.value = []
  selectedAlgorithm.value = algorithm
  route.value = selected.route
}

function addSelectedPoiToRoute() {
  if (!selectedPoi.value) return
  plannerPanel.value?.addPoi(selectedPoi.value)
  showToast(`已将“${selectedPoi.value.name}”加入路线`)
  selectedPoi.value = null
}

async function refreshAgentSessions() {
  try {
    agentSessions.value = await getAgentSessions()
  } catch {
    // Chat remains usable when the optional history list is unavailable.
  }
}

function createNewConversation() {
  if (agentThinking.value) return
  sessionId.value = `session-${crypto.randomUUID()}`
  window.localStorage.setItem('zyourroad.session-id', sessionId.value)
  messages.value = [{ ...welcomeMessage, id: `welcome-${crypto.randomUUID()}` }]
  agentSteps.value = []
  route.value = null
  priorRoutes.value = []
  optimizeResult.value = null
  selectedAlgorithm.value = ''
  dataSource.value = '新对话'
}

async function selectConversation(selectedSessionId: string, force = false) {
  if (
    agentThinking.value
    || (!force && selectedSessionId === sessionId.value)
  ) return
  try {
    const history = await getAgentSession(selectedSessionId)
    sessionId.value = selectedSessionId
    window.localStorage.setItem('zyourroad.session-id', selectedSessionId)
    messages.value = history.messages.map((message) => ({
      id: message.id,
      role: message.role,
      content: message.content,
    }))
    if (!messages.value.length) messages.value = [{ ...welcomeMessage }]
    agentSteps.value = history.traces
    route.value = null
    priorRoutes.value = []
    optimizeResult.value = null
    selectedAlgorithm.value = ''
    selectedPoi.value = null
    dataSource.value = '历史对话'
  } catch (error) {
    showToast(error instanceof Error ? error.message : '会话加载失败')
  }
}

function samePoint(
  first: { latitude: number; longitude: number },
  second: { latitude: number; longitude: number },
) {
  return (
    Math.abs(first.latitude - second.latitude) < 0.000001
    && Math.abs(first.longitude - second.longitude) < 0.000001
  )
}

function buildRouteContext(): RouteContext | null {
  const current = route.value
  if (!current) return null
  const stops = current.visited_points.map((point, index) => {
    const poi = pois.value.find((item) => samePoint(item, point))
    return {
      index: index + 1,
      name: poi?.name ?? `地点${index + 1}`,
      latitude: point.latitude,
      longitude: point.longitude,
    }
  })
  return {
    distance_m: current.distance_m,
    estimated_duration_min: current.estimated_duration_min,
    network_type: current.network_type,
    weight: current.weight,
    closed_loop: current.closed_loop,
    source: optimizeResult.value ? 'optimize' : 'planner',
    stops,
    segments: current.segments.map((segment) => ({
      index: segment.index,
      distance_m: segment.distance_m,
      duration_min: segment.duration_min ?? 0,
    })),
  }
}

async function handleAgentMessage(message: string) {
  messages.value.push({
    id: crypto.randomUUID(),
    role: 'user',
    content: message,
  })
  agentSteps.value = []
  agentThinking.value = true
  try {
    await streamAgentChat(message, sessionId.value, {
      onStatus: (status) => {
        dataSource.value = status
      },
      onTrace: (trace) => {
        const index = agentSteps.value.findIndex((step) => step.id === trace.id)
        if (index === -1) agentSteps.value.push(trace)
        else agentSteps.value[index] = trace
      },
      onMessage: (response) => {
        if (response.route) {
          route.value = response.route
          priorRoutes.value = []
          optimizeResult.value = null
          selectedAlgorithm.value = ''
          dataSource.value = 'Agent · OSM真实路网'
        }
        if (response.poi_result) {
          pois.value = response.poi_result.pois
          poiLoaded.value = true
          dataSource.value = poiSourceLabel(response.poi_result.source, true)
        }
        messages.value.push({
          id: crypto.randomUUID(),
          role: 'agent',
          content: response.answer || 'Agent已完成处理，但没有返回文本。',
        })
        void refreshAgentSessions()
      },
      onError: (error) => {
        messages.value.push({
          id: crypto.randomUUID(),
          role: 'system',
          content: error,
        })
        void refreshAgentSessions()
      },
    }, buildRouteContext())
  } catch (error) {
    messages.value.push({
      id: crypto.randomUUID(),
      role: 'system',
      content: error instanceof Error ? error.message : 'Agent连接失败',
    })
    void refreshAgentSessions()
  } finally {
    agentThinking.value = false
  }
}

onMounted(async () => {
  await loadHealth()
  if (!health.value) {
    showToast('后端尚未启动，请运行 start-backend.ps1')
  }
  healthTimer = window.setInterval(loadHealth, 20_000)
  await loadDemoPois()
  await refreshAgentSessions()
  if (
    storedSessionId
    && agentSessions.value.some((session) => session.session_id === storedSessionId)
  ) {
    await selectConversation(storedSessionId, true)
  }
})

onUnmounted(() => {
  if (healthTimer !== undefined) window.clearInterval(healthTimer)
})
</script>

<template>
  <main class="app-shell">
    <MapCanvas
      :route="route"
      :prior-routes="priorRoutes"
      :pois="pois"
      @select-poi="selectedPoi = $event"
    />
    <div class="map-vignette" />
    <div class="ambient ambient--one" />
    <div class="ambient ambient--two" />

    <header class="topbar glass-panel">
      <div class="brand-mark">
        <Map :size="21" />
      </div>
      <div class="brand">
        <strong>ZYourRoad</strong>
        <span>PATH INTELLIGENCE</span>
      </div>
      <div class="topbar-divider" />
      <div class="topbar-context">
        <Layers3 :size="14" />
        {{ mapContext }}
      </div>
      <div class="system-status">
        <span :class="{ online: health?.status === 'ok' }" />
        <div>
          <strong>{{ health?.status === 'ok' ? 'SYSTEM ONLINE' : 'CONNECTING' }}</strong>
          <small>{{ health?.dsh_model || 'DeepSeek Harness' }}</small>
        </div>
      </div>
    </header>

    <FloatingPanel
      v-model:open="plannerOpen"
      panel-id="planner"
      title="路线规划器"
      :initial-width="440"
      :initial-height="720"
      :initial-x="24"
      :initial-y="98"
      :min-width="380"
      :min-height="520"
    >
      <PlannerPanel
        ref="plannerPanel"
        :loading="planning"
        :optimizing="optimizing"
        :route="route"
        :pois="pois"
        :poi-count="poiLoaded ? pois.length : null"
        :data-source="dataSource"
        :comparison="optimizeResult"
        :selected-algorithm="selectedAlgorithm"
        @plan="handlePlan"
        @optimize="handleOptimize"
        @replan="handleReplan"
        @select-algorithm="handleSelectAlgorithm"
      />
    </FloatingPanel>

    <FloatingPanel
      v-model:open="agentOpen"
      panel-id="agent"
      title="DeepSeek Harness Agent"
      :initial-width="480"
      :initial-height="720"
      :initial-right="24"
      :initial-y="98"
      :min-width="400"
      :min-height="520"
    >
      <AgentPanel
        :messages="messages"
        :steps="agentSteps"
        :sessions="agentSessions"
        :current-session-id="sessionId"
        :thinking="agentThinking"
        :configured="Boolean(health?.deepseek_configured)"
        @new-chat="createNewConversation"
        @select-session="selectConversation"
        @send="handleAgentMessage"
      />
    </FloatingPanel>

    <div v-if="!plannerOpen || !agentOpen" class="window-dock">
      <button v-if="!plannerOpen" type="button" @click="plannerOpen = true">
        <PanelLeftOpen :size="15" />
        路线规划器
      </button>
      <button v-if="!agentOpen" type="button" @click="agentOpen = true">
        <Bot :size="15" />
        Agent
      </button>
    </div>

    <div v-if="selectedPoi" class="poi-card glass-panel">
      <button class="poi-card__close" type="button" aria-label="关闭" @click="selectedPoi = null">
        <X :size="15" />
      </button>
      <span class="poi-card__kicker">SELECTED POINT</span>
      <strong>{{ selectedPoi.name }}</strong>
      <div class="poi-card__meta">
        <Activity :size="13" />
        {{ Object.keys(selectedPoi.categories).join(' · ') || 'OSM POI' }}
      </div>
      <small>
        {{ selectedPoi.latitude.toFixed(5) }},
        {{ selectedPoi.longitude.toFixed(5) }}
      </small>
      <button class="poi-card__add" type="button" @click="addSelectedPoiToRoute">
        <Plus :size="13" />
        加入当前路线
      </button>
    </div>

    <Transition name="toast">
      <div v-if="toast" class="toast">{{ toast }}</div>
    </Transition>

    <div class="map-credit">© OpenStreetMap contributors</div>
  </main>
</template>
