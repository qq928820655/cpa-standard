<template>
  <el-config-provider :locale="zhCn">
    <el-container class="app-shell" :class="{ 'is-mobile-shell': isMobile }">
      <el-aside v-if="!isMobile" width="220px" class="sidebar-shell">
        <div class="sidebar-panel">
          <div class="logo-block">
            <div class="logo-mark" @click="toggleMenuMode">CPA</div>
          </div>

          <el-menu
            :default-active="currentRoute"
            router
            class="app-menu"
          >
            <template v-if="menuMode === 'main'">
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
              <el-menu-item v-if="showSettings" index="/provider-model-mappings">
                <el-icon><Connection /></el-icon>
                <span>模型映射</span>
              </el-menu-item>
              <el-menu-item v-if="showImageSquare" index="/images">
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
              <el-menu-item v-if="showRuntimeLogs" index="/runtime-logs">
                <el-icon><Document /></el-icon>
                <span>运行日志</span>
              </el-menu-item>
              <el-menu-item v-if="showSettings" index="/settings">
                <el-icon><Setting /></el-icon>
                <span>系统设置</span>
              </el-menu-item>
            </template>
            <template v-else>
              <el-menu-item v-if="showSettings" index="/openai-plus">
                <el-icon><Link /></el-icon>
                <span>OpenAI</span>
              </el-menu-item>
              <el-menu-item v-if="showSettings" index="/grok-pool">
                <el-icon><Connection /></el-icon>
                <span>Grok</span>
              </el-menu-item>
            </template>
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
        <div v-if="isMobile" class="mobile-topbar">
          <div class="mobile-topbar__brand" @click="toggleMenuMode">CPA</div>
          <div class="mobile-topbar__title">{{ currentNavLabel }}</div>
          <div class="mobile-topbar__spacer"></div>
          <button
            type="button"
            class="mobile-topbar__more"
            aria-label="打开菜单"
            @click="mobileDrawerVisible = true"
          >
            <el-icon><Operation /></el-icon>
          </button>
        </div>

        <div class="main-panel">
          <router-view v-slot="{ Component }">
            <keep-alive>
              <component :is="Component" :key="`${route.fullPath}:${sessionVersion}`" />
            </keep-alive>
          </router-view>
        </div>
      </el-main>

      <nav v-if="isMobile" class="mobile-tabbar" aria-label="主导航">
        <button
          v-for="item in mobileTabItems"
          :key="item.path"
          type="button"
          class="mobile-tab"
          :class="{ 'is-active': currentRoute === item.path }"
          @click="goMobileRoute(item.path)"
        >
          <el-icon class="mobile-tab__icon"><component :is="item.icon" /></el-icon>
          <span class="mobile-tab__label">{{ item.label }}</span>
        </button>
        <button
          type="button"
          class="mobile-tab"
          :class="{ 'is-active': isDrawerRouteActive }"
          @click="mobileDrawerVisible = true"
        >
          <el-icon class="mobile-tab__icon"><Operation /></el-icon>
          <span class="mobile-tab__label">更多</span>
        </button>
      </nav>

      <el-drawer
        v-if="isMobile"
        v-model="mobileDrawerVisible"
        direction="rtl"
        size="78%"
        :with-header="false"
        class="mobile-nav-drawer"
      >
        <div class="mobile-drawer-body">
          <div class="mobile-drawer__head">
            <div class="mobile-drawer__logo" @click="toggleMenuMode">CPA</div>
            <div class="mobile-drawer__mode">{{ menuMode === 'main' ? '主菜单' : 'OpenAI 菜单' }}</div>
          </div>

          <div class="mobile-drawer__list">
            <button
              v-for="item in mobileDrawerItems"
              :key="item.path"
              type="button"
              class="mobile-drawer__item"
              :class="{ 'is-active': currentRoute === item.path }"
              @click="goMobileRoute(item.path)"
            >
              <el-icon><component :is="item.icon" /></el-icon>
              <span>{{ item.label }}</span>
            </button>
          </div>

          <div class="mobile-drawer__footer">
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

            <div v-if="loginEnabled && isLoggedIn" class="logout-row">
              <span class="logout-user">{{ username }}</span>
              <button type="button" class="logout-btn" @click="handleLogout">退出</button>
            </div>
          </div>
        </div>
      </el-drawer>
    </el-container>
  </el-config-provider>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import { adminApi, authApi } from './api'
import { Connection, Document, User, Warning, Link, Operation } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()

// 手机竖屏改用底部标签栏 + 抽屉导航，桌面端继续走左侧栏
const MOBILE_NAV_QUERY = '(max-width: 768px)'
const isMobile = ref(false)
const mobileDrawerVisible = ref(false)
let navMediaQuery = null
const syncMobileNav = (event) => {
  isMobile.value = event.matches
  if (!event.matches) mobileDrawerVisible.value = false
}
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
const showImageSquare = ref(false)
const menuMode = ref('main')
const lastMainRoute = ref('/dashboard')
const lastOpenAIRoute = ref('/openai-plus')

const isOpenAIRoute = (path) => path === '/openai-plus'

const toggleMenuMode = () => {
  if (menuMode.value === 'main') {
    if (!isOpenAIRoute(route.path)) {
      lastMainRoute.value = route.path || lastMainRoute.value
    }
    menuMode.value = 'openai'
    return
  }
  if (isOpenAIRoute(route.path)) {
    lastOpenAIRoute.value = route.path || lastOpenAIRoute.value
  }
  menuMode.value = 'main'
}

const showKeyManage = computed(() => {
  if (!loginEnabled.value) return true
  return userRole.value === 'admin'
})

const showUserManage = computed(() => loginEnabled.value && isLoggedIn.value)

const showSettings = computed(() => {
  if (!loginEnabled.value) return true
  return userRole.value === 'admin'
})

const runtimeLogEnabled = ref(false)
const showRuntimeLogs = computed(() => showSettings.value && runtimeLogEnabled.value)

const loadRuntimeLogConfig = async () => {
  if (!showSettings.value) {
    runtimeLogEnabled.value = false
    return
  }
  try {
    const data = await adminApi.getRuntimeLogConfig()
    runtimeLogEnabled.value = !!data.enabled
  } catch {
    runtimeLogEnabled.value = false
  }
}

const handleRuntimeLogConfigChanged = (event) => {
  runtimeLogEnabled.value = !!event.detail?.enabled
}

const handleSessionChanged = () => {
  sessionVersion.value++
  checkLoginConfig()
}

// 主菜单项集中描述，供桌面侧栏之外的移动端底部栏与抽屉复用
const mainNavItems = computed(() => [
  { path: '/dashboard', label: '仪表盘', icon: 'DataAnalysis', visible: true },
  { path: '/keys', label: 'Key 管理', icon: 'Key', visible: showKeyManage.value },
  { path: '/usage', label: '用量统计', icon: 'TrendCharts', visible: true },
  { path: '/images', label: '光影世界', icon: 'Picture', visible: showImageSquare.value },
  { path: '/models', label: '模型广场', icon: 'Grid', visible: true },
  { path: '/provider-model-mappings', label: '模型映射', icon: 'Connection', visible: showSettings.value },
  { path: '/users', label: '用户管理', icon: 'User', visible: showUserManage.value },
  { path: '/security-events', label: '安全事件', icon: 'Warning', visible: showSettings.value },
  { path: '/runtime-logs', label: '运行日志', icon: 'Document', visible: showRuntimeLogs.value },
  { path: '/settings', label: '系统设置', icon: 'Setting', visible: showSettings.value },
].filter((item) => item.visible))

// 底部标签栏只放高频入口，其余进抽屉，避免小屏图标挤在一起划不准
const MOBILE_TAB_PATHS = ['/dashboard', '/keys', '/usage', '/images']

const mobileTabItems = computed(() => {
  const items = mainNavItems.value.filter((item) => MOBILE_TAB_PATHS.includes(item.path))
  return items.sort((a, b) => MOBILE_TAB_PATHS.indexOf(a.path) - MOBILE_TAB_PATHS.indexOf(b.path))
})

const mobileDrawerItems = computed(() => {
  if (menuMode.value === 'openai') return openaiNavItems.value
  return mainNavItems.value.filter((item) => !MOBILE_TAB_PATHS.includes(item.path))
})

const openaiNavItems = computed(() => [
  { path: '/openai-plus', label: 'OpenAI', icon: 'Link', visible: showSettings.value },
  { path: '/grok-pool', label: 'Grok', icon: 'Connection', visible: showSettings.value },
].filter((item) => item.visible))

// 抽屉里已经展开了完整菜单，标签栏的“更多”只负责开合
const isDrawerRouteActive = computed(() => mobileDrawerItems.value.some((item) => item.path === route.path))

const goMobileRoute = (path) => {
  mobileDrawerVisible.value = false
  if (route.path !== path) router.push(path)
}

// 移动端顶栏显示当前页名称，替代被隐藏的侧栏标识
const currentNavLabel = computed(() => {
  const all = [...mainNavItems.value, ...openaiNavItems.value]
  return all.find((item) => item.path === route.path)?.label || 'CPA'
})

// 检查登录是否启用
const checkLoginConfig = async () => {
  try {
    const res = await authApi.getConfig()
    loginEnabled.value = !!res.login_enabled
    userRole.value = loginEnabled.value ? authApi.getCurrentRole() : ''
    showImageSquare.value = !loginEnabled.value || userRole.value === 'admin'
    if (loginEnabled.value && authApi.isLoggedIn() && userRole.value !== 'admin') {
      const user = await authApi.getMe()
      showImageSquare.value = !!user.show_image_square
    }
    sessionVersion.value++
  } catch {
    loginEnabled.value = false
    userRole.value = ''
    showImageSquare.value = true
    sessionVersion.value++
  }
}

// 监听路由变化，刷新登录配置（从设置页回来时）
watch(() => route.path, (path) => {
  if (isOpenAIRoute(path)) {
    lastOpenAIRoute.value = path
    menuMode.value = 'openai'
  } else if (path !== '/login' && path !== '/register') {
    lastMainRoute.value = path
    menuMode.value = 'main'
  }
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
  checkLoginConfig().then(loadRuntimeLogConfig)
  window.addEventListener('runtime-log-config-changed', handleRuntimeLogConfigChanged)
  window.addEventListener('session-changed', handleSessionChanged)
  if (typeof window !== 'undefined' && window.matchMedia) {
    navMediaQuery = window.matchMedia(MOBILE_NAV_QUERY)
    isMobile.value = navMediaQuery.matches
    if (navMediaQuery.addEventListener) navMediaQuery.addEventListener('change', syncMobileNav)
    else navMediaQuery.addListener(syncMobileNav)
  }
})

onUnmounted(() => {
  window.removeEventListener('runtime-log-config-changed', handleRuntimeLogConfigChanged)
  window.removeEventListener('session-changed', handleSessionChanged)
  if (!navMediaQuery) return
  if (navMediaQuery.removeEventListener) navMediaQuery.removeEventListener('change', syncMobileNav)
  else navMediaQuery.removeListener(syncMobileNav)
  navMediaQuery = null
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
  cursor: pointer;
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
    padding: 10px 12px 0;
    position: static;
    height: auto;
  }

  .sidebar-panel {
    flex-direction: row;
    align-items: center;
    gap: 10px;
    height: auto;
    padding: 8px 10px;
    border-radius: 18px;
    overflow: hidden;
  }

  .logo-block {
    width: auto;
    padding: 0;
    flex-shrink: 0;
  }

  .logo-mark {
    width: 46px;
    height: 46px;
    border-radius: 14px;
    font-size: 20px;
  }

  /* 菜单改为横向可滚动的紧凑菜单条，避免竖排铺满整屏 */
  .app-menu {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-wrap: nowrap;
    overflow-x: auto;
    overflow-y: hidden;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
  }

  .app-menu::-webkit-scrollbar {
    display: none;
  }

  .app-menu .el-menu-item {
    flex: 0 0 auto;
    height: 40px;
    margin-bottom: 0;
    padding: 0 12px;
  }

  /* 横向菜单条下隐藏文字，仅留图标，节省空间 */
  .app-menu .el-menu-item span {
    display: none;
  }

  .app-menu .el-menu-item .el-icon {
    margin-right: 0;
  }

  .theme-switcher {
    flex-shrink: 0;
    margin: 0;
    padding: 6px 8px;
    border-radius: 14px;
  }

  .theme-switcher__options {
    gap: 6px;
  }

  .theme-option {
    padding: 5px 0;
  }

  .sidebar-logout-row {
    flex-shrink: 0;
    margin-top: 0;
    padding-top: 0;
    border-top: none;
  }

  .main-shell {
    max-width: 100vw;
    margin-left: 0;
    padding: 12px;
  }

  .main-panel {
    height: auto;
    min-height: calc(100vh - 96px);
    padding: 14px;
    border-radius: 18px;
  }
}

/* 手机竖屏：菜单条进一步压缩，主题切换器可换行到菜单下方 */
@media (max-width: 640px) {
  .sidebar-panel {
    flex-wrap: wrap;
    gap: 8px;
  }

  .app-menu {
    order: 2;
    width: 100%;
    flex: 1 1 100%;
  }

  .logo-block {
    order: 1;
  }

  .theme-switcher {
    order: 1;
    margin-left: auto;
  }

  .sidebar-logout-row {
    order: 1;
  }

  .main-shell {
    padding: 8px;
  }

  .main-panel {
    padding: 12px;
    border-radius: 16px;
  }
}

/* 手机竖屏导航：顶部标题栏 + 底部标签栏 + 右侧抽屉，
   整块只在 768px 以下渲染，桌面端不加载这些节点。 */
.mobile-topbar,
.mobile-tabbar {
  display: none;
}

@media (max-width: 768px) {
  .app-shell.is-mobile-shell {
    flex-direction: column;
    padding-bottom: calc(58px + env(safe-area-inset-bottom, 0px));
  }

  .is-mobile-shell .main-shell {
    max-width: 100vw;
    margin-left: 0;
    padding: 0 10px 10px;
  }

  .mobile-topbar {
    display: flex;
    align-items: center;
    gap: 10px;
    position: sticky;
    top: 0;
    z-index: 90;
    margin: 0 -10px 8px;
    padding: 8px 12px;
    background: var(--cpa-sidebar-bg);
    border-bottom: 1px solid var(--cpa-sidebar-border);
    backdrop-filter: blur(16px);
  }

  .mobile-topbar__brand {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 40px;
    height: 34px;
    border-radius: 11px;
    background: var(--cpa-brand-gradient);
    color: #fff;
    font-size: 15px;
    font-weight: 800;
    flex-shrink: 0;
    cursor: pointer;
  }

  .mobile-topbar__title {
    font-size: 16px;
    font-weight: 700;
    color: var(--cpa-text-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .mobile-topbar__spacer {
    flex: 1;
    min-width: 0;
  }

  .mobile-topbar__more {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 34px;
    border: 1px solid var(--cpa-panel-border-soft);
    border-radius: 11px;
    background: var(--cpa-theme-option-bg);
    color: var(--cpa-menu-text);
    font-size: 17px;
    flex-shrink: 0;
    cursor: pointer;
  }

  .is-mobile-shell .main-panel {
    min-height: calc(100vh - 130px);
    padding: 12px;
    border-radius: 16px;
  }

  .mobile-tabbar {
    display: flex;
    align-items: stretch;
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 200;
    padding: 4px 4px calc(4px + env(safe-area-inset-bottom, 0px));
    border-top: 1px solid var(--cpa-sidebar-border);
    background: var(--cpa-sidebar-bg);
    backdrop-filter: blur(16px);
  }

  .mobile-tab {
    display: flex;
    flex: 1 1 0;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 2px;
    min-width: 0;
    padding: 6px 2px;
    border: none;
    border-radius: 12px;
    background: none;
    color: var(--cpa-text-secondary);
    cursor: pointer;
  }

  .mobile-tab.is-active {
    background: var(--cpa-menu-active-bg);
    color: var(--cpa-menu-active-text);
  }

  .mobile-tab__icon {
    font-size: 19px;
  }

  .mobile-tab__label {
    font-size: 11px;
    font-weight: 600;
    line-height: 1.2;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 100%;
  }

  .mobile-nav-drawer .el-drawer__body {
    padding: 0;
  }

  .mobile-drawer-body {
    display: flex;
    flex-direction: column;
    height: 100%;
    padding: 14px 14px calc(14px + env(safe-area-inset-bottom, 0px));
    background: var(--cpa-sidebar-bg);
  }

  .mobile-drawer__head {
    display: flex;
    align-items: center;
    gap: 10px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--cpa-panel-border-soft);
  }

  .mobile-drawer__logo {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 46px;
    height: 40px;
    border-radius: 13px;
    background: var(--cpa-brand-gradient);
    color: #fff;
    font-size: 17px;
    font-weight: 800;
    flex-shrink: 0;
    cursor: pointer;
  }

  .mobile-drawer__mode {
    font-size: 13px;
    font-weight: 600;
    color: var(--cpa-text-secondary);
  }

  .mobile-drawer__list {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin-top: 12px;
    overflow-y: auto;
  }

  .mobile-drawer__item {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    padding: 12px 12px;
    border: 1px solid transparent;
    border-radius: 14px;
    background: var(--cpa-theme-option-bg);
    color: var(--cpa-menu-text);
    font-size: 14px;
    font-weight: 600;
    text-align: left;
    cursor: pointer;
  }

  .mobile-drawer__item .el-icon {
    font-size: 18px;
  }

  .mobile-drawer__item.is-active {
    border-color: var(--cpa-theme-option-active-border);
    background: var(--cpa-menu-active-bg);
    color: var(--cpa-menu-active-text);
  }

  .mobile-drawer__footer {
    margin-top: 12px;
  }

  .mobile-drawer__footer .theme-switcher {
    margin: 0;
  }
}
</style>

