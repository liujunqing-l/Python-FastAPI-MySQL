/** Shared browser API client. It deliberately has no fixture/demo fallback. */
import { auth, clearAuth } from './auth.js'

export const isDemo = false

export function today(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now)
  const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]))
  return `${values.year}-${values.month}-${values.day}`
}

export function dayRange(start = today(), end = start) {
  const endExclusive = new Date(`${end}T00:00:00+08:00`)
  endExclusive.setTime(endExclusive.getTime() + 24 * 60 * 60 * 1000)
  return { start: `${start}T00:00:00+08:00`, end: endExclusive.toISOString() }
}

export async function request(path, { method = 'GET', query, body, headers = {} } = {}) {
  const search = new URLSearchParams()
  Object.entries(query || {}).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== '') search.set(key, value)
  })
  const authorization = auth.token ? { Authorization: `Bearer ${auth.token}` } : {}
  const response = await fetch(`${path}${search.size ? `?${search}` : ''}`, {
    method,
    credentials: 'same-origin',
    cache: 'no-store',
    headers: { Accept: 'application/json', ...authorization, ...headers, ...(body ? { 'Content-Type': 'application/json' } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}),
  })
  const text = await response.text()
  let data = {}
  try { data = text ? JSON.parse(text) : {} } catch { data = {} }
  if (!response.ok) {
    const error = new Error(data.detail || `接口暂不可用（HTTP ${response.status}）`)
    error.status = response.status
    if (response.status === 401) clearAuth()
    throw error
  }
  return data
}

function commandPayload(payload = {}) {
  const {
    location_interval_minutes: locationInterval,
    health_interval_minutes: healthInterval,
    ...rest
  } = payload
  if (locationInterval !== undefined && locationInterval !== null) rest.interval_minutes = locationInterval
  if (healthInterval !== undefined && healthInterval !== null) rest.interval_minutes = healthInterval
  return rest
}

export const api = {
  devices: (page = 1, pageSize = 100) => request('/api/v1/devices', { query: { page, page_size: pageSize } }),
  latest: (imei) => request('/api/v1/health/latest', { query: { imei } }),
  history: (imei, start, end, page = 1, pageSize = 100) => request('/api/v1/health/history', { query: { imei, start, end, page, page_size: pageSize } }),
  locationsLatest: (imei) => request('/api/v1/locations/latest', { query: { imei } }),
  locationsHistory: (imei, start, end, page = 1, pageSize = 100) => request('/api/v1/locations/history', { query: { imei, start, end, page, page_size: pageSize } }),
  sleepHistory: (imei, start, end, page = 1, pageSize = 100) => request('/api/v1/sleep/history', { query: { imei, start, end, page, page_size: pageSize } }),
  deviceConfig: (imei) => request(`/api/v1/device-config/${encodeURIComponent(imei)}`),
  createCommand: (payload) => request('/api/v1/commands', { method: 'POST', body: commandPayload(payload) }),
  listCommands: (query = {}) => request('/api/v1/commands', { query }),
  // Alias used by views that refresh the command collection after enqueueing.
  getCommands: (query = {}) => request('/api/v1/commands', { query }),
  accounts: (page = 1, pageSize = 100) => request('/api/v1/accounts', { query: { page, page_size: pageSize } }),
  createAccount: (payload) => request('/api/v1/accounts', { method: 'POST', body: payload }),
  updateAccount: (id, payload) => request(`/api/v1/accounts/${encodeURIComponent(id)}`, { method: 'PATCH', body: payload }),
  replaceBindings: (id, imeis) => request(`/api/v1/accounts/${encodeURIComponent(id)}/bindings`, { method: 'PUT', body: { imeis } }),
  alarms: (query = {}) => request('/api/v1/alarms', { query }),
  alarmStats: async () => {
    const [all, pending] = await Promise.all([
      request('/api/v1/alarms', { query: { page: 1, page_size: 1 } }),
      request('/api/v1/alarms', { query: { status: 'pending', page: 1, page_size: 1 } }),
    ])
    return {
      total: Number(all?.total ?? 0),
      pending: Number(pending?.total ?? 0),
    }
  },
  commands: (query = {}) => request('/api/v1/commands', { query }),
  rules: (query = {}) => request('/api/v1/alarm-rules', { query }),
  roles: (page = 1, pageSize = 100) => request('/api/v1/roles', { query: { page, page_size: pageSize } }),
  createDevice: (payload) => request('/api/v1/devices', { method: 'POST', body: payload }),
  updateDevice: (imei, payload) => request(`/api/v1/devices/${encodeURIComponent(imei)}`, { method: 'PATCH', body: payload }),
  batchUpdateDevices: (payload) => request('/api/v1/devices/batch', { method: 'PATCH', body: payload }),
  acknowledgeAlarm: (id) => request(`/api/v1/alarms/${id}/acknowledge`, { method: 'PATCH' }),
  createRule: (payload) => request('/api/v1/alarm-rules', { method: 'POST', body: payload }),
  updateRule: (id, payload) => request(`/api/v1/alarm-rules/${encodeURIComponent(id)}`, { method: 'PATCH', body: payload }),
  deleteRule: (id) => request(`/api/v1/alarm-rules/${id}`, { method: 'DELETE' }),
  createRole: (payload) => request('/api/v1/roles', { method: 'POST', body: payload }),
}

export function items(body) {
  if (Array.isArray(body)) return body
  if (Array.isArray(body?.items)) return body.items
  if (Array.isArray(body?.data)) return body.data
  if (Array.isArray(body?.data?.items)) return body.data.items
  return []
}

/** Read a pagination total without coupling views to one response envelope. */
export function total(body) {
  const raw = body?.total ?? body?.data?.total
  if (raw === null || raw === undefined || raw === '') return null
  const value = Number(raw)
  return Number.isFinite(value) ? value : null
}

export function first(body) {
  return body?.item || body?.data || (Array.isArray(body?.items) ? body.items[0] : body) || null
}

export function formatDate(value) {
  if (!value) return '--'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false })
}
