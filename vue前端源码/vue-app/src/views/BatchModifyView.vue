<script setup>
import { onMounted, ref } from 'vue'
import { CheckSquare, RefreshCw, Save } from 'lucide-vue-next'
import { api, items } from '../services/healthApi.js'

const devices = ref([])
const selected = ref(new Set())
const model = ref('')
const enabled = ref(null)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const notice = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try { devices.value = items(await api.devices()) } catch (err) { error.value = `设备加载失败：${err.message || '接口暂不可用'}` } finally { loading.value = false }
}

function toggle(imei) {
  const next = new Set(selected.value)
  if (next.has(imei)) next.delete(imei)
  else next.add(imei)
  selected.value = next
}

async function save() {
  if (!selected.value.size || (!model.value && enabled.value === null)) { error.value = '请选择设备并填写至少一个修改项'; return }
  saving.value = true
  error.value = ''
  try { const body = { imeis: [...selected.value] }; if (model.value) body.model = model.value; if (enabled.value !== null) body.enabled = enabled.value; const result = await api.batchUpdateDevices(body); notice.value = `已更新 ${result.updated} 台设备`; await load() } catch (err) { error.value = `批量保存失败：${err.message || '请稍后重试'}` } finally { saving.value = false }
}

onMounted(load)
</script>

<template>
  <section class="admin-view"><div class="page-heading"><h2>批量修改</h2><span class="state">先选择设备，再提交统一修改</span><button type="button" @click="load" :disabled="loading"><RefreshCw :size="16" />刷新</button></div><p v-if="notice" class="notice" role="status">{{ notice }}</p><p v-if="error" class="error" role="alert">{{ error }}</p><div class="batch-toolbar"><input v-model.trim="model" placeholder="统一型号（可选）"><select v-model="enabled"><option :value="null">不修改启用状态</option><option :value="true">全部启用</option><option :value="false">全部停用</option></select><button class="primary" type="button" @click="save" :disabled="saving"><Save :size="16" />保存到已选设备</button></div><div class="table-wrap"><table class="admin-table"><thead><tr><th><CheckSquare :size="15" /></th><th>IMEI</th><th>名称</th><th>型号</th><th>当前状态</th></tr></thead><tbody><tr v-if="loading"><td colspan="5" class="empty">正在读取设备...</td></tr><tr v-else-if="!devices.length"><td colspan="5" class="empty">暂无设备</td></tr><tr v-for="device in devices" v-else :key="device.imei"><td><input type="checkbox" :checked="selected.has(device.imei)" @change="toggle(device.imei)"></td><td>{{ device.imei }}</td><td>{{ device.name || '--' }}</td><td>{{ device.model }}</td><td>{{ device.enabled ? '启用' : '停用' }}</td></tr></tbody></table></div></section>
</template>

<style scoped>
.admin-view{min-width:0}.page-heading{display:flex;align-items:center;gap:10px}.page-heading h2{margin-right:auto}.page-heading button,.batch-toolbar button{display:inline-flex;align-items:center;gap:5px;height:34px;padding:0 10px;border:1px solid #3d5879;border-radius:4px;background:#101d31;color:#e9f1ff;cursor:pointer}.page-heading button:disabled,.batch-toolbar button:disabled{opacity:.5}.batch-toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:14px 0;padding:14px;background:#17233a;border:1px solid #293d5b;border-radius:8px}.batch-toolbar input,.batch-toolbar select{height:34px;min-width:200px;border:1px solid #3d5879;border-radius:4px;background:#101d31;color:#e9f1ff;padding:0 9px}.primary{background:#1677ff!important;border-color:#1677ff!important}.admin-table{min-width:760px}.empty{text-align:center;color:#91a6c2;padding:24px}
</style>
