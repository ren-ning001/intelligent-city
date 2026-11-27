import type { OptimizeResult, RouteResult } from '../types'

function cell(value: unknown): string {
  const text = value === null || value === undefined ? '' : String(value)
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

function rowsToCsv(rows: unknown[][]): string {
  return rows.map((row) => row.map(cell).join(',')).join('\n')
}

export function downloadText(
  filename: string,
  content: string,
  mime = 'text/plain;charset=utf-8',
): void {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.style.display = 'none'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function exportStamp(): string {
  return new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
}

export function comparisonCsv(result: OptimizeResult): string {
  const rows: unknown[][] = [[
    'weight',
    'closed_loop',
    'algorithm',
    'label',
    'cost',
    'cost_unit',
    'cost_m',
    'cost_s',
    'route_distance_m',
    'duration_min',
    'elapsed_ms',
    'gap_percent',
    'improvement_percent',
    'order',
  ]]
  for (const item of result.algorithms) {
    rows.push([
      result.weight,
      result.closed_loop,
      item.algorithm,
      item.label,
      item.cost,
      item.cost_unit,
      item.cost_m,
      item.cost_s,
      item.route.distance_m,
      item.route.estimated_duration_min,
      item.elapsed_ms,
      item.gap_percent,
      item.improvement_percent,
      item.names.join(' -> '),
    ])
  }
  return `\ufeff${rowsToCsv(rows)}`
}

export function pairsCsv(result: OptimizeResult): string {
  const rows: unknown[][] = [[
    'from_index',
    'from_name',
    'to_index',
    'to_name',
    'network_m',
    'travel_s',
    'straight_m',
    'ratio',
  ]]
  for (const pair of result.pairs) {
    rows.push([
      pair.from_index,
      pair.from_name,
      pair.to_index,
      pair.to_name,
      pair.network_m,
      pair.travel_s,
      pair.straight_m,
      pair.ratio,
    ])
  }
  return `\ufeff${rowsToCsv(rows)}`
}

export function routeGeoJson(
  route: RouteResult,
  names: string[] = [],
): string {
  const features: Array<Record<string, unknown>> = [
    {
      type: 'Feature',
      properties: {
        kind: 'route',
        distance_m: route.distance_m,
        estimated_duration_min: route.estimated_duration_min,
        network_type: route.network_type,
        weight: route.weight,
        closed_loop: route.closed_loop,
      },
      geometry: route.geometry,
    },
  ]
  route.visited_points.forEach((point, index) => {
    features.push({
      type: 'Feature',
      properties: {
        kind: 'stop',
        index: index + 1,
        name: names[index] ?? `地点 ${index + 1}`,
      },
      geometry: {
        type: 'Point',
        coordinates: [point.longitude, point.latitude],
      },
    })
  })
  return JSON.stringify({ type: 'FeatureCollection', features }, null, 2)
}

function escapeXml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;')
}

function trkseg(coordinates: [number, number][]): string {
  const points = coordinates
    .map(([longitude, latitude]) => `<trkpt lat="${latitude}" lon="${longitude}"></trkpt>`)
    .join('')
  return `<trkseg>${points}</trkseg>`
}

export function routeGpx(route: RouteResult, name = 'ZYourRoad route'): string {
  const segments = route.geometry.type === 'MultiLineString'
    ? route.geometry.coordinates
    : [route.geometry.coordinates]
  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<gpx version="1.1" creator="ZYourRoad" xmlns="http://www.topografix.com/GPX/1/1">',
    `<trk><name>${escapeXml(name)}</name>`,
    ...segments.map(trkseg),
    '</trk></gpx>',
  ].join('\n')
}
