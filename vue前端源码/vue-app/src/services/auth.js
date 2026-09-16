const STORAGE_KEY = 'b2315p.auth'
const ROLE_LEVEL = { viewer: 1, operator: 2, admin: 3 }

function storage() {
  try {
    return globalThis.sessionStorage
  } catch {
    return null
  }
}

const memory = { value: null }

function readStored() {
  const target = storage()
  const raw = target?.getItem(STORAGE_KEY)
  if (!raw) return memory.value
  try {
    return JSON.parse(raw)
  } catch {
    target.removeItem(STORAGE_KEY)
    return null
  }
}

export const auth = readStored() || { token: null, user: null, expiresAt: null }

function notify() {
  if (typeof globalThis.dispatchEvent === 'function' && typeof globalThis.CustomEvent === 'function') {
    globalThis.dispatchEvent(new CustomEvent('b2315p-auth-changed'))
  }
}

export function setAuth(payload) {
  const expiresIn = Number(payload?.expires_in || 3600)
  const next = {
    token: payload?.access_token || null,
    user: payload?.user || null,
    expiresAt: Number.isFinite(expiresIn) ? Date.now() + expiresIn * 1000 : null,
  }
  auth.token = next.token
  auth.user = next.user
  auth.expiresAt = next.expiresAt
  memory.value = next
  const target = storage()
  if (target) target.setItem(STORAGE_KEY, JSON.stringify(next))
  notify()
  return auth
}

export function clearAuth() {
  auth.token = null
  auth.user = null
  auth.expiresAt = null
  memory.value = null
  const target = storage()
  if (target) target.removeItem(STORAGE_KEY)
  notify()
}

export function authState() {
  return { token: auth.token, user: auth.user, expiresAt: auth.expiresAt }
}

export function hasRole(user, minimumRole) {
  const current = ROLE_LEVEL[String(user?.role || '').toLowerCase()] || 0
  return current >= (ROLE_LEVEL[minimumRole] || Number.POSITIVE_INFINITY)
}

export function canAccessPage(user, key) {
  if (key === 'device-settings') return hasRole(user, 'operator')
  if (['alarm-settings', 'roles', 'batch-modify'].includes(key)) return hasRole(user, 'admin')
  return true
}

export async function loginRequest(username, password) {
  const body = new URLSearchParams({ username: String(username || ''), password: String(password || '') })
  const response = await fetch('/api/v1/auth/login', {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString(),
  })
  const text = await response.text()
  let data = {}
  try { data = text ? JSON.parse(text) : {} } catch { data = {} }
  if (!response.ok) {
    const error = new Error(data.detail || `登录失败（HTTP ${response.status}）`)
    error.status = response.status
    throw error
  }
  setAuth(data)
  return data
}

export function roleLabel(role) {
  return { admin: '管理员', operator: '操作员', viewer: '查看员' }[role] || '未知角色'
}
