<script setup>
import { onMounted, ref } from 'vue'
import { RefreshCw, Save, UserPlus } from 'lucide-vue-next'
import { api, items, total } from '../services/healthApi.js'

const accounts = ref([])
const roles = ref([])
const devices = ref([])
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const notice = ref('')
const createForm = ref({ username: '', password: '', display_name: '', role: 'viewer' })

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [accountBody, roleBody, deviceBody] = await Promise.all([
      api.accounts(),
      api.roles(),
      api.devices(),
    ])
    accounts.value = items(accountBody)
    roles.value = items(roleBody)
    devices.value = items(deviceBody)
  } catch (err) {
    error.value = `账号管理加载失败：${err.message || '接口暂不可用'}`
  } finally {
    loading.value = false
  }
}

async function createAccount() {
  error.value = ''
  notice.value = ''
  if (!createForm.value.username || !createForm.value.password) {
    error.value = '请输入用户名和至少 6 位密码'
    return
  }
  saving.value = true
  try {
    await api.createAccount(createForm.value)
    createForm.value = { username: '', password: '', display_name: '', role: 'viewer' }
    notice.value = '账号已创建'
    await load()
  } catch (err) {
    error.value = `账号创建失败：${err.message || '请稍后重试'}`
  } finally {
    saving.value = false
  }
}

async function saveAccount(account) {
  error.value = ''
  notice.value = ''
  saving.value = true
  try {
    await api.updateAccount(account.id, { role: account.role, enabled: account.enabled, display_name: account.display_name })
    await api.replaceBindings(account.id, account.device_imeis || [])
    notice.value = `${account.username} 已保存`
    await load()
  } catch (err) {
    error.value = `账号保存失败：${err.message || '请稍后重试'}`
  } finally {
    saving.value = false
  }
}

function toggleDevice(account, imei) {
  const current = new Set(account.device_imeis || [])
  if (current.has(imei)) current.delete(imei)
  else current.add(imei)
  account.device_imeis = [...current]
}

onMounted(load)
</script>

<template>
  <section class="admin-view">
    <div class="page-heading"><h2>角色与账号</h2><span class="state">仅管理员可维护账号、角色和设备绑定</span><button type="button" @click="load" :disabled="loading"><RefreshCw :size="16" />刷新</button></div>
    <p v-if="notice" class="notice" role="status">{{ notice }}</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <form class="admin-create" @submit.prevent="createAccount">
      <UserPlus :size="18" /><input v-model.trim="createForm.username" placeholder="用户名" autocomplete="off"><input v-model="createForm.password" type="password" minlength="6" placeholder="初始密码"><input v-model.trim="createForm.display_name" placeholder="显示名称"><select v-model="createForm.role"><option v-for="role in roles" :key="role.id" :value="role.name">{{ role.name }}</option></select><button class="primary" type="submit" :disabled="saving">创建账号</button>
    </form>
    <div class="table-wrap">
      <table class="admin-table"><thead><tr><th>用户名</th><th>显示名称</th><th>角色</th><th>启用</th><th>设备绑定</th><th>操作</th></tr></thead>
        <tbody><tr v-if="loading"><td colspan="6" class="empty">正在读取账号...</td></tr><tr v-else-if="!accounts.length"><td colspan="6" class="empty">暂无账号</td></tr><tr v-for="account in accounts" v-else :key="account.id">
          <td>{{ account.username }}</td><td><input v-model.trim="account.display_name"></td><td><select v-model="account.role"><option v-for="role in roles" :key="role.id" :value="role.name">{{ role.name }}</option></select></td><td><input v-model="account.enabled" type="checkbox"></td><td><div class="binding-list"><label v-for="device in devices" :key="device.imei"><input type="checkbox" :checked="(account.device_imeis || []).includes(device.imei)" @change="toggleDevice(account, device.imei)">{{ device.name || device.imei }}</label></div></td><td><button type="button" @click="saveAccount(account)" :disabled="saving"><Save :size="15" />保存</button></td>
        </tr></tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.admin-view{min-width:0}.page-heading{display:flex;align-items:center;gap:10px}.page-heading h2{margin-right:auto}.page-heading button,.admin-create button,.admin-table button{display:inline-flex;align-items:center;gap:5px;height:34px;padding:0 10px;border:1px solid #3d5879;border-radius:4px;background:#101d31;color:#e9f1ff;cursor:pointer}.page-heading button:disabled,.admin-create button:disabled,.admin-table button:disabled{opacity:.5}.admin-create{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:14px 0;padding:14px;background:#17233a;border:1px solid #293d5b;border-radius:8px}.admin-create input,.admin-create select,.admin-table input,.admin-table select{height:34px;border:1px solid #3d5879;border-radius:4px;background:#101d31;color:#e9f1ff;padding:0 9px}.admin-create input{width:180px}.admin-table input,.admin-table select{max-width:180px}.binding-list{display:flex;flex-wrap:wrap;gap:6px;max-width:280px}.binding-list label{font-size:11px;white-space:nowrap}.admin-table{min-width:980px}.admin-table td{vertical-align:top}.primary{background:#1677ff!important;border-color:#1677ff!important}.empty{text-align:center;color:#91a6c2;padding:24px}
</style>
