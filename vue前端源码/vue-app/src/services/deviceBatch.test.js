import test from 'node:test'
import assert from 'node:assert/strict'

import { bindingPairs, parseImeis, parseLines, remainingBindings } from './deviceBatch.js'

test('parseLines trims values and ignores blank lines', () => {
  assert.deepEqual(parseLines(' 861431071299189\r\n\n 861431071299180 '), [
    '861431071299189',
    '861431071299180',
  ])
})

test('parseImeis rejects invalid and duplicate device identifiers', () => {
  assert.deepEqual(parseImeis('861431071299189\n861431071299180'), [
    '861431071299189',
    '861431071299180',
  ])
  assert.throws(() => parseImeis('861431071299189\n861431071299189'), /重复|duplicate/i)
  assert.throws(() => parseImeis('not-an-imei'), /IMEI/i)
})

test('bindingPairs keeps the name aligned with each IMEI', () => {
  assert.deepEqual(bindingPairs('861431071299189\n861431071299180', '张三\n李四'), [
    { imei: '861431071299189', name: '张三' },
    { imei: '861431071299180', name: '李四' },
  ])
  assert.throws(() => bindingPairs('861431071299189\n861431071299180', '张三'), /数量/i)
})

test('remainingBindings removes only the requested IMEIs', () => {
  assert.deepEqual(
    remainingBindings(['861431071299189', '861431071299180'], '861431071299189'),
    ['861431071299180'],
  )
})
