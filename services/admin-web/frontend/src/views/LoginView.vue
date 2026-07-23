<script setup lang="ts">
import { ref } from 'vue'
import { BookOpen, KeyRound, LogIn, ShieldCheck, UserRound } from '@lucide/vue'
import { api, errorMessage } from '../api'

const emit = defineEmits<{ authenticated: [session: any] }>()

const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

async function login() {
  error.value = ''
  loading.value = true
  try {
    const session = await api.post('/api/auth/login', {
      username: username.value,
      password: password.value,
    })
    password.value = ''
    emit('authenticated', session)
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="login-shell">
    <section class="login-panel" aria-labelledby="login-title">
      <div class="login-brand">
        <div class="login-brand__mark"><BookOpen :size="22" /></div>
        <div>
          <strong>Knowledge Hub</strong>
          <span>知识管理控制台</span>
        </div>
      </div>

      <div class="login-copy">
        <div class="login-copy__icon"><ShieldCheck :size="20" /></div>
        <div>
          <h1 id="login-title">登录管理控制台</h1>
          <p>使用 LDAP 目录账户验证身份。</p>
        </div>
      </div>

      <form class="login-form" @submit.prevent="login">
        <label class="field">
          <span><UserRound :size="14" /> 用户名</span>
          <input v-model.trim="username" autocomplete="username" required :disabled="loading" />
        </label>
        <label class="field">
          <span><KeyRound :size="14" /> 密码</span>
          <input v-model="password" type="password" autocomplete="current-password" required :disabled="loading" />
        </label>
        <div v-if="error" class="notice is-error">{{ error }}</div>
        <button class="button primary login-submit" type="submit" :disabled="loading">
          <LogIn :size="15" /> {{ loading ? '正在验证' : '登录' }}
        </button>
      </form>
    </section>
  </main>
</template>
