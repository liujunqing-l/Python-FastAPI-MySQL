# 步数卡路里展示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变后端接口的前提下，使用健康记录中的真实步数计算并展示卡路里。

**Architecture:** 在前端展示层增加唯一的步数换算纯函数，所有表格、详情、图表和导出都调用它。健康记录中的 `calories` 原字段不作为第一阶段数据源；缺少有效步数时保持缺失显示。

**Tech Stack:** Vue 3、Vite、ECharts、Node.js built-in test runner、现有 ExcelJS 导出工具。

---

### Task 1: Add and test the shared calorie conversion

**Files:**
- Modify: `vue前端源码/vue-app/src/services/presentation.js`
- Modify: `vue前端源码/vue-app/src/services/presentation.test.js`

- [x] **Step 1: Write the failing tests**

Add these imports and tests to `presentation.test.js`:

```js
import { caloriesFromSteps, healthMetricValue } from './presentation.js'

test('converts valid steps to one-decimal calories', () => {
  assert.equal(caloriesFromSteps(180), 7.2)
  assert.equal(caloriesFromSteps('25'), 1.0)
  assert.equal(caloriesFromSteps(0), 0.0)
})

test('keeps invalid or negative steps missing', () => {
  for (const value of [null, undefined, '', 'not-a-number', -1, Infinity]) {
    assert.equal(caloriesFromSteps(value), null)
  }
})

test('derives the calories metric from the row steps field', () => {
  assert.equal(healthMetricValue({ steps: 50 }, 'calories'), 2.0)
  assert.equal(healthMetricValue({ step_count: 75 }, 'calories'), 3.0)
  assert.equal(healthMetricValue({ calories: 99, steps: null }, 'calories'), null)
})
```

- [x] **Step 2: Run the focused tests and verify they fail**

Run from `C:\Users\27838\Desktop\B2315P\vue前端源码\vue-app`:

```powershell
npm test -- src/services/presentation.test.js
```

Expected: FAIL because `caloriesFromSteps` and `healthMetricValue` do not yet exist.

- [x] **Step 3: Implement the minimal shared helpers**

Append to `presentation.js`:

```js
export const CALORIES_PER_STEP = 0.04

export function caloriesFromSteps(steps) {
  if (steps === null || steps === undefined || steps === '') return null
  const value = Number(steps)
  if (!Number.isFinite(value) || value < 0) return null
  return Number((value * CALORIES_PER_STEP).toFixed(1))
}

export function healthMetricValue(row, metric, aliases = []) {
  if (metric === 'calories') {
    const steps = [row?.steps, row?.step_count]
      .find((value) => value !== undefined && value !== null && value !== '')
    return caloriesFromSteps(steps)
  }
  return aliases
    .map((name) => row?.[name])
    .find((value) => value !== undefined && value !== null && value !== '') ?? null
}
```

- [x] **Step 4: Run the focused tests and verify they pass**

```powershell
npm test -- src/services/presentation.test.js
```

Expected: all presentation tests pass.

### Task 2: Make the chart use step-derived calories

**Files:**
- Modify: `vue前端源码/vue-app/src/components/HealthChart.vue`

- [x] **Step 1: Replace the local field lookup for chart points**

Import `healthMetricValue` from `presentation.js`, remove `calories` from the local alias-only assumption, and calculate each point with:

```js
value: Number(healthMetricValue(row, props.metric, aliases.value))
```

The existing finite-number filter remains, so rows without valid steps are not plotted.

- [x] **Step 2: Keep chart title and unit unchanged**

The metric definitions continue to use `title: '卡路里'` and `unit: 'kcal'`; no “估算” text is added.

### Task 3: Update the health list table and export

**Files:**
- Modify: `vue前端源码/vue-app/src/views/HealthView.vue`

- [x] **Step 1: Use the shared metric helper in the table**

Import `healthMetricValue`, then replace the table cell expression:

```vue
{{ show(healthMetricValue(row, metric.key, metric.aliases)) }}
```

- [x] **Step 2: Use the same helper when building Excel rows**

Replace the export assignment:

```js
selectedMetrics.forEach((metric) => {
  record[metric.key] = healthMetricValue(row, metric.key, metric.aliases)
})
```

Keep the existing header generation; the calories header remains `卡路里（kcal）`.

### Task 4: Update the health detail page

**Files:**
- Modify: `vue前端源码/vue-app/src/views/HealthDetailView.vue`

- [x] **Step 1: Use the shared helper for the latest metric value**

Import `healthMetricValue` and change `latestValue` to call it for each row:

```js
const value = healthMetricValue(rows.value[index], metric.key, metric.aliases)
```

- [x] **Step 2: Use the shared helper in detail Excel export**

Replace the per-metric export loop with:

```js
metrics.forEach((metric) => {
  record[metric.key] = healthMetricValue(row, metric.key, metric.aliases)
})
```

The detail metric title remains `卡路里`.

### Task 5: Run complete frontend verification

**Files:**
- Test: `vue前端源码/vue-app/src/services/*.test.js`
- Build: `vue前端源码/vue-app/package.json`

- [x] **Step 1: Run all frontend tests**

```powershell
npm test
```

Expected: zero failed tests.

- [x] **Step 2: Build the production bundle**

```powershell
npm run build
```

Expected: Vite exits with code 0 and writes `dist/index.html` and assets.

- [x] **Step 3: Inspect the final diff**

```powershell
git diff -- vue前端源码/vue-app/src/services/presentation.js vue前端源码/vue-app/src/services/presentation.test.js vue前端源码/vue-app/src/components/HealthChart.vue vue前端源码/vue-app/src/views/HealthView.vue vue前端源码/vue-app/src/views/HealthDetailView.vue docs/superpowers/specs/2026-10-04-step-calorie-display-design.md docs/superpowers/plans/2026-10-04-step-calorie-display.md
```

Confirm there are no backend, database, TCP, or API-contract changes and that all visible labels say `卡路里`, not `估算卡路里`.
