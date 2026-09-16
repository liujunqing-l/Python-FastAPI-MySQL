async function request(path, { method = 'GET', query, body } = {}) {
  const search = new URLSearchParams()
  Object.entries(query || {}).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== '') search.set(key, value)
  })
  const response = await fetch(`${path}${search.size ? `?${search}` : ''}`, {
    method,
    credentials: 'same-origin',
    cache: 'no-store',
    headers: { Accept: 'application/json', ...(body ? { 'Content-Type': 'application/json' } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}),
  })
  const text = await response.text()
  let data = {}
  try { data = text ? JSON.parse(text) : {} } catch { data = {} }
  if (!response.ok) throw new Error(data.detail || `接口暂不可用（HTTP ${response.status}）`)
  return data
}

function emptyPage(pageNumber = 1, pageSize = 100) {
  return { items: [], page: pageNumber, page_size: pageSize, total: 0 }
}

async function safePage(promise, pageNumber = 1, pageSize = 100) {
  try { return await promise } catch { return emptyPage(pageNumber, pageSize) }
}

async function safeLatest(promise) {
  try { return await promise } catch { return { item: null } }
}

export const api = {
  devices: (pageNumber = 1, pageSize = 100) => safePage(request('/api/v1/devices', { query: { page: pageNumber, page_size: pageSize } }), pageNumber, pageSize),
  latest: (imei) => safeLatest(request('/api/v1/health/latest', { query: { imei } })),
  history: (imei, start, end, pageNumber = 1, pageSize = 100) => safePage(request('/api/v1/health/history', { query: { imei, start, end, page: pageNumber, page_size: pageSize } }), pageNumber, pageSize),
  accounts: (pageNumber = 1, pageSize = 100) => safePage(request('/api/v1/accounts', { query: { page: pageNumber, page_size: pageSize } }), pageNumber, pageSize),
  alarms: (query = {}) => safePage(request('/api/v1/alarms', { query }), query.page || 1, query.page_size || 100),
  rules: (query = {}) => safePage(request('/api/v1/alarm-rules', { query }), query.page || 1, query.page_size || 100),
  roles: (pageNumber = 1, pageSize = 100) => safePage(request('/api/v1/roles', { query: { page: pageNumber, page_size: pageSize } }), pageNumber, pageSize),
  createDevice: (payload) => request('/api/v1/devices', { method: 'POST', body: payload }),
  acknowledgeAlarm: (id) => request(`/api/v1/alarms/${id}/acknowledge`, { method: 'PATCH' }),
  acknowledgeAll: () => request('/api/v1/alarms/acknowledge-all', { method: 'POST' }),
  createRule: (payload) => request('/api/v1/alarm-rules', { method: 'POST', body: payload }),
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

export function first(body) {
  return body?.item || body?.data || (Array.isArray(body?.items) ? body.items[0] : body) || null
}

export function formatDate(value) {
  if (!value) return '--'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false })
}

export function today() {
  return new Date().toISOString().slice(0, 10)
}

export function dayRange(start, end) {
  return {
    start: `${start}T00:00:00+08:00`,
    end: `${end}T23:59:59+08:00`,
  }
}
