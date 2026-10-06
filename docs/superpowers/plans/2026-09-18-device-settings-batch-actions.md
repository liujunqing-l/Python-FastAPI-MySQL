# 设备设置批量操作 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将批量绑定、批量解绑、批量修改整合进设备设置页面，并保持现有真实 API 和旧组件兼容。

**Architecture:** 在设备设置视图内增加筛选、设备表和三个弹窗；纯业务解析逻辑放在独立服务模块并用 Node 测试覆盖。绑定/解绑复用账号绑定接口，批量修改复用现有健康周期命令接口，不增加后端路由。

**Tech Stack:** Vue 3、Vite、Node `node:test`、现有 `healthApi.js`、PostgreSQL-backed FastAPI contracts。

---

### Task 1: Define batch input behavior with failing tests

**Files:**
- Create: `vue前端源码/vue-app/src/services/deviceBatch.test.js`
- Create: `vue前端源码/vue-app/src/services/deviceBatch.js`

- [ ] **Step 1: Write tests for line parsing, binding pairs, and unbind set calculation.**

Tests must assert that blank lines are ignored, duplicate IMEIs are rejected, IMEI/name counts must match when names are supplied, and unbind removes only requested values.

- [ ] **Step 2: Run `pnpm test` and confirm the new module tests fail because `deviceBatch.js` is absent.**

- [ ] **Step 3: Implement the smallest pure functions:** `parseLines`, `parseImeis`, `bindingPairs`, and `remainingBindings`.

- [ ] **Step 4: Run `pnpm test` and confirm all tests pass.**

### Task 2: Move navigation without deleting legacy code

**Files:**
- Modify: `vue前端源码/vue-app/src/App.vue`
- Test: `vue前端源码/vue-app/src/services/auth.test.js`

- [ ] **Step 1: Remove only the `batch-modify` child from the computed device-management navigation.**
- [ ] **Step 2: Keep the import, title mapping, access rule, and render branch for direct legacy bookmarks.**
- [ ] **Step 3: Run the existing auth/navigation tests.**

### Task 3: Add device-settings batch UI and real operations

**Files:**
- Modify: `vue前端源码/vue-app/src/views/DeviceSettingsView.vue`
- Modify: `vue前端源码/vue-app/src/services/healthApi.js` only if a missing existing contract helper is needed.

- [ ] **Step 1: Add account/model/IMEI filters and a device table using the already loaded real device catalog.**
- [ ] **Step 2: Add the three-option batch menu and modal state.**
- [ ] **Step 3: Implement binding using create/update device plus complete account binding replacement.**
- [ ] **Step 4: Implement unbinding by subtracting requested IMEIs from the selected account’s real binding list.**
- [ ] **Step 5: Implement batch health-frequency commands for selected real devices; show a protocol notice and do not submit 1 minute.**
- [ ] **Step 6: Match the supplied modal fields, Chinese labels, dark shell, white modal, cancel and confirm controls without changing unrelated pages.**

### Task 4: Verify locally and package

**Files:**
- Modify: `docs/superpowers/specs/2026-09-18-device-settings-batch-actions-design.md`
- Modify: `docs/superpowers/plans/2026-09-18-device-settings-batch-actions.md`

- [ ] **Step 1: Run `pnpm test` and require zero failures.**
- [ ] **Step 2: Run `pnpm run build` and require exit code 0.**
- [ ] **Step 3: Inspect the diff for accidental backend/TCP changes and verify the generated `dist` contains only frontend assets.**
- [ ] **Step 4: Create a release ZIP only after the checks pass; do not deploy it automatically.**
