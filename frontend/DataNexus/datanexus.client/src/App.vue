<script lang="ts">
import { defineComponent } from 'vue'
import Frame from './components/Frame.vue'
import { service } from './common/APIService.js'

export default defineComponent({
  components: { Frame },
  data() {
    return {
      authenticated: false,
      authError: false,
      errorMessage: '',
    }
  },
  async mounted() {
    try {
      await service.authenticate()
      this.authenticated = true
    } catch {
      // authenticate() 会触发 acquireTokenRedirect，页面将自动跳转登录页；
      // 期间保持加载遮罩。
      this.authError = true
      this.errorMessage = '正在跳转登录页…'
    }
  },
})
</script>

<template>
  <!-- 已登录：显示主应用 -->
  <Frame v-if="authenticated" />

  <!-- 未登录：全屏登录遮罩 -->
  <div v-else class="auth-overlay">
    <div class="auth-card">
      <div class="auth-spinner" :class="{ 'auth-spinner--warn': authError }"></div>
      <p class="auth-text">
        {{ authError ? errorMessage : '正在登录，请稍候…' }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.auth-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  display: flex;
  justify-content: center;
  align-items: center;
  background: linear-gradient(180deg, var(--beone-white) 0%, var(--beone-bg-page) 100%);
  color: var(--beone-midnight-blue);
  font-family: var(--beone-font-family);
  z-index: 99999;
}

.auth-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 18px;
}

.auth-spinner {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 3px solid var(--beone-border);
  border-top-color: var(--beone-midnight-blue);
  animation: auth-spin 0.8s cubic-bezier(0.4, 0, 0.2, 1) infinite;
}

.auth-spinner--warn {
  border-top-color: var(--beone-autumn-leaf);
}

@keyframes auth-spin {
  to { transform: rotate(360deg); }
}

.auth-text {
  font-size: 14px;
  color: var(--beone-text-secondary);
  margin: 0;
  letter-spacing: 0.3px;
}
</style>

