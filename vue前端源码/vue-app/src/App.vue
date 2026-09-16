<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { LogOut } from 'lucide-vue-next'
import { api, dayRange, first, formatDate, items } from './services/healthApi'
import { displayValue, isMissingHealthError, isOnline, trendPoints as makeTrendPoints } from './services/presentation.js'
import { isHealthPath, pageFromRoute, pageToPath } from './services/routing.js'
import { auth, canAccessPage, clearAuth, hasRole, roleLabel } from './services/auth.js'
import HealthView from './views/HealthView.vue'
import HealthDetailView from './views/HealthDetailView.vue'
import AlarmView from './views/AlarmView.vue'
import LocationView from './views/LocationView.vue'
import SleepView from './views/SleepView.vue'
import DeviceSettingsView from './views/DeviceSettingsView.vue'
import RolesView from './views/RolesView.vue'
import DeviceInfoView from './views/DeviceInfoView.vue'
import AlarmSettingsView from './views/AlarmSettingsView.vue'
import BatchModifyView from './views/BatchModifyView.vue'

const route = useRoute()
const router = useRouter()
const pageName = ref(pageFromRoute(route.path, location.hash))
const devices = ref([])
const latest = ref({})
const healthByImei = ref({})
const healthTotals = ref({})
const alarmSummary = ref({ total: null, pending: null })
const loading = ref(false)
const hasLoaded = ref(false)
const searchImei = ref('')
const notice = ref('')
const openGroup = ref('')
const pinnedGroup = ref('')
const navElement = ref(null)
const currentUser = ref(auth.user)
let refreshTimer = null

const dataSource = import.meta.env.VITE_DATA_SOURCE || '开发数据库 / b2315p_dev'

const canOperate = computed(() => hasRole(currentUser.value, 'operator'))
const isAdmin = computed(() => hasRole(currentUser.value, 'admin'))
const navGroups = computed(() => [
  { label: '实时监控', icon: '◉', key: 'monitor' },
  {
    label: '设备管理',
    icon: '▦',
    children: [
      ...(canOperate.value ? [{ label: '设备设置', key: 'device-settings' }] : []),
      { label: '设备信息', key: 'device-info' },
      ...(isAdmin.value ? [
        { label: '角色设置', key: 'roles' },
        { label: '批量修改', key: 'batch-modify' },
      ] : []),
    ],
  },
  {
    label: '报警管理',
    icon: '♟',
    children: [
      { label: '报警列表', key: 'alarms' },
      ...(isAdmin.value ? [{ label: '报警设置', key: 'alarm-settings' }] : []),
    ],
  },
  { label: '定位记录', icon: '⌖', key: 'locations' },
  { label: '睡眠记录', icon: '◒', key: 'sleep' },
  { label: '健康数据', icon: '▦', key: 'health' },
])

const currentTitle = computed(() => ({
  monitor: '实时监控',
  health: '健康数据',
  'health-detail': '健康数据详情',
  'device-settings': '设备设置',
  'device-info': '设备信息',
  alarms: '报警列表',
  'alarm-settings': '报警设置',
  locations: '定位记录',
  sleep: '睡眠记录',
  roles: '角色设置',
  'batch-modify': '批量修改',
}[pageName.value] || '实时监控'))

const onlineCount = computed(() => devices.value.filter((device) => isOnline(device.last_seen_at) === true).length)
const healthRecordCount = computed(() => Object.values(healthTotals.value).reduce((sum, total) => sum + Number(total || 0), 0))
const filteredDevices = computed(() => devices.value.filter((device) => !searchImei.value || String(device.imei).includes(searchImei.value)))

function isGroupActive(group) {
  return Boolean(group.children?.some((child) => child.key === pageName.value))
}

function closeGroups() {
  openGroup.value = ''
  pinnedGroup.value = ''
}

function enforcePageAccess() {
  if (canAccessPage(currentUser.value, pageName.value)) return
  notice.value = '当前角色无权访问该页面。'
  pageName.value = 'monitor'
  location.hash = 'monitor'
}

function syncAuth() {
  currentUser.value = auth.user
  if (!currentUser.value) {
    void router.push('/login')
    return
  }
  enforcePageAccess()
}

function logout() {
  clearAuth()
  void router.push('/login')
}

function navigate(key) {
  notice.value = ''
  if (!canAccessPage(currentUser.value, key)) {
    notice.value = '当前角色无权访问该页面。'
    return
  }
  closeGroups()
  if (key === 'health' || key === 'health-detail') {
    void router.push(pageToPath(key))
    return
  }
  if (isHealthPath(route.path)) {
    // Leave a real health route before switching back to the shell's legacy
    // hash pages.  The hash is applied after navigation so route precedence
    // cannot briefly render the wrong page.
    void router.push('/').then(() => { location.hash = key })
    return
  }
  pageName.value = key
  location.hash = key
}

function toggleGroup(label) {
  if (pinnedGroup.value === label) closeGroups()
  else {
    openGroup.value = label
    pinnedGroup.value = label
  }
}

function previewGroup(label, event) {
  if (event.pointerType !== 'mouse') return
  if (pinnedGroup.value !== label) pinnedGroup.value = ''
  openGroup.value = label
}

function leaveGroup(label) {
  if (openGroup.value === label && pinnedGroup.value !== label) closeGroups()
}

function leaveGroupFocus(event) {
  if (!event.currentTarget.contains(event.relatedTarget)) closeGroups()
}

async function focusFirstChild(label, event) {
  const menu = event.currentTarget.closest('.nav-menu')
  openGroup.value = label
  await nextTick()
  menu?.querySelector('.nav-dropdown button')?.focus()
}

function closeOutside(event) {
  if (!navElement.value?.contains(event.target)) closeGroups()
}

function closeOnEscape(event) {
  if (event.key !== 'Escape' || !openGroup.value) return
  const trigger = navElement.value?.querySelector('.nav-menu.open > button')
  closeGroups()
  trigger?.focus()
}

function syncPage() {
  pageName.value = pageFromRoute(route.path, location.hash)
  closeGroups()
  enforcePageAccess()
}

function value(input) {
  return displayValue(input)
}

function deviceName(device) {
  return value(device?.name)
}

function deviceInitial(device) {
  const name = device?.name
  return name ? String(name).slice(0, 1) : '?'
}

function latestFor(device) {
  return latest.value[device.imei] || {}
}

function statusKey(device) {
  return isOnline(device?.last_seen_at)
}

function statusLabel(device) {
  const status = statusKey(device)
  return status === true ? '在线' : status === false ? '离线' : '未知'
}

function batteryLabel(device) {
  const percent = device?.battery_percent
  return percent === null || percent === undefined || percent === '' ? '--' : `${percent}%`
}

function batteryWidth(device) {
  const percent = Number(device?.battery_percent)
  return Number.isFinite(percent) ? `${Math.max(0, Math.min(100, percent))}%` : '0%'
}

function trendPoints(device, field) {
  return makeTrendPoints(healthByImei.value[device.imei] || [], field)
}

function showUnavailable(feature) {
  notice.value = `${feature}接口暂未接入，当前不显示演示数据。`
}

async function fetchHistory(imei) {
  const range = dayRange()
  const body = await api.history(imei, range.start, range.end, 1, 1000)
  return { rows: items(body), total: Number(body?.total || 0) }
}

async function load() {
  if (loading.value) return
  loading.value = true
  try {
    const deviceBody = await api.devices()
    const nextDevices = items(deviceBody)
    devices.value = nextDevices

    const latestEntries = await Promise.all(nextDevices.map(async (device) => {
      try {
        return [device.imei, first(await api.latest(device.imei)) || {}]
      } catch (error) {
        if (isMissingHealthError(error)) return [device.imei, {}]
        throw error
      }
    }))
    latest.value = Object.fromEntries(latestEntries)

    const historyEntries = await Promise.all(nextDevices.map(async (device) => {
      try {
        const result = await fetchHistory(device.imei)
        return [device.imei, result]
      } catch (error) {
        if (isMissingHealthError(error)) return [device.imei, { rows: [], total: 0 }]
        throw error
      }
    }))
    healthByImei.value = Object.fromEntries(historyEntries.map(([imei, result]) => [imei, result.rows]))
    healthTotals.value = Object.fromEntries(historyEntries.map(([imei, result]) => [imei, result.total]))
    try {
      alarmSummary.value = await api.alarmStats()
    } catch {
      // Keep the rest of the monitor usable, but do not invent alarm counts.
      alarmSummary.value = { total: null, pending: null }
    }
    hasLoaded.value = true
  } catch (error) {
    notice.value = `后端连接失败：${error.message || error}`
    if (!hasLoaded.value) {
      devices.value = []
      latest.value = {}
      healthByImei.value = {}
      healthTotals.value = {}
      alarmSummary.value = { total: null, pending: null }
    }
  } finally {
    loading.value = false
  }
}

function exportCsv() {
  showUnavailable('导出')
}

onMounted(() => {
  window.addEventListener('hashchange', syncPage)
  window.addEventListener('b2315p-auth-changed', syncAuth)
  document.addEventListener('pointerdown', closeOutside)
  document.addEventListener('keydown', closeOnEscape)
  enforcePageAccess()
  if (!isHealthPath(route.path) && !['health', 'health-detail'].includes(pageName.value)) void load()
  refreshTimer = window.setInterval(() => {
    if (!isHealthPath(route.path) && !['health', 'health-detail'].includes(pageName.value)) void load()
  }, 10000)
})

watch(() => route.path, (path) => {
  pageName.value = pageFromRoute(path, location.hash)
  closeGroups()
  if (!isHealthPath(path) && !['health', 'health-detail'].includes(pageName.value)) void load()
})

onBeforeUnmount(() => {
  window.removeEventListener('hashchange', syncPage)
  window.removeEventListener('b2315p-auth-changed', syncAuth)
  document.removeEventListener('pointerdown', closeOutside)
  document.removeEventListener('keydown', closeOnEscape)
  if (refreshTimer !== null) window.clearInterval(refreshTimer)
})
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="brand">
        <span class="logo">🏃</span>
        <div>
          <h1>运动员生命体征 <strong>实时监控平台</strong></h1>
          <small><i /> 实时数据接收中 · 每10秒自动刷新</small>
        </div>
      </div>
      <div class="session-area">
        <span v-if="currentUser" class="session-user">{{ currentUser.display_name || currentUser.username }} · {{ roleLabel(currentUser.role) }}</span>
        <button class="logout-button" type="button" title="退出登录" @click="logout"><LogOut :size="15" />退出登录</button>
        <div class="clock">{{ new Date().toLocaleString('zh-CN', { hour12: false }) }}　|　数据源：{{ dataSource }}</div>
      </div>
    </header>

    <nav ref="navElement" class="nav" aria-label="主导航">
      <template v-for="(group, index) in navGroups" :key="group.label">
        <div
          v-if="group.children"
          class="nav-menu"
          :class="{ open: openGroup === group.label }"
          @pointerenter="previewGroup(group.label, $event)"
          @pointerleave="leaveGroup(group.label)"
          @focusout="leaveGroupFocus"
        >
          <button
            class="nav-group"
            :class="{ 'group-active': isGroupActive(group) }"
            type="button"
            :aria-expanded="openGroup === group.label"
            :aria-controls="`nav-children-${index}`"
            @click="toggleGroup(group.label)"
            @keydown.down.prevent="focusFirstChild(group.label, $event)"
          >
            {{ group.icon }} {{ group.label }} <span aria-hidden="true">⌃</span>
          </button>
          <div :id="`nav-children-${index}`" class="nav-dropdown">
            <button
              v-for="child in group.children"
              :key="child.key"
              type="button"
              :class="{ active: pageName === child.key }"
              :aria-current="pageName === child.key ? 'page' : undefined"
              @click="navigate(child.key)"
            >{{ child.label }}</button>
          </div>
        </div>
        <button v-else :class="{ active: pageName === group.key }" type="button" @click="navigate(group.key)">
          {{ group.icon }} {{ group.label }}
        </button>
      </template>
    </nav>

    <main class="content">
      <div v-if="notice" class="notice" role="alert">{{ notice }}</div>
      <div v-if="loading && !hasLoaded" class="notice">正在读取真实数据……</div>

      <template v-if="pageName === 'monitor'">
        <section class="summary">
          <div><b>{{ devices.length }}</b><span>设备数量</span></div>
          <div><b>{{ onlineCount }}</b><span>在线设备</span></div>
          <div><b>{{ alarmSummary.total ?? '--' }}</b><span>累计报警</span></div>
          <div><b>{{ alarmSummary.pending ?? '--' }}</b><span>待处理报警</span></div>
          <div><b>{{ healthRecordCount }}</b><span>今日健康记录</span></div>
        </section>

        <h2>设备监测</h2>
        <section v-if="devices.length" class="device-grid">
          <article v-for="device in devices" :key="device.imei" class="device-card">
            <div class="device-head">
              <div class="person">
                <span>{{ deviceInitial(device) }}</span>
                <div><b>{{ deviceName(device) }}</b><small>ID: {{ device.imei }}</small></div>
              </div>
              <em :class="statusKey(device) === true ? 'online' : statusKey(device) === false ? 'offline' : ''">● {{ statusLabel(device) }}</em>
            </div>
            <div class="model"><span>{{ value(device.model) }}</span><em>4G手表</em></div>
            <div class="vitals">
              <div><b>♥ {{ value(latestFor(device).heart_rate) }}</b><small>心率 bpm</small></div>
              <div><b>◆ {{ value(latestFor(device).blood_oxygen) }}</b><small>血氧 SpO₂</small></div>
              <div><b>♟ {{ value(latestFor(device).steps) }}</b><small>步数</small></div>
            </div>
            <div class="battery">
              <span>▣ 设备电量</span><b>{{ batteryLabel(device) }}</b>
              <i><span :style="{ width: batteryWidth(device) }" /></i>
            </div>
            <div class="trends">
              <div><svg viewBox="0 0 150 30" preserveAspectRatio="none"><polyline :points="trendPoints(device, 'heart_rate')" /></svg><small>真实心率趋势</small></div>
              <div><svg viewBox="0 0 150 30" preserveAspectRatio="none"><polyline class="blue" :points="trendPoints(device, 'blood_oxygen')" /></svg><small>真实血氧趋势</small></div>
            </div>
            <footer>最近更新：{{ formatDate(latestFor(device).collected_at) }} · 体温 {{ value(latestFor(device).body_temperature) }}℃</footer>
          </article>
        </section>
        <div v-else class="notice">暂无设备数据。请确认 TCP 程序已经向 FastAPI 上报。</div>
      </template>

      <HealthView v-else-if="pageName === 'health'" />

      <HealthDetailView v-else-if="pageName === 'health-detail'" />

      <DeviceSettingsView v-else-if="pageName === 'device-settings'" :devices="devices" />

      <DeviceInfoView v-else-if="pageName === 'device-info'" />

      <RolesView v-else-if="pageName === 'roles'" />

      <BatchModifyView v-else-if="pageName === 'batch-modify'" />

      <AlarmView v-else-if="pageName === 'alarms'" :devices="devices" :can-acknowledge="canOperate" />

      <LocationView v-else-if="pageName === 'locations'" :devices="devices" />

      <SleepView v-else-if="pageName === 'sleep'" :devices="devices" />

      <AlarmSettingsView v-else-if="pageName === 'alarm-settings'" />

    </main>
  </div>
</template>
