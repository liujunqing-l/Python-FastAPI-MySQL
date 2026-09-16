import test from 'node:test'
import assert from 'node:assert/strict'

import { api } from './healthApi.js'

function installFetch() {
  const original = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), options })
    return { ok: true, status: 200, text: async () => '{}' }
  }
  return { calls, restore: () => { globalThis.fetch = original } }
}

test('admin API methods use the account, role, binding, and device contracts', async () => {
  const fetcher = installFetch()
  try {
    await api.accounts(2, 25)
    await api.roles()
    await api.createAccount({ username: 'op', password: 'secret2', role: 'operator' })
    await api.updateAccount(4, { enabled: false })
    await api.replaceBindings(4, ['861431071299189'])
    await api.createDevice({ imei: '861431071299180', model: 'B2315P' })
    await api.updateDevice('861431071299180', { name: '二号表' })
    assert.equal(fetcher.calls[0].url, '/api/v1/accounts?page=2&page_size=25')
    assert.equal(fetcher.calls[1].url, '/api/v1/roles?page=1&page_size=100')
    assert.equal(fetcher.calls[2].options.method, 'POST')
    assert.equal(fetcher.calls[2].url, '/api/v1/accounts')
    assert.equal(fetcher.calls[3].url, '/api/v1/accounts/4')
    assert.equal(fetcher.calls[4].url, '/api/v1/accounts/4/bindings')
    assert.equal(fetcher.calls[4].options.method, 'PUT')
    assert.equal(fetcher.calls[5].url, '/api/v1/devices')
    assert.equal(fetcher.calls[6].url, '/api/v1/devices/861431071299180')
  } finally {
    fetcher.restore()
  }
})
