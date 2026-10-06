<script setup>
import { onMounted, ref } from 'vue'
import { Plus, RefreshCw, Trash2 } from 'lucide-vue-next'
import { api, items } from '../services/healthApi.js'
import { alarmTypeLabel } from '../services/presentation.js'

const rules = ref([])
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const notice = ref('')
const form = ref({ name: '', alarm_type: 'heart_rate', threshold: '', direction: 'gte', enabled: true })

async function load() {
  loading.value = true
  error.value = ''
  try { rules.value = items(await api.rules()) } catch (err) { error.value = `报警规则加载失败：${err.message || '接口暂不可用'}` } finally { loading.value = false }
}

async function createRule() {
  if (!form.value.name || form.value.threshold === '') { error.value = '请输入规则名称和阈值'; return }
  saving.value = true
  error.value = ''
  try { await api.createRule({ ...form.value, threshold: Number(form.value.threshold) }); form.value = { name: '', alarm_type: 'heart_rate', threshold: '', direction: 'gte', enabled: true }; notice.value = '报警规则已创建'; await load() } catch (err) { error.value = `规则创建失败：${err.message || '请稍后重试'}` } finally { saving.value = false }
}

async function toggleRule(rule) {
  saving.value = true
  error.value = ''
  try { const updated = await api.updateRule(rule.id, { enabled: rule.enabled }); Object.assign(rule, updated); notice.value = '报警规则已更新' } catch (err) { error.value = `规则更新失败：${err.message || '请稍后重试'}`; await load() } finally { saving.value = false }
}

async function removeRule(rule) {
  saving.value = true
  error.value = ''
  try { await api.deleteRule(rule.id); rules.value = rules.value.filter((item) => item.id !== rule.id); notice.value = '报警规则已删除' } catch (err) { error.value = `规则删除失败：${err.message || '请稍后重试'}` } finally { saving.value = false }
}

onMounted(load)
</script>

<template>
  <section class="admin-view"><div class="page-heading"><h2>报警设置</h2><span class="state">规则保存后用于后端报警数据解释</span><button type="button" @click="load" :disabled="loading"><RefreshCw :size="16" />刷新</button></div><p v-if="notice" class="notice" role="status">{{ notice }}</p><p v-if="error" class="error" role="alert">{{ error }}</p>
    <form class="rule-form" @submit.prevent="createRule"><input v-model.trim="form.name" placeholder="规则名称"><select v-model="form.alarm_type"><option value="heart_rate">心率</option><option value="blood_oxygen">血氧</option><option value="body_temperature">体温</option><option value="fall">跌倒</option></select><input v-model="form.threshold" type="number" step="any" placeholder="阈值"><select v-model="form.direction"><option value="gte">大于等于</option><option value="lte">小于等于</option></select><label><input v-model="form.enabled" type="checkbox">启用</label><button class="primary" type="submit" :disabled="saving"><Plus :size="16" />新增规则</button></form>
    <div class="table-wrap"><table class="admin-table"><thead><tr><th>名称</th><th>类型</th><th>方向</th><th>阈值</th><th>启用</th><th>操作</th></tr></thead><tbody><tr v-if="loading"><td colspan="6" class="empty">正在读取规则...</td></tr><tr v-else-if="!rules.length"><td colspan="6" class="empty">暂无报警规则</td></tr><tr v-for="rule in rules" v-else :key="rule.id"><td>{{ rule.name }}</td><td>{{ alarmTypeLabel(rule.alarm_type) }}</td><td>{{ rule.direction === 'lte' ? '小于等于' : '大于等于' }}</td><td>{{ rule.threshold ?? '--' }}</td><td><input v-model="rule.enabled" type="checkbox" @change="toggleRule(rule)"></td><td><button type="button" @click="removeRule(rule)" :disabled="saving"><Trash2 :size="15" />删除</button></td></tr></tbody></table></div>
  </section>
</template>

<style scoped>
.admin-view{min-width:0}.page-heading{display:flex;align-items:center;gap:10px}.page-heading h2{margin-right:auto}.page-heading button,.rule-form button,.admin-table button{display:inline-flex;align-items:center;gap:5px;height:34px;padding:0 10px;border:1px solid #3d5879;border-radius:4px;background:#101d31;color:#e9f1ff;cursor:pointer}.page-heading button:disabled,.rule-form button:disabled,.admin-table button:disabled{opacity:.5}.rule-form{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:14px 0;padding:14px;background:#17233a;border:1px solid #293d5b;border-radius:8px}.rule-form input,.rule-form select{height:34px;min-width:145px;border:1px solid #3d5879;border-radius:4px;background:#101d31;color:#e9f1ff;padding:0 9px}.rule-form label{font-size:12px;color:#a9b8cb}.primary{background:#1677ff!important;border-color:#1677ff!important}.admin-table{min-width:760px}.empty{text-align:center;color:#91a6c2;padding:24px}
</style>
