<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { loginRequest } from '../services/auth.js'

const router = useRouter()
const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

async function submit() {
  error.value = ''
  if (!username.value.trim() || !password.value) {
    error.value = '请输入用户名和密码'
    return
  }
  loading.value = true
  try {
    await loginRequest(username.value.trim(), password.value)
    await router.replace('/')
  } catch (err) {
    error.value = err.message || '登录失败，请稍后重试'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-panel" aria-labelledby="login-title">
      <div class="login-mark">B2315P</div>
      <h1 id="login-title">生命体征监控平台</h1>
      <p class="state">请登录后查看已授权设备</p>
      <form @submit.prevent="submit">
        <label>用户名<input v-model="username" autocomplete="username" required></label>
        <label>密码<input v-model="password" type="password" autocomplete="current-password" required></label>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
        <button class="primary login-button" type="submit" :disabled="loading">{{ loading ? '登录中...' : '登录' }}</button>
      </form>
    </section>
  </main>
</template>

<style scoped>
.login-page { min-height: 100vh; display: grid; place-items: center; padding: 24px; background: #080f1e; }
.login-panel { width: min(420px, 100%); padding: 32px; border: 1px solid #293d5b; border-radius: 8px; background: #17233a; box-shadow: 0 18px 48px #0006; }
.login-mark { color: #08c5e6; font-weight: 700; letter-spacing: .08em; }
h1 { margin: 12px 0 8px; color: #e9f1ff; font-size: 24px; }
.state { margin: 0 0 24px; }
label { display: block; margin: 14px 0; color: #a9b8cb; font-size: 13px; }
input { display: block; width: 100%; height: 38px; margin-top: 7px; padding: 0 11px; border: 1px solid #3d5879; border-radius: 4px; background: #101d31; color: #e9f1ff; }
.login-button { width: 100%; height: 38px; margin-top: 8px; border: 0; border-radius: 4px; cursor: pointer; }
.login-button:disabled { cursor: not-allowed; opacity: .55; }
.error { margin: 12px 0; }
</style>
