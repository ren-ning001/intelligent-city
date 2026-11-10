<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  ArrowDown,
  ArrowUp,
  Compass,
  Footprints,
  ListPlus,
  MapPinned,
  RotateCcw,
  Sparkles,
  X,
} from 'lucide-vue-next'
import type { GeocodeResult, PoiFeature, RouteResult } from '../types'
import LocationSearchInput from './LocationSearchInput.vue'

type PlannerMode = 'endpoints' | 'places'

const props = defineProps<{
  loading: boolean
  route: RouteResult | null
  poiCount: number
  dataSource: string
}>()

const emit = defineEmits<{
  plan: [payload: { points: GeocodeResult[]; categories: string[] }]
}>()

const mode = ref<PlannerMode>('endpoints')
const start = ref<GeocodeResult | null>(null)
const end = ref<GeocodeResult | null>(null)
const waypoints = ref<GeocodeResult[]>([])
const places = ref<GeocodeResult[]>([])
const returnToStart = ref(false)
const startKey = ref(0)
const endKey = ref(0)

const categoryOptions = [
  { value: 'attraction', label: '景点' },
  { value: 'history', label: '历史' },
  { value: 'park', label: '公园' },
  { value: 'museum', label: '博物馆' },
  { value: 'hotel', label: '酒店' },
]
const selected = ref(['attraction', 'history', 'park'])

const distance = computed(() =>
  props.route ? `${(props.route.distance_m / 1000).toFixed(2)} km` : '—',
)
const duration = computed(() =>
  props.route ? `${Math.round(props.route.estimated_duration_min)} min` : '—',
)
const activePoints = computed(() =>
  mode.value === 'endpoints'
    ? [start.value, ...waypoints.value, end.value].filter(
        (point): point is GeocodeResult => point !== null,
      )
    : places.value,
)
const canSubmit = computed(() =>
  mode.value === 'endpoints'
    ? Boolean(start.value && end.value)
    : places.value.length >= 2,
)

function sameLocation(first: GeocodeResult, second: GeocodeResult) {
  return (
    Math.abs(first.latitude - second.latitude) < 0.000001
    && Math.abs(first.longitude - second.longitude) < 0.000001
  )
}

function addUnique(target: GeocodeResult[], location: GeocodeResult) {
  if (!target.some((item) => sameLocation(item, location))) target.push(location)
}

function shortName(location: GeocodeResult) {
  return location.display_name.split(',')[0] ?? location.display_name
}

function clearEndpoint(kind: 'start' | 'end') {
  if (kind === 'start') {
    start.value = null
    startKey.value += 1
  } else {
    end.value = null
    endKey.value += 1
  }
}

function addWaypoint(location: GeocodeResult) {
  addUnique(waypoints.value, location)
}

function addPlace(location: GeocodeResult) {
  addUnique(places.value, location)
}

function addPoi(poi: PoiFeature) {
  const location: GeocodeResult = {
    query: poi.name,
    display_name: poi.name,
    latitude: poi.latitude,
    longitude: poi.longitude,
  }
  if (mode.value === 'places') addPlace(location)
  else addWaypoint(location)
}

function movePoint(list: GeocodeResult[], index: number, direction: -1 | 1) {
  const target = index + direction
  if (target < 0 || target >= list.length) return
  const copy = [...list]
  ;[copy[index], copy[target]] = [copy[target]!, copy[index]!]
  if (list === places.value) places.value = copy
  else waypoints.value = copy
}

function toggleCategory(value: string) {
  selected.value = selected.value.includes(value)
    ? selected.value.filter((item) => item !== value)
    : [...selected.value, value]
}

function submit() {
  if (!canSubmit.value || props.loading) return
  const points = [...activePoints.value]
  if (mode.value === 'places' && returnToStart.value && points[0]) {
    points.push(points[0])
  }
  emit('plan', {
    points,
    categories: selected.value.length ? selected.value : ['attraction'],
  })
}

defineExpose({ addPoi })
</script>

<template>
  <section class="glass-panel planner-panel">
    <div class="panel-kicker">
      <span class="pulse-dot" />
      OSM LIVE PLANNER
    </div>
    <div class="panel-title-row">
      <div>
        <h1>探索你的城市轨迹</h1>
        <p>真实路网 · 动态POI · 可验证路线</p>
      </div>
      <div class="compass-orbit">
        <Compass :size="24" />
      </div>
    </div>

    <div class="planner-mode">
      <button
        type="button"
        :class="{ active: mode === 'endpoints' }"
        @click="mode = 'endpoints'"
      >
        <MapPinned :size="14" />
        起终点模式
      </button>
      <button
        type="button"
        :class="{ active: mode === 'places' }"
        @click="mode = 'places'"
      >
        <ListPlus :size="14" />
        自由选点
      </button>
    </div>

    <div v-if="mode === 'endpoints'" class="planner-fields">
      <div class="planner-field">
        <span class="field-label">起点</span>
        <LocationSearchInput
          :key="`start-${startKey}`"
          icon="pin"
          placeholder="搜索并选择起点"
          @select="start = $event"
        />
        <div v-if="start" class="selected-location">
          <span>{{ shortName(start) }}</span>
          <button type="button" aria-label="清除起点" @click="clearEndpoint('start')">
            <X :size="12" />
          </button>
        </div>
      </div>

      <div class="planner-field">
        <span class="field-label">终点</span>
        <LocationSearchInput
          :key="`end-${endKey}`"
          icon="pin"
          placeholder="搜索并选择终点"
          @select="end = $event"
        />
        <div v-if="end" class="selected-location selected-location--end">
          <span>{{ shortName(end) }}</span>
          <button type="button" aria-label="清除终点" @click="clearEndpoint('end')">
            <X :size="12" />
          </button>
        </div>
      </div>

      <div class="planner-field">
        <span class="field-label">途经点（可选）</span>
        <LocationSearchInput
          placeholder="搜索景点，或从地图POI卡片加入"
          @select="addWaypoint"
        />
        <div v-if="waypoints.length" class="stop-list">
          <div
            v-for="(point, index) in waypoints"
            :key="`${point.latitude}-${point.longitude}`"
            class="stop-item"
          >
            <b>{{ index + 1 }}</b>
            <span>{{ shortName(point) }}</span>
            <button type="button" :disabled="index === 0" @click="movePoint(waypoints, index, -1)">
              <ArrowUp :size="11" />
            </button>
            <button
              type="button"
              :disabled="index === waypoints.length - 1"
              @click="movePoint(waypoints, index, 1)"
            >
              <ArrowDown :size="11" />
            </button>
            <button type="button" @click="waypoints.splice(index, 1)">
              <X :size="11" />
            </button>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="planner-fields">
      <div class="free-mode-hint">
        不需要预设起终点。搜索或点击地图POI加入至少2个地点，再按列表顺序连接。
      </div>
      <div class="planner-field">
        <span class="field-label">添加游览地点</span>
        <LocationSearchInput
          placeholder="例如：断桥残雪、苏堤春晓"
          @select="addPlace"
        />
      </div>
      <div class="stop-list stop-list--free">
        <div
          v-for="(point, index) in places"
          :key="`${point.latitude}-${point.longitude}`"
          class="stop-item"
        >
          <b>{{ index + 1 }}</b>
          <span>{{ shortName(point) }}</span>
          <button type="button" :disabled="index === 0" @click="movePoint(places, index, -1)">
            <ArrowUp :size="11" />
          </button>
          <button
            type="button"
            :disabled="index === places.length - 1"
            @click="movePoint(places, index, 1)"
          >
            <ArrowDown :size="11" />
          </button>
          <button type="button" @click="places.splice(index, 1)">
            <X :size="11" />
          </button>
        </div>
        <div v-if="!places.length" class="stop-list__empty">
          还没有选点，也可以在地图上点击POI后加入
        </div>
      </div>
      <label class="loop-option">
        <input v-model="returnToStart" type="checkbox" />
        <RotateCcw :size="13" />
        最后返回第一个地点，生成闭环
      </label>
    </div>

    <div class="category-section">
      <span class="field-label">地图显示的POI</span>
      <div class="category-grid">
        <button
          v-for="option in categoryOptions"
          :key="option.value"
          type="button"
          class="category-chip"
          :class="{ active: selected.includes(option.value) }"
          @click="toggleCategory(option.value)"
        >
          {{ option.label }}
        </button>
      </div>
    </div>

    <button class="plan-button" type="button" :disabled="loading || !canSubmit" @click="submit">
      <span class="button-shine" />
      <Sparkles v-if="!loading" :size="18" />
      <span v-else class="spinner" />
      {{
        loading
          ? '正在穿行真实路网…'
          : canSubmit
            ? `连接 ${activePoints.length} 个地点`
            : mode === 'places'
              ? '请至少选择2个地点'
              : '请选择起点和终点'
      }}
    </button>

    <div class="metric-grid">
      <div class="metric-card">
        <span>总距离</span>
        <strong>{{ distance }}</strong>
      </div>
      <div class="metric-card">
        <span>步行时间</span>
        <strong>{{ duration }}</strong>
      </div>
      <div class="metric-card">
        <span>周边POI</span>
        <strong>{{ poiCount || '—' }}</strong>
      </div>
    </div>

    <div class="data-footnote">
      <Footprints :size="14" />
      <span>{{ dataSource || '等待规划' }}</span>
      <i />
      <span>© OSM</span>
    </div>
  </section>
</template>

<style scoped>
.planner-panel {
  position: relative;
  width: 100%;
  height: 100%;
  max-height: none;
  overflow-x: hidden;
  overflow-y: auto;
  padding: 22px;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  backdrop-filter: none;
  scrollbar-color: rgba(77, 107, 254, 0.24) transparent;
}

.panel-kicker {
  display: flex;
  align-items: center;
  gap: 9px;
  color: rgba(48, 78, 170, 0.7);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.18em;
}

.pulse-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #4d6bfe;
  box-shadow: 0 0 0 0 rgba(77, 107, 254, 0.42);
  animation: pulse 2s infinite;
}

.panel-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 15px 0 22px;
}

h1 {
  max-width: 260px;
  margin: 0;
  font-size: 25px;
  line-height: 1.15;
  letter-spacing: -0.04em;
}

.panel-title-row p {
  margin: 8px 0 0;
  color: var(--muted);
  font-size: 12px;
}

.panel-title-row h1 { color: #1d3475; }

.planner-mode {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  margin-bottom: 16px;
  padding: 4px;
  border: 1px solid rgba(77, 107, 254, 0.12);
  border-radius: 13px;
  background: rgba(77, 107, 254, 0.05);
}

.planner-mode button {
  display: flex;
  height: 34px;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: rgba(37, 58, 111, 0.56);
  border: 0;
  border-radius: 9px;
  background: transparent;
  font-size: 10px;
  transition: 180ms ease;
}

.planner-mode button.active {
  color: #2949ad;
  background: rgba(77, 107, 254, 0.12);
  box-shadow: inset 0 0 18px rgba(77, 107, 254, 0.05);
}

.planner-fields {
  display: grid;
  gap: 12px;
}

.planner-field {
  min-width: 0;
}

.selected-location {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: 6px;
  padding: 5px 7px 5px 9px;
  color: rgba(28, 49, 100, 0.76);
  border-left: 2px solid #4d6bfe;
  border-radius: 6px;
  background: rgba(77, 107, 254, 0.07);
  font-size: 10px;
}

.selected-location--end {
  border-left-color: #7f9dff;
}

.selected-location span {
  overflow: hidden;
  flex: 1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selected-location button,
.stop-item button {
  display: grid;
  width: 22px;
  height: 22px;
  flex: 0 0 auto;
  place-items: center;
  color: rgba(35, 56, 108, 0.54);
  border: 0;
  border-radius: 6px;
  background: rgba(77, 107, 254, 0.06);
}

.selected-location button:hover,
.stop-item button:hover:not(:disabled) {
  color: #2b4ab0;
  background: rgba(77, 107, 254, 0.13);
}

.stop-list {
  display: grid;
  gap: 5px;
  margin-top: 7px;
}

.stop-list--free {
  max-height: 174px;
  overflow-y: auto;
}

.stop-item {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 5px;
  padding: 6px;
  border: 1px solid rgba(77, 107, 254, 0.1);
  border-radius: 9px;
  background: rgba(248, 250, 255, 0.72);
}

.stop-item b {
  display: grid;
  width: 20px;
  height: 20px;
  flex: 0 0 auto;
  place-items: center;
  color: #fff;
  border-radius: 7px;
  background: #607df5;
  font-size: 9px;
}

.stop-item span {
  overflow: hidden;
  flex: 1;
  color: rgba(29, 49, 98, 0.76);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stop-item button:disabled {
  cursor: default;
  opacity: 0.18;
}

.stop-list__empty,
.free-mode-hint {
  padding: 9px 10px;
  color: rgba(38, 59, 109, 0.5);
  border: 1px dashed rgba(77, 107, 254, 0.17);
  border-radius: 10px;
  background: rgba(77, 107, 254, 0.035);
  font-size: 9px;
  line-height: 1.55;
}

.loop-option {
  display: flex;
  align-items: center;
  gap: 7px;
  color: rgba(37, 57, 107, 0.62);
  font-size: 10px;
}

.loop-option input {
  accent-color: #4d6bfe;
}

.compass-orbit {
  display: grid;
  width: 44px;
  height: 44px;
  place-items: center;
  color: #4d6bfe;
  border: 1px solid rgba(77, 107, 254, 0.24);
  border-radius: 50%;
  background: radial-gradient(circle, rgba(77, 107, 254, 0.15), transparent 68%);
  animation: float 4s ease-in-out infinite;
}

.route-inputs {
  position: relative;
  display: grid;
  gap: 13px;
  padding-left: 27px;
}

.route-inputs label > span,
.field-label {
  display: block;
  margin: 0 0 6px 2px;
  color: rgba(38, 58, 108, 0.58);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.route-thread {
  position: absolute;
  top: 29px;
  bottom: 18px;
  left: 5px;
  width: 10px;
}

.thread-dot {
  position: absolute;
  left: 1px;
  width: 8px;
  height: 8px;
  border: 2px solid #91ffe0;
  border-radius: 50%;
  background: #10211f;
}

.thread-dot--start { top: 0; }
.thread-dot--end {
  bottom: 0;
  border-radius: 2px;
  border-color: #ffd38b;
}

.thread-line {
  position: absolute;
  top: 13px;
  bottom: 13px;
  left: 4px;
  width: 1px;
  background: linear-gradient(#77f9d2, rgba(255, 210, 136, 0.72));
  opacity: 0.45;
}

.input-shell {
  display: flex;
  align-items: center;
  gap: 9px;
  height: 43px;
  padding: 0 12px;
  color: rgba(154, 255, 226, 0.62);
  border: 1px solid rgba(192, 255, 238, 0.1);
  border-radius: 13px;
  background: rgba(5, 17, 16, 0.47);
  transition: 180ms ease;
}

.input-shell:focus-within {
  border-color: rgba(122, 255, 215, 0.4);
  box-shadow: 0 0 0 3px rgba(71, 224, 184, 0.08);
  transform: translateY(-1px);
}

.input-shell input {
  width: 100%;
  border: 0;
  outline: 0;
  color: var(--text);
  background: transparent;
  font: inherit;
  font-size: 13px;
}

.input-shell input::placeholder { color: rgba(219, 255, 245, 0.25); }

.category-section { margin-top: 18px; }
.category-grid { display: flex; flex-wrap: wrap; gap: 7px; }

.category-chip {
  padding: 7px 11px;
  color: rgba(35, 56, 108, 0.58);
  border: 1px solid rgba(77, 107, 254, 0.12);
  border-radius: 999px;
  background: rgba(77, 107, 254, 0.045);
  font-size: 11px;
  transition: 180ms ease;
}

.category-chip:hover { transform: translateY(-1px); }
.category-chip.active {
  color: #2949ad;
  border-color: rgba(77, 107, 254, 0.34);
  background: rgba(77, 107, 254, 0.12);
  box-shadow: inset 0 0 18px rgba(77, 107, 254, 0.05);
}

.plan-button {
  position: relative;
  display: flex;
  overflow: hidden;
  width: 100%;
  height: 47px;
  align-items: center;
  justify-content: center;
  gap: 9px;
  margin-top: 19px;
  color: #fff;
  border: 0;
  border-radius: 14px;
  background: linear-gradient(105deg, #3f5ee9, #6683ff 52%, #9db3ff);
  box-shadow: 0 12px 32px rgba(77, 107, 254, 0.24);
  font-weight: 750;
  transition: 200ms ease;
}

.plan-button:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 16px 38px rgba(77, 107, 254, 0.34);
}

.plan-button:disabled { cursor: progress; opacity: 0.82; }
.button-shine {
  position: absolute;
  top: -50%;
  left: -35%;
  width: 28%;
  height: 200%;
  background: rgba(255, 255, 255, 0.36);
  transform: skewX(-22deg);
  animation: shine 4.5s ease-in-out infinite;
}

.spinner {
  width: 15px;
  height: 15px;
  border: 2px solid rgba(255, 255, 255, 0.35);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-top: 13px;
}

.metric-card {
  padding: 10px;
  border: 1px solid rgba(77, 107, 254, 0.1);
  border-radius: 12px;
  background: rgba(77, 107, 254, 0.045);
}

.metric-card span {
  display: block;
  color: rgba(38, 58, 108, 0.48);
  font-size: 9px;
}

.metric-card strong {
  display: block;
  margin-top: 3px;
  color: #1f387c;
  font-size: 14px;
}

.data-footnote {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: 13px;
  color: rgba(38, 58, 108, 0.44);
  font-size: 9px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.data-footnote i {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: currentColor;
}

@keyframes pulse {
  70% { box-shadow: 0 0 0 7px rgba(77, 107, 254, 0); }
  100% { box-shadow: 0 0 0 0 rgba(77, 107, 254, 0); }
}
@keyframes float { 50% { transform: translateY(-4px) rotate(8deg); } }
@keyframes shine {
  0%, 70% { left: -35%; opacity: 0; }
  78% { opacity: 1; }
  100% { left: 120%; opacity: 0; }
}
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 900px) {
  .planner-panel {
    width: 100%;
  }
}
</style>
