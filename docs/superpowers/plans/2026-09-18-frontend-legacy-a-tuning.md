# Frontend Legacy A Tuning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the formal Vue shell to match the approved `legacy-static` dark monitoring layout, rename the product and location navigation, and remove the sleep feature from the frontend without changing the data pipeline.

**Architecture:** Keep the existing authenticated Vue shell, API service, router, and view components. Change only the shell markup/navigation and shared CSS; the shell continues to fetch real device and health data through the existing services. Sleep remains as an unused source file and backend capability, but no longer has a navigation entry or rendered page.

**Tech Stack:** Vue 3, Vite, Vue Router, lucide-vue-next, CSS, pnpm.

---

### Task 1: Update the authenticated shell header and navigation

**Files:**
- Modify: `vue前端源码/vue-app/src/App.vue`
- Test: `vue前端源码/vue-app/src/services/*.test.js` (run existing service contract tests; no API contract changes)

- [ ] **Step 1: Remove the unused data-source presentation value and sleep import.**

  Delete the `dataSource` constant and `import SleepView from './views/SleepView.vue'`. Keep `healthApi.js`, `auth.js`, and router imports unchanged.

- [ ] **Step 2: Replace the product title and clock markup.**

  Replace the current logo/title/subtitle block and data-source clock with:

  ```vue
  <div class="brand">
    <div class="brand-title">救援人员体能训练体征监测平台</div>
  </div>
  <div class="session-area">
    <span v-if="currentUser" class="session-user">{{ currentUser.display_name || currentUser.username }} · {{ roleLabel(currentUser.role) }}</span>
    <button class="logout-button" type="button" title="退出登录" @click="logout"><LogOut :size="15" />退出登录</button>
    <div class="clock">{{ new Date().toLocaleString('zh-CN', { hour12: false }) }}</div>
  </div>
  ```

  Preserve the existing `logout()` handler and user/role display.

- [ ] **Step 3: Rename the location navigation and remove sleep navigation.**

  In `navGroups`, replace:

  ```js
  { label: '定位记录', icon: '⌖', key: 'locations' },
  { label: '睡眠记录', icon: '◒', key: 'sleep' },
  ```

  with:

  ```js
  { label: '定位数据', icon: '⌖', key: 'locations' },
  ```

  Remove the `sleep` entry from `currentTitle`.

- [ ] **Step 4: Guard direct legacy `#sleep` links.**

  At the beginning of `enforcePageAccess()`, redirect a direct `sleep` hash to `monitor` with the notice `睡眠功能已从当前前端移除。` so an old bookmark cannot render a blank shell:

  ```js
  function enforcePageAccess() {
    if (pageName.value === 'sleep') {
      notice.value = '睡眠功能已从当前前端移除。'
      pageName.value = 'monitor'
      location.hash = 'monitor'
      return
    }
    if (canAccessPage(currentUser.value, pageName.value)) return
    // existing permission branch remains unchanged
  }
  ```

- [ ] **Step 5: Remove the sleep template branch.**

  Delete:

  ```vue
  <SleepView v-else-if="pageName === 'sleep'" :devices="devices" />
  ```

- [ ] **Step 6: Run the existing frontend service tests.**

  Run from `vue前端源码/vue-app`:

  ```powershell
  pnpm test
  ```

  Expected: all existing service tests pass; request paths and JWT behavior remain unchanged.

### Task 2: Apply the approved legacy-static visual system

**Files:**
- Modify: `vue前端源码/vue-app/src/style.css`

- [ ] **Step 1: Replace the brand rules.**

  Replace the old `.logo`, `.brand h1`, `.brand strong`, `.brand small`, and `.brand i` rules with a compact title rule:

  ```css
  .brand-title {
    color: #f2f7fc;
    font-size: 23px;
    font-weight: 700;
    letter-spacing: .5px;
  }
  .brand-title::after {
    content: '';
    display: block;
    width: 52px;
    height: 3px;
    margin-top: 8px;
    border-radius: 2px;
    background: #09c7e8;
  }
  ```

- [ ] **Step 2: Keep the existing dark shell and tune the approved layout.**

  Preserve the existing dark colors, summary grid, device grid, device cards, status colors, and responsive rules. Ensure `.topbar` remains a two-sided flex layout and `.session-area` keeps the user, logout, and clock aligned.

- [ ] **Step 3: Add responsive title/clock rules.**

  In the existing `@media(max-width:850px)` block, set `.brand-title` to `18px` and `.clock` to `11px`, while retaining the existing column layout so the long Chinese title cannot overlap the session controls.

- [ ] **Step 4: Check the source contract.**

  Run:

  ```powershell
  rg -n "救援人员体能训练体征监测平台|定位数据|睡眠|dataSource|SleepView|/api/v1" src/App.vue src/style.css
  ```

  Expected: the new product title and `定位数据` are present; no `SleepView`, `dataSource`, or sleep navigation remains in `App.vue`; API paths are untouched outside the service layer.

### Task 3: Test, build, and review the UI-only change

**Files:**
- Modify: none beyond Tasks 1-2
- Test: `vue前端源码/vue-app/src/services/*.test.js`

- [ ] **Step 1: Run the frontend test suite.**

  ```powershell
  pnpm test
  ```

  Expected: all tests pass.

- [ ] **Step 2: Build the production bundle.**

  ```powershell
  pnpm run build
  ```

  Expected: Vite exits with code 0 and writes `dist/index.html` plus hashed assets.

- [ ] **Step 3: Inspect the diff and build output.**

  ```powershell
  git diff --check
  git diff -- src/App.vue src/style.css
  Get-ChildItem -Recurse -File dist | Select-Object FullName,Length
  ```

  Confirm the diff contains only presentation/navigation changes and no API URL, token, database, or TCP changes.

- [ ] **Step 4: Commit the frontend change.**

  ```powershell
  git add -- 'vue前端源码/vue-app/src/App.vue' 'vue前端源码/vue-app/src/style.css'
  git diff --cached --check
  git commit -m "style: align dashboard with rescue training monitor"
  ```

### Task 4: Publish with backup and verify the running version

**Files:**
- Create locally: release ZIP containing the built `dist` directory
- Modify remotely: `/var/www/b2315p/frontend/dist` only

- [ ] **Step 1: Package the exact built `dist` directory and calculate SHA256.**

  ```powershell
  $stamp = Get-Date -Format 'yyyyMMddHHmmss'
  $zip = Join-Path $env:TEMP "b2315p-frontend-rescue-$stamp.zip"
  Compress-Archive -Path '.\dist\*' -DestinationPath $zip -Force
  Get-FileHash $zip -Algorithm SHA256
  ```

- [ ] **Step 2: Upload the package to the server.**

  ```powershell
  scp $zip root@8.152.103.37:/tmp/
  ```

- [ ] **Step 3: Back up and stage the server copy.**

  On the cloud SSH terminal, verify the ZIP checksum, extract to a temporary directory, and move the current `dist` to `/var/backups/b2315p/frontend/dist.previous-<timestamp>` before installing the new `dist`.

- [ ] **Step 4: Reload Nginx and verify without touching the data services.**

  ```bash
  sudo nginx -t
  sudo systemctl reload nginx
  systemctl is-active b2315p-tcp-parser.service health-api.service postgresql
  curl -i -H 'Host: 8.152.103.37' http://127.0.0.1/healthz
  ```

  Expected: Nginx syntax succeeds, all three data services remain active, and `/healthz` returns `200`.

- [ ] **Step 5: Browser acceptance.**

  Open `http://8.152.103.37/`, log in, confirm the new title, time-only right header, `定位数据` navigation, no sleep navigation, real device values, logout behavior, and role restrictions. If the UI fails, restore the previous `dist` backup and reload Nginx; do not restart TCP, FastAPI, or PostgreSQL.
