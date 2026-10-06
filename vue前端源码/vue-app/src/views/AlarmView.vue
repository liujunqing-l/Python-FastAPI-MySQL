<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { Check, RefreshCw, Search } from 'lucide-vue-next'
import { api, dayRange, formatDate, items, today, total } from '../services/healthApi.js'
import { alarmTypeLabel, displayValue, eventViewState } from '../services/presentation.js'

const props = defineProps({
  devices: { type: Array, default: () => [] },
  canAcknowledge: { type: Boolean, default: false },
})

const catalog = ref([])
const selectedImei = ref('')
const status = ref('')
const startDate = ref(today())
const endDate = ref(today())
const rows = ref([])
const totalCount = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const catalogLoading = ref(false)
const error = ref('')
const notice = ref('')
const acknowledging = ref(new Set())

const devices = computed(() => props.devices.length ? props.devices : catalog.value)
const pageCount = computed(() => Math.max(1, Math.ceil(totalCount.value / pageSize.value)))
const viewState = computed(() => eventViewState({ loading: loading.value, error: error.value, items: rows.value }))

function field(row, names) {
  return names.map((name) => row?.[name]).find((value) => value !== null && value !== undefined && value !== '') ?? null
}

function deviceLabel(imei) {
  const device = devices.value.find((item) => String(item.imei) === String(imei))
  return field(device, ['person_name', 'name', 'device_name']) || imei || '--'
}

function alarmLabel(row) {
  const codes = Array.isArray(row?.alarm_codes) ? row.alarm_codes.filter(Boolean) : []
  if (codes.length) return codes.map((code) => alarmTypeLabel(code)).join('、')
  if (row?.alarm_type !== null && row?.alarm_type !== undefined && row?.alarm_type !== '') return alarmTypeLabel(row.alarm_type)
  if (row?.alarm_mask !== null && row?.alarm_mask !== undefined) return `位掩码 ${row.alarm_mask}`
  if (row?.sensor_type !== null && row?.sensor_type !== undefined) return `传感器异常（类型 ${row.sensor_type}）`
  return `协议消息 0x${Number(row?.message_id || 0).toString(16).padStart(2, '0').toUpperCase()}`
}

function statusLabel(value) {
  return value === 'acknowledged' ? '已确认' : value === 'pending' ? '待处理' : displayValue(value)
}

function validateDates() {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(startDate.value) || !/^\d{4}-\d{2}-\d{2}$/.test(endDate.value)) throw new Error('请选择有效的起止日期')
  if (startDate.value > endDate.value) throw new Error('起始日期不能晚于结束日期')
  return dayRange(startDate.value, endDate.value)
}

async function loadCatalog() {
  if (props.devices.length) return
  catalogLoading.value = true
  try {
    catalog.value = items(await api.devices())
  } catch (err) {
    // The event table can still be queried without the optional device catalog.
    notice.value = `设备目录暂不可用：${err.message || '请稍后重试'}`
  } finally {
    catalogLoading.value = false
  }
}

async function load() {
  error.value = ''
  notice.value = ''
  let range
  try { range = validateDates() } catch (err) { error.value = err.message; return }
  loading.value = true
  try {
    const body = await api.alarms({
      imei: selectedImei.value,
      status: status.value,
      start: range.start,
      end: range.end,
      page: page.value,
      page_size: pageSize.value,
    })
    rows.value = items(body)
    totalCount.value = total(body) ?? rows.value.length
  } catch (err) {
    rows.value = []
    totalCount.value = 0
    error.value = `报警加载失败：${err.message || '接口暂不可用'}`
  } finally {
    loading.value = false
  }
}

async function query() {
  page.value = 1
  await load()
}

async function acknowledge(row) {
  if (!row?.id || row.status === 'acknowledged' || acknowledging.value.has(row.id)) return
  acknowledging.value = new Set(acknowledging.value).add(row.id)
  error.value = ''
  try {
    const updated = await api.acknowledgeAlarm(row.id)
    const index = rows.value.findIndex((item) => item.id === row.id)
    if (index >= 0) rows.value.splice(index, 1, updated)
    notice.value = `报警 ${row.id} 已确认`
  } catch (err) {
    error.value = `确认失败：${err.message || '请稍后重试'}`
  } finally {
    const next = new Set(acknowledging.value)
    next.delete(row.id)
    acknowledging.value = next
  }
}

function changePage(next) {
  if (next < 1 || next > pageCount.value || next === page.value) return
  page.value = next
  load()
}

watch(() => props.devices, (next) => {
  if (!selectedImei.value && next.length) selectedImei.value = String(next[0].imei)
}, { deep: true, immediate: true })
watch(pageSize, () => { page.value = 1; load() })
onMounted(async () => { await loadCatalog(); await load() })
</script>

<template>
  <section class="event-view alarm-view">
    <div class="page-heading"><h2>报警列表</h2><span class="state">仅显示后端已解析并入库的报警</span></div>
    <form class="filters" @submit.prevent="query">
      <label>设备 / IMEI
        <select v-model="selectedImei" :disabled="catalogLoading">
          <option value="">全部设备</option>
          <option v-for="device in devices" :key="device.imei" :value="String(device.imei)">{{ deviceLabel(device.imei) }} · {{ device.imei }}</option>
        </select>
      </label>
      <label>状态
        <select v-model="status"><option value="">全部状态</option><option value="pending">待处理</option><option value="acknowledged">已确认</option></select>
      </label>
      <label>起始日期<input v-model="startDate" type="date" required></label>
      <label>结束日期<input v-model="endDate" type="date" required></label>
      <div class="actions"><button class="primary" type="submit" :disabled="loading"><Search :size="16" />{{ loading ? '查询中...' : '查询' }}</button><button type="button" :disabled="loading" @click="load"><RefreshCw :size="16" />刷新</button></div>
    </form>
    <p v-if="notice" class="state" role="status">{{ notice }}</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <div class="table-wrap">
      <table class="event-table">
        <thead><tr><th>采集时间</th><th>设备</th><th>报警类型</th><th>传感器值</th><th>状态</th><th>确认时间</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-if="viewState === 'loading'"><td colspan="7" class="empty">正在读取报警数据...</td></tr>
          <tr v-else-if="viewState === 'error'"><td colspan="7" class="empty">读取失败，请根据上方提示处理后重试。</td></tr>
          <tr v-else-if="viewState === 'empty'"><td colspan="7" class="empty">当前日期范围内没有真实报警记录。</td></tr>
          <tr v-for="row in rows" v-else :key="row.id">
            <td>{{ formatDate(row.collected_at) }}</td>
            <td><span>{{ deviceLabel(row.imei) }}</span><small class="muted">{{ row.imei }}</small></td>
            <td><span>{{ alarmLabel(row) }}</span><small class="muted">0x{{ Number(row.message_id || 0).toString(16).padStart(2, '0').toUpperCase() }}</small></td>
            <td>{{ displayValue(row.measured_value) }}</td>
            <td><span :class="['status-pill', row.status]">{{ statusLabel(row.status) }}</span></td>
            <td>{{ formatDate(row.acknowledged_at) }}</td>
            <td>
              <button v-if="canAcknowledge" class="link-button" type="button" :disabled="row.status === 'acknowledged' || acknowledging.has(row.id)" @click="acknowledge(row)"><Check :size="15" />{{ row.status === 'acknowledged' ? '已确认' : acknowledging.has(row.id) ? '确认中...' : '确认' }}</button>
              <span v-else class="muted">只读</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="pagination"><span class="state">共 {{ totalCount }} 条报警</span><label>每页<select v-model.number="pageSize"><option :value="20">20 条</option><option :value="50">50 条</option><option :value="100">100 条</option></select></label><button type="button" :disabled="page <= 1 || loading" @click="changePage(page - 1)">上一页</button><span>{{ page }} / {{ pageCount }}</span><button type="button" :disabled="page >= pageCount || loading" @click="changePage(page + 1)">下一页</button></div>
  </section>
</template>

<style scoped>
.event-view { min-width: 0; }
.event-table { min-width: 900px; }
.event-table td > span, .event-table td > small { display: block; }
.muted { margin-top: 4px; color: #91a6c2; font-size: 11px; }
.status-pill { display: inline-block !important; padding: 3px 8px; border-radius: 12px; font-size: 11px; }
.status-pill.pending { color: #ffd166; background: #5a461c; }
.status-pill.acknowledged { color: #8ce9ba; background: #194d3b; }
.event-view .filters select { min-width: 145px; }
.event-view .pagination { display: flex; align-items: center; justify-content: flex-end; gap: 10px; padding: 14px 0; font-size: 13px; }
.event-view .pagination .state { margin-right: auto; }
.event-view .pagination button { height: 32px; padding: 0 10px; border: 1px solid #3d5879; border-radius: 4px; background: #101d31; color: #e9f1ff; cursor: pointer; }
.event-view .pagination button:disabled { opacity: .5; cursor: not-allowed; }
.event-view .pagination select { height: 32px; margin-left: 5px; border: 1px solid #3d5879; border-radius: 4px; background: #101d31; color: #e9f1ff; }
</style>
