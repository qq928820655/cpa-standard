import { createRouter, createWebHistory } from 'vue-router'
import { authApi } from './api'

const routes = [
  {
    path: '/',
    redirect: '/dashboard',
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('./views/Login.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('./views/Register.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('./views/Dashboard.vue'),
  },
  {
    path: '/keys',
    name: 'KeyManage',
    component: () => import('./views/KeyManage.vue'),
    meta: { requiresAdmin: true },
  },
  {
    path: '/usage',
    name: 'UsageStats',
    component: () => import('./views/UsageStats.vue'),
  },
  {
    path: '/security-events',
    name: 'SecurityEvents',
    component: () => import('./views/SecurityEvents.vue'),
    meta: { requiresAdmin: true },
  },
  {
    path: '/runtime-logs',
    name: 'RuntimeLogs',
    component: () => import('./views/RuntimeLogs.vue'),
    meta: { requiresAdmin: true },
  },
  {
    path: '/models',
    name: 'ModelMarket',
    component: () => import('./views/ModelMarket.vue'),
  },
  {
    path: '/provider-model-mappings',
    name: 'ProviderModelMapping',
    component: () => import('./views/ProviderModelMapping.vue'),
    meta: { requiresAdmin: true },
  },
  {
    path: '/images',
    name: 'ImageSquare',
    component: () => import('./views/ImageSquare.vue'),
  },
  {
    path: '/openai-plus',
    name: 'OpenAIPlus',
    component: () => import('./views/OpenAIPlus.vue'),
    meta: { requiresAdmin: true },
  },
  {
    path: '/grok-pool',
    name: 'GrokPool',
    component: () => import('./views/GrokPool.vue'),
    meta: { requiresAdmin: true },
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('./views/Settings.vue'),
    meta: { requiresAdmin: true },
  },
  {
    path: '/users',
    name: 'UserManage',
    component: () => import('./views/UserManage.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior() {
    return { top: 0 }
  },
})

// 路由守卫：检查登录状态
router.beforeEach(async (to, from, next) => {
  // 登录页不需要认证
  if (to.meta.requiresAuth === false || to.path === '/login') {
    next()
    return
  }

  // 检查登录是否启用
  try {
    const status = await authApi.status()

    // 登录未启用，直接放行
    if (!status.login_enabled) {
      next()
      return
    }

    // 登录已启用，检查是否已登录
    if (authApi.isLoggedIn()) {
      // 管理页需要管理员角色，普通用户重定向到仪表盘
      if (to.meta.requiresAdmin && !authApi.isAdmin()) {
        next({ path: '/dashboard' })
        return
      }
      // 图片广场由管理员按用户授权，未授权时禁止手工访问路由
      if (to.path === '/images' && !authApi.isAdmin()) {
        try {
          const user = await authApi.getMe()
          if (!user.show_image_square) {
            next({ path: '/dashboard' })
            return
          }
        } catch {
          next({ path: '/dashboard' })
          return
        }
      }
      next()
      return
    }

    // 未登录，检查是否已初始化账户
    if (!status.initialized) {
      next({ path: '/login', query: { mode: 'setup' } })
    } else {
      next({ path: '/login' })
    }
  } catch {
    // 后端不可达时放行
    next()
  }
})

export default router
