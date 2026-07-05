<template>
  <div class="placeholder">
    <el-icon class="placeholder-icon"><Tools /></el-icon>
    <h2>{{ title }}</h2>
    <p>此页面尚在建设中。</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ menu: string }>()

const titles: Record<string, string> = {
  runs: '运行历史',
  ontology: '本体管理',
  resolvers: '源管理',
  llms: 'LLM 管理',
}

const title = computed(() => titles[props.menu] ?? props.menu)
</script>

<style scoped>
.placeholder {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--beone-text-secondary);
  gap: 6px;
}

.placeholder-icon {
  font-size: 44px;
  color: var(--beone-border-strong);
  margin-bottom: 8px;
}

.placeholder h2 {
  font-size: 18px;
  font-weight: 600;
  color: var(--beone-text-primary);
}
</style>
