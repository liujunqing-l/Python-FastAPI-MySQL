import test from 'node:test'
import assert from 'node:assert/strict'

import { api } from './healthApi.js'
import { commandExecutionLabel, commandIntervalBounds, commandStatusLabel, isCommandIntervalValid } from './presentation.js'

function installFetch(responseBody = { id: 7, status: 'pending' }) {
  const original = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), options })
    return { ok: true, status: 200, text: async () => JSON.stringify(responseBody) }
  }
  return { calls, restore: () => { globalThis.fetch = original } }
}

test('createCommand translates location and health interval fields to the backend contract', async () => {
  const fetcher = installFetch()
  try {
    await api.createCommand({
      imei: '861431071299189',
      command_type: 'location_frequency',
      location_interval_minutes: 10,
    })
    await api.createCommand({
      imei: '861431071299189',
      command_type: 'health_frequency',
      health_interval_minutes: 5,
    })
    assert.equal(fetcher.calls[0].url, '/api/v1/commands')
    assert.equal(fetcher.calls[0].options.method, 'POST')
    assert.deepEqual(JSON.parse(fetcher.calls[0].options.body), {
      imei: '861431071299189',
      command_type: 'location_frequency',
      interval_minutes: 10,
    })
    assert.deepEqual(JSON.parse(fetcher.calls[1].options.body), {
      imei: '861431071299189',
      command_type: 'health_frequency',
      interval_minutes: 5,
    })
  } finally {
    fetcher.restore()
  }
})

test('list/get command methods query the authenticated browser-safe collection endpoint', async () => {
  const fetcher = installFetch({ items: [{ id: 7, status: 'acknowledged' }], total: 1 })
  try {
    await api.listCommands({ imei: '861431071299189', page: 1, page_size: 20 })
    await api.getCommands({ imei: '861431071299189', status: 'pending' })
    assert.equal(fetcher.calls[0].url, '/api/v1/commands?imei=861431071299189&page=1&page_size=20')
    assert.equal(fetcher.calls[1].url, '/api/v1/commands?imei=861431071299189&status=pending')
  } finally {
    fetcher.restore()
  }
})

test('command status never claims execution before acknowledgement', () => {
  assert.equal(commandStatusLabel('pending'), '待发送')
  assert.equal(commandStatusLabel('sent'), '已发送，等待设备回执')
  assert.equal(commandStatusLabel('failed'), '下发失败')
  assert.equal(commandStatusLabel('acknowledged'), '已确认')
  assert.equal(commandExecutionLabel({ status: 'pending', executed: false }), '尚未执行')
  assert.equal(commandExecutionLabel({ status: 'sent', executed: false }), '尚未执行')
  assert.equal(commandExecutionLabel({ status: 'acknowledged', executed: true }), '设备已执行')
})

test('command interval validation follows the protocol byte limits', () => {
  assert.deepEqual(commandIntervalBounds('location_frequency'), { min: 1, max: 1440 })
  assert.deepEqual(commandIntervalBounds('health_frequency'), { min: 2, max: 255 })
  assert.equal(isCommandIntervalValid(1, 'health_frequency'), false)
  assert.equal(isCommandIntervalValid(2, 'health_frequency'), true)
  assert.equal(isCommandIntervalValid(255, 'health_frequency'), true)
  assert.equal(isCommandIntervalValid(256, 'health_frequency'), false)
})
