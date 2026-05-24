<template>
  <el-config-provider :locale="zhCn">
    <el-container class="app-shell">
      <el-aside width="220px" class="sidebar-shell">
        <div class="sidebar-panel">
          <div class="logo-block">
            <div class="logo-mark">CPA</div>
          </div>

          <el-menu
            :default-active="currentRoute"
            router
            class="app-menu"
          >
            <el-menu-item index="/dashboard">
              <el-icon><DataAnalysis /></el-icon>
              <span>仪表盘</span>
            </el-menu-item>
            <el-menu-item v-if="showKeyManage" index="/keys">
              <el-icon><Key /></el-icon>
              <span>Key 管理</span>
            </el-menu-item>
            <el-menu-item index="/usage">
              <el-icon><TrendCharts /></el-icon>
              <span>用量统计</span>
            </el-menu-item>
            <el-menu-item index="/models">
              <el-icon><Grid /></el-icon>
              <span>模型广场</span>
            </el-menu-item>
            <el-menu-item index="/provider-model-mappings">
              <el-icon><Connection /></el-icon>
              <span>模型映射</span>
            </el-menu-item>
            <el-menu-item index="/images">
              <el-icon><Picture /></el-icon>
              <span>光影世界</span>
            </el-menu-item>
            <el-menu-item v-if="showUserManage" index="/users">
              <el-icon><User /></el-icon>
              <span>用户管理</span>
            </el-menu-item>
            <el-menu-item v-if="showSettings" index="/security-events">
              <el-icon><Warning /></el-icon>
              <span>安全事件</span>
            </el-menu-item>
            <el-menu-item v-if="showSettings" index="/settings">
              <el-icon><Setting /></el-icon>
              <span>系统设置</span>
            </el-menu-item>
          </el-menu>

          <div class="theme-switcher">
            <div class="theme-switcher__options">
              <button
                v-for="theme in themeOptions"
                :key="theme.value"
                type="button"
                class="theme-option"
                :class="{ 'is-active': currentTheme === theme.value }"
                :aria-label="theme.label"
                :title="theme.label"
                @click="selectTheme(theme.value)"
              >
                <span class="theme-option__swatch" :style="{ background: theme.preview }"></span>
              </button>
            </div>
          </div>

          <div v-if="loginEnabled && isLoggedIn" class="logout-row sidebar-logout-row">
            <span class="logout-user">{{ username }}</span>
            <button type="button" class="logout-btn" @click="handleLogout">退出</button>
          </div>
        </div>
      </el-aside>

      <el-main class="main-shell">
        <div class="main-panel">
          <router-view v-slot="{ Component }">
            <keep-alive>
              <component :is="Component" />
            </keep-alive>
          </router-view>
        </div>
      </el-main>
    </el-container>
  </el-config-provider>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import { authApi } from './api'
import { Connection, User, Warning } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const sessionVersion = ref(0)
const isLoggedIn = computed(() => {
  sessionVersion.value  // 触发响应式依赖
  return authApi.isLoggedIn()
})
const username = computed(() => {
  sessionVersion.value  // 触发响应式依赖
  return authApi.getCurrentUsername()
})
const loginEnabled = ref(false)
const userRole = ref('')

const showKeyManage = computed(() => {
  if (!loginEnabled.value) return true
  return userRole.value === 'admin'
})

const showUserManage = computed(() => {
  return loginEnabled.value && !!userRole.value
})

const showSettings = computed(() => {
  if (!loginEnabled.value) return true
  return userRole.value === 'admin'
})

// 检查登录是否启用
const checkLoginConfig = async () => {
  try {
    const res = await authApi.getConfig()
    loginEnabled.value = !!res.login_enabled
    userRole.value = loginEnabled.value ? authApi.getCurrentRole() : ''
    sessionVersion.value++
  } catch {
    loginEnabled.value = false
    userRole.value = ''
    sessionVersion.value++
  }
}

// 监听路由变化，刷新登录配置（从设置页回来时）
watch(() => route.path, () => {
  checkLoginConfig()
})

const handleLogout = () => {
  authApi.logout()
  userRole.value = ''
  sessionVersion.value++
  router.push('/login')
}

const THEME_STORAGE_KEY = 'cpaTheme'
const DEFAULT_THEME = 'ocean-blue'
const themeOptions = [
  { value: 'ocean-blue', label: '海之蓝', preview: 'linear-gradient(135deg, #2563eb, #06b6d4)' },
  { value: 'sakura-pink', label: '樱花粉', preview: 'linear-gradient(135deg, #ec4899, #fb7185)' },
  { value: 'lavender-purple', label: '薰衣草紫', preview: 'linear-gradient(135deg, #8b5cf6, #c084fc)' },
]

const currentRoute = computed(() => route.path)
const currentTheme = ref(DEFAULT_THEME)

const applyTheme = (theme) => {
  const resolvedTheme = themeOptions.some((item) => item.value === theme) ? theme : DEFAULT_THEME
  document.documentElement.setAttribute('data-theme', resolvedTheme)
  currentTheme.value = resolvedTheme
}

const selectTheme = (theme) => {
  applyTheme(theme)
  localStorage.setItem(THEME_STORAGE_KEY, currentTheme.value)
}

onMounted(() => {
  applyTheme(localStorage.getItem(THEME_STORAGE_KEY) || DEFAULT_THEME)
  checkLoginConfig()
})

watch(currentTheme, (value) => {
  document.documentElement.setAttribute('data-theme', value)
})
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body, #app {
  min-height: 100%;
}

.app-shell {
  min-height: 100vh;
  min-width: 0;
  max-width: 100vw;
  overflow-x: hidden;
  background: transparent;
}

.sidebar-shell {
  width: 220px;
  padding: 10px 0 10px 14px;
  background: transparent;
  position: fixed;
  left: 0;
  top: 0;
  bottom: 0;
  z-index: 100;
}

.sidebar-panel {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 20px);
  padding: 14px 14px 12px;
  border: 1px solid var(--cpa-sidebar-border);
  border-radius: 24px;
  background: var(--cpa-sidebar-bg);
  box-shadow: var(--cpa-sidebar-shadow);
  backdrop-filter: blur(16px);
  overflow: hidden;
}

.logo-block {
  display: flex;
  align-items: center;
  width: 100%;
  padding: 0 0 12px;
}

.logo-mark {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 58px;
  border-radius: 18px;
  background: var(--cpa-brand-gradient);
  color: #fff;
  font-size: 30px;
  font-weight: 800;
  letter-spacing: 0.02em;
  box-shadow: var(--cpa-brand-shadow);
}

.nav-caption {
  display: none;
}

.app-menu {
  flex: 1;
  border-right: none;
  background: transparent;
}

.app-menu .el-menu-item {
  height: 44px;
  margin-bottom: 6px;
  border-radius: 14px;
  color: var(--cpa-menu-text);
  font-weight: 600;
}

.app-menu .el-menu-item .el-icon {
  font-size: 18px;
}

.app-menu .el-menu-item:hover {
  background: var(--cpa-menu-hover-bg);
  color: var(--cpa-menu-hover-text);
}

.app-menu .el-menu-item.is-active {
  background: var(--cpa-menu-active-bg);
  color: var(--cpa-menu-active-text);
}

.theme-switcher {
  margin-top: 4px;
  margin-bottom: 0;
  padding: 10px;
  border: 1px solid var(--cpa-panel-border-soft);
  border-radius: 18px;
  background: var(--cpa-theme-panel-bg);
}

.theme-switcher__options {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.theme-option {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  padding: 8px 0;
  border: 1px solid var(--cpa-theme-option-border);
  border-radius: 14px;
  background: var(--cpa-theme-option-bg);
  cursor: pointer;
  transition: all 0.2s ease;
}

.theme-option:hover {
  border-color: var(--cpa-theme-option-hover-border);
  transform: translateY(-1px);
}

.theme-option.is-active {
  border-color: var(--cpa-theme-option-active-border);
  background: var(--cpa-theme-option-active-bg);
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.12);
}

.theme-option__swatch {
  width: 18px;
  height: 18px;
  border-radius: 999px;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.45);
  flex-shrink: 0;
}

.sidebar-footer {
  padding: 14px;
  border: 1px solid var(--cpa-panel-border-soft);
  border-radius: 18px;
  background: var(--cpa-footer-bg);
}

.footer-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 96px;
  padding: 6px 10px;
  border-radius: 999px;
  background: var(--cpa-chip-bg);
  color: var(--cpa-chip-text);
  font-size: 12px;
  font-weight: 700;
}

.sidebar-footer p {
  margin-top: 10px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--cpa-text-secondary);
}

.logout-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--cpa-panel-border-soft);
}

.logout-user {
  font-size: 12px;
  font-weight: 600;
  color: var(--cpa-text-secondary);
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.logout-btn {
  font-size: 12px;
  color: var(--cpa-danger);
  background: none;
  border: 1px solid var(--cpa-border);
  border-radius: 8px;
  padding: 3px 10px;
  cursor: pointer;
  transition: all 0.2s;
}

.logout-btn:hover {
  background: rgba(239, 68, 68, 0.08);
  border-color: var(--cpa-danger);
}

.main-shell {
  min-width: 0;
  max-width: calc(100vw - 220px);
  margin-left: 220px;
  padding: 16px 16px 16px 10px;
  overflow-x: hidden;
  overflow-y: visible;
  background: transparent;
}

.main-panel {
  min-height: calc(100vh - 32px);
  min-width: 0;
  max-width: 100%;
  padding: 20px;
  border: 1px solid var(--cpa-main-panel-border);
  border-radius: 24px;
  background: var(--cpa-main-panel-bg);
  box-shadow: inset 0 1px 0 var(--cpa-main-panel-highlight);
  overflow-x: hidden;
  overflow-y: visible;
}

@media (max-width: 1080px) {
  .app-shell {
    flex-direction: column;
  }

  .sidebar-shell {
    width: 100% !important;
    padding: 20px 20px 0;
    position: static;
  }

  .sidebar-panel {
    height: auto;
  }

  .main-shell {
    max-width: 100vw;
    margin-left: 0;
    padding: 16px 20px 20px;
  }

  .main-panel {
    height: auto;
    min-height: calc(100vh - 220px);
  }
}
</style>

