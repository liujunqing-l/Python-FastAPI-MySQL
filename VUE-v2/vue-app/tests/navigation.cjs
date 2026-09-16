const assert = require('node:assert/strict')
const path = require('node:path')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')

const baseUrl = process.env.NAV_TEST_URL || 'http://127.0.0.1:5174/'

async function assertReachable(dropdown, page) {
  assert.equal(await dropdown.isVisible(), true, 'Dropdown is hidden')
  for (const item of await dropdown.locator('button').all()) {
    // A layout box alone does not prove an item escaped its ancestor clip.
    assert.equal(await item.evaluate((element) => {
      const box = element.getBoundingClientRect()
      const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2)
      return element.contains(hit) && box.left >= 0 && box.right <= innerWidth
    }), true, 'Dropdown item is clipped, covered, or outside the viewport')
  }
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
}

async function verify(browser, width, touch) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, hasTouch: touch })
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  try {
    await page.goto(baseUrl)
    const menus = page.locator('.nav-menu')
    const triggers = page.locator('.nav-group')
    const drops = page.locator('.nav-dropdown')
    const activate = (locator) => touch ? locator.tap() : locator.click()
    await triggers.first().waitFor()
    assert.equal(await menus.count(), 2)
    for (let group = 0; group < 2; group++) {
      const trigger = triggers.nth(group)
      const dropdown = drops.nth(group)
      await activate(trigger)
      assert.equal(await trigger.getAttribute('aria-expanded'), 'true')
      await assertReachable(dropdown, page)
      await activate(trigger)
      assert.equal(await dropdown.isVisible(), false, 'Second click did not close the dropdown')
      await activate(trigger)
      await activate(page.locator('h1'))
      assert.equal(await dropdown.isVisible(), false, 'Outside click did not close the dropdown')
      const count = await dropdown.locator('button').count()
      for (let child = 0; child < count; child++) {
        await activate(trigger)
        await assertReachable(dropdown, page)
        const option = dropdown.locator('button').nth(child)
        const label = (await option.textContent()).trim()
        await activate(option)
        await page.waitForFunction((title) => document.querySelector('main h2')?.textContent.trim() === title, label)
        assert.equal(await dropdown.isVisible(), false, 'Dropdown remained open after navigation')
      }
    }
    await activate(triggers.first())
    await activate(triggers.nth(1))
    assert.equal(await drops.first().isVisible(), false, 'Switching groups left the first menu open')
    await assertReachable(drops.nth(1), page)
    if (width === 1440 || width === 390) {
      await page.screenshot({ path: path.join(__dirname, `navigation-${width}.png`) })
    }
    await page.keyboard.press('Escape')
    assert.equal(await drops.nth(1).isVisible(), false)
    assert.equal(await triggers.nth(1).evaluate((el) => el === document.activeElement), true)
    await triggers.first().focus()
    await page.keyboard.press('ArrowDown')
    assert.equal(await drops.first().locator('button').first().evaluate((el) => el === document.activeElement), true)
    await page.keyboard.press('Escape')
    await page.mouse.move(width - 1, 850)
    await page.reload()
    await triggers.first().waitFor()
    assert.equal(await drops.first().isVisible(), false, 'Reload left the menu open')
    if (!touch) {
      await triggers.first().hover()
      await assertReachable(drops.first(), page)
      await page.locator('h1').hover()
      assert.equal(await drops.first().isVisible(), false, 'Hover menu did not close on leave')
    }
    assert.deepEqual(errors, [])
    console.log(`PASS ${width}px ${touch ? 'touch' : 'mouse'}: open/close, hit testing, all routes, outside, Escape, keyboard, reload`)
  } finally {
    await context.close()
  }
}

;(async () => {
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge' })
  try {
    for (const [width, touch] of [[1440, false], [768, false], [390, true], [320, true]]) {
      await verify(browser, width, touch)
    }
  } finally {
    await browser.close()
  }
})().catch((error) => { console.error(error); process.exitCode = 1 })
