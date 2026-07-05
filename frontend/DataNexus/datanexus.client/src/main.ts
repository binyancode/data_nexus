import './assets/main.css'
import 'element-plus/dist/index.css'

import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'

const app = createApp(App)

// 全局注册 Element Plus 图标（FrameHeader 用字符串名引用 <component :is="icon" />）
for (const [name, comp] of Object.entries(ElementPlusIconsVue)) {
  app.component(name, comp)
}

app.use(ElementPlus)
app.mount('#app')
