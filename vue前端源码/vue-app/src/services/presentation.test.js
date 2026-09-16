import test from 'node:test'
import assert from 'node:assert/strict'

import { displayValue, isOnline, personLabel, trendPoints, isMissingHealthError } from './presentation.js'

test('displayValue renders missing values as a visible placeholder', () => {
  assert.equal(displayValue(null), '--')
  assert.equal(displayValue(undefined), '--')
  assert.equal(displayValue(''), '--')
  assert.equal(displayValue(0), 0)
})

test('person labels render a visible placeholder when the name is missing', () => {
  assert.equal(personLabel(null), '--')
  assert.equal(personLabel(undefined), '--')
  assert.equal(personLabel(''), '--')
  assert.equal(personLabel('张三'), '张三')
})

test('isOnline reads last_seen_at and honors an explicit freshness timeout', () => {
  const now = new Date('2026-09-09T12:00:00Z')
  assert.equal(isOnline({ enabled: true, last_seen_at: '2026-09-09T11:59:00Z' }, now, 180), true)
  assert.equal(isOnline({ enabled: true, last_seen_at: '2026-09-09T11:56:59Z' }, now, 180), false)
  assert.equal(isOnline({ enabled: false, last_seen_at: '2026-09-09T11:59:00Z' }, now, 30), false)
  assert.equal(isOnline({ enabled: false, last_seen_at: '2026-09-09T11:59:40Z' }, now, 30), true)
  assert.equal(isOnline({ enabled: true }, now, 180), null)
  assert.equal(isOnline({ enabled: true, last_seen_at: 'not-a-date' }, now, 180), null)
})

test('isOnline treats a future last_seen_at as online and keeps timestamp compatibility', () => {
  const now = Date.parse('2026-09-09T12:00:00Z')
  assert.equal(isOnline({ last_seen_at: '2026-09-09T12:01:00Z' }, now, 180), true)
  assert.equal(isOnline('2026-09-09T11:59:00Z', now), true)
  assert.equal(isOnline('2026-09-09T11:59:00Z', now, { enabled: false }), true)
})

test('trendPoints only creates points from supplied real history rows', () => {
  const rows = [
    { collected_at: '2026-09-09T11:00:00Z', heart_rate: 80 },
    { collected_at: '2026-09-09T11:01:00Z', heart_rate: 90 },
  ]
  const points = trendPoints(rows, 'heart_rate')
  assert.equal(typeof points, 'string')
  assert.equal(points.split(' ').length, 2)
  assert.equal(trendPoints([{ heart_rate: 92 }], 'heart_rate'), '0,10')
  assert.equal(trendPoints([], 'heart_rate'), '')
  assert.equal(trendPoints([{ heart_rate: null }], 'heart_rate'), '')
})

test('only a health 404 means there is no record; server and network errors stay visible', () => {
  assert.equal(isMissingHealthError({ status: 404, message: 'no health records found' }), true)
  assert.equal(isMissingHealthError({ status: 404, message: 'Not Found' }), false)
  assert.equal(isMissingHealthError({ status: 500 }), false)
  assert.equal(isMissingHealthError(new TypeError('fetch failed')), false)
})
