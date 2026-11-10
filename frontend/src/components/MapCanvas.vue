<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  GeoJSONSource,
  LngLatBounds,
  Map,
  Marker,
  NavigationControl,
} from 'maplibre-gl'
import type { PoiFeature, RouteResult } from '../types'

const props = defineProps<{
  route: RouteResult | null
  pois: PoiFeature[]
}>()

const emit = defineEmits<{
  selectPoi: [poi: PoiFeature]
}>()

const container = ref<HTMLDivElement>()
let map: Map | null = null
let loaded = false
let endpointMarkers: Marker[] = []

const emptyCollection = {
  type: 'FeatureCollection' as const,
  features: [],
}

function poiGeoJson() {
  return {
    type: 'FeatureCollection' as const,
    features: props.pois.map((poi) => ({
      type: 'Feature' as const,
      geometry: {
        type: 'Point' as const,
        coordinates: [poi.longitude, poi.latitude],
      },
      properties: {
        osm_id: poi.osm_id,
        name: poi.name,
      },
    })),
  }
}

function updatePois() {
  if (!map || !loaded) return
  const source = map.getSource('pois') as GeoJSONSource | undefined
  source?.setData(poiGeoJson())
}

function clearMarkers() {
  endpointMarkers.forEach((marker) => marker.remove())
  endpointMarkers = []
}

function markerElement(kind: 'start' | 'waypoint' | 'end', label: string) {
  const element = document.createElement('div')
  element.className = `route-marker route-marker--${kind}`
  const badge = document.createElement('span')
  badge.textContent = label
  element.append(badge)
  return element
}

function routeLines(): [number, number][][] {
  if (!props.route) return []
  return props.route.geometry.type === 'MultiLineString'
    ? props.route.geometry.coordinates
    : [props.route.geometry.coordinates]
}

function transferGeoJson() {
  return {
    type: 'FeatureCollection' as const,
    features: (props.route?.transfers ?? []).map((transfer) => ({
      type: 'Feature' as const,
      properties: { kind: transfer.kind },
      geometry: {
        type: 'LineString' as const,
        coordinates: [
          [transfer.start.longitude, transfer.start.latitude],
          [transfer.end.longitude, transfer.end.latitude],
        ],
      },
    })),
  }
}

function updateRoute() {
  if (!map || !loaded) return
  const source = map.getSource('route') as GeoJSONSource | undefined
  const transferSource = map.getSource('transfers') as GeoJSONSource | undefined
  clearMarkers()

  const lines = routeLines().filter((line) => line.length)
  if (!props.route || !lines.length) {
    source?.setData(emptyCollection)
    transferSource?.setData(emptyCollection)
    return
  }

  source?.setData({
    type: 'Feature',
    properties: {},
    geometry: props.route.geometry,
  })
  transferSource?.setData(transferGeoJson())

  endpointMarkers = props.route.visited_points.map((point, index, points) => {
    const kind =
      index === 0 ? 'start' : index === points.length - 1 ? 'end' : 'waypoint'
    return new Marker({
      element: markerElement(kind, String(index + 1)),
      anchor: 'center',
    })
      .setLngLat([point.longitude, point.latitude])
      .addTo(map!)
  })

  const coordinates = lines.flat()
  const bounds = coordinates.reduce(
    (result, coordinate) => result.extend(coordinate),
    new LngLatBounds(coordinates[0], coordinates[0]),
  )
  map.fitBounds(bounds, {
    padding: { top: 110, right: 110, bottom: 110, left: 110 },
    duration: 1200,
    maxZoom: 16,
  })
}

onMounted(() => {
  if (!container.value) return
  map = new Map({
    container: container.value,
    center: [120.1552, 30.2525],
    zoom: 13.2,
    pitch: 46,
    bearing: -12,
    attributionControl: false,
    style: {
      version: 8,
      sources: {
        osm: {
          type: 'raster',
          tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
          tileSize: 256,
          attribution: '© OpenStreetMap contributors',
        },
      },
      layers: [
        {
          id: 'osm',
          type: 'raster',
          source: 'osm',
          paint: {
            'raster-saturation': -0.82,
            'raster-contrast': 0.08,
            'raster-brightness-min': 0.42,
            'raster-brightness-max': 0.94,
            'raster-hue-rotate': 8,
          },
        },
      ],
    },
  })
  map.addControl(new NavigationControl({ visualizePitch: true }), 'bottom-left')

  map.on('load', () => {
    if (!map) return
    loaded = true
    map.addSource('pois', { type: 'geojson', data: poiGeoJson() })
    map.addLayer({
      id: 'poi-halo',
      type: 'circle',
      source: 'pois',
      paint: {
        'circle-radius': 11,
        'circle-color': '#4d6bfe',
        'circle-opacity': 0.12,
        'circle-blur': 0.45,
      },
    })
    map.addLayer({
      id: 'poi-point',
      type: 'circle',
      source: 'pois',
      paint: {
        'circle-radius': 4.5,
        'circle-color': '#f7f9ff',
        'circle-stroke-color': '#3858d4',
        'circle-stroke-width': 1.5,
      },
    })
    map.addSource('route', { type: 'geojson', data: emptyCollection })
    map.addSource('transfers', { type: 'geojson', data: emptyCollection })
    map.addLayer({
      id: 'route-transfer',
      type: 'line',
      source: 'transfers',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': '#e29a39',
        'line-width': 3,
        'line-opacity': 0.9,
        'line-dasharray': [2, 2],
      },
    })
    map.addLayer({
      id: 'route-glow',
      type: 'line',
      source: 'route',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': '#4d6bfe',
        'line-width': 13,
        'line-opacity': 0.17,
        'line-blur': 7,
      },
    })
    map.addLayer({
      id: 'route-line',
      type: 'line',
      source: 'route',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': '#4264ed',
        'line-width': 4,
        'line-opacity': 0.95,
      },
    })
    updateRoute()
  })

  map.on('click', 'poi-point', (event) => {
    const osmId = event.features?.[0]?.properties?.osm_id
    const poi = props.pois.find((item) => item.osm_id === String(osmId))
    if (poi) emit('selectPoi', poi)
  })
  map.on('mouseenter', 'poi-point', () => {
    if (map) map.getCanvas().style.cursor = 'pointer'
  })
  map.on('mouseleave', 'poi-point', () => {
    if (map) map.getCanvas().style.cursor = ''
  })
})

watch(() => props.pois, updatePois, { deep: true })
watch(() => props.route, updateRoute, { deep: true })

onBeforeUnmount(() => {
  clearMarkers()
  map?.remove()
  map = null
})
</script>

<template>
  <div ref="container" class="map-canvas" />
</template>

<style scoped>
.map-canvas {
  position: absolute;
  inset: 0;
  background: #eaf0ff;
}

:global(.maplibregl-ctrl-bottom-left) {
  left: 22px;
  bottom: 24px;
}

:global(.maplibregl-ctrl-group) {
  overflow: hidden;
  border: 1px solid rgba(77, 107, 254, 0.2);
  border-radius: 13px;
  background: rgba(248, 250, 255, 0.88);
  box-shadow: 0 12px 36px rgba(27, 52, 117, 0.2);
  backdrop-filter: blur(18px);
}

:global(.maplibregl-ctrl button) {
  filter: opacity(0.68);
}

:global(.route-marker) {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border-radius: 50%;
  background: rgba(248, 250, 255, 0.94);
  border: 1px solid rgba(77, 107, 254, 0.72);
  box-shadow: 0 0 0 7px rgba(77, 107, 254, 0.12), 0 0 30px rgba(77, 107, 254, 0.42);
}

:global(.route-marker span) {
  display: grid;
  width: 18px;
  height: 18px;
  place-items: center;
  color: #fff;
  border-radius: 50%;
  background: #4d6bfe;
  font-size: 9px;
  font-weight: 800;
}

:global(.route-marker--waypoint) {
  width: 24px;
  height: 24px;
  border-color: rgba(105, 133, 236, 0.72);
  box-shadow: 0 0 0 5px rgba(77, 107, 254, 0.09), 0 0 22px rgba(77, 107, 254, 0.3);
}

:global(.route-marker--waypoint span) {
  width: 15px;
  height: 15px;
  font-size: 8px;
}

:global(.route-marker--end) {
  border-radius: 8px;
  transform: rotate(12deg);
  border-color: rgba(45, 72, 177, 0.82);
  box-shadow: 0 0 0 7px rgba(77, 107, 254, 0.11), 0 0 30px rgba(45, 72, 177, 0.38);
}

:global(.route-marker--end span) {
  border-radius: 2px;
  background: #2947b8;
  transform: rotate(-12deg);
}
</style>
