import { createApp } from 'vue'
import * as Vue from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import './styles/theme.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'
import router from './router'
import { adminApi } from './api'
import { addPluginMenuItem } from './plugin-runtime'

const app = createApp(App)

// 注册所有图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(ElementPlus)
app.use(router)

window.CpaPluginRuntime = { adminApi }
window.Vue = Vue
window.ElementPlus = ElementPlus
window.ElementPlusIconsVue = ElementPlusIconsVue

const loadPluginScript = (url) => new Promise((resolve, reject) => {
  if (document.querySelector(`script[data-cpa-plugin-url="${url}"]`)) return resolve()
  const script = document.createElement('script')
  script.src = url
  script.async = true
  script.dataset.cpaPluginUrl = url
  script.onload = resolve
  script.onerror = () => reject(new Error('插件前端资源加载失败'))
  document.head.appendChild(script)
})

const loadPluginStylesheet = (url) => {
  if (!url || document.querySelector(`link[data-cpa-plugin-url="${url}"]`)) return
  const link = document.createElement('link')
  link.rel = 'stylesheet'
  link.href = url
  link.dataset.cpaPluginUrl = url
  document.head.appendChild(link)
}

const loadFrontendPlugins = async () => {
  try {
    const data = await adminApi.listPlugins()
    for (const plugin of data.frontend || []) {
      loadPluginStylesheet(plugin.css_url)
      await loadPluginScript(plugin.entry_url)
      window.CpaPluginModules?.[plugin.id]?.register({ router, addMenuItem: addPluginMenuItem })
    }
  } catch (error) {
    console.warn('CPA plugin frontend loading skipped:', error)
  }
}

const bootstrap = async () => {
  await loadFrontendPlugins()
  app.mount('#app')
}

bootstrap()
