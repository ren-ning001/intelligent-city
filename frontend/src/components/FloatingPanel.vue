<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { GripHorizontal, Maximize2, Minus, PanelTopOpen, X } from 'lucide-vue-next'

const props = withDefaults(
  defineProps<{
    panelId: string
    title: string
    open: boolean
    initialWidth: number
    initialHeight: number
    initialX?: number
    initialY?: number
    initialRight?: number
    minWidth?: number
    minHeight?: number
  }>(),
  {
    initialX: 24,
    initialY: 98,
    minWidth: 320,
    minHeight: 280,
  },
)

const emit = defineEmits<{
  'update:open': [value: boolean]
}>()

interface PanelRect {
  x: number
  y: number
  width: number
  height: number
}

const panel = ref<HTMLElement>()
const collapsed = ref(false)
const maximized = ref(false)
const zIndex = ref(props.initialRight === undefined ? 21 : 22)
const rect = reactive<PanelRect>({
  x: props.initialX,
  y: props.initialY,
  width: props.initialWidth,
  height: props.initialHeight,
})
let restoreRect: PanelRect | null = null
let resizeObserver: ResizeObserver | undefined
let drag:
  | {
      pointerId: number
      offsetX: number
      offsetY: number
    }
  | undefined

const storageKey = computed(() => `zyourroad.panel.v2.${props.panelId}`)
const panelStyle = computed(() => ({
  left: `${rect.x}px`,
  top: `${rect.y}px`,
  width: `${rect.width}px`,
  height: `${collapsed.value ? 42 : rect.height}px`,
  zIndex: zIndex.value,
  minWidth: `${props.minWidth}px`,
  minHeight: collapsed.value ? '42px' : `${props.minHeight}px`,
}))

function clampRect() {
  rect.width = Math.min(Math.max(rect.width, props.minWidth), window.innerWidth - 20)
  rect.height = Math.min(Math.max(rect.height, props.minHeight), window.innerHeight - 20)
  rect.x = Math.min(Math.max(rect.x, 10), Math.max(10, window.innerWidth - rect.width - 10))
  rect.y = Math.min(Math.max(rect.y, 76), Math.max(76, window.innerHeight - 52))
}

function saveRect() {
  if (maximized.value) return
  window.localStorage.setItem(
    storageKey.value,
    JSON.stringify({ x: rect.x, y: rect.y, width: rect.width, height: rect.height }),
  )
}

function restoreSavedRect() {
  const raw = window.localStorage.getItem(storageKey.value)
  if (raw) {
    try {
      const saved = JSON.parse(raw) as Partial<PanelRect>
      if (
        [saved.x, saved.y, saved.width, saved.height].every(
          (value) => typeof value === 'number' && Number.isFinite(value),
        )
      ) {
        Object.assign(rect, saved)
        clampRect()
        return
      }
    } catch {
      window.localStorage.removeItem(storageKey.value)
    }
  }
  if (props.initialRight !== undefined) {
    rect.x = window.innerWidth - props.initialRight - props.initialWidth
  }
  clampRect()
}

function bringToFront() {
  zIndex.value = 1000 + Math.floor(performance.now())
}

function startDrag(event: PointerEvent) {
  if (event.button !== 0 || maximized.value) return
  const target = event.target as HTMLElement
  if (target.closest('button')) return
  bringToFront()
  drag = {
    pointerId: event.pointerId,
    offsetX: event.clientX - rect.x,
    offsetY: event.clientY - rect.y,
  }
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
}

function moveDrag(event: PointerEvent) {
  if (!drag || drag.pointerId !== event.pointerId) return
  rect.x = event.clientX - drag.offsetX
  rect.y = event.clientY - drag.offsetY
  clampRect()
}

function stopDrag(event: PointerEvent) {
  if (!drag || drag.pointerId !== event.pointerId) return
  drag = undefined
  saveRect()
}

function toggleCollapsed() {
  collapsed.value = !collapsed.value
  if (!collapsed.value) void nextTick(clampRect)
}

function toggleMaximized() {
  if (maximized.value && restoreRect) {
    Object.assign(rect, restoreRect)
    restoreRect = null
    maximized.value = false
    clampRect()
    return
  }
  restoreRect = { ...rect }
  collapsed.value = false
  maximized.value = true
  Object.assign(rect, {
    x: 18,
    y: 78,
    width: window.innerWidth - 36,
    height: window.innerHeight - 96,
  })
}

function close() {
  saveRect()
  emit('update:open', false)
}

function onResize() {
  if (maximized.value) {
    Object.assign(rect, {
      x: 18,
      y: 78,
      width: window.innerWidth - 36,
      height: window.innerHeight - 96,
    })
  } else {
    clampRect()
  }
}

onMounted(() => {
  restoreSavedRect()
  window.addEventListener('resize', onResize)
  if (panel.value) {
    resizeObserver = new ResizeObserver(([entry]) => {
      if (!entry || collapsed.value || maximized.value) return
      rect.width = entry.contentRect.width
      rect.height = entry.contentRect.height
    })
    resizeObserver.observe(panel.value)
  }
})

onBeforeUnmount(() => {
  saveRect()
  resizeObserver?.disconnect()
  window.removeEventListener('resize', onResize)
})
</script>

<template>
  <section
    v-if="open"
    ref="panel"
    class="floating-panel"
    :class="{ collapsed, maximized }"
    :style="panelStyle"
    @pointerdown="bringToFront"
  >
    <header
      class="floating-panel__chrome"
      @pointerdown="startDrag"
      @pointermove="moveDrag"
      @pointerup="stopDrag"
      @pointercancel="stopDrag"
    >
      <GripHorizontal :size="14" />
      <span>{{ title }}</span>
      <div class="floating-panel__actions">
        <button type="button" :aria-label="collapsed ? '展开' : '折叠'" @click="toggleCollapsed">
          <PanelTopOpen v-if="collapsed" :size="13" />
          <Minus v-else :size="13" />
        </button>
        <button type="button" :aria-label="maximized ? '还原' : '最大化'" @click="toggleMaximized">
          <Maximize2 :size="12" />
        </button>
        <button type="button" aria-label="关闭" @click="close">
          <X :size="13" />
        </button>
      </div>
    </header>
    <div v-show="!collapsed" class="floating-panel__content">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.floating-panel {
  position: absolute;
  display: flex;
  overflow: hidden;
  max-width: calc(100vw - 20px);
  max-height: calc(100vh - 88px);
  flex-direction: column;
  border: 1px solid rgba(111, 142, 235, 0.28);
  border-radius: 18px;
  background: rgba(245, 248, 255, 0.94);
  box-shadow: 0 24px 70px rgba(22, 43, 97, 0.25);
  resize: both;
  backdrop-filter: blur(24px) saturate(1.2);
}

.floating-panel.collapsed,
.floating-panel.maximized {
  resize: none;
}

.floating-panel__chrome {
  display: flex;
  height: 42px;
  flex: 0 0 42px;
  align-items: center;
  gap: 8px;
  padding: 0 9px 0 13px;
  color: rgba(31, 55, 116, 0.58);
  border-bottom: 1px solid rgba(75, 105, 195, 0.12);
  background: linear-gradient(90deg, rgba(77, 107, 254, 0.1), rgba(255, 255, 255, 0.72));
  cursor: grab;
  user-select: none;
  touch-action: none;
}

.floating-panel__chrome:active { cursor: grabbing; }

.floating-panel__chrome > span {
  color: #253a78;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.floating-panel__actions {
  display: flex;
  gap: 4px;
  margin-left: auto;
}

.floating-panel__actions button {
  display: grid;
  width: 25px;
  height: 25px;
  place-items: center;
  color: #52689f;
  border: 0;
  border-radius: 7px;
  background: rgba(78, 105, 184, 0.07);
}

.floating-panel__actions button:hover {
  color: #2846a5;
  background: rgba(77, 107, 254, 0.14);
}

.floating-panel__content {
  min-width: 0;
  min-height: 0;
  flex: 1;
  overflow: hidden;
}

@media (max-width: 760px) {
  .floating-panel {
    min-width: min(320px, calc(100vw - 20px)) !important;
  }
}
</style>
