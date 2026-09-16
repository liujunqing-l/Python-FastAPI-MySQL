import test from 'node:test'
import assert from 'node:assert/strict'

import { auth, authState, canAccessPage, clearAuth, hasRole, loginRequest, setAuth } from './auth.js'
import { request } from './healthApi.js'

function installFetch(handler) {
  const original = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), options })
    return handler(url, options)
  }
  return { calls, restore: () => { globalThis.fetch = original } }
}

function response(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, text: async () => JSON.stringify(body) }
}

test('login request sends form credentials and returns the server token', async () => {
  const fetcher = installFetch(() => response({ access_token: 'jwt-1', token_type: 'bearer', expires_in: 3600, user: { id: 1, username: 'admin', role: 'admin' } }))
  try {
    const result = await loginRequest('admin', 'secret')
    assert.equal(result.access_token, 'jwt-1')
    assert.equal(fetcher.calls[0].url, '/api/v1/auth/login')
    assert.equal(fetcher.calls[0].options.method, 'POST')
    assert.equal(fetcher.calls[0].options.body, 'username=admin&password=secret')
    assert.equal(fetcher.calls[0].options.headers['Content-Type'], 'application/x-www-form-urlencoded')
  } finally {
    fetcher.restore()
  }
})

test('API request adds bearer token and clears auth after 401', async () => {
  setAuth({ access_token: 'jwt-2', user: { role: 'viewer' } })
  const fetcher = installFetch(() => response({ detail: 'expired' }, 401))
  try {
    await assert.rejects(request('/api/v1/devices'), (error) => error.status === 401)
    assert.equal(fetcher.calls[0].options.headers.Authorization, 'Bearer jwt-2')
    assert.equal(authState().token, null)
  } finally {
    fetcher.restore()
    clearAuth()
  }
})

test('role helpers allow inherited permissions without granting writes to viewers', () => {
  assert.equal(hasRole({ role: 'admin' }, 'operator'), true)
  assert.equal(hasRole({ role: 'operator' }, 'viewer'), true)
  assert.equal(hasRole({ role: 'viewer' }, 'operator'), false)
  assert.equal(hasRole({ role: 'viewer' }, 'viewer'), true)
})

test('page access helper keeps writes away from viewers and admin-only pages away from operators', () => {
  assert.equal(canAccessPage({ role: 'viewer' }, 'health'), true)
  assert.equal(canAccessPage({ role: 'viewer' }, 'device-settings'), false)
  assert.equal(canAccessPage({ role: 'operator' }, 'device-settings'), true)
  assert.equal(canAccessPage({ role: 'operator' }, 'roles'), false)
  assert.equal(canAccessPage({ role: 'admin' }, 'batch-modify'), true)
})

test('auth state stores the current user and token in session storage', () => {
  setAuth({ access_token: 'jwt-3', user: { username: 'op', role: 'operator' } })
  assert.equal(auth.token, 'jwt-3')
  assert.equal(auth.user.username, 'op')
  clearAuth()
  assert.equal(authState().token, null)
})
