import test from 'node:test'
import assert from 'node:assert/strict'

import { pageFromRoute, pageToPath } from './routing.js'

test('health pages map to real history routes while legacy pages stay in the shell', () => {
  assert.equal(pageToPath('health'), '/health')
  assert.equal(pageToPath('health-detail'), '/health-detail')
  assert.equal(pageToPath('monitor'), '/')
  assert.equal(pageToPath('alarms'), '/')
})

test('route page takes precedence over a stale hash and unknown paths return to monitor', () => {
  assert.equal(pageFromRoute('/health', '#monitor'), 'health')
  assert.equal(pageFromRoute('/health-detail', '#health'), 'health-detail')
  assert.equal(pageFromRoute('/', '#alarms'), 'alarms')
  assert.equal(pageFromRoute('/not-a-page', ''), 'monitor')
})
