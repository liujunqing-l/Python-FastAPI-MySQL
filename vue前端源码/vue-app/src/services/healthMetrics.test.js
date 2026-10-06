import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const uiFiles = [
  '../views/HealthView.vue',
  '../views/HealthDetailView.vue',
  '../components/HealthChart.vue',
  './presentation.js',
]

test('health monitoring UI and presentation helpers no longer expose the removed metric', async () => {
  for (const file of uiFiles) {
    const path = fileURLToPath(new URL(file, import.meta.url))
    const source = await readFile(path, 'utf8')
    assert.doesNotMatch(source, /calories|卡路里|kcal/i, `${file} should not contain the removed metric`)
  }
})
