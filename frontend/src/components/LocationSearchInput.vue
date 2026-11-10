<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { LoaderCircle, MapPin, Search } from 'lucide-vue-next'
import { searchLocations } from '../services/api'
import type { GeocodeResult } from '../types'

const props = withDefaults(
  defineProps<{
    placeholder?: string
    icon?: 'search' | 'pin'
  }>(),
  {
    placeholder: '搜索地点',
    icon: 'search',
  },
)

const emit = defineEmits<{
  select: [location: GeocodeResult]
}>()

const query = ref('')
const suggestions = ref<GeocodeResult[]>([])
const loading = ref(false)
const open = ref(false)
let debounceTimer: number | undefined
let controller: AbortController | undefined
let requestVersion = 0

function choose(location: GeocodeResult) {
  query.value = location.display_name.split(',')[0] ?? location.display_name
  suggestions.value = []
  open.value = false
  emit('select', location)
}

async function runSearch() {
  const value = query.value.trim()
  if (value.length < 2) {
    suggestions.value = []
    open.value = false
    return
  }
  controller?.abort()
  controller = new AbortController()
  const version = ++requestVersion
  loading.value = true
  try {
    const result = await searchLocations(value, 8, controller.signal)
    if (version !== requestVersion) return
    suggestions.value = result.results
    open.value = true
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') return
    suggestions.value = []
    open.value = true
  } finally {
    if (version === requestVersion) loading.value = false
  }
}

function onInput() {
  window.clearTimeout(debounceTimer)
  debounceTimer = window.setTimeout(runSearch, 260)
}

function submitFirst() {
  if (suggestions.value[0]) {
    choose(suggestions.value[0])
    return
  }
  void runSearch()
}

function hideLater() {
  window.setTimeout(() => {
    open.value = false
  }, 160)
}

onBeforeUnmount(() => {
  window.clearTimeout(debounceTimer)
  controller?.abort()
})
</script>

<template>
  <div class="location-search">
    <div class="location-search__shell">
      <Search v-if="props.icon === 'search'" :size="15" />
      <MapPin v-else :size="15" />
      <input
        v-model="query"
        :placeholder="placeholder"
        autocomplete="off"
        @input="onInput"
        @focus="suggestions.length && (open = true)"
        @blur="hideLater"
        @keydown.enter.prevent="submitFirst"
      />
      <LoaderCircle v-if="loading" class="location-search__loader" :size="14" />
    </div>

    <Transition name="search-pop">
      <div v-if="open" class="location-search__results">
        <button
          v-for="location in suggestions"
          :key="`${location.latitude}-${location.longitude}-${location.display_name}`"
          type="button"
          @mousedown.prevent="choose(location)"
        >
          <MapPin :size="13" />
          <span>
            <strong>{{ location.display_name.split(',')[0] }}</strong>
            <small>{{ location.display_name }}</small>
          </span>
        </button>
        <div v-if="!loading && !suggestions.length" class="location-search__empty">
          没找到匹配地点，请换个更具体的名称
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.location-search {
  position: relative;
  min-width: 0;
}

.location-search__shell {
  display: flex;
  height: 42px;
  align-items: center;
  gap: 8px;
  padding: 0 11px;
  color: rgba(55, 83, 177, 0.68);
  border: 1px solid rgba(77, 107, 254, 0.14);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.76);
  transition: 180ms ease;
}

.location-search__shell:focus-within {
  border-color: rgba(77, 107, 254, 0.42);
  box-shadow: 0 0 0 3px rgba(77, 107, 254, 0.08);
}

.location-search__shell input {
  width: 100%;
  min-width: 0;
  border: 0;
  outline: 0;
  color: var(--text);
  background: transparent;
  font: inherit;
  font-size: 12px;
}

.location-search__shell input::placeholder {
  color: rgba(43, 64, 117, 0.34);
}

.location-search__loader {
  flex: 0 0 auto;
  animation: search-spin 0.8s linear infinite;
}

.location-search__results {
  position: absolute;
  z-index: 30;
  top: calc(100% + 7px);
  right: 0;
  left: 0;
  overflow: hidden;
  max-height: 240px;
  overflow-y: auto;
  padding: 5px;
  border: 1px solid rgba(77, 107, 254, 0.18);
  border-radius: 12px;
  background: rgba(248, 250, 255, 0.98);
  box-shadow: 0 18px 45px rgba(29, 54, 119, 0.24);
  backdrop-filter: blur(22px);
}

.location-search__results button {
  display: flex;
  width: 100%;
  align-items: flex-start;
  gap: 8px;
  padding: 8px;
  color: rgba(28, 48, 96, 0.76);
  border: 0;
  border-radius: 8px;
  background: transparent;
  text-align: left;
}

.location-search__results button:hover {
  color: #2949ad;
  background: rgba(77, 107, 254, 0.09);
}

.location-search__results button > svg {
  margin-top: 2px;
  flex: 0 0 auto;
  color: #4d6bfe;
}

.location-search__results span {
  min-width: 0;
}

.location-search__results strong,
.location-search__results small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.location-search__results strong {
  font-size: 11px;
}

.location-search__results small {
  margin-top: 3px;
  color: rgba(40, 61, 112, 0.46);
  font-size: 8px;
}

.location-search__empty {
  padding: 12px 9px;
  color: rgba(40, 61, 112, 0.5);
  font-size: 10px;
  text-align: center;
}

.search-pop-enter-active,
.search-pop-leave-active { transition: 140ms ease; }
.search-pop-enter-from,
.search-pop-leave-to {
  transform: translateY(-4px);
  opacity: 0;
}

@keyframes search-spin {
  to { transform: rotate(360deg); }
}
</style>
