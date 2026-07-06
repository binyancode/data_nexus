<template>
  <div class="frame-header">
    <div class="brand">
      <img class="brand-logo" src="../assets/logo.svg" alt="Data Nexus" />
      <span class="brand-title">Data Nexus</span>
    </div>

    <nav class="header-menu" aria-label="主导航">
      <button
        v-for="item in menuItems"
        :key="item.id"
        type="button"
        class="menu-item"
        :class="{ 'is-active': activeMenu === item.id }"
        @click="$emit('menu-select', item.id)"
      >
        <el-icon><component :is="item.icon" /></el-icon>
        <span>{{ item.label }}</span>
      </button>
    </nav>

    <div class="header-spacer"></div>

    <button type="button" class="header-action-button" title="帮助" aria-label="帮助" @click="openHelp">
      <el-icon><QuestionFilled /></el-icon>
    </button>
    <div class="header-user" :title="username">
      <el-icon><User /></el-icon>
      <span>{{ username }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { API } from '../common/API.js'
import { authState } from '../common/authState.js'

defineProps<{ activeMenu: string }>()
defineEmits<{ (e: 'menu-select', id: string): void }>()

// 登录后 API.username 才有值；轮询兜底直到拿到
const account = ref(API.username)
const timer = window.setInterval(() => {
  if (API.username) {
    account.value = API.username
    window.clearInterval(timer)
  }
}, 500)
onBeforeUnmount(() => window.clearInterval(timer))

// 优先显示 BFF 返回的 displayName（nexus.app_user），否则回退到 AAD 账号
const username = computed(() => authState.displayName || account.value)

const menuItems = [
  { id: 'ask', label: '提问台', icon: 'ChatDotRound' },
  { id: 'runs', label: '运行历史', icon: 'Histogram' },
  { id: 'ontology', label: '本体', icon: 'Share' },
  { id: 'resolvers', label: '源管理', icon: 'Coin' },
  { id: 'llms', label: 'LLM', icon: 'MagicStick' },
  { id: 'credentials', label: '凭据', icon: 'Key' },
]

function openHelp() {
  ElMessage.info('Data Nexus：用自然语言提问，看它怎么一步步算出答案。')
}
</script>

<style scoped>
.frame-header {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  height: 100%;
  min-width: 0;
  color: var(--beone-white);
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.brand-logo {
  width: 30px;
  height: 30px;
  flex: 0 0 auto;
}

.brand-title {
  color: var(--beone-white);
  font-size: 16px;
  font-weight: 600;
  white-space: nowrap;
  letter-spacing: 0.3px;
}

.header-menu {
  display: flex;
  align-items: center;
  gap: 2px;
  min-width: 0;
  height: 36px;
  margin-left: 16px;
  padding: 2px;
  overflow-x: auto;
  scrollbar-width: none;
}

.header-menu::-webkit-scrollbar {
  display: none;
}

.menu-item {
  height: 32px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
  padding: 0 12px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: rgba(255, 255, 255, 0.86);
  font-family: var(--beone-font-family);
  font-size: 13px;
  font-weight: 500;
  line-height: 1;
  white-space: nowrap;
  cursor: pointer;
  transition: background-color 0.12s ease, color 0.12s ease;
}

.menu-item:hover,
.menu-item:focus {
  color: var(--beone-white);
  background: rgba(255, 255, 255, 0.12);
}

.menu-item.is-active {
  color: var(--beone-white);
  background: rgba(255, 255, 255, 0.18);
}

.menu-item .el-icon {
  flex: 0 0 auto;
  font-size: 15px;
}

.header-spacer {
  flex: 1;
  min-width: 16px;
}

.header-action-button {
  width: 32px;
  height: 32px;
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--beone-white);
  cursor: pointer;
  transition: color 0.12s ease, background-color 0.12s ease;
}

.header-action-button:hover,
.header-action-button:focus {
  color: var(--beone-midnight-blue);
  background-color: var(--beone-white);
}

.header-action-button .el-icon {
  font-size: 16px;
}

.header-user {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  color: var(--beone-white);
  font-size: 13px;
  white-space: nowrap;
}

.header-user span {
  overflow: hidden;
  text-overflow: ellipsis;
}

@media (max-width: 640px) {
  .brand-title {
    display: none;
  }

  .menu-item span {
    display: none;
  }

  .menu-item {
    width: 32px;
    padding: 0;
    justify-content: center;
  }
}
</style>
