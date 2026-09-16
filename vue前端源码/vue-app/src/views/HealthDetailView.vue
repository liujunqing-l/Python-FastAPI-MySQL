<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Download, Search, HeartPulse, Thermometer, Footprints, Flame, Droplets } from 'lucide-vue-next'
import { api, items, formatDate, today, dayRange, isDemo } from '../services/healthApi.js'
import { personLabel } from '../services/presentation.js'
import { exportWorkbook } from '../utils/export.js'
import HealthChart from '../components/HealthChart.vue'

const route = useRoute()
const router = useRouter()
const imei = ref('')
const startDate = ref(today())
const endDate = ref(today())
const rows = ref([])
const loading = ref(false)
const exporting = ref(false)
const error = ref('')
const notice = ref('')
const applied = ref(null)
const device = ref(null)
let loadVersion = 0

const metrics = [
  { key: 'body_temperature', title: '体温', unit: '℃', color: '#29a9ff', aliases: ['body_temperature', 'temperature'], icon: Thermometer },
  { key: 'wrist_temperature', title: '腕温', unit: '℃', color: '#20b783', aliases: ['wrist_temperature'], icon: Thermometer },
  { key: 'heart_rate', title: '心率', unit: '次/分', color: '#ff6b9d', aliases: ['heart_rate'], icon: HeartPulse },
  { key: 'blood_oxygen', title: '血氧', unit: '%', color: '#ffd166', aliases: ['blood_oxygen', 'spo2'], icon: Droplets },
  { key: 'steps', title: '步数', unit: '步', color: '#8b9cff', aliases: ['steps', 'step_count'], icon: Footprints },
  { key: 'calories', title: '卡路里', unit: 'kcal', color: '#ff9f43', aliases: ['calories'], icon: Flame },
]
const displayName = computed(() => personLabel(field(device.value, ['person_name', 'name', 'device_name']) || field(rows.value.at(-1), ['person_name', 'name'])))
const latestTime = computed(() => rows.value.length ? formatDate(measuredAt(rows.value.at(-1))) : '--')

function field(row, names) {
  return names.map((name) => row?.[name]).find((value) => value !== undefined && value !== null && value !== '') ?? null
}
function measuredAt(row) { return field(row, ['collected_at', 'device_time', 'measured_at', 'received_at']) }
function latestValue(metric) {
  for (let index = rows.value.length - 1; index >= 0; index -= 1) {
    const value = field(rows.value[index], metric.aliases)
    if (value !== null) return value
  }
  return '--'
}

async function fetchHistory(range, selectedImei) {
  const result = []
  const pageSize = 100
  let number = 1
  while (true) {
    const body = await api.history(selectedImei, range.start, range.end, number, pageSize)
    const batch = items(body)
    result.push(...batch)
    const rawTotal = body?.total ?? body?.data?.total
    const total = rawTotal !== undefined && rawTotal !== null ? Number(rawTotal) : null
    if (!batch.length || (total !== null && Number.isFinite(total) && result.length >= total) || (total === null && batch.length < pageSize)) break
    number += 1
  }
  return result
}

async function load() {
  const version = ++loadVersion
  error.value = ''
  notice.value = ''
  rows.value = []
  applied.value = null
  if (!imei.value) { error.value = '未选择设备，请从健康数据列表打开详情'; return }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(startDate.value) || !/^\d{4}-\d{2}-\d{2}$/.test(endDate.value)) { error.value = '请选择有效的起止日期'; return }
  if (startDate.value > endDate.value) { error.value = '起始日期不能晚于结束日期'; return }
  let range
  try { range = dayRange(startDate.value, endDate.value) } catch (err) { error.value = err.message; return }
  const selection = { imei: imei.value, start: startDate.value, end: endDate.value }
  loading.value = true
  try {
    const result = await fetchHistory(range, selection.imei)
    if (version !== loadVersion) return
    rows.value = result.sort((a, b) => new Date(measuredAt(a) || 0) - new Date(measuredAt(b) || 0))
    applied.value = selection
  } catch (err) {
    if (version === loadVersion) error.value = `查询失败：${err.message || '无法读取健康数据'}`
  } finally {
    if (version === loadVersion) loading.value = false
  }
}

function readRoute() {
  imei.value = typeof route.query.imei === 'string' ? route.query.imei : ''
  startDate.value = typeof route.query.start === 'string' ? route.query.start : typeof route.query.date === 'string' ? route.query.date : today()
  endDate.value = typeof route.query.end === 'string' ? route.query.end : startDate.value
  device.value = null
  load()
}

async function query() {
  const nextQuery = { imei: imei.value, start: startDate.value, end: endDate.value }
  if (Object.entries(nextQuery).every(([key, value]) => route.query[key] === value)) await load()
  else await router.replace({ path: '/health-detail', query: nextQuery })
}

function goBack() {
  router.push({ path: '/health', query: { imei: imei.value, start: startDate.value, end: endDate.value } })
}

async function exportData() {
  if (!rows.value.length) { error.value = '当前没有可导出的健康数据'; return }
  exporting.value = true
  error.value = ''
  try {
    const selected = applied.value
    await exportWorkbook(`健康详情_${selected.imei}_${selected.start}_${selected.end}.xlsx`, [
      { header: '归属账号', key: 'account', width: 20 },
      { header: '姓名', key: 'person', width: 16 },
      { header: '设备 IMEI', key: 'imei', width: 22 },
      { header: '采集时间', key: 'time', width: 25 },
      ...metrics.map((metric) => ({ header: `${metric.title}（${metric.unit}）`, key: metric.key, width: 18 })),
      { header: '收缩压（mmHg）', key: 'systolic', width: 18 },
      { header: '舒张压（mmHg）', key: 'diastolic', width: 18 },
    ], rows.value.map((row) => {
      const record = {
        account: field(row, ['account_name', 'account']) || '',
        person: field(row, ['person_name', 'name']) || displayName.value,
        imei: row.imei || selected.imei,
        time: formatDate(measuredAt(row)),
        systolic: field(row, ['systolic', 'systolic_pressure']),
        diastolic: field(row, ['diastolic', 'diastolic_pressure']),
      }
      metrics.forEach((metric) => { record[metric.key] = field(row, metric.aliases) })
      return record
    }))
    notice.value = `已导出 ${rows.value.length} 条健康数据`
  } catch (err) {
    error.value = `导出失败：${err.message || '请重试'}`
  } finally {
    exporting.value = false
  }
}

watch(() => route.fullPath, readRoute)
onMounted(readRoute)
onBeforeUnmount(() => { loadVersion += 1 })
</script>

<template>
  <div class="health-detail-view">
    <button type="button" class="link-button back-button" @click="goBack"><ArrowLeft :size="16" />返回健康数据</button>
    <div class="page-heading"><h2>健康数据详情</h2><span class="state">{{ isDemo ? '演示数据' : '实时接口数据' }}</span></div>
    <p class="device-meta"><span>{{ displayName }}</span><span>设备 IMEI：{{ imei || '--' }}</span><span>最近测量：{{ latestTime }}</span></p>
    <form class="filters" @submit.prevent="query"><label>起始日期<input v-model="startDate" type="date" required></label><label>结束日期<input v-model="endDate" type="date" required></label><div class="actions"><button class="primary" type="submit" :disabled="loading || !imei"><Search :size="16" />{{ loading ? '查询中...' : '查询' }}</button><button type="button" :disabled="loading || exporting || !rows.length" @click="exportData"><Download :size="16" />{{ exporting ? '正在导出...' : '导出 Excel' }}</button></div><span class="state">{{ loading ? '正在读取测量记录...' : `共 ${rows.length} 条测量记录` }}</span></form>
    <p v-if="error" class="error" role="alert">{{ error }}</p><p v-if="notice" class="state" role="status">{{ notice }}</p>
    <div class="latest-metrics"><div v-for="metric in metrics" :key="metric.key"><span class="metric-label"><component :is="metric.icon" :size="17" :color="metric.color" />{{ metric.title }}</span><strong>{{ latestValue(metric) }}<small>{{ metric.unit }}</small></strong></div></div>
    <div class="detail-charts"><HealthChart v-for="metric in metrics" :key="metric.key" :rows="rows" :metric="metric.key" :title="metric.title" :unit="metric.unit" :color="metric.color" :height="270" /></div>
  </div>
</template>

<style scoped>
.health-detail-view { min-width: 0; }
.back-button { display: inline-flex; align-items: center; gap: 6px; padding-left: 0; }
.device-meta { display: flex; flex-wrap: wrap; gap: 10px 24px; color: #91a6c2; font-size: 13px; margin: 0 0 18px; }
.health-detail-view .filters label { display: flex; align-items: center; gap: 8px; color: #a9b8cb; font-size: 13px; }
.health-detail-view .filters .state { margin-left: auto; }
.latest-metrics { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 0; padding: 20px 0; }
.latest-metrics > div { min-width: 0; padding: 0 18px; border-right: 1px solid #2b4362; }
.latest-metrics > div:first-child { padding-left: 0; }
.latest-metrics > div:last-child { border-right: 0; }
.metric-label { display: flex; align-items: center; gap: 7px; color: #a9b8cb; font-size: 13px; }
.latest-metrics strong { display: block; margin-top: 10px; font-size: 24px; font-weight: 600; color: #e9f1ff; }
.latest-metrics small { margin-left: 7px; color: #91a6c2; font-size: 11px; font-weight: 400; }
.detail-charts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
@media (max-width: 1050px) { .latest-metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); row-gap: 20px; } .latest-metrics > div:nth-child(4) { padding-left: 0; } .latest-metrics > div:nth-child(3) { border-right: 0; } }
@media (max-width: 760px) { .detail-charts { grid-template-columns: minmax(0, 1fr); } .health-detail-view .filters label { flex: 1 1 180px; flex-direction: column; align-items: stretch; } .health-detail-view .filters .state { flex-basis: 100%; margin-left: 0; } .latest-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } .latest-metrics > div:nth-child(2n) { border-right: 0; padding-left: 18px; } .latest-metrics > div:nth-child(2n + 1) { border-right: 1px solid #2b4362; padding-left: 0; } }
</style>
