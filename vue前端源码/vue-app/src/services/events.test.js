import test from 'node:test'
import assert from 'node:assert/strict'

import { api, items, total } from './healthApi.js'
import { eventViewState } from './presentation.js'

function installFetch(handler) {
  const original = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), options })
    return handler(url, options)
  }
  return { calls, restore: () => { globalThis.fetch = original } }
}

function ok(body) {
  return { ok: true, status: 200, text: async () => JSON.stringify(body) }
}

test('event API methods use the documented paths and query parameters', async () => {
  const fetcher = installFetch(() => ok({ items: [], page: 2, page_size: 25, total: 0 }))
  try {
    await api.alarms({ imei: '861431071299189', status: 'pending', page: 2, page_size: 25 })
    await api.locationsLatest('861431071299189')
    await api.locationsHistory('861431071299189', '2026-09-09T00:00:00Z', '2026-09-10T00:00:00Z', 2, 25)
    await api.sleepHistory('861431071299189', '2026-09-09T00:00:00Z', '2026-09-10T00:00:00Z', 2, 25)
    await api.deviceConfig('861431071299189')
    await api.acknowledgeAlarm(17)
    assert.equal(fetcher.calls[0].url, '/api/v1/alarms?imei=861431071299189&status=pending&page=2&page_size=25')
    assert.equal(fetcher.calls[1].url, '/api/v1/locations/latest?imei=861431071299189')
    assert.equal(fetcher.calls[2].url, '/api/v1/locations/history?imei=861431071299189&start=2026-09-09T00%3A00%3A00Z&end=2026-09-10T00%3A00%3A00Z&page=2&page_size=25')
    assert.equal(fetcher.calls[3].url, '/api/v1/sleep/history?imei=861431071299189&start=2026-09-09T00%3A00%3A00Z&end=2026-09-10T00%3A00%3A00Z&page=2&page_size=25')
    assert.equal(fetcher.calls[4].url, '/api/v1/device-config/861431071299189')
    assert.equal(fetcher.calls[5].url, '/api/v1/alarms/17/acknowledge')
    assert.equal('acknowledgeAll' in api, false)
  } finally {
    fetcher.restore()
  }
})

test('alarmStats reads total and pending counts from the real alarm endpoint', async () => {
  const original = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url) => {
    calls.push(String(url))
    const pending = String(url).includes('status=pending')
    return ok({ items: [], total: pending ? 2 : 7 })
  }
  try {
    assert.deepEqual(await api.alarmStats(), { total: 7, pending: 2 })
    assert.deepEqual(calls, [
      '/api/v1/alarms?page=1&page_size=1',
      '/api/v1/alarms?status=pending&page=1&page_size=1',
    ])
  } finally {
    globalThis.fetch = original
  }
})

test('event API keeps server errors visible to callers', async () => {
  const fetcher = installFetch(() => ({ ok: false, status: 503, text: async () => JSON.stringify({ detail: 'database unavailable' }) }))
  try {
    await assert.rejects(api.locationsLatest('861431071299189'), (error) => error.status === 503 && error.message === 'database unavailable')
  } finally {
    fetcher.restore()
  }
})

test('event response helpers normalize list and total shapes', () => {
  assert.deepEqual(items({ data: { items: [{ id: 1 }] } }), [{ id: 1 }])
  assert.equal(total({ data: { total: 7 } }), 7)
  assert.equal(total({ total: '3' }), 3)
  assert.equal(total({}), null)
})

test('event view state distinguishes loading, error, empty, and real data', () => {
  assert.equal(eventViewState({ loading: true, error: '', items: [] }), 'loading')
  assert.equal(eventViewState({ loading: false, error: 'network', items: [] }), 'error')
  assert.equal(eventViewState({ loading: false, error: '', items: [] }), 'empty')
  assert.equal(eventViewState({ loading: false, error: '', items: [{ id: 1 }] }), 'ready')
})
