<script setup>
import { computed, onMounted, ref } from 'vue'
import { RefreshCw, Save } from 'lucide-vue-next'
import { api, items } from '../services/healthApi.js'
import { auth, hasRole } from '../services/auth.js'

const devices = ref([])
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const notice = ref('')
const canEdit = computed(() => hasRole(auth.user, 'admin'))

async function load() {
  loading.value = true
  error.value = ''
  try { devices.value = items(await api.devices()) } catch (err) { error.value = `设备加载失败：${err.message || '接口暂不可用'}` } finally { loading.value = false }
}

async function save(device) {
  if (!canEdit.value) return
  saving.value = true
  error.value = ''
  notice.value = ''
  try { await api.updateDevice(device.imei, { name: device.name, model: device.model, enabled: device.enabled }); notice.value = `${device.imei} 已保存` } catch (err) { error.value = `设备保存失败：${err.message || '请稍后重试'}` } finally { saving.value = false }
}

onMounted(load)
</script>

<template>
  <section class="admin-view"><div class="page-heading"><h2>设备信息</h2><span class="state">{{ canEdit ? '管理员可修改名称、型号和启用状态' : '当前角色只读' }}</span><button type="button" @click="load" :disabled="loading"><RefreshCw :size="16" />刷新</button></div><p v-if="notice" class="notice" role="status">{{ notice }}</p><p v-if="error" class="error" role="alert">{{ error }}</p><div class="table-wrap"><table class="admin-table"><thead><tr><th>IMEI</th><th>名称</th><th>型号</th><th>状态</th><th>最后上报</th><th>操作</th></tr></thead><tbody><tr v-if="loading"><td colspan="6" class="empty">正在读取设备...</td></tr><tr v-else-if="!devices.length"><td colspan="6" class="empty">暂无设备</td></tr><tr v-for="device in devices" v-else :key="device.imei"><td>{{ device.imei }}</td><td><input v-model.trim="device.name" :readonly="!canEdit"></td><td><input v-model.trim="device.model" :readonly="!canEdit"></td><td><label><input v-model="device.enabled" type="checkbox" :disabled="!canEdit">启用</label></td><td>{{ device.last_seen_at || '--' }}</td><td><button v-if="canEdit" type="button" @click="save(device)" :disabled="saving"><Save :size="15" />保存</button><span v-else class="state">只读</span></td></tr></tbody></table></div></section>
</template>

<style scoped>
.admin-view{min-width:0}.page-heading{display:flex;align-items:center;gap:10px}.page-heading h2{margin-right:auto}.page-heading button,.admin-table button{display:inline-flex;align-items:center;gap:5px;height:34px;padding:0 10px;border:1px solid #3d5879;border-radius:4px;background:#101d31;color:#e9f1ff;cursor:pointer}.page-heading button:disabled,.admin-table button:disabled{opacity:.5}.admin-table{min-width:800px}.admin-table input{height:34px;max-width:180px;border:1px solid #3d5879;border-radius:4px;background:#101d31;color:#e9f1ff;padding:0 9px}.empty{text-align:center;color:#91a6c2;padding:24px}
</style>
