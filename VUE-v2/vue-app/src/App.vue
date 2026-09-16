<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, first, formatDate, items } from './services/healthApi'

const pageName = ref(location.hash.replace(/^#\/?/, '') || 'monitor')
const devices = ref([])
const latest = ref({})
const healthRows = ref([])
const alarms = ref([])
const rules = ref([])
const roles = ref([])
const accounts = ref([])
const selectedImei = ref('')
const selectedAccount = ref('')
const alarmType = ref('')
const alarmDate = ref('')
const searchImei = ref('')
const notice = ref('')
const modal = ref(null)
const openGroup = ref('')
const pinnedGroup = ref('')
const navElement = ref(null)
const modalForm = ref({ name: '', description: '', type: '心率异常', level: '普通级别', threshold: '' })

const navGroups = [
  { label: '实时监控', icon: '◉', key: 'monitor' },
  { label: '设备管理', icon: '▦', children: [{ label: '设备设置', key: 'device-settings' }, { label: '设备信息', key: 'device-info' }, { label: '角色设置', key: 'roles' }] },
  { label: '报警管理', icon: '♟', children: [{ label: '报警列表', key: 'alarms' }, { label: '报警设置', key: 'alarm-settings' }] },
  { label: '健康数据', icon: '▦', key: 'health' },
]
const currentTitle = computed(() => ({ monitor: '实时监控', health: '健康数据', 'device-settings': '设备设置', 'device-info': '设备信息', alarms: '报警列表', 'alarm-settings': '报警设置', roles: '角色设置' })[pageName.value] || '实时监控')
function isGroupActive(group) {
  return Boolean(group.children?.some((child) => child.key === pageName.value))
}
const onlineCount = computed(() => devices.value.filter((device) => device.status === '在线' || device.enabled).length)
const filteredDevices = computed(() => devices.value.filter((device) => (!selectedAccount.value || String(device.account_id) === String(selectedAccount.value)) && (!searchImei.value || device.imei.includes(searchImei.value))))
const filteredAlarms = computed(() => alarms.value.filter((alarm) => (!selectedAccount.value || String(alarm.account_id) === String(selectedAccount.value)) && (!alarmType.value || alarm.alarm_type === alarmType.value) && (!alarmDate.value || String(alarm.alarm_time || '').slice(0, 10) === alarmDate.value) && (!searchImei.value || alarm.imei.includes(searchImei.value))))

function closeGroups() { openGroup.value = ''; pinnedGroup.value = '' }
function navigate(key) { pageName.value = key; location.hash = key; notice.value = ''; closeGroups() }
function toggleGroup(label) {
  if (pinnedGroup.value === label) closeGroups()
  else { openGroup.value = label; pinnedGroup.value = label }
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
  menu.querySelector('.nav-dropdown button')?.focus()
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
function syncPage() { pageName.value = location.hash.replace(/^#\/?/, '') || 'monitor'; closeGroups() }
function field(item, names) { return names.map((name) => item?.[name]).find((value) => value !== undefined && value !== null) }
function value(input) { return input === undefined || input === null || input === '' ? '--' : input }
function latestFor(device) { return latest.value[device.imei] || {} }
// 未加载到真实历史数据时保持折线区域为空。
function trendPoints(device, name) { return '' }

async function loadHealth() {
  if (!selectedImei.value) {
    healthRows.value = []
    return
  }
  const today = new Date().toISOString().slice(0, 10)
  healthRows.value = []
  healthRows.value = items(await api.history(selectedImei.value, `${today}T00:00:00+08:00`, `${today}T23:59:59+08:00`))
}
async function load() {
  const [deviceBody, accountBody, alarmBody, ruleBody, roleBody] = await Promise.all([api.devices(), api.accounts(), api.alarms({ page: 1, page_size: 100 }), api.rules({ page: 1, page_size: 100 }), api.roles()])
  devices.value = items(deviceBody); accounts.value = items(accountBody); alarms.value = items(alarmBody); rules.value = items(ruleBody); roles.value = items(roleBody)
  latest.value = {}
  if (!devices.value.some((device) => String(device.imei) === String(selectedImei.value))) selectedImei.value = ''
  if (!selectedImei.value && devices.value.length) selectedImei.value = devices.value[0].imei
  await Promise.all(devices.value.map(async (device) => { latest.value[device.imei] = first(await api.latest(device.imei)) || {} }))
  if (selectedImei.value) await loadHealth()
  else healthRows.value = []
}
function openRole() { modal.value = 'role'; modalForm.value = { name: '', description: '' } }
function openRule() { modal.value = 'rule'; modalForm.value = { type: '心率异常', level: '普通级别', threshold: '' } }
function closeModal() { modal.value = null }
function saveModal() { if (modal.value === 'role' && modalForm.value.name.trim()) roles.value.push({ id: Date.now(), name: modalForm.value.name, description: modalForm.value.description || '自定义角色', color: '#8b9cff', icon: '●', device_count: 0, created_at: new Date().toISOString() }); if (modal.value === 'rule') rules.value.push({ id: Date.now(), alarm_type: modalForm.value.type, level: modalForm.value.level, threshold: modalForm.value.threshold || '未设置', enabled: true, page_push: true, ring_mode: '响几声' }); closeModal() }
function exportCsv(rows, filename) { if (!rows.length) { notice.value = '当前没有可导出的数据'; return }; const csv = '\ufeff' + rows.map((row) => Object.values(row).map((cell) => `"${String(cell ?? '').replaceAll('"', '""')}"`).join(',')).join('\r\n'); const link = document.createElement('a'); link.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' })); link.download = filename; link.click(); URL.revokeObjectURL(link.href) }
onMounted(() => {
  window.addEventListener('hashchange', syncPage)
  document.addEventListener('pointerdown', closeOutside)
  document.addEventListener('keydown', closeOnEscape)
  load()
})
onBeforeUnmount(() => {
  window.removeEventListener('hashchange', syncPage)
  document.removeEventListener('pointerdown', closeOutside)
  document.removeEventListener('keydown', closeOnEscape)
})
</script>

<template>
  <div class="app-shell">
    <header class="topbar"><div class="brand"><span class="logo">🏃</span><div><h1>运动员生命体征 <strong>实时监控平台</strong></h1><small><i /> 实时数据接收中 · 每10秒自动刷新</small></div></div><div class="clock">{{ new Date().toLocaleString('zh-CN', { hour12: false }) }}　|　数据源：PostgreSQL / b2315p</div></header>
    <nav ref="navElement" class="nav" aria-label="主导航">
      <template v-for="(group, index) in navGroups" :key="group.label">
        <div v-if="group.children" class="nav-menu" :class="{ open: openGroup === group.label }"
          @pointerenter="previewGroup(group.label, $event)" @pointerleave="leaveGroup(group.label)" @focusout="leaveGroupFocus">
          <button class="nav-group" :class="{ 'group-active': isGroupActive(group) }" type="button"
            :aria-expanded="openGroup === group.label" :aria-controls="`nav-children-${index}`"
            @click="toggleGroup(group.label)" @keydown.down.prevent="focusFirstChild(group.label, $event)">
            {{ group.icon }} {{ group.label }} <span aria-hidden="true">⌃</span>
          </button>
          <div :id="`nav-children-${index}`" class="nav-dropdown">
            <button v-for="child in group.children" :key="child.key" type="button"
              :class="{ active: pageName === child.key }" :aria-current="pageName === child.key ? 'page' : undefined"
              @click="navigate(child.key)">{{ child.label }}</button>
          </div>
        </div>
        <button v-else :class="{ active: pageName === group.key }" type="button" @click="navigate(group.key)">{{ group.icon }} {{ group.label }}</button>
      </template>
    </nav>
    <main class="content"><div v-if="notice" class="notice">{{ notice }}</div>
      <template v-if="pageName === 'monitor'"><section class="summary"><div><b>{{ devices.length }}</b><span>设备数量</span></div><div><b>{{ onlineCount }}</b><span>在线设备</span></div><div><b>{{ alarms.length }}</b><span>累计报警</span></div><div><b>{{ alarms.filter((alarm) => alarm.status === '待处理').length }}</b><span>待处理报警</span></div><div><b>{{ healthRows.length }}</b><span>健康记录</span></div></section><h2>设备监测</h2><section class="device-grid"><article v-for="device in devices" :key="device.imei" class="device-card"><div class="device-head"><div class="person"><span>{{ device.name?.slice(0, 1) }}</span><div><b>{{ device.name }}</b><small>ID: {{ device.imei }}</small></div></div><em :class="device.enabled ? 'online' : 'offline'">● {{ device.enabled ? '在线' : '离线' }}</em></div><div class="model"><span>{{ device.model }}</span><em>4G手表</em></div><div class="vitals"><div><b>♥ {{ value(latestFor(device).heart_rate) }}</b><small>心率 bpm</small></div><div><b>◆ {{ value(latestFor(device).blood_oxygen) }}</b><small>血氧 SpO₂</small></div><div><b>♟ {{ value(latestFor(device).steps) }}</b><small>步数</small></div></div><div class="battery"><span>▣ 设备电量</span><b>{{ value(device.battery) }}{{ device.battery == null || device.battery === '' ? '' : '%' }}</b><i><span :style="{ width: `${device.battery || 0}%` }" /></i></div><div class="trends"><div><svg viewBox="0 0 150 30" preserveAspectRatio="none"><polyline :points="trendPoints(device, 'heart_rate')" /></svg><small>心率趋势</small></div><div><svg viewBox="0 0 150 30" preserveAspectRatio="none"><polyline class="blue" :points="trendPoints(device, 'blood_oxygen')" /></svg><small>血氧趋势</small></div></div><footer>最近更新：{{ formatDate(latestFor(device).collected_at) }} · 体温 {{ value(latestFor(device).body_temperature) }}℃</footer></article></section></template>
      <template v-else-if="pageName === 'health'"><section class="toolbar"><h2>健康数据</h2><select v-model="selectedImei" @change="loadHealth"><option v-for="device in devices" :key="device.imei" :value="device.imei">{{ device.name }} · {{ device.imei }}</option></select><button @click="loadHealth">查询</button><button @click="exportCsv(healthRows.map((row) => ({ IMEI: row.imei, 采集时间: formatDate(row.collected_at), 体温: row.body_temperature, 腕温: row.wrist_temperature, 心率: row.heart_rate, 血氧: row.blood_oxygen, 步数: row.steps, 卡路里: row.calories })), '健康数据.csv')">导出</button></section><div class="table-wrap"><table><thead><tr><th>#</th><th>账号</th><th>姓名</th><th>IMEI</th><th>采集时间</th><th>体温</th><th>腕温</th><th>心率</th><th>血氧</th><th>步数</th><th>卡路里</th></tr></thead><tbody><tr v-for="(row, index) in healthRows" :key="row.id"><td>{{ index + 1 }}</td><td>{{ row.account_name }}</td><td>{{ row.name }}</td><td>{{ row.imei }}</td><td>{{ formatDate(row.collected_at) }}</td><td>{{ row.body_temperature }}</td><td>{{ row.wrist_temperature }}</td><td>{{ row.heart_rate }}</td><td>{{ row.blood_oxygen }}</td><td>{{ row.steps }}</td><td>{{ row.calories }}</td></tr></tbody></table></div></template>
      <template v-else-if="pageName === 'alarms'"><section class="toolbar"><h2>报警列表</h2><select v-model="selectedAccount"><option value="">全部账号</option><option v-for="account in accounts" :key="account.id" :value="account.id">{{ account.name }}</option></select><select v-model="alarmType"><option value="">所有报警</option><option>心率异常</option><option>低电量</option><option>SOS报警</option></select><input v-model="alarmDate" type="date"><input v-model="searchImei" placeholder="请输入设备 IMEI"><button @click="filteredAlarms.forEach((alarm) => alarm.status = '已确认')">一键确认报警</button><button @click="exportCsv(filteredAlarms.map((row) => ({ 报警时间: formatDate(row.alarm_time), 报警类型: row.alarm_type, IMEI: row.imei, 姓名: row.person_name, 状态: row.status })), '报警列表.csv')">导出</button></section><div class="table-wrap"><table><thead><tr><th>#</th><th>报警时间</th><th>报警类型</th><th>设备IMEI</th><th>姓名</th><th>报警值</th><th>状态</th><th>操作</th></tr></thead><tbody><tr v-for="(alarm, index) in filteredAlarms" :key="alarm.id"><td>{{ index + 1 }}</td><td>{{ formatDate(alarm.alarm_time) }}</td><td>{{ alarm.alarm_type }}</td><td>{{ alarm.imei }}</td><td>{{ alarm.person_name }}</td><td>{{ alarm.alarm_value }}</td><td>{{ alarm.status }}</td><td><button class="link" @click="alarm.status = '已确认'">确认</button></td></tr></tbody></table></div></template>
      <template v-else-if="pageName === 'alarm-settings'"><section class="toolbar"><h2>报警设置</h2><button class="primary" @click="openRule">添加报警规则</button></section><div class="table-wrap"><table><thead><tr><th>#</th><th>报警类型</th><th>报警阈值</th><th>状态</th><th>通知</th><th>响铃</th><th>操作</th></tr></thead><tbody><tr v-for="(rule, index) in rules" :key="rule.id"><td>{{ index + 1 }}</td><td>{{ rule.alarm_type }}</td><td>{{ rule.threshold }}</td><td>{{ rule.enabled ? '启用' : '停用' }}</td><td>{{ rule.page_push ? '页面推送' : '--' }}</td><td>{{ rule.ring_mode }}</td><td><button class="link" @click="rules = rules.filter((item) => item.id !== rule.id)">删除</button></td></tr></tbody></table></div></template>
      <template v-else-if="pageName === 'roles'"><section class="toolbar"><h2>角色设置</h2><button class="primary" @click="openRole">添加角色</button><button @click="notice = '请选择角色后分配设备'">分配角色</button></section><div class="table-wrap"><table><thead><tr><th>#</th><th>角色名称</th><th>设备数</th><th>角色描述</th><th>创建时间</th></tr></thead><tbody><tr v-for="(role, index) in roles" :key="role.id"><td>{{ index + 1 }}</td><td>{{ role.name }}</td><td>{{ role.device_count }}</td><td>{{ role.description }}</td><td>{{ formatDate(role.created_at) }}</td></tr></tbody></table></div></template>
      <template v-else><section class="toolbar"><h2>{{ currentTitle }}</h2><input v-model="searchImei" placeholder="请输入设备 IMEI"><select v-model="selectedAccount"><option value="">全部账号</option><option v-for="account in accounts" :key="account.id" :value="account.id">{{ account.name }}</option></select><button @click="exportCsv(filteredDevices.map((device) => ({ IMEI: device.imei, 姓名: device.name, 型号: device.model, 状态: device.status, 账号: device.account_name, 电量: device.battery })), '设备列表.csv')">导出</button></section><div class="table-wrap"><table><thead><tr><th>#</th><th>姓名</th><th>IMEI</th><th>设备型号</th><th>状态</th><th>归属账号</th><th>电量</th></tr></thead><tbody><tr v-for="(device, index) in filteredDevices" :key="device.imei"><td>{{ index + 1 }}</td><td>{{ device.name }}</td><td>{{ device.imei }}</td><td>{{ device.model }}</td><td>{{ device.status }}</td><td>{{ device.account_name }}</td><td>{{ device.battery }}%</td></tr></tbody></table></div></template>
    </main>
    <div v-if="modal" class="modal" @click.self="closeModal"><form class="modal-box" @submit.prevent="saveModal"><button type="button" class="close" @click="closeModal">×</button><h3>{{ modal === 'role' ? '添加角色' : '添加报警规则' }}</h3><template v-if="modal === 'role'"><label>角色名称<input v-model="modalForm.name" required></label><label>角色描述<input v-model="modalForm.description"></label></template><template v-else><label>报警类型<select v-model="modalForm.type"><option>心率异常</option><option>低电量</option><option>SOS报警</option></select></label><label>报警级别<select v-model="modalForm.level"><option>普通级别</option><option>重要级别</option><option>紧急级别</option></select></label><label>报警阈值<input v-model="modalForm.threshold" placeholder="例如：60-160 bpm"></label></template><div class="modal-actions"><button type="button" @click="closeModal">取消</button><button class="primary" type="submit">确定</button></div></form></div>
  </div>
</template>
