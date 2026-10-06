<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Download, Search, ChevronLeft, ChevronRight, X, ChartNoAxesCombined } from 'lucide-vue-next'
import { api, items, formatDate, today, dayRange, isDemo } from '../services/healthApi.js'
import { personLabel } from '../services/presentation.js'
import { exportWorkbook } from '../utils/export.js'
import HealthChart from '../components/HealthChart.vue'

const router = useRouter()
const route = useRoute()
const devices = ref([])
const selectedAccount = ref('')
const selectedImei = ref(typeof route.query.imei === 'string' ? route.query.imei : '')
const startDate = ref(typeof route.query.start === 'string' ? route.query.start : today())
const endDate = ref(typeof route.query.end === 'string' ? route.query.end : startDate.value)
const rows = ref([])
const loading = ref(false)
const deviceLoading = ref(false)
const error = ref('')
const catalogError = ref('')
const catalogNotice = ref('')
const resultRange = ref(null)
const page = ref(1)
const pageSize = ref(20)
const exportOpen = ref(false)
const exportStart = ref(today())
const exportEnd = ref(today())
const exportPeople = ref([])
const exportMetrics = ref(['body_temperature', 'wrist_temperature', 'heart_rate', 'blood_oxygen', 'systolic', 'diastolic', 'steps'])
const exporting = ref(false)
const exportError = ref('')
const exportProgress = ref('')
const notice = ref('')
let loadVersion = 0

const metrics = [
  { key: 'body_temperature', title: '体温', unit: '℃', color: '#29a9ff', aliases: ['body_temperature', 'temperature'] },
  { key: 'wrist_temperature', title: '腕温', unit: '℃', color: '#20b783', aliases: ['wrist_temperature'] },
  { key: 'heart_rate', title: '心率', unit: '次/分', color: '#ff6b9d', aliases: ['heart_rate'] },
  { key: 'blood_oxygen', title: '血氧', unit: '%', color: '#ffd166', aliases: ['blood_oxygen', 'spo2'] },
  { key: 'systolic', title: '收缩压', unit: 'mmHg', aliases: ['systolic', 'systolic_pressure'] },
  { key: 'diastolic', title: '舒张压', unit: 'mmHg', aliases: ['diastolic', 'diastolic_pressure'] },
  { key: 'steps', title: '步数', unit: '步', color: '#8b9cff', aliases: ['steps', 'step_count'] },
]
const chartMetrics = metrics.filter((metric) => !['systolic', 'diastolic'].includes(metric.key))
const filteredDevices = computed(() => devices.value.filter((device) => !selectedAccount.value || accountId(device) === selectedAccount.value))
const currentDevice = computed(() => devices.value.find((device) => String(device.imei) === selectedImei.value))
const pageCount = computed(() => Math.max(1, Math.ceil(rows.value.length / pageSize.value)))
const displayedRows = computed(() => rows.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
const allPeopleSelected = computed(() => devices.value.length > 0 && exportPeople.value.length === devices.value.length)
const accountOptions = computed(() => {
  const result = new Map()
  devices.value.forEach((device) => {
    if (accountId(device)) result.set(accountId(device), field(device, ['account_name', 'account']) ?? accountId(device))
  })
  return [...result.entries()].map(([id, name]) => ({ id, name }))
})

function field(row, names) {
  return names.map((name) => row?.[name]).find((value) => value !== undefined && value !== null && value !== '') ?? null
}
function show(value) { return value === null || value === undefined || value === '' ? '--' : value }
function personName(device) { return personLabel(field(device, ['person_name', 'name', 'device_name'])) }
function accountId(device) { return String(field(device, ['account_id', 'account_name', 'account']) ?? '') }
function measuredAt(row) { return field(row, ['collected_at', 'device_time', 'measured_at', 'received_at']) }

async function fetchAll(fetchPage, onProgress) {
  const result = []
  const size = 100
  let pageNumber = 1
  while (true) {
    const body = await fetchPage(pageNumber, size)
    const batch = items(body)
    result.push(...batch)
    const rawTotal = body?.total ?? body?.data?.total
    const total = rawTotal !== null && rawTotal !== undefined ? Number(rawTotal) : null
    onProgress?.(result.length, total)
    if (!batch.length || (total !== null && Number.isFinite(total) && result.length >= total) || (total === null && batch.length < size)) break
    pageNumber += 1
  }
  return result
}

function validateDates(start, end) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(start) || !/^\d{4}-\d{2}-\d{2}$/.test(end)) throw new Error('请选择有效的起止日期')
  if (start > end) throw new Error('起始日期不能晚于结束日期')
  return dayRange(start, end)
}

async function query() {
  const version = ++loadVersion
  error.value = ''
  notice.value = ''
  rows.value = []
  page.value = 1
  resultRange.value = null
  if (!selectedImei.value) { error.value = '请选择人员或设备'; return }
  let range
  try { range = validateDates(startDate.value, endDate.value) } catch (err) { error.value = err.message; return }
  loading.value = true
  const imei = selectedImei.value
  const applied = { imei, start: startDate.value, end: endDate.value }
  try {
    const result = await fetchAll((number, size) => api.history(imei, range.start, range.end, number, size))
    if (version !== loadVersion) return
    rows.value = result.sort((a, b) => new Date(measuredAt(a) || 0) - new Date(measuredAt(b) || 0))
    resultRange.value = applied
  } catch (err) {
    if (version === loadVersion) error.value = `查询失败：${err.message || '无法读取健康数据'}`
  } finally {
    if (version === loadVersion) loading.value = false
  }
}

async function loadCatalog() {
  deviceLoading.value = true
  catalogError.value = ''
  catalogNotice.value = '账号绑定接口暂未接入，筛选使用设备返回的账号字段；未绑定设备显示“--”。'
  const results = await Promise.allSettled([fetchAll((number, size) => api.devices(number, size))])
  if (results[0].status === 'fulfilled') devices.value = results[0].value
  else catalogError.value = `设备加载失败：${results[0].reason?.message || '接口不可用'}`
  deviceLoading.value = false
  if (!selectedImei.value && devices.value.length) selectedImei.value = String(devices.value[0].imei)
  if (selectedImei.value) await query()
}

function openDetail(row = null) {
  const selected = resultRange.value || { imei: selectedImei.value, start: startDate.value, end: endDate.value }
  const imei = row?.imei || selected.imei
  if (imei) router.push({ path: '/health-detail', query: { imei, start: selected.start, end: selected.end } })
}

function openExport() {
  exportStart.value = startDate.value
  exportEnd.value = endDate.value
  exportPeople.value = selectedImei.value ? [selectedImei.value] : []
  exportError.value = ''
  exportProgress.value = ''
  exportOpen.value = true
}

function selectAllPeople(event) { exportPeople.value = event.target.checked ? devices.value.map((device) => String(device.imei)) : [] }
function closeExport() { if (!exporting.value) exportOpen.value = false }
function onKeydown(event) { if (event.key === 'Escape') closeExport() }

async function exportData() {
  exportError.value = ''
  if (!exportPeople.value.length) { exportError.value = '请至少勾选一名人员'; return }
  if (!exportMetrics.value.length) { exportError.value = '请至少勾选一项检测数据'; return }
  let range
  try { range = validateDates(exportStart.value, exportEnd.value) } catch (err) { exportError.value = err.message; return }
  exporting.value = true
  const output = []
  const selectedMetrics = metrics.filter((metric) => exportMetrics.value.includes(metric.key))
  try {
    for (let index = 0; index < exportPeople.value.length; index += 1) {
      const imei = exportPeople.value[index]
      const device = devices.value.find((item) => String(item.imei) === imei)
      const records = await fetchAll(
        (number, size) => api.history(imei, range.start, range.end, number, size),
        (count) => { exportProgress.value = `正在读取 ${personName(device)}：${count} 条（${index + 1}/${exportPeople.value.length}）` },
      )
      for (const row of records) {
        const record = {
          account: field(row, ['account_name', 'account']) ?? field(device, ['account_name', 'account']) ?? '',
          person: field(row, ['person_name', 'name']) ?? personName(device),
          imei: row.imei || imei,
          measured_at: formatDate(measuredAt(row)),
        }
        selectedMetrics.forEach((metric) => { record[metric.key] = field(row, metric.aliases) })
        output.push(record)
      }
    }
    if (!output.length) { exportError.value = '所选人员和日期范围内暂无可导出的检测数据'; return }
    exportProgress.value = '正在生成 Excel 文件...'
    await exportWorkbook(`健康数据_${exportStart.value}_${exportEnd.value}.xlsx`, [
      { header: '归属账号', key: 'account', width: 20 },
      { header: '姓名', key: 'person', width: 16 },
      { header: '设备 IMEI', key: 'imei', width: 22 },
      { header: '采集时间', key: 'measured_at', width: 25 },
      ...selectedMetrics.map((metric) => ({ header: `${metric.title}（${metric.unit}）`, key: metric.key, width: 18 })),
    ], output)
    notice.value = `已导出 ${output.length} 条健康数据`
    exportOpen.value = false
  } catch (err) {
    exportError.value = `导出失败：${err.message || '无法读取完整数据，请重试'}`
  } finally {
    exporting.value = false
    exportProgress.value = ''
  }
}

watch(selectedAccount, () => {
  if (!filteredDevices.value.some((device) => String(device.imei) === selectedImei.value)) selectedImei.value = ''
})
watch(pageSize, () => { page.value = 1 })
onMounted(() => { loadCatalog(); window.addEventListener('keydown', onKeydown) })
onBeforeUnmount(() => { loadVersion += 1; window.removeEventListener('keydown', onKeydown) })
</script>

<template>
  <div class="health-view">
    <div class="page-heading"><h2>健康数据</h2><span class="state">{{ isDemo ? '演示数据' : '实时接口数据' }}</span></div>
    <form class="filters" @submit.prevent="query">
      <label>账号（未接入时按设备字段）<select v-model="selectedAccount" :disabled="deviceLoading"><option value="">全部账号</option><option v-for="account in accountOptions" :key="account.id" :value="account.id">{{ account.name }}</option></select></label>
      <label>起始日期<input v-model="startDate" type="date" required></label>
      <label>结束日期<input v-model="endDate" type="date" required></label>
      <label class="person-filter">人员 / 设备<select v-model="selectedImei" :disabled="deviceLoading"><option value="">请选择人员或设备</option><option v-for="device in filteredDevices" :key="device.imei" :value="String(device.imei)">{{ personName(device) }} · {{ device.imei }}</option></select></label>
      <div class="actions"><button class="primary" type="submit" :disabled="loading || deviceLoading"><Search :size="16" />{{ loading ? '查询中...' : '查询' }}</button><button type="button" :disabled="deviceLoading || !devices.length" @click="openExport"><Download :size="16" />导出 Excel</button></div>
    </form>
    <p v-if="catalogNotice" class="state" role="status">{{ catalogNotice }}</p>
    <p v-if="catalogError" class="error" role="alert">{{ catalogError }}</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="notice" class="state" role="status">{{ notice }}</p>
    <div class="table-wrap">
      <table class="health-table"><thead><tr><th>#</th><th>归属账号</th><th>姓名</th><th>设备 IMEI</th><th>采集时间</th><th v-for="metric in metrics" :key="metric.key">{{ metric.title }}<small>{{ metric.unit }}</small></th><th>更多</th></tr></thead>
        <tbody>
          <tr v-if="loading || deviceLoading"><td colspan="13" class="empty">正在加载健康数据...</td></tr>
          <tr v-else-if="!rows.length"><td colspan="13" class="empty">{{ selectedImei ? '所选日期范围内暂无健康数据' : '请选择人员或设备后查询' }}</td></tr>
          <template v-else>
            <tr v-for="(row, index) in displayedRows" :key="`${row.id || measuredAt(row)}-${index}`">
              <td>{{ (page - 1) * pageSize + index + 1 }}</td><td>{{ show(field(row, ['account_name', 'account']) ?? field(currentDevice, ['account_name', 'account'])) }}</td><td>{{ show(field(row, ['person_name', 'name']) || personName(currentDevice)) }}</td><td>{{ row.imei || resultRange?.imei }}</td><td>{{ formatDate(measuredAt(row)) }}</td><td v-for="metric in metrics" :key="metric.key">{{ show(field(row, metric.aliases)) }}</td><td><button class="link-button" type="button" @click="openDetail(row)">详情</button></td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
    <div class="pagination"><span class="state">共 {{ rows.length }} 条记录</span><label>每页<select v-model.number="pageSize"><option :value="20">20 条</option><option :value="50">50 条</option><option :value="100">100 条</option></select></label><button title="上一页" aria-label="上一页" :disabled="page <= 1" @click="page -= 1"><ChevronLeft :size="16" /></button><span>{{ page }} / {{ pageCount }}</span><button title="下一页" aria-label="下一页" :disabled="page >= pageCount" @click="page += 1"><ChevronRight :size="16" /></button></div>
    <section class="trends-section"><div class="trend-heading"><h3><ChartNoAxesCombined :size="18" />健康趋势</h3><span v-if="resultRange" class="state">{{ resultRange.start }} 至 {{ resultRange.end }}</span><button class="link-button" :disabled="!selectedImei" @click="openDetail()">详情</button></div><div class="charts-grid"><HealthChart v-for="metric in chartMetrics" :key="metric.key" :rows="rows" :metric="metric.key" :title="metric.title" :unit="metric.unit" :color="metric.color" :height="230" /></div></section>

    <Teleport to="body">
      <div v-if="exportOpen" class="health-modal-mask" @click.self="closeExport"><section class="health-modal" role="dialog" aria-modal="true" aria-labelledby="health-export-title"><header><h3 id="health-export-title">导出健康数据</h3><button class="icon-close" title="关闭" aria-label="关闭" :disabled="exporting" @click="closeExport"><X :size="20" /></button></header><form @submit.prevent="exportData"><fieldset :disabled="exporting"><div class="export-dates"><label>起始日期<input v-model="exportStart" type="date" required></label><label>结束日期<input v-model="exportEnd" type="date" required></label></div><div class="section-title"><h4>选择人员</h4><label class="check"><input type="checkbox" :checked="allPeopleSelected" @change="selectAllPeople">全选</label></div><div class="people-list"><label v-for="device in devices" :key="device.imei" class="check person-option"><input v-model="exportPeople" type="checkbox" :value="String(device.imei)"><span>{{ personName(device) }}<small>{{ device.imei }}</small></span></label></div><h4>检测数据</h4><div class="metric-options"><label v-for="metric in metrics" :key="metric.key" class="check"><input v-model="exportMetrics" type="checkbox" :value="metric.key">{{ metric.title }}</label></div></fieldset><p v-if="exportError" class="error" role="alert">{{ exportError }}</p><p v-if="exportProgress" class="state" role="status">{{ exportProgress }}</p><footer><button type="button" :disabled="exporting" @click="closeExport">取消</button><button class="primary" type="submit" :disabled="exporting"><Download :size="16" />{{ exporting ? '正在导出...' : '导出 Excel' }}</button></footer></form></section></div>
    </Teleport>
  </div>
</template>

<style scoped>
.health-view { min-width: 0; }
.health-view label { display: flex; align-items: center; gap: 8px; color: #a9b8cb; font-size: 13px; }
.health-view input, .health-view select { min-width: 0; }
.person-filter select { max-width: 310px; }
.health-table { min-width: 1420px; }
.health-table th small { display: block; font-size: 10px; font-weight: 400; margin-top: 4px; }
.pagination { display: flex; align-items: center; justify-content: flex-end; gap: 10px; padding: 14px 0; font-size: 13px; }
.pagination .state { margin-right: auto; }
.pagination button { display: grid; place-items: center; width: 32px; padding: 0; }
.pagination select { width: 75px; }
.trends-section { margin-top: 12px; }
.trend-heading { display: flex; gap: 14px; align-items: center; margin-bottom: 12px; }
.trend-heading h3 { display: flex; align-items: center; gap: 7px; margin: 0; font-size: 16px; }
.trend-heading button { margin-left: auto; }
.charts-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.health-modal-mask { position: fixed; inset: 0; z-index: 2000; display: grid; place-items: center; padding: 20px; background: #030a15b8; }
.health-modal { width: min(700px, 100%); max-height: calc(100dvh - 40px); overflow-y: auto; color: #e9f1ff; background: #17253d; border: 1px solid #3d5879; border-radius: 8px; box-shadow: 0 20px 70px #0008; }
.health-modal header, .health-modal footer { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 18px 22px; }
.health-modal header { border-bottom: 1px solid #2b4362; }
.health-modal h3 { margin: 0; font-size: 18px; }
.health-modal h4 { margin: 18px 0 12px; font-size: 14px; }
.health-modal fieldset { min-width: 0; margin: 0; padding: 20px 22px 4px; border: 0; }
.health-modal label { display: flex; gap: 8px; align-items: center; color: #c5d3e4; font-size: 13px; }
.health-modal button, .health-modal input { height: 34px; background: #101d31; color: #e9f1ff; border: 1px solid #3d5879; border-radius: 4px; padding: 0 10px; }
.health-modal button { display: inline-flex; align-items: center; justify-content: center; gap: 7px; cursor: pointer; }
.health-modal input[type="checkbox"] { width: 15px; height: 15px; padding: 0; accent-color: #20b783; }
.health-modal .icon-close { padding: 0; width: 30px; background: transparent; border: 0; }
.health-modal .export-dates { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.health-modal .export-dates label { display: flex; flex-direction: column; align-items: stretch; }
.health-modal .section-title { display: flex; align-items: center; justify-content: space-between; }
.health-modal .people-list { max-height: 200px; overflow-y: auto; border: 1px solid #2b4362; border-radius: 4px; background: #101d31; }
.health-modal .person-option { padding: 10px 12px; border-bottom: 1px solid #213650; }
.health-modal .person-option:last-child { border-bottom: 0; }
.health-modal .person-option span { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
.health-modal .person-option small { color: #91a6c2; }
.health-modal .metric-options { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 13px; }
.health-modal footer { justify-content: flex-end; margin-top: 18px; border-top: 1px solid #2b4362; }
.health-modal .error, .health-modal .state { margin: 16px 22px 0; }
.health-modal button:disabled { opacity: .5; cursor: not-allowed; }
@media (max-width: 760px) { .charts-grid { grid-template-columns: minmax(0, 1fr); } .health-view .filters label { flex: 1 1 220px; align-items: stretch; flex-direction: column; } .person-filter select { max-width: none; width: 100%; } .pagination { flex-wrap: wrap; } .trend-heading { flex-wrap: wrap; } .health-modal-mask { padding: 12px; } .health-modal { max-height: calc(100dvh - 24px); } .health-modal .metric-options { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
