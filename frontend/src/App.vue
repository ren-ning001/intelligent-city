<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Activity, Bot, Layers3, Map, PanelLeftOpen, Plus, X } from 'lucide-vue-next'
import AgentPanel from './components/AgentPanel.vue'
import FloatingPanel from './components/FloatingPanel.vue'
import MapCanvas from './components/MapCanvas.vue'
import PlannerPanel from './components/PlannerPanel.vue'
import {
  getAgentSession,
  getAgentSessions,
  getHealth,
  planRoute,
  searchPois,
  streamAgentChat,
} from './services/api'
import type {
  AgentTrace,
  ChatMessage,
  ConversationSummary,
  GeocodeResult,
  HealthStatus,
  PoiFeature,
  PoiSearchResult,
  RouteResult,
} from './types'

const WEST_LAKE = { latitude: 30.2525, longitude: 120.1552 }
const health = ref<HealthStatus | null>(null)
const route = ref<RouteResult | null>(null)
const pois = ref<PoiFeature[]>([])
const dataSource = ref('')
const planning = ref(false)
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

async function loadDemoPois() {
  try {
    const result = await searchPois(WEST_LAKE, ['attraction', 'history', 'park'], 3000)
    pois.value = result.pois
    dataSource.value = poiSourceLabel(result.source)
  } catch (error) {
    showToast(error instanceof Error ? error.message : 'POI加载失败')
  }
}

async function handlePlan(payload: {
  points: GeocodeResult[]
  categories: string[]
}) {
  if (payload.points.length < 2) return
  planning.value = true
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
      planRoute(start, end, waypoints),
      searchPois(center, payload.categories, 3000),
    ])
    route.value = routeResult
    pois.value = poiResult.pois
    dataSource.value = poiSourceLabel(poiResult.source)
  } catch (error) {
    showToast(error instanceof Error ? error.message : '路线规划失败')
  } finally {
    planning.value = false
  }
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
    selectedPoi.value = null
    dataSource.value = '历史对话'
  } catch (error) {
    showToast(error instanceof Error ? error.message : '会话加载失败')
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
          dataSource.value = 'Agent · OSM真实路网'
        }
        if (response.poi_result) {
          pois.value = response.poi_result.pois
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
    })
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
  try {
    health.value = await getHealth()
  } catch {
    showToast('后端尚未启动，请运行 start-backend.ps1')
  }
  await loadDemoPois()
  await refreshAgentSessions()
  if (
    storedSessionId
    && agentSessions.value.some((session) => session.session_id === storedSessionId)
  ) {
    await selectConversation(storedSessionId, true)
  }
})
</script>

<template>
  <main class="app-shell">
    <MapCanvas :route="route" :pois="pois" @select-poi="selectedPoi = $event" />
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
        :route="route"
        :poi-count="pois.length"
        :data-source="dataSource"
        @plan="handlePlan"
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
