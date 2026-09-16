<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RefreshCw, Settings2 } from 'lucide-vue-next'
import { api, formatDate, items } from '../services/healthApi.js'
import { commandExecutionLabel, commandIntervalBounds, commandStatusLabel, displayValue, isCommandIntervalValid } from '../services/presentation.js'

const props = defineProps({
  devices: { type: Array, default: () => [] },
})

const catalog = ref([])
const selectedImei = ref('')
const config = ref(null)
const loading = ref(false)
const catalogLoading = ref(false)
const error = ref('')
const notice = ref('')
const locationInterval = ref('')
const healthInterval = ref('')
const commands = ref([])
const commandLoading = ref(false)
const commandSubmitting = ref('')
const commandError = ref('')
let commandRefreshTimer = null

const devices = computed(() => props.devices.length ? props.devices : catalog.value)

function field(row, names) {
  return names.map((name) => row?.[name]).find((value) => value !== null && value !== undefined && value !== '') ?? null
}

function deviceLabel(imei) {
  const device = devices.value.find((item) => String(item.imei) === String(imei))
  return field(device, ['person_name', 'name', 'device_name']) || imei || '--'
}

async function loadCatalog() {
  if (props.devices.length) return
  catalogLoading.value = true
  try { catalog.value = items(await api.devices()); if (!selectedImei.value && catalog.value.length) selectedImei.value = String(catalog.value[0].imei) } catch (err) { notice.value = `设备目录暂不可用：${err.message || '请稍后重试'}` } finally { catalogLoading.value = false }
}

async function load() {
  config.value = null
  error.value = ''
  notice.value = ''
  if (!selectedImei.value) { notice.value = '请选择设备后查看最近一次配置回执。'; return }
  loading.value = true
  try {
    config.value = await api.deviceConfig(selectedImei.value)
    locationInterval.value = config.value.location_interval_minutes ?? ''
    healthInterval.value = config.value.health_interval_minutes ?? ''
  } catch (err) {
    if (Number(err.status) === 404) notice.value = '该设备尚未收到配置回执；可以先提交命令，设备下次连接时会尝试下发。'
    else error.value = `配置加载失败：${err.message || '接口暂不可用'}`
  } finally {
    loading.value = false
  }
}

function validateInterval(value) {
  return isCommandIntervalValid(value, 'location_frequency')
}

function validateHealthInterval(value) {
  return isCommandIntervalValid(value, 'health_frequency')
}

const locationBounds = commandIntervalBounds('location_frequency')
const healthBounds = commandIntervalBounds('health_frequency')

function commandTypeLabel(commandType) {
  return commandType === 'location_frequency' ? '定位上传周期' : commandType === 'health_frequency' ? '健康采样周期' : displayValue(commandType)
}

async function loadCommands() {
  if (!selectedImei.value) { commands.value = []; return }
  commandLoading.value = true
  commandError.value = ''
  try {
    const body = await api.listCommands({ imei: selectedImei.value, page: 1, page_size: 100 })
    commands.value = items(body)
  } catch (err) {
    commandError.value = `命令状态加载失败：${err.message || '接口暂不可用'}`
  } finally {
    commandLoading.value = false
  }
}

async function refreshSelected() {
  await Promise.all([load(), loadCommands()])
}

async function submitCommand(commandType) {
  const value = commandType === 'location_frequency' ? locationInterval.value : healthInterval.value
  const valid = commandType === 'location_frequency' ? validateInterval(value) : validateHealthInterval(value)
  if (!selectedImei.value) { notice.value = '请先选择设备'; return }
  if (!valid) {
    commandError.value = commandType === 'location_frequency'
      ? `定位周期必须是 ${locationBounds.min}–${locationBounds.max} 分钟的整数`
      : `健康周期必须是 ${healthBounds.min}–${healthBounds.max} 分钟的整数`
    return
  }
  commandSubmitting.value = commandType
  commandError.value = ''
  notice.value = ''
  try {
    const payload = {
      imei: selectedImei.value,
      command_type: commandType,
      ...(commandType === 'location_frequency'
        ? { location_interval_minutes: Number(value) }
        : { health_interval_minutes: Number(value) }),
    }
    const created = await api.createCommand(payload)
    commands.value = [created, ...commands.value.filter((item) => item.id !== created.id)]
    notice.value = created.status === 'acknowledged' && created.executed === true
      ? `${commandTypeLabel(commandType)}已由设备确认执行`
      : `${commandTypeLabel(commandType)}已入队，等待设备连接和回执；当前尚未执行`
    await loadCommands()
  } catch (err) {
    commandError.value = `命令提交失败：${err.message || '接口暂不可用'}`
  } finally {
    commandSubmitting.value = ''
  }
}

watch(() => props.devices, (next) => { if (!selectedImei.value && next.length) selectedImei.value = String(next[0].imei) }, { deep: true, immediate: true })
watch(selectedImei, refreshSelected)
onMounted(async () => {
  await loadCatalog()
  await refreshSelected()
  commandRefreshTimer = window.setInterval(() => { if (selectedImei.value) void loadCommands() }, 5000)
})
onBeforeUnmount(() => { if (commandRefreshTimer !== null) window.clearInterval(commandRefreshTimer) })
</script>

<template>
  <section class="event-view settings-view">
    <div class="page-heading"><h2>设备设置</h2><span class="state">配置回执只读；周期命令通过短连接队列下发</span></div>
    <div class="toolbar settings-toolbar"><label>设备 / IMEI<select v-model="selectedImei" :disabled="catalogLoading"><option value="">请选择设备</option><option v-for="device in devices" :key="device.imei" :value="String(device.imei)">{{ deviceLabel(device.imei) }} · {{ device.imei }}</option></select></label><button type="button" :disabled="loading || commandLoading || !selectedImei" @click="refreshSelected"><RefreshCw :size="16" />刷新配置与命令</button></div>
    <p v-if="notice" class="notice" role="status">{{ notice }}</p><p v-if="error" class="error" role="alert">{{ error }}</p>
    <section v-if="config" class="settings-card">
      <header><Settings2 :size="18" /><h3>最近一次配置回执</h3><span class="state">{{ formatDate(config.collected_at) }}</span></header>
      <div class="settings-grid"><div><small>定位上传周期</small><strong>{{ displayValue(config.location_interval_minutes) }}<em v-if="config.location_interval_minutes !== null && config.location_interval_minutes !== undefined"> 分钟</em></strong><span>{{ config.location_modified === null || config.location_modified === undefined ? '未说明' : config.location_modified ? '已修改' : '未修改' }}</span></div><div><small>健康上传周期</small><strong>{{ displayValue(config.health_interval_minutes) }}<em v-if="config.health_interval_minutes !== null && config.health_interval_minutes !== undefined"> 分钟</em></strong><span>{{ config.health_modified === null || config.health_modified === undefined ? '未说明' : config.health_modified ? '已修改' : '未修改' }}</span></div><div><small>回执来源</small><strong>{{ displayValue(config.timestamp_source) }}</strong><span>消息 0x{{ Number(config.message_id || 233).toString(16).padStart(2, '0').toUpperCase() }}</span></div></div>
    </section>
    <section class="settings-card command-card">
      <header><Settings2 :size="18" /><h3>上传周期下发</h3><span class="state">命令先入队，设备回传 0xC0 后才算执行</span></header>
      <p class="state">设备是短连接，提交后可能先显示“待发送”或“已发送，等待设备回执”；只有“已确认”才表示设备执行成功。</p>
      <div class="command-grid"><label>定位周期（1–1440 分钟）<input v-model="locationInterval" type="number" min="1" max="1440" step="1" :disabled="!selectedImei || Boolean(commandSubmitting)"><small v-if="locationInterval && !validateInterval(locationInterval)" class="error-text">请输入 1–1440 的整数</small></label><label>健康周期（2–255 分钟）<input v-model="healthInterval" type="number" min="2" max="255" step="1" :disabled="!selectedImei || Boolean(commandSubmitting)"><small v-if="healthInterval && !validateHealthInterval(healthInterval)" class="error-text">请输入 2–255 的整数</small></label></div>
      <div class="actions"><button type="button" :disabled="!selectedImei || Boolean(commandSubmitting) || !validateInterval(locationInterval)" @click="submitCommand('location_frequency')">{{ commandSubmitting === 'location_frequency' ? '提交中...' : '下发定位周期' }}</button><button type="button" :disabled="!selectedImei || Boolean(commandSubmitting) || !validateHealthInterval(healthInterval)" @click="submitCommand('health_frequency')">{{ commandSubmitting === 'health_frequency' ? '提交中...' : '下发健康周期' }}</button></div>
      <p v-if="commandError" class="error" role="alert">{{ commandError }}</p>
      <div class="command-history"><h4>最近命令状态</h4><p v-if="commandLoading" class="state">正在读取命令状态...</p><p v-else-if="!commands.length" class="state">暂无命令记录。</p><div v-else class="table-wrap"><table><thead><tr><th>提交时间</th><th>命令</th><th>状态</th><th>执行结果</th><th>错误</th></tr></thead><tbody><tr v-for="command in commands" :key="command.id"><td>{{ formatDate(command.created_at) }}</td><td>{{ commandTypeLabel(command.command_type) }}</td><td><span :class="['command-status', command.status]">{{ commandStatusLabel(command.status) }}</span></td><td>{{ commandExecutionLabel(command) }}</td><td>{{ displayValue(command.last_error) }}</td></tr></tbody></table></div></div>
    </section>
  </section>
</template>

<style scoped>
.event-view { min-width: 0; }
.settings-toolbar { justify-content: flex-start; }
.settings-toolbar label { display: flex; align-items: center; gap: 10px; color: #a9b8cb; }
.settings-toolbar select { height: 34px; min-width: 280px; border: 1px solid #3d5879; border-radius: 4px; background: #101d31; color: #e9f1ff; padding: 0 10px; }
.settings-toolbar button { display: inline-flex; align-items: center; gap: 7px; height: 34px; padding: 0 12px; border: 1px solid #3d5879; border-radius: 4px; background: #101d31; color: #e9f1ff; cursor: pointer; }
.settings-toolbar button:disabled { opacity: .5; cursor: not-allowed; }
.settings-card { margin-top: 14px; padding: 18px; border: 1px solid #293d5b; border-radius: 8px; background: #17233a; }
.settings-card header { display: flex; align-items: center; gap: 8px; color: #38b6ff; }
.settings-card header h3 { margin: 0; color: #e9f1ff; font-size: 16px; }
.settings-card header .state { margin-left: auto; }
.settings-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; margin-top: 18px; }
.settings-grid > div { padding: 14px; border: 1px solid #2d466b; border-radius: 6px; background: #1c2b48; }
.settings-grid small, .settings-grid strong, .settings-grid span { display: block; }
.settings-grid small { color: #91a6c2; font-size: 11px; }
.settings-grid strong { margin: 8px 0 5px; color: #e9f1ff; font-size: 21px; font-weight: 500; }
.settings-grid em { color: #91a6c2; font-size: 12px; font-style: normal; }
.settings-grid span { color: #a9b8cb; font-size: 12px; }
.command-card p { margin: 15px 0; }
.command-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.command-grid label { display: flex; flex-direction: column; gap: 7px; color: #a9b8cb; font-size: 13px; }
.command-grid input { height: 34px; border: 1px solid #3d5879; border-radius: 4px; background: #101d31; color: #e9f1ff; padding: 0 10px; }
.command-grid input:disabled { opacity: .65; }
.error-text { color: #ff9eae; }
.command-card .actions { display: flex; gap: 9px; margin-top: 18px; }
.command-card button { height: 34px; padding: 0 13px; border: 1px solid #3d5879; border-radius: 4px; background: #101d31; color: #e9f1ff; cursor: pointer; }
.command-card button:disabled { cursor: not-allowed; opacity: .5; }
.command-history { margin-top: 22px; }
.command-history h4 { margin: 0 0 10px; color: #e9f1ff; font-size: 14px; }
.command-history .table-wrap { margin-top: 0; }
.command-status { display: inline-block; padding: 3px 8px; border-radius: 12px; font-size: 11px; }
.command-status.pending, .command-status.claimed { color: #ffd166; background: #5a461c; }
.command-status.sent { color: #8cc8ff; background: #1d4260; }
.command-status.acknowledged { color: #8ce9ba; background: #194d3b; }
.command-status.failed, .command-status.expired { color: #ff9eae; background: #5a2435; }
@media (max-width: 760px) { .settings-grid, .command-grid { grid-template-columns: 1fr; } .settings-toolbar { align-items: stretch; flex-direction: column; } .settings-toolbar label { align-items: stretch; flex-direction: column; } .settings-toolbar select { min-width: 0; } }
</style>
