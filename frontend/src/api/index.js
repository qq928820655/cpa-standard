import axios from 'axios'

const MASTER_KEY_STORAGE_KEY = 'masterKey'
const SESSION_TOKEN_KEY = 'sessionToken'
const SESSION_USERNAME_KEY = 'sessionUsername'
const SESSION_ROLE_KEY = 'sessionRole'
const SESSION_API_KEY_KEY = 'sessionApiKey'
const CHECK_REQUEST_TIMEOUT = 65000
const IMAGE_REQUEST_TIMEOUT = 360000
const IMPORT_REQUEST_TIMEOUT = 300000

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
let sessionLogoutInProgress = false
let sessionRequestVersion = 0

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
    config._sessionRequestVersion = sessionRequestVersion
    if (sessionLogoutInProgress && window.location.pathname === '/login') {
      return new Promise(() => {})
    }

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
    if (response.config?._sessionRequestVersion !== sessionRequestVersion) {
      return new Promise(() => {})
    }
    if (response.config?.responseType === 'blob') {
      return response.data
    }
    return response.data
  },
  async (error) => {
    const originalRequest = error.config || {}
    if (originalRequest._sessionRequestVersion !== undefined && originalRequest._sessionRequestVersion !== sessionRequestVersion) {
      return new Promise(() => {})
    }
    const status = error.response?.status
    const requestUrl = originalRequest.url || ''

    // 退出后缓存页面可能仍有尚未结束的请求；静默标记，避免登录页继续弹认证错误。
    if (status === 401 && !getSessionToken() && window.location.pathname === '/login') {
      const silentError = new Error('__session_logged_out__')
      silentError.silent = true
      return Promise.reject(silentError)
    }

    // 仅 401 代表 session token 已失效；403 表示当前登录用户没有该接口权限，不能登出。
    if (status === 401 && getSessionToken() && !originalRequest._retriedWithFreshSession) {
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
  importKeys: (items) => api.post('/admin/keys/import', { items }, { timeout: IMPORT_REQUEST_TIMEOUT }),
  batchUpdateKeyModels: (data) => api.post('/admin/keys/batch/models', data),
  batchSetKeysProxy: (data) => api.post('/admin/keys/batch/models', data),
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
  batchSetProviderModelMappingsEnabled: (data) => api.post('/admin/provider-model-mappings/batch/enabled', data),
  deleteProviderModelMapping: (id) => api.delete(`/admin/provider-model-mappings/${id}`),

  listModels: (provider, params) => api.get('/admin/models', { params: { provider, ...(params || {}) } }),
  getModelPricingConfig: () => api.get('/admin/models/pricing-config'),
  updateModelPricingConfig: (data) => api.put('/admin/models/pricing-config', data),
  syncModelsDevPricing: () => api.post('/admin/models/pricing/models-dev/sync'),
  exportModels: () => api.get('/admin/models/export'),
  createModel: (data) => api.post('/admin/models', data),
  importModels: (items) => api.post('/admin/models/import', { items }),
  quickCreateModels: (names) => api.post('/admin/models/quick-create', { names }),
  updateModel: (id, data) => api.put(`/admin/models/${id}`, data),
  deleteModel: (id) => api.delete(`/admin/models/${id}`),

  getImageModels: () => api.get('/admin/image/models'),
  createImageModel: (data) => api.post('/admin/image/models', data),
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

  listOpenAIPlusAccounts: () => api.get('/admin/openai-plus/accounts'),
  listOpenAIPlusQuotas: () => api.get('/admin/openai-plus/quotas', { timeout: 180000 }),
  listOpenAIPlusUsageLogs: (params) => api.get('/admin/openai-plus/usage-logs', { params }),
  getOpenAIPlusQuota: (id) => api.get(`/admin/openai-plus/accounts/${id}/quota`, { timeout: 120000 }),
  getOpenAIPlusQuotaRefreshConfig: () => api.get('/admin/openai-plus/quota-refresh-config'),
  updateOpenAIPlusQuotaRefreshConfig: (data) => api.put('/admin/openai-plus/quota-refresh-config', data),
  getOpenAIPlusProxyConfig: () => api.get('/admin/openai-plus/proxy-config'),
  updateOpenAIPlusProxyConfig: (data) => api.put('/admin/openai-plus/proxy-config', data),
  createGrokOAuthAuthUrl: (data) => api.post('/admin/grok/oauth/auth-url', data || {}),
  exchangeGrokOAuthCode: (data) => api.post('/admin/grok/oauth/exchange-code', data),
  listGrokUsageLogs: (params) => api.get('/admin/grok/usage-logs', { params }),
  listGrokAccounts: () => api.get('/admin/grok/accounts'),
  createGrokAccount: (data) => api.post('/admin/grok/accounts', data),
  updateGrokAccountStatus: (id, data) => api.put(`/admin/grok/accounts/${id}/status`, data),
  checkGrokAccount: (id, data) => api.post(`/admin/grok/accounts/${id}/check`, data, { timeout: CHECK_REQUEST_TIMEOUT }),
  refreshGrokAccount: (id) => api.post(`/admin/grok/accounts/${id}/refresh`, null, { timeout: CHECK_REQUEST_TIMEOUT }),
  batchDeleteGrokAccounts: (accountIds) => api.delete('/admin/grok/accounts/batch', { data: { account_ids: accountIds } }),
  deleteGrokAccount: (id) => api.delete(`/admin/grok/accounts/${id}`),
  importOpenAIPlusAccounts: (content) => api.post('/admin/openai-plus/accounts/import', { content }, { timeout: 600000 }),
  exportOpenAIPlusAccounts: (data) => api.post('/admin/openai-plus/accounts/export', data, data?.mode === 'separate' ? { responseType: 'blob' } : undefined),
  updateOpenAIPlusAccount: (id, data) => api.put(`/admin/openai-plus/accounts/${id}`, data),
  batchUpdateOpenAIPlusAccounts: (data) => api.put('/admin/openai-plus/accounts/batch', data),
  batchDeleteOpenAIPlusAccounts: (data) => api.delete('/admin/openai-plus/accounts/batch', { data }),
  deleteOpenAIPlusAccount: (id) => api.delete(`/admin/openai-plus/accounts/${id}`),
  checkOpenAIPlusAccount: (id) => api.post(`/admin/openai-plus/accounts/${id}/check`),

  getPassThroughErrorCodes: () => api.get('/admin/pass-through-error-codes'),
  updatePassThroughErrorCodes: (data) => api.put('/admin/pass-through-error-codes', data),
  getProviderContinueErrorRules: () => api.get('/admin/provider-continue-error-rules'),
  updateProviderContinueErrorRules: (data) => api.put('/admin/provider-continue-error-rules', data),

  getModelSeedConfig: () => api.get('/admin/model-seed-config'),
  updateModelSeedConfig: (data) => api.put('/admin/model-seed-config', data),

  getRuntimeLogConfig: () => api.get('/admin/runtime-log-config'),
  updateRuntimeLogConfig: (data) => api.put('/admin/runtime-log-config', data),
  listRuntimeLogs: (params) => api.get('/admin/runtime-logs', { params }),
  clearRuntimeLogs: () => api.delete('/admin/runtime-logs'),

  getProxyTraceConfig: () => api.get('/admin/proxy-trace-config'),
  updateProxyTraceConfig: (data) => api.put('/admin/proxy-trace-config', data),
  listProxyTraces: (params) => api.get('/admin/proxy-traces', { params }),
  getProxyTrace: (traceId) => api.get(`/admin/proxy-traces/${traceId}`),
  cleanupProxyTraces: () => api.delete('/admin/proxy-traces/cleanup'),
  getIntelligentProtocolRoutingConfig: () => api.get('/admin/intelligent-protocol-routing-config'),
  updateIntelligentProtocolRoutingConfig: (data) => api.put('/admin/intelligent-protocol-routing-config', data),
  listProtocolCapabilities: (params) => api.get('/admin/protocol-capabilities', { params }),
  clearProtocolCapabilities: (data) => api.delete('/admin/protocol-capabilities', { data }),

  getThinkingModeConfig: () => api.get('/admin/thinking-mode-config'),
  updateThinkingModeConfig: (data) => api.put('/admin/thinking-mode-config', data),

  getUsageRetentionConfig: () => api.get('/admin/usage-retention-config'),
  updateUsageRetentionConfig: (data) => api.put('/admin/usage-retention-config', data),

  getRetrySameKeyConfig: () => api.get('/admin/retry-same-key-config'),
  updateRetrySameKeyConfig: (data) => api.put('/admin/retry-same-key-config', data),

  factoryReset: (data) => api.post('/admin/factory-reset', data),
}

export const authApi = {
  status: () => rawApi.get('/auth/status').then((r) => r.data),
  setup: (username, password) => rawApi.post('/auth/setup', { username, password }).then((r) => r.data),
  login: (username, password) => rawApi.post('/auth/login', { username, password }).then((r) => r.data),
  register: (username, password) => rawApi.post('/auth/register', { username, password }).then((r) => r.data),
  changePassword: (oldPassword, newPassword) =>
    api.post('/auth/change-password', { old_password: oldPassword, new_password: newPassword }),
  logout: () => {
    sessionLogoutInProgress = true
    sessionRequestVersion++
    const token = getSessionToken()
    if (token) {
      rawApi.post('/auth/logout', null, { headers: { Authorization: `Bearer ${token}` } }).catch(() => {})
    }
    clearSessionToken()
    // 清除缓存的 master key，避免登出/切换用户后残留管理员凭证
    clearMasterKey()
    window.dispatchEvent(new Event('session-changed'))
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
  sessionLogoutInProgress = false
  sessionRequestVersion++
  if (data?.token) localStorage.setItem(SESSION_TOKEN_KEY, data.token)
  if (data?.username) localStorage.setItem(SESSION_USERNAME_KEY, data.username)
  if (data?.role) localStorage.setItem(SESSION_ROLE_KEY, data.role)
  if (data?.api_key) localStorage.setItem(SESSION_API_KEY_KEY, data.api_key)
  window.dispatchEvent(new Event('session-changed'))
}

/**
 * 通用复制到剪贴板，兼容非安全上下文（http 远程访问）
 */
export async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text)
  } else {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.cssText = 'position:fixed;left:-9999px;top:-9999px'
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
}

export const statsApi = {
  getSummary: (params = {}) => api.get('/stats/summary', { params, paramsSerializer: { serialize: serializeParams } }),
  getByKey: (params = {}) => api.get('/stats/by-key', { params, paramsSerializer: { serialize: serializeParams } }),
  getDaily: (params = {}) => api.get('/stats/daily', { params, paramsSerializer: { serialize: serializeParams } }),
  getLogs: (params) => api.get('/stats/logs', { params, paramsSerializer: { serialize: serializeParams } }),
}

export default api
