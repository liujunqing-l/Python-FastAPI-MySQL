<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { MapPin, RefreshCw, Search } from 'lucide-vue-next'
import { api, dayRange, formatDate, items, today, total } from '../services/healthApi.js'
import { displayValue, eventViewState } from '../services/presentation.js'

const props = defineProps({
  devices: { type: Array, default: () => [] },
})

const catalog = ref([])
const selectedImei = ref('')
const startDate = ref(today())
const endDate = ref(today())
const rows = ref([])
const latest = ref(null)
const totalCount = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const catalogLoading = ref(false)
const error = ref('')
const notice = ref('')

const devices = computed(() => props.devices.length ? props.devices : catalog.value)
const pageCount = computed(() => Math.max(1, Math.ceil(totalCount.value / pageSize.value)))
const viewState = computed(() => eventViewState({ loading: loading.value, error: error.value, items: rows.value }))

const sourceNames = {
  gps: 'GPS / 北斗',
  lbs: '基站 LBS',
  wifi: 'Wi‑Fi',
  ble: '蓝牙 Beacon',
  bds: '北斗',
}

function field(row, names) {
  return names.map((name) => row?.[name]).find((value) => value !== null && value !== undefined && value !== '') ?? null
}

function deviceLabel(imei) {
  const device = devices.value.find((item) => String(item.imei) === String(imei))
  return field(device, ['person_name', 'name', 'device_name']) || imei || '--'
}

function sourceLabel(source) {
  const key = String(source || '').toLowerCase()
  return sourceNames[key] || displayValue(source)
}

function coordinate(row) {
  const latitude = field(row, ['latitude'])
  const longitude = field(row, ['longitude'])
  if (latitude === null || longitude === null) return '--'
  return `${latitude}, ${longitude}`
}

function hasCoordinates(row) {
  return field(row, ['latitude']) !== null && field(row, ['longitude']) !== null
}

function validateDates() {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(startDate.value) || !/^\d{4}-\d{2}-\d{2}$/.test(endDate.value)) throw new Error('请选择有效的起止日期')
  if (startDate.value > endDate.value) throw new Error('起始日期不能晚于结束日期')
  return dayRange(startDate.value, endDate.value)
}

async function loadCatalog() {
  if (props.devices.length) return
  catalogLoading.value = true
  try { catalog.value = items(await api.devices()); if (!selectedImei.value && catalog.value.length) selectedImei.value = String(catalog.value[0].imei) } catch (err) { notice.value = `设备目录暂不可用：${err.message || '请稍后重试'}` } finally { catalogLoading.value = false }
}

async function fetchHistory(range) {
  const result = []
  let pageNumber = 1
  const size = 100
  while (true) {
    const body = await api.locationsHistory(selectedImei.value, range.start, range.end, pageNumber, size)
    const batch = items(body)
    result.push(...batch)
    const count = total(body)
    if (!batch.length || (count !== null && result.length >= count) || (count === null && batch.length < size)) break
    pageNumber += 1
  }
  return result
}

async function load() {
  error.value = ''
  notice.value = ''
  rows.value = []
  latest.value = null
  totalCount.value = 0
  if (!selectedImei.value) { error.value = '请选择设备后查询定位记录'; return }
  let range
  try { range = validateDates() } catch (err) { error.value = err.message; return }
  loading.value = true
  try {
    const [latestResult, historyResult] = await Promise.allSettled([api.locationsLatest(selectedImei.value), fetchHistory(range)])
    if (latestResult.status === 'fulfilled') latest.value = latestResult.value
    else if (Number(latestResult.reason?.status) !== 404) throw latestResult.reason
    if (historyResult.status === 'rejected') throw historyResult.reason
    rows.value = historyResult.value
    totalCount.value = historyResult.value.length
    if (!latest.value && rows.value.length) latest.value = rows.value[0]
    if (!rows.value.length && !latest.value) notice.value = '当前日期范围内没有真实定位记录。'
  } catch (err) {
    error.value = `定位加载失败：${err.message || '接口暂不可用'}`
  } finally {
    loading.value = false
  }
}

async function query() { page.value = 1; await load() }
function changePage(next) { if (next < 1 || next > pageCount.value || next === page.value) return; page.value = next }

watch(() => props.devices, (next) => { if (!selectedImei.value && next.length) selectedImei.value = String(next[0].imei) }, { deep: true, immediate: true })
watch(pageSize, () => { page.value = 1 })
onMounted(async () => { await loadCatalog(); await load() })
</script>

<template>
  <section class="event-view location-view">
    <div class="page-heading"><h2>定位记录</h2><span class="state">只显示设备真实上报的定位或扫描记录</span></div>
    <form class="filters" @submit.prevent="query">
      <label>设备 / IMEI
        <select v-model="selectedImei" :disabled="catalogLoading"><option value="">请选择设备</option><option v-for="device in devices" :key="device.imei" :value="String(device.imei)">{{ deviceLabel(device.imei) }} · {{ device.imei }}</option></select>
      </label>
      <label>起始日期<input v-model="startDate" type="date" required></label>
      <label>结束日期<input v-model="endDate" type="date" required></label>
      <div class="actions"><button class="primary" type="submit" :disabled="loading || !selectedImei"><Search :size="16" />{{ loading ? '查询中...' : '查询' }}</button><button type="button" :disabled="loading || !selectedImei" @click="load"><RefreshCw :size="16" />刷新</button></div>
    </form>
    <p v-if="notice" class="state" role="status">{{ notice }}</p><p v-if="error" class="error" role="alert">{{ error }}</p>
    <section v-if="latest" class="location-latest">
      <div class="location-latest-title"><MapPin :size="18" /><h3>最近定位</h3><span class="state">{{ formatDate(latest.collected_at) }}</span></div>
      <div class="location-latest-grid"><div><small>来源</small><strong>{{ sourceLabel(latest.source) }}</strong></div><div><small>坐标</small><strong>{{ coordinate(latest) }}</strong></div><div><small>有效性</small><strong>{{ latest.position_valid === null || latest.position_valid === undefined ? '--' : latest.position_valid ? '有效' : '无效' }}</strong></div><div><small>坐标系</small><strong>{{ displayValue(latest.coordinate_system) }}</strong></div></div>
      <p v-if="!hasCoordinates(latest)" class="state">此条是扫描/基站记录，协议没有提供经纬度；页面不会自行推算坐标。</p>
    </section>
    <div class="table-wrap">
      <table class="event-table"><thead><tr><th>采集时间</th><th>设备</th><th>来源</th><th>经纬度</th><th>定位状态</th><th>解析状态</th></tr></thead>
        <tbody>
          <tr v-if="viewState === 'loading'"><td colspan="6" class="empty">正在读取定位数据...</td></tr>
          <tr v-else-if="viewState === 'error'"><td colspan="6" class="empty">读取失败，请根据上方提示处理后重试。</td></tr>
          <tr v-else-if="viewState === 'empty'"><td colspan="6" class="empty">当前日期范围内没有真实定位记录。</td></tr>
          <tr v-for="row in rows.slice((page - 1) * pageSize, page * pageSize)" v-else :key="row.id"><td>{{ formatDate(row.collected_at) }}</td><td><span>{{ deviceLabel(row.imei) }}</span><small class="muted">{{ row.imei }}</small></td><td>{{ sourceLabel(row.source) }}</td><td>{{ coordinate(row) }}</td><td>{{ row.position_valid === null || row.position_valid === undefined ? displayValue(row.position_status) : row.position_valid ? '有效' : '无效' }}</td><td>{{ displayValue(row.resolution_status) }}</td></tr>
        </tbody>
      </table>
    </div>
    <div class="pagination"><span class="state">共 {{ totalCount }} 条定位记录</span><label>每页<select v-model.number="pageSize"><option :value="20">20 条</option><option :value="50">50 条</option><option :value="100">100 条</option></select></label><button type="button" :disabled="page <= 1" @click="changePage(page - 1)">上一页</button><span>{{ page }} / {{ pageCount }}</span><button type="button" :disabled="page >= pageCount" @click="changePage(page + 1)">下一页</button></div>
  </section>
</template>

<style scoped>
.event-view { min-width: 0; }
.event-table { min-width: 850px; }
.event-table td > span, .event-table td > small { display: block; }
.muted { margin-top: 4px; color: #91a6c2; font-size: 11px; }
.location-latest { margin-top: 14px; padding: 16px; border: 1px solid #293d5b; border-radius: 8px; background: #17233a; }
.location-latest-title { display: flex; align-items: center; gap: 8px; color: #38b6ff; }
.location-latest-title h3 { margin: 0; color: #e9f1ff; font-size: 16px; }
.location-latest-title .state { margin-left: auto; }
.location-latest-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; margin-top: 16px; }
.location-latest-grid small, .location-latest-grid strong { display: block; }
.location-latest-grid small { color: #91a6c2; font-size: 11px; }
.location-latest-grid strong { margin-top: 5px; color: #e9f1ff; font-size: 15px; font-weight: 500; overflow-wrap: anywhere; }
.location-latest p { margin: 14px 0 0; }
.event-view .pagination { display: flex; align-items: center; justify-content: flex-end; gap: 10px; padding: 14px 0; font-size: 13px; }
.event-view .pagination .state { margin-right: auto; }
.event-view .pagination button { height: 32px; padding: 0 10px; border: 1px solid #3d5879; border-radius: 4px; background: #101d31; color: #e9f1ff; cursor: pointer; }
.event-view .pagination button:disabled { opacity: .5; cursor: not-allowed; }
.event-view .pagination select { height: 32px; margin-left: 5px; border: 1px solid #3d5879; border-radius: 4px; background: #101d31; color: #e9f1ff; }
@media (max-width: 760px) { .location-latest-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
