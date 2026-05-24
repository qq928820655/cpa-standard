import axios from 'axios'

const MASTER_KEY_STORAGE_KEY = 'masterKey'
const SESSION_TOKEN_KEY = 'sessionToken'
const SESSION_USERNAME_KEY = 'sessionUsername'
const SESSION_ROLE_KEY = 'sessionRole'
const SESSION_API_KEY_KEY = 'sessionApiKey'
const CHECK_REQUEST_TIMEOUT = 65000
const IMAGE_REQUEST_TIMEOUT = 360000

const getMasterKey = () => localStorage.getItem(MASTER_KEY_STORAGE_KEY) || ''
const setMasterKey = (value) => localStorage.setItem(MASTER_KEY_STORAGE_KEY, value)
const clearMasterKey = () => localStorage.removeItem(MASTER_KEY_STORAGE_KEY)

const getSessionToken = () => localStorage.getItem(SESSION_TOKEN_KEY) || ''
const setSessionToken = (value) => localStorage.setItem(SESSION_TOKEN_KEY, value)
const clearSessionToken = () => {
  localStorage.removeItem(SESSION_TOKEN_KEY)
  localStorage.removeItem(SESSION_USERNAME_KEY)
  localStorage.removeItem(SESSION_ROLE_KEY)
  localStorage.removeItem(SESSION_API_KEY_KEY)
}

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

const rawApi = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

let masterKeyRequest = null

const ensureMasterKey = async (forceRefresh = false) => {
  const cachedMasterKey = getMasterKey()
  if (cachedMasterKey && !forceRefresh) {
    return cachedMasterKey
  }

  if (forceRefresh) {
    clearMasterKey()
  }

  if (!masterKeyRequest) {
    masterKeyRequest = rawApi.get('/admin/master-key')
      .then((response) => {
        const fetchedMasterKey = response.data?.master_key || ''
        if (fetchedMasterKey) {
          setMasterKey(fetchedMasterKey)
        }
        return fetchedMasterKey
      })
      .finally(() => {
        masterKeyRequest = null
      })
  }

  return masterKeyRequest
}

const serializeParams = (params = {}) => {
  const searchParams = new URLSearchParams()

  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    if (Array.isArray(value)) {
      value.forEach((item) => {
        if (item !== undefined && item !== null && item !== '') {
          searchParams.append(key, item)
        }
      })
      return
    }
    searchParams.append(key, value)
  })

  return searchParams.toString()
}

api.interceptors.request.use(
  async (config) => {
    // 优先使用 session token（登录凭证）
    const sessionToken = getSessionToken()
    if (sessionToken) {
      config.headers = config.headers || {}
      config.headers.Authorization = `Bearer ${sessionToken}`
      return config
    }

    // 回退到 master key（兼容旧模式 / API 代理调用）
    let masterKey = getMasterKey()

    if (!masterKey && config.url !== '/admin/master-key') {
      masterKey = await ensureMasterKey()
    }

    if (masterKey) {
      config.headers = config.headers || {}
      config.headers.Authorization = `Bearer ${masterKey}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

api.interceptors.response.use(
  (response) => {
    if (response.config?.responseType === 'blob') {
      return response.data
    }
    return response.data
  },
  async (error) => {
    const originalRequest = error.config || {}
    const status = error.response?.status
    const requestUrl = originalRequest.url || ''

    // 如果是 session token 认证失败（403 也视为凭证无效）
    if ((status === 401 || status === 403) && getSessionToken() && !originalRequest._retriedWithFreshSession) {
      // session token 无效，清除并跳转登录
      clearSessionToken()
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
      const message = error.response?.data?.detail || '登录已过期，请重新登录'
      return Promise.reject(new Error(message))
    }

    // 旧模式：master key 401 自动重试
    if (status === 401 && requestUrl !== '/admin/master-key' && !originalRequest._retriedWithFreshMasterKey) {
      originalRequest._retriedWithFreshMasterKey = true
      try {
        const refreshedMasterKey = await ensureMasterKey(true)
        if (refreshedMasterKey) {
          originalRequest.headers = originalRequest.headers || {}
          originalRequest.headers.Authorization = `Bearer ${refreshedMasterKey}`
          return api(originalRequest)
        }
      } catch (_) {
        clearMasterKey()
      }
    }

    if (status === 401) {
      clearMasterKey()
    }

    const rawDetail = error.response?.data?.detail
    let message
    if (Array.isArray(rawDetail)) {
      // FastAPI 422 validation error：detail 是数组
      message = rawDetail.map((e) => e.msg || JSON.stringify(e)).join('; ')
    } else {
      message = rawDetail || error.message || '请求失败'
    }
    return Promise.reject(new Error(message))
  }
)

export const adminApi = {
  getMasterKey: () => api.get('/admin/master-key'),

  getKeyProviders: () => api.get('/admin/providers'),
  getModelProviders: () => api.get('/admin/model-providers'),
  listKeys: (params) => api.get('/admin/keys', { params, paramsSerializer: { serialize: serializeParams } }),
  exportKeys: () => api.get('/admin/keys/export'),
  createKey: (data) => api.post('/admin/keys', data),
  importKeys: (items) => api.post('/admin/keys/import', { items }),
  batchUpdateKeyModels: (data) => api.post('/admin/keys/batch/models', data),
  batchSetKeysFakeIp: (data) => api.post('/admin/keys/batch/fake-ip', data),
  batchCheckKeyEndpoints: (data) => api.post('/admin/keys/batch/check', data),
  checkKey: (id, data) => api.post(`/admin/keys/${id}/check`, data, { timeout: CHECK_REQUEST_TIMEOUT }),
  batchDeleteKeys: (data) => api.post('/admin/keys/batch/delete', data),
  createKeyCheckTask: (data) => api.post('/admin/key-check/tasks', data),
  listKeyCheckTasks: (params) => api.get('/admin/key-check/tasks', { params }),
  getKeyCheckTask: (id) => api.get(`/admin/key-check/tasks/${id}`),
  listKeyCheckTaskResults: (id, params) => api.get(`/admin/key-check/tasks/${id}/results`, { params }),
  getKeyCheckTaskStats: (id) => api.get(`/admin/key-check/tasks/${id}/stats`),
  batchSetKeysActive: (data) => api.post('/admin/keys/batch/active', data),
  batchClearKeysCooldown: (data) => api.post('/admin/keys/batch/cooldown/clear', data),
  getKey: (id) => api.get(`/admin/keys/${id}`),
  updateKey: (id, data) => api.put(`/admin/keys/${id}`, data),
  deleteKey: (id) => api.delete(`/admin/keys/${id}`),
  toggleKey: (id) => api.post(`/admin/keys/${id}/toggle`),
  clearKeyCooldown: (id) => api.post(`/admin/keys/${id}/cooldown/clear`),
  getKeyCooldownConfig: () => api.get('/admin/key-cooldown-config'),
  updateKeyCooldownConfig: (data) => api.put('/admin/key-cooldown-config', data),
  getProxyTimeoutConfig: () => api.get('/admin/proxy-timeout-config'),
  updateProxyTimeoutConfig: (data) => api.put('/admin/proxy-timeout-config', data),
  getContentGuardConfig: () => api.get('/admin/content-guard-config'),
  updateContentGuardConfig: (data) => api.put('/admin/content-guard-config', data),
  listContentGuardEvents: (params) => api.get('/admin/content-guard-events', { params }),
  getKeyCheckDefaultConfig: () => api.get('/admin/key-check-default-config'),
  updateKeyCheckDefaultConfig: (data) => api.put('/admin/key-check-default-config', data),
  getKeyCheckShortcutModels: () => api.get('/admin/key-check-shortcut-models'),
  updateKeyCheckShortcutModels: (data) => api.put('/admin/key-check-shortcut-models', data),
  getKeyById: (id) => api.get(`/admin/keys/${id}`),
  getKeyUsageDetail: (id, params) => api.get('/stats/by-key', { params: { api_key_id: id, ...(params || {}) } }),
  getKeyUsageLogs: (id, params) => api.get('/stats/logs', { params: { api_key_id: id, ...(params || {}) } }),
  getKeyUsageSummary: (id, params) => api.get('/stats/summary', { params: { api_key_id: id, ...(params || {}) } }),
  getDashboardKeyUsage: (params) => api.get('/stats/by-key', { params, paramsSerializer: { serialize: serializeParams } }),
  listProviderModelPriorities: (provider) => api.get('/admin/provider-model-priorities', { params: { provider } }),
  listProviderModelPriorityKeyOptions: (provider) => api.get('/admin/provider-model-priority-key-options', { params: { provider } }),
  saveProviderModelPriority: (data) => api.put('/admin/provider-model-priorities', data),
  clearProviderModelPriority: (data) => api.delete('/admin/provider-model-priorities', { data }),
  listProviderModelMappings: (params) => api.get('/admin/provider-model-mappings', { params }),
  exportProviderModelMappings: () => api.get('/admin/provider-model-mappings/export'),
  importProviderModelMappings: (items) => api.post('/admin/provider-model-mappings/import', { items }),
  createProviderModelMapping: (data) => api.post('/admin/provider-model-mappings', data),
  updateProviderModelMapping: (id, data) => api.put(`/admin/provider-model-mappings/${id}`, data),
  deleteProviderModelMapping: (id) => api.delete(`/admin/provider-model-mappings/${id}`),

  listModels: (provider, params) => api.get('/admin/models', { params: { provider, ...(params || {}) } }),
  exportModels: () => api.get('/admin/models/export'),
  createModel: (data) => api.post('/admin/models', data),
  importModels: (items) => api.post('/admin/models/import', { items }),
  quickCreateModels: (names) => api.post('/admin/models/quick-create', { names }),
  updateModel: (id, data) => api.put(`/admin/models/${id}`, data),
  deleteModel: (id) => api.delete(`/admin/models/${id}`),

  getImageModels: () => api.get('/admin/image/models'),
  getImageCapabilities: () => api.get('/admin/image/capabilities'),
  generateImage: (data) => api.post('/admin/image/generations', data, { timeout: IMAGE_REQUEST_TIMEOUT }),
  validateImageGeneration: (data) => api.post('/admin/image/validate', data, { timeout: data?.probe_only === false ? IMAGE_REQUEST_TIMEOUT : 130000 }),
  listImageTasks: (params) => api.get('/admin/image/tasks', { params }),
  getImageTask: (id) => api.get(`/admin/image/tasks/${id}`),
  refreshImageTask: (id) => api.post(`/admin/image/tasks/${id}/refresh`, null, { timeout: IMAGE_REQUEST_TIMEOUT }),
  refreshImageTaskByUpstreamId: (id, upstreamTaskId) => api.post(`/admin/image/tasks/${id}/refresh-by-upstream-id`, { upstream_task_id: upstreamTaskId }, { timeout: IMAGE_REQUEST_TIMEOUT }),
  listImageTaskResults: (id, params) => api.get(`/admin/image/tasks/${id}/results`, { params }),
  getImageKeyStats: (params) => api.get('/admin/image/key-stats', { params }),
  getImageStorageConfig: () => api.get('/admin/image/storage-config'),
  updateImageStorageConfig: (data) => api.put('/admin/image/storage-config', data),
  getImageAutoRefreshConfig: () => api.get('/admin/image/auto-refresh-config'),
  updateImageAutoRefreshConfig: (data) => api.put('/admin/image/auto-refresh-config', data),
  getStaleTaskCleanupConfig: () => api.get('/admin/image/stale-task-cleanup-config'),
  updateStaleTaskCleanupConfig: (data) => api.put('/admin/image/stale-task-cleanup-config', data),
  deleteImageTask: (id, data) => api.delete(`/admin/image/tasks/${id}`, { data }),
  getImageResultFileUrl: (id) => `/api/admin/image/results/${id}/file`,
  getImageResultPsdFileUrl: (id) => `/api/admin/image/results/${id}/psd`,
  downloadImageResultPsd: (id) => api.get(`/admin/image/results/${id}/psd`, { responseType: 'blob', timeout: 180000 }),
  saveImageResultLocal: (id) => api.post(`/admin/image/results/${id}/save-local`, null, { timeout: 180000 }),
  openImageResultFolder: (id) => api.post(`/admin/image/results/${id}/open-folder`),
  revealImageResultFile: (id) => api.post(`/admin/image/results/${id}/reveal-file`),

  exportConfig: (model) => api.get('/admin/export-config', { params: { model } }),

  getProviderExtConfig: () => api.get('/admin/provider-ext-config'),
  updateProviderExtConfig: (data) => api.put('/admin/provider-ext-config', data),
  getProviderBalance: (keyId) =>
    api.get('/admin/provider-balance', { params: { key_id: keyId } }),

  getBalanceDowngradeRules: () => api.get('/admin/balance-downgrade-rules'),
  updateBalanceDowngradeRules: (data) => api.put('/admin/balance-downgrade-rules', data),

  getStreamBufferRules: () => api.get('/admin/stream-buffer-rules'),
  updateStreamBufferRules: (data) => api.put('/admin/stream-buffer-rules', data),

  getShowActualModel: () => api.get('/admin/show-actual-model'),
  updateShowActualModel: (data) => api.put('/admin/show-actual-model', data),

  getUserQuotaUsage: (userId) => api.get(`/admin/users/${userId}/quota-usage`),
  resetUserQuota: (userId) => api.post(`/admin/users/${userId}/quota-reset`),

  getProviderMigrationRules: () => api.get('/admin/provider-migration-rules'),
  updateProviderMigrationRules: (data) => api.put('/admin/provider-migration-rules', data),
}

export const authApi = {
  status: () => rawApi.get('/auth/status').then((r) => r.data),
  setup: (username, password) => rawApi.post('/auth/setup', { username, password }).then((r) => r.data),
  login: (username, password) => rawApi.post('/auth/login', { username, password }).then((r) => r.data),
  register: (username, password) => rawApi.post('/auth/register', { username, password }).then((r) => r.data),
  changePassword: (oldPassword, newPassword) =>
    api.post('/auth/change-password', { old_password: oldPassword, new_password: newPassword }),
  logout: () => {
    const token = getSessionToken()
    if (token) {
      rawApi.post('/auth/logout', null, { headers: { Authorization: `Bearer ${token}` } }).catch(() => {})
    }
    clearSessionToken()
  },
  isLoggedIn: () => !!getSessionToken(),
  getCurrentUsername: () => localStorage.getItem(SESSION_USERNAME_KEY) || '',
  getCurrentRole: () => localStorage.getItem(SESSION_ROLE_KEY) || '',
  getCurrentApiKey: () => localStorage.getItem(SESSION_API_KEY_KEY) || '',
  isAdmin: () => localStorage.getItem(SESSION_ROLE_KEY) === 'admin',
  getMe: () => api.get('/auth/me'),
  listUsers: () => api.get('/auth/users'),
  createUser: (data) => api.post('/auth/users', data),
  updateUser: (userId, data) => api.put(`/auth/users/${userId}`, data),
  deleteUser: (userId) => api.delete(`/auth/users/${userId}`),
  regenerateUserKey: (userId) => api.post(`/auth/users/${userId}/regenerate-key`),
  regenerateMyKey: () => api.post('/auth/my/regenerate-key'),
  getConfig: () => rawApi.get('/auth/config').then((r) => r.data),
  updateConfig: (loginEnabled) => api.put('/auth/config', { login_enabled: loginEnabled }),
}

/**
 * 存储登录/注册后的用户信息到 localStorage
 */
export function saveSessionUser(data) {
  if (data?.token) localStorage.setItem(SESSION_TOKEN_KEY, data.token)
  if (data?.username) localStorage.setItem(SESSION_USERNAME_KEY, data.username)
  if (data?.role) localStorage.setItem(SESSION_ROLE_KEY, data.role)
  if (data?.api_key) localStorage.setItem(SESSION_API_KEY_KEY, data.api_key)
}

export const statsApi = {
  getSummary: (params = {}) => api.get('/stats/summary', { params }),
  getByKey: (params = {}) => api.get('/stats/by-key', { params, paramsSerializer: { serialize: serializeParams } }),
  getDaily: (params = {}) => api.get('/stats/daily', { params }),
  getLogs: (params) => api.get('/stats/logs', { params }),
}

export default api
