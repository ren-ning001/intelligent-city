<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  ArrowDown,
  ArrowUp,
  Compass,
  Download,
  Footprints,
  ListPlus,
  MapPinned,
  RotateCcw,
  Sparkles,
  X,
} from 'lucide-vue-next'
import type {
  AlgorithmName,
  Coordinate,
  GeocodeResult,
  OptimizeResult,
  PoiFeature,
  RouteResult,
  WeightKind,
} from '../types'
import {
  comparisonCsv,
  downloadText,
  exportStamp,
  pairsCsv,
  routeGeoJson,
  routeGpx,
} from '../utils/export'
import LocationSearchInput from './LocationSearchInput.vue'

type PlannerMode = 'endpoints' | 'places'

const props = defineProps<{
  loading: boolean
  optimizing?: boolean
  route: RouteResult | null
  pois?: PoiFeature[]
  poiCount: number | null
  dataSource: string
  comparison?: OptimizeResult | null
  selectedAlgorithm?: AlgorithmName | ''
}>()

const emit = defineEmits<{
  plan: [payload: {
    points: GeocodeResult[]
    categories: string[]
    weight: WeightKind
  }]
  optimize: [payload: {
    start: GeocodeResult
    attractions: GeocodeResult[]
    categories: string[]
    weight: WeightKind
    closedLoop: boolean
  }]
  replan: [payload: {
    points: GeocodeResult[]
    categories: string[]
    weight: WeightKind
    closedLoop: boolean
  }]
  selectAlgorithm: [algorithm: AlgorithmName]
}>()

const mode = ref<PlannerMode>('endpoints')
const start = ref<GeocodeResult | null>(null)
const end = ref<GeocodeResult | null>(null)
const waypoints = ref<GeocodeResult[]>([])
const places = ref<GeocodeResult[]>([])
const returnToStart = ref(false)
interface RemovalStop {
  point: GeocodeResult
  name: string
  key: string
}

const weight = ref<WeightKind>('length')
const routeStops = ref<RemovalStop[]>([])
const removedStopKeys = ref<string[]>([])
const preserveRemoval = ref(false)
const hasAppliedRemoval = ref(false)
const startKey = ref(0)
const endKey = ref(0)
const waypointKey = ref(0)
const placeKey = ref(0)

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
const optimizeSelection = computed(() => {
  if (mode.value === 'endpoints') {
    if (!start.value) return null
    const attractions: GeocodeResult[] = []
    waypoints.value.forEach((point) => addUnique(attractions, point))
    if (end.value && !sameLocation(start.value, end.value)) {
      addUnique(attractions, end.value)
    }
    return { start: start.value, attractions }
  }
  const [first, ...rest] = places.value
  if (!first) return null
  const attractions: GeocodeResult[] = []
  rest.forEach((point) => addUnique(attractions, point))
  return { start: first, attractions }
})
const canOptimize = computed(() => {
  const count = optimizeSelection.value?.attractions.length ?? 0
  return count >= 2 && count <= 15
})
const selectedSolution = computed(() =>
  props.comparison?.algorithms.find((item) => item.algorithm === props.selectedAlgorithm) ?? null,
)
const maxSnapDistance = computed(() => {
  const distances = props.comparison?.snap.map((item) => item.snap_distance_m) ?? []
  if (!distances.length) return null
  return Math.max(...distances).toFixed(0)
})

const isClosedRoute = computed(() => {
  const current = props.route
  if (!current) return false
  if (current.closed_loop) return true
  const points = current.visited_points
  return Boolean(
    points.length > 1
    && sameCoordinate(points[0]!, points[points.length - 1]!),
  )
})

function buildRouteStops(current: RouteResult | null): RemovalStop[] {
  if (!current) return []
  const unique: Coordinate[] = []
  current.visited_points.forEach((point) => {
    const previous = unique[unique.length - 1]
    if (!previous || !sameCoordinate(previous, point)) unique.push(point)
  })
  if (unique.length > 1 && sameCoordinate(unique[0]!, unique[unique.length - 1]!)) {
    unique.pop()
  }

  const solution = selectedSolution.value
  const startName = props.comparison?.snap[0]?.name
  let names: string[]
  if (solution && startName && solution.names.length === unique.length - 1) {
    names = [startName, ...solution.names]
  } else {
    names = unique.map((point, index) => {
      const matched = activePoints.value.find((item) => sameCoordinate(item, point))
      if (matched) return shortName(matched)
      const poi = props.pois?.find((item) => sameCoordinate(item, point))
      return poi?.name ?? `地点${index + 1}`
    })
  }

  return unique.map((point, index) => ({
    point: {
      query: names[index]!,
      display_name: names[index]!,
      latitude: point.latitude,
      longitude: point.longitude,
    },
    name: names[index]!,
    key: `${index}-${point.latitude.toFixed(6)}-${point.longitude.toFixed(6)}`,
  }))
}

const remainingStops = computed(() =>
  routeStops.value.filter((stop) => !removedStopKeys.value.includes(stop.key)),
)
const removedCount = computed(() => removedStopKeys.value.length)

watch(() => props.route, (current) => {
  if (preserveRemoval.value) {
    preserveRemoval.value = false
    return
  }
  routeStops.value = buildRouteStops(current)
  removedStopKeys.value = []
  hasAppliedRemoval.value = false
}, { immediate: true })

// If a replan fails, the route watcher never consumes preserveRemoval. Clear it
// shortly after loading ends so a later external plan rebuilds the base list.
watch(() => props.loading, (loading) => {
  if (loading) return
  window.setTimeout(() => {
    preserveRemoval.value = false
  }, 250)
})

function toggleRemoval(key: string) {
  removedStopKeys.value = removedStopKeys.value.includes(key)
    ? removedStopKeys.value.filter((item) => item !== key)
    : [...removedStopKeys.value, key]
}

function clearRemoval() {
  removedStopKeys.value = []
}

function applyRemoval() {
  const remaining = remainingStops.value
  if (props.loading || remaining.length < 2) return
  if (!removedCount.value && !hasAppliedRemoval.value) return
  const points = remaining.map((stop) => stop.point)
  const restoringAll = removedCount.value === 0
  const closed = isClosedRoute.value
  if (mode.value === 'places') {
    places.value = points
    returnToStart.value = closed
  } else {
    start.value = points[0]!
    end.value = closed ? points[0]! : points[points.length - 1]!
    waypoints.value = closed ? points.slice(1) : points.slice(1, -1)
    startKey.value += 1
    endKey.value += 1
  }
  waypointKey.value += 1
  placeKey.value += 1
  preserveRemoval.value = true
  hasAppliedRemoval.value = !restoringAll
  emit('replan', {
    points,
    categories: selected.value.length ? selected.value : ['attraction'],
    weight: weight.value,
    closedLoop: closed,
  })
  // If the request fails, the route watcher never consumes the flag. Clear it
  // later so a future external plan does not skip rebuilding the base list.
  window.setTimeout(() => {
    preserveRemoval.value = false
  }, 120_000)
}

function sameLocation(first: GeocodeResult, second: GeocodeResult) {
  return sameCoordinate(first, second)
}

function sameCoordinate(first: Coordinate, second: Coordinate) {
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

function segmentText(index: number, distanceM: number, durationMin?: number) {
  const distance = `${(distanceM / 1000).toFixed(2)} km`
  const duration = durationMin === undefined ? '' : ` · ${Math.round(durationMin)} min`
  const solution = selectedSolution.value
  const startName = props.comparison?.snap[0]?.name
  if (!solution || !startName || index > solution.names.length) {
    return `第 ${index + 1} 段 ${distance}${duration}`
  }
  const from = index === 0 ? startName : solution.names[index - 1]
  const to = index >= solution.names.length ? startName : solution.names[index]
  return `${from} → ${to} ${distance}${duration}`
}

function formatGap(value: number | null) {
  if (value === null) return '无精确解'
  return `${value.toFixed(2)}%`
}

function formatCost(item: OptimizeResult['algorithms'][number]) {
  if (item.cost_unit === 's') return `${(item.cost / 60).toFixed(1)} min`
  return `${(item.cost / 1000).toFixed(2)} km`
}

function routeNames() {
  const startName = props.comparison?.snap[0]?.name ?? '起点'
  const names = selectedSolution.value?.names ?? []
  return [startName, ...names]
}

function exportComparison() {
  if (!props.comparison) return
  downloadText(
    `zyourroad-${exportStamp()}-compare.csv`,
    comparisonCsv(props.comparison),
    'text/csv;charset=utf-8',
  )
}

function exportPairs() {
  if (!props.comparison) return
  downloadText(
    `zyourroad-${exportStamp()}-pairs.csv`,
    pairsCsv(props.comparison),
    'text/csv;charset=utf-8',
  )
}

function exportGeoJson() {
  if (!props.route) return
  downloadText(
    `zyourroad-${exportStamp()}-route.geojson`,
    routeGeoJson(props.route, routeNames()),
    'application/geo+json;charset=utf-8',
  )
}

function exportGpx() {
  if (!props.route) return
  downloadText(
    `zyourroad-${exportStamp()}-route.gpx`,
    routeGpx(props.route),
    'application/gpx+xml;charset=utf-8',
  )
}

function submitOptimize() {
  if (!canOptimize.value || props.loading || props.optimizing) return
  const selection = optimizeSelection.value
  if (!selection) return
  const closedLoop = (mode.value === 'places' && returnToStart.value)
    || (
      mode.value === 'endpoints'
      && Boolean(start.value && end.value && sameLocation(start.value, end.value))
    )
  emit('optimize', {
    start: selection.start,
    attractions: selection.attractions,
    categories: selected.value.length ? selected.value : ['attraction'],
    weight: weight.value,
    closedLoop,
  })
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
    weight: weight.value,
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
          :key="`waypoint-${waypointKey}`"
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
          :key="`place-${placeKey}`"
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

    <div class="weight-section">
      <span class="field-label">路线代价口径</span>
      <div class="weight-toggle">
        <button
          type="button"
          :class="{ active: weight === 'length' }"
          @click="weight = 'length'"
        >
          距离优先
        </button>
        <button
          type="button"
          :class="{ active: weight === 'time' }"
          @click="weight = 'time'"
        >
          时间优先
        </button>
      </div>
      <p class="optimize-hint">
        {{
          weight === 'time'
            ? '按道路等级估速选择路径，不是实时路况；结果同时报告公里数。'
            : '按路网长度最短选择路径；预计时间由同一路径的道路等级估速得到。'
        }}
      </p>
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

    <button
      class="optimize-button"
      type="button"
      :disabled="props.loading || props.optimizing || !canOptimize"
      @click="submitOptimize"
    >
      <span v-if="props.optimizing" class="spinner spinner--blue" />
      {{
        props.optimizing
          ? '正在计算代价矩阵…'
          : canOptimize
            ? '优化访问顺序'
            : '优化需要起点和2至15个景点'
      }}
    </button>
    <p class="optimize-hint">
      {{
        mode === 'places' && returnToStart
          ? '固定起点、最后回到起点的闭环行程。'
          : '固定起点的开放行程，不返回起点。'
      }}
      终点和途经点都作为待排序景点；当前为
      {{ weight === 'time' ? '时间口径' : '距离口径' }}。
    </p>

    <div v-if="comparison?.algorithms.length" class="comparison">
      <div class="comparison-head">
        <span>
          {{ comparison.weight === 'time' ? '时间口径' : '距离口径' }}
          · {{ comparison.closed_loop ? '闭环' : '开放' }}
        </span>
        <span>
          {{ comparison.cache_hit ? '缓存命中' : '矩阵构建' }}
          {{ comparison.matrix_elapsed_ms.toFixed(0) }} ms
        </span>
      </div>
      <button
        v-for="item in comparison.algorithms"
        :key="item.algorithm"
        type="button"
        class="comparison-row"
        :class="{ active: item.algorithm === selectedAlgorithm }"
        @click="emit('selectAlgorithm', item.algorithm)"
      >
        <strong>{{ item.label }}</strong>
        <span>{{ formatCost(item) }}</span>
        <span>{{ item.elapsed_ms.toFixed(1) }} ms</span>
        <span>Gap {{ formatGap(item.gap_percent) }}</span>
        <small>{{ item.names.join(' → ') }}</small>
        <small v-if="item.improvement_percent !== null">
          2-opt 改进 {{ item.improvement_percent.toFixed(2) }}%
        </small>
      </button>
      <p class="optimize-hint">
        路网距离 / 直线距离平均
        {{ comparison.straight_line.mean_ratio?.toFixed(2) ?? '—' }}
        <template v-if="maxSnapDistance !== null">，最大映射 {{ maxSnapDistance }} m</template>
        <template v-if="comparison.component">
          ，强连通清洗剔除 {{ comparison.component.removed_nodes }} 个节点 /
          {{ comparison.component.removed_edges }} 条边
        </template>
      </p>
      <p v-if="comparison.cache_hit && comparison.matrix_build_ms" class="optimize-hint">
        首次构建矩阵 {{ comparison.matrix_build_ms.toFixed(0) }} ms，本次读取
        {{ comparison.matrix_lookup_ms.toFixed(1) }} ms。
      </p>
      <div class="export-row">
        <button type="button" @click="exportComparison">
          <Download :size="11" />对照 CSV
        </button>
        <button type="button" @click="exportPairs">
          <Download :size="11" />距离明细 CSV
        </button>
        <button type="button" @click="exportGeoJson">
          <Download :size="11" />路线 GeoJSON
        </button>
        <button type="button" @click="exportGpx">
          <Download :size="11" />路线 GPX
        </button>
      </div>
    </div>

    <div class="metric-grid">
      <div class="metric-card">
        <span>总距离</span>
        <strong>{{ distance }}</strong>
      </div>
      <div class="metric-card">
        <span>{{ route?.weight === 'time' ? '预计时间' : '步行时间' }}</span>
        <strong>{{ duration }}</strong>
      </div>
      <div class="metric-card">
        <span>周边POI</span>
        <strong>{{ poiCount ?? '—' }}</strong>
      </div>
    </div>

    <ol v-if="route?.segments.length" class="segment-list">
      <li v-for="segment in route.segments" :key="segment.index">
        {{ segmentText(segment.index, segment.distance_m, segment.duration_min) }}
      </li>
    </ol>

    <div v-if="route && !comparison" class="export-row">
      <button type="button" @click="exportGeoJson">
        <Download :size="11" />路线 GeoJSON
      </button>
      <button type="button" @click="exportGpx">
        <Download :size="11" />路线 GPX
      </button>
    </div>

    <div v-if="routeStops.length > 2" class="removal-section">
      <div class="removal-head">
        <span>路线地点</span>
        <small>勾选要移出本次规划的地点</small>
      </div>
      <div class="removal-list">
        <label
          v-for="(stop, index) in routeStops"
          :key="stop.key"
          class="removal-item"
          :class="{ removed: removedStopKeys.includes(stop.key) }"
        >
          <input
            type="checkbox"
            :checked="removedStopKeys.includes(stop.key)"
            @change="toggleRemoval(stop.key)"
          />
          <b>{{ index + 1 }}</b>
          <span>{{ stop.name }}</span>
          <em v-if="removedStopKeys.includes(stop.key)">移出</em>
        </label>
      </div>
      <div class="removal-actions">
        <button
          type="button"
          :disabled="props.loading
            || remainingStops.length < 2
            || (!removedCount && !hasAppliedRemoval)"
          @click="applyRemoval"
        >
          {{
            props.loading
              ? '正在重算保留地点…'
              : removedCount
                ? `仅规划保留的 ${remainingStops.length} 个地点`
                : hasAppliedRemoval
                  ? `恢复全部 ${remainingStops.length} 个地点并重规划`
                  : `仅规划保留的 ${remainingStops.length} 个地点`
          }}
        </button>
        <button v-if="removedCount" type="button" class="removal-clear" @click="clearRemoval">
          清空选择
        </button>
      </div>
      <p class="optimize-hint">
        暗色：原路线与已移出地点；亮色：当前保留路线。重合路段显示新路线。
      </p>
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

.weight-section { margin-top: 14px; }

.weight-toggle {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 5px;
  padding: 4px;
  border: 1px solid rgba(77, 107, 254, 0.12);
  border-radius: 11px;
  background: rgba(77, 107, 254, 0.045);
}

.weight-toggle button {
  height: 30px;
  color: rgba(37, 58, 111, 0.56);
  border: 0;
  border-radius: 8px;
  background: transparent;
  font-size: 10px;
  font-weight: 650;
  transition: 180ms ease;
}

.weight-toggle button.active {
  color: #2949ad;
  background: rgba(77, 107, 254, 0.14);
  box-shadow: inset 0 0 16px rgba(77, 107, 254, 0.05);
}

.export-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.export-row button {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 9px;
  color: rgba(35, 56, 108, 0.62);
  border: 1px solid rgba(77, 107, 254, 0.14);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.5);
  font-size: 9px;
}

.export-row button:hover {
  color: #2949ad;
  border-color: rgba(77, 107, 254, 0.32);
  background: rgba(77, 107, 254, 0.08);
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

.optimize-button {
  display: flex;
  width: 100%;
  height: 40px;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: 8px;
  color: #2949ad;
  border: 1px solid rgba(77, 107, 254, 0.28);
  border-radius: 12px;
  background: rgba(77, 107, 254, 0.06);
  font-size: 13px;
  font-weight: 700;
}

.optimize-button:disabled { cursor: not-allowed; opacity: 0.55; }

.optimize-hint {
  margin: 8px 2px 0;
  color: rgba(38, 58, 108, 0.5);
  font-size: 10px;
  line-height: 1.5;
}

.comparison {
  display: grid;
  gap: 6px;
  margin-top: 12px;
}

.comparison-head,
.comparison-row {
  display: grid;
  grid-template-columns: 1.3fr 0.7fr 0.7fr 0.8fr;
  gap: 4px 8px;
  align-items: center;
}

.comparison-head {
  color: rgba(38, 58, 108, 0.48);
  font-size: 9px;
  letter-spacing: 0.06em;
}

.comparison-row {
  padding: 8px;
  border: 1px solid rgba(77, 107, 254, 0.12);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.45);
  text-align: left;
}

.comparison-row strong,
.comparison-row span {
  color: #1f387c;
  font-size: 11px;
}

.comparison-row small {
  grid-column: 1 / -1;
  color: rgba(38, 58, 108, 0.62);
  font-size: 10px;
  line-height: 1.45;
}

.comparison-row.active {
  border-color: rgba(77, 107, 254, 0.45);
  background: rgba(77, 107, 254, 0.1);
}

.segment-list {
  display: grid;
  gap: 4px;
  margin: 10px 0 0;
  padding: 0;
  list-style: none;
}

.segment-list li {
  color: rgba(31, 56, 124, 0.78);
  font-size: 11px;
}

.spinner--blue {
  border-color: rgba(41, 73, 173, 0.25);
  border-top-color: #2949ad;
}
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

.removal-section {
  margin-top: 14px;
  padding: 10px;
  border: 1px solid rgba(77, 107, 254, 0.12);
  border-radius: 12px;
  background: rgba(77, 107, 254, 0.035);
}

.removal-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 7px;
}

.removal-head span {
  color: #1f387c;
  font-size: 11px;
  font-weight: 700;
}

.removal-head small {
  color: rgba(38, 58, 108, 0.48);
  font-size: 9px;
}

.removal-list {
  display: grid;
  max-height: 164px;
  gap: 4px;
  overflow-y: auto;
}

.removal-item {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 6px;
  padding: 5px 7px;
  border: 1px solid rgba(77, 107, 254, 0.1);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.48);
  transition: 160ms ease;
}

.removal-item.removed {
  border-color: rgba(120, 130, 155, 0.24);
  background: rgba(120, 130, 155, 0.1);
  opacity: 0.72;
}

.removal-item input {
  flex: 0 0 auto;
  accent-color: #4d6bfe;
}

.removal-item b {
  display: grid;
  width: 18px;
  height: 18px;
  flex: 0 0 auto;
  place-items: center;
  color: #fff;
  border-radius: 6px;
  background: #607df5;
  font-size: 8px;
}

.removal-item.removed b {
  background: #8690a8;
}

.removal-item span {
  overflow: hidden;
  flex: 1;
  color: rgba(29, 49, 98, 0.78);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.removal-item em {
  color: #7c879e;
  font-size: 8px;
  font-style: normal;
}

.removal-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.removal-actions button {
  padding: 7px 10px;
  color: #fff;
  border: 0;
  border-radius: 8px;
  background: linear-gradient(105deg, #3f5ee9, #6683ff);
  font-size: 9px;
  font-weight: 650;
}

.removal-actions button:disabled {
  cursor: not-allowed;
  opacity: 0.42;
}

.removal-actions .removal-clear {
  color: rgba(35, 56, 108, 0.62);
  border: 1px solid rgba(77, 107, 254, 0.14);
  background: rgba(255, 255, 255, 0.5);
  font-weight: 500;
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
