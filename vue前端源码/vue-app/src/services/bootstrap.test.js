import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const mainSource = fs.readFileSync(new URL('../main.js', import.meta.url), 'utf8')

test('application mounts a router-aware root so /login can render LoginView', () => {
  assert.match(mainSource, /import\s+RootApp\s+from\s+['"]\.\/RootApp\.vue['"]/)
  assert.match(mainSource, /createApp\(RootApp\)/)
})
