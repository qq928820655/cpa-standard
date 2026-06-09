<template>
  <div class="openai-plus-page">
    <el-card shadow="never" class="panel-card">
      <template #header>
        <div class="panel-header">
          <div>
            <div class="panel-title">OpenAI</div>
          </div>
          <el-button type="primary" @click="loadAccounts">刷新</el-button>
        </div>
      </template>

      <div class="unified-box">
        <div class="unified-item">
          <span class="unified-label">统一地址</span>
          <span class="unified-value">{{ buildBaseUrl() }}</span>
          <el-button link type="primary" @click="copyToClipboard(buildBaseUrl())">复制</el-button>
        </div>
        <div class="unified-item">
          <span class="unified-label">统一 API Key</span>
          <span class="unified-value">{{ unifiedApiKey }}</span>
          <el-button link type="primary" @click="copyToClipboard(unifiedApiKey)">复制</el-button>
        </div>
        <div class="unified-stats">
          <span>启用 {{ summary.enabled_count || 0 }}/{{ summary.account_count || 0 }}</span>
          <span>请求 {{ summary.success_count || 0 }}/{{ summary.request_count || 0 }}</span>
          <span>消耗 {{ formatToken(summary.total_tokens) }} token</span>
        </div>
      </div>

      <el-tabs v-model="activeTab" class="openai-tabs">
        <el-tab-pane label="账号管理" name="accounts">
          <div class="quota-actions">
            <el-button size="small" @click="toggleAllCards">{{ allCardsExpanded ? '一键折叠' : '一键展开' }}</el-button>
            <el-button size="small" type="primary" :loading="quotaLoading" @click="loadQuotas">刷新配额</el-button>
          </div>
          <div class="quota-grid">
            <div v-for="account in accounts" :key="account.id" class="quota-card">
              <div class="quota-card__header" @click="toggleQuotaCard(account.id)">
                <span class="quota-card__name">{{ account.email || account.name || `#${account.id}` }}</span>
                <div class="quota-card__header-actions">
                  <el-button
                    size="small"
                    link
                    type="primary"
                    :loading="quotaRefreshingId === account.id"
                    @click.stop="refreshAccountQuota(account)"
                  >刷新配额</el-button>
                  <el-tag :type="account.disabled ? 'danger' : 'success'" size="small">{{ account.disabled ? '禁用' : '启用' }}</el-tag>
                  <span class="quota-card__toggle">{{ isQuotaCardCollapsed(account.id) ? '展开' : '折叠' }}</span>
                </div>
              </div>
              <div class="quota-card__meta">套餐：{{ getDisplayPlan(account) }} / 过期：{{ formatTime(account.expires_at) }}</div>
              <div v-if="quotaLoading" class="quota-card__quota">官方配额加载中...</div>
              <div v-else-if="hasQuotaDetail(account)" class="quota-card__quota">
                <span>支持模型：{{ formatSupportedModels(account) }}</span>
                <span>5h：{{ formatPercent(quotas[account.id].primary?.used_percent) }} / {{ formatResetTime(quotas[account.id].primary?.reset_at) }}</span>
                <template v-if="!isQuotaCardCollapsed(account.id)">
                  <span>7d：{{ formatPercent(quotas[account.id].secondary?.used_percent) }} / {{ formatResetTime(quotas[account.id].secondary?.reset_at) }}</span>
                  <span>Credits：{{ formatCredits(quotas[account.id].credits) }}</span>
                  <span v-if="!quotas[account.id].available" class="quota-card__warning">状态：{{ quotas[account.id].message || '不可用' }}</span>
                  <div v-if="getAdditionalLimits(account).length" class="model-limits">
                    <div class="model-limits__title">模型/功能限额</div>
                    <div v-for="limit in getAdditionalLimits(account)" :key="`${limit.metered_feature || ''}-${limit.limit_name || ''}`" class="model-limits__item">
                      <span>{{ formatLimitName(limit) }}</span>
                      <span>5h {{ formatPercent(normalizeLimitWindow(limit, 'primary')?.used_percent) }}</span>
                      <span>7d {{ formatPercent(normalizeLimitWindow(limit, 'secondary')?.used_percent) }}</span>
                    </div>
                  </div>
                  <div v-else class="model-limits__empty">官方未返回具体模型/功能额度；当前仅返回账号级 5h/7d 限额</div>
                </template>
              </div>
              <div v-else class="quota-card__quota">官方配额：{{ quotas?.[account.id]?.message || '暂无数据' }}</div>
              <template v-if="!isQuotaCardCollapsed(account.id)">
                <div class="quota-card__stats">
                  <span>请求 {{ account.success_count || 0 }}/{{ account.request_count || 0 }}</span>
                  <span>失败 {{ account.error_count || 0 }}</span>
                  <span>输入 {{ formatToken(account.prompt_tokens) }}</span>
                  <span>输出 {{ formatToken(account.completion_tokens) }}</span>
                  <span>总量 {{ formatToken(account.total_tokens) }}</span>
                </div>
                <div class="quota-card__check">检测：{{ account.last_check_message || '-' }}</div>
              </template>
            </div>
          </div>

          <el-card shadow="never" class="panel-card account-list-card">
            <template #header>
              <div class="panel-header">
                <div class="panel-title">OpenAI 账号列表</div>
                <div class="account-actions">
                  <el-button size="small" :disabled="!selectedAccounts.length" @click="batchSetAccountsDisabled(false)">批量启用</el-button>
                  <el-button size="small" :disabled="!selectedAccounts.length" @click="batchSetAccountsDisabled(true)">批量禁用</el-button>
                  <el-button size="small" type="danger" :disabled="!selectedAccounts.length" @click="batchDeleteAccounts">批量删除</el-button>
                  <el-button type="primary" :loading="importing" @click="openImportDialog">导入账号</el-button>
                </div>
              </div>
            </template>
            <el-table :data="accounts" stripe border v-loading="loading" size="small" @selection-change="handleAccountSelectionChange">
              <el-table-column type="selection" width="42" />
              <el-table-column prop="id" label="ID" width="54" />
              <el-table-column prop="name" label="名称" width="152" />
              <el-table-column prop="email" label="邮箱" width="143" />
              <el-table-column prop="plan_type" label="套餐" width="49">
                <template #default="{ row }">{{ row.plan_type || '-' }}</template>
              </el-table-column>
              <el-table-column prop="expires_at" label="过期时间" width="113">
                <template #default="{ row }">{{ formatTime(row.expires_at) }}</template>
              </el-table-column>
              <el-table-column prop="disabled" label="状态" width="74" align="center">
                <template #default="{ row }">
                  <el-tag :type="row.disabled ? 'danger' : 'success'" size="small">{{ row.disabled ? '禁用' : '启用' }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="proxy_key" label="Proxy Key" width="167">
                <template #default="{ row }">
                  <div class="key-row">
                    <span>{{ row.proxy_key }}</span>
                    <el-button link type="primary" @click="copyToClipboard(row.proxy_key)">复制</el-button>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="统计" width="71">
                <template #default="{ row }">
                  <div class="stats-mini">{{ row.success_count || 0 }}/{{ row.request_count || 0 }} 成功</div>
                  <div class="stats-mini">{{ formatToken(row.total_tokens) }} token</div>
                </template>
              </el-table-column>
              <el-table-column prop="last_check_message" label="检测结果" width="179">
                <template #default="{ row }">{{ row.last_check_message || '-' }}</template>
              </el-table-column>
              <el-table-column label="操作" width="172" fixed="right">
                <template #default="{ row }">
                  <div class="table-actions-row">
                    <el-button size="small" type="primary" :loading="checkingId === row.id" @click="checkAccount(row)">测试</el-button>
                    <el-button size="small" :type="row.disabled ? 'success' : 'warning'" @click="toggleAccount(row)">{{ row.disabled ? '启用' : '禁用' }}</el-button>
                    <el-button size="small" type="danger" @click="deleteAccount(row)">删除</el-button>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-tab-pane>

        <el-tab-pane label="用量管理" name="usage">
          <div class="usage-toolbar">
            <el-button size="small" @click="moveUsageColumn(-1)">列左移</el-button>
            <el-button size="small" @click="moveUsageColumn(1)">列右移</el-button>
            <el-button size="small" @click="moveUsageRow(-1)">行上移</el-button>
            <el-button size="small" @click="moveUsageRow(1)">行下移</el-button>
            <el-button size="small" type="primary" @click="loadUsageLogs">刷新用量</el-button>
          </div>
          <el-table :data="usageLogs" stripe border size="small" v-loading="usageLoading" highlight-current-row @current-change="handleUsageCurrentChange">
            <el-table-column
              v-for="column in usageColumns"
              :key="column.prop"
              :prop="column.prop"
              :label="column.label"
              :width="column.width"
              show-overflow-tooltip
            >
              <template #default="{ row }">
                <el-tag v-if="column.prop === 'success'" :type="row.success ? 'success' : 'danger'" size="small">{{ row.success ? '成功' : '失败' }}</el-tag>
                <span v-else-if="column.prop === 'stream'">{{ row.stream ? '流式' : '非流式' }}</span>
                <span v-else-if="column.prop === 'created_at'">{{ formatTime(row.created_at) }}</span>
                <span v-else>{{ row[column.prop] ?? '-' }}</span>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>

      <el-dialog v-model="importDialogVisible" title="导入 OpenAI 账号" width="680px">
        <div class="import-file-box">
          <input
            ref="importFileInput"
            class="import-file-input"
            type="file"
            accept=".json,application/json"
            multiple
            @change="handleImportFilesChange"
          />
          <div class="form-tip">可同时选择多个 cpatoken JSON 文件；也可继续在下方粘贴单个对象或数组。</div>
          <div v-if="importFiles.length" class="import-file-list">
            <span v-for="file in importFiles" :key="file.name">{{ file.name }}</span>
          </div>
        </div>
        <el-input
          v-model="importContent"
          type="textarea"
          :rows="10"
          placeholder="粘贴 access_token / Codex session JSON，可为单个对象或数组"
        />
        <template #footer>
          <el-button @click="importDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="importing" @click="handleImport">确认导入</el-button>
        </template>
      </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { adminApi, copyText } from '../api'

const accounts = ref([])
const quotas = ref(null)
const quotaLoading = ref(false)
const quotaRefreshingId = ref(null)
const summary = ref({})
const unifiedApiKey = ref('cpa-plus-unified')
const allCardsExpanded = ref(false)
const loading = ref(false)
const importing = ref(false)
const checkingId = ref(null)
const importDialogVisible = ref(false)
const importContent = ref('')
const importFiles = ref([])
const importFileInput = ref(null)
const selectedAccounts = ref([])
const activeTab = ref('accounts')
const usageLoading = ref(false)
const usageLogs = ref([])
const selectedUsageRow = ref(null)
const usageColumns = ref([
  { prop: 'id', label: 'ID', width: 70 },
  { prop: 'account_email', label: '账号', width: 210 },
  { prop: 'model', label: '模型', width: 120 },
  { prop: 'endpoint', label: '接口', width: 120 },
  { prop: 'stream', label: '模式', width: 80 },
  { prop: 'prompt_tokens', label: '输入', width: 80 },
  { prop: 'completion_tokens', label: '输出', width: 80 },
  { prop: 'total_tokens', label: '总量', width: 80 },
  { prop: 'success', label: '状态', width: 80 },
  { prop: 'status_code', label: 'HTTP', width: 80 },
  { prop: 'created_at', label: '时间', width: 160 },
])

const loadAccounts = async () => {
  loading.value = true
  try {
    const res = await adminApi.listOpenAIPlusAccounts()
    accounts.value = res.items || []
    summary.value = res.summary || {}
    unifiedApiKey.value = res.unified_api_key || 'cpa-plus-unified'
  } catch (error) {
    ElMessage.error(error.message || '加载失败')
  } finally {
    loading.value = false
  }
}

const loadQuotas = async () => {
  quotaLoading.value = true
  try {
    const res = await adminApi.listOpenAIPlusQuotas()
    quotas.value = Object.fromEntries((res.items || []).map((item) => [String(item.account_id), item]))
  } catch (error) {
    ElMessage.warning(error.message || '用量配额加载失败')
  } finally {
    quotaLoading.value = false
  }
}

const refreshAccountQuota = async (account) => {
  quotaRefreshingId.value = account.id
  try {
    const quota = await adminApi.getOpenAIPlusQuota(account.id)
    quotas.value = {
      ...(quotas.value || {}),
      [String(account.id)]: { ...quota, account_id: account.id },
    }
    ElMessage.success('配额已刷新')
  } catch (error) {
    quotas.value = {
      ...(quotas.value || {}),
      [String(account.id)]: { account_id: account.id, available: false, message: error.message || '配额刷新失败' },
    }
    ElMessage.warning(error.message || '配额刷新失败')
  } finally {
    quotaRefreshingId.value = null
  }
}

const loadUsageLogs = async () => {
  usageLoading.value = true
  try {
    const res = await adminApi.listOpenAIPlusUsageLogs({ limit: 200 })
    usageLogs.value = res.items || []
  } catch (error) {
    ElMessage.error(error.message || '用量加载失败')
  } finally {
    usageLoading.value = false
  }
}

const handleUsageCurrentChange = (row) => {
  selectedUsageRow.value = row
}

const moveUsageColumn = (direction) => {
  if (!usageColumns.value.length) return
  const currentIndex = 0
  const nextIndex = currentIndex + direction
  if (nextIndex < 0 || nextIndex >= usageColumns.value.length) return
  const nextColumns = [...usageColumns.value]
  const [item] = nextColumns.splice(currentIndex, 1)
  nextColumns.splice(nextIndex, 0, item)
  usageColumns.value = nextColumns
}

const moveUsageRow = (direction) => {
  if (!selectedUsageRow.value) return
  const index = usageLogs.value.findIndex((item) => item.id === selectedUsageRow.value.id)
  const nextIndex = index + direction
  if (index < 0 || nextIndex < 0 || nextIndex >= usageLogs.value.length) return
  const rows = [...usageLogs.value]
  const [item] = rows.splice(index, 1)
  rows.splice(nextIndex, 0, item)
  usageLogs.value = rows
}

const openImportDialog = () => {
  importContent.value = ''
  importFiles.value = []
  if (importFileInput.value) {
    importFileInput.value.value = ''
  }
  importDialogVisible.value = true
}

const handleImportFilesChange = (event) => {
  importFiles.value = Array.from(event.target.files || [])
}

const normalizeImportPayload = (payload) => {
  if (Array.isArray(payload)) return payload.filter((item) => item && typeof item === 'object' && !Array.isArray(item))
  if (payload && typeof payload === 'object') return [payload]
  return []
}

const readImportFile = (file) => new Promise((resolve, reject) => {
  const reader = new FileReader()
  reader.onload = () => {
    try {
      resolve(normalizeImportPayload(JSON.parse(String(reader.result || ''))))
    } catch {
      reject(new Error(`${file.name} 不是有效 JSON`))
    }
  }
  reader.onerror = () => reject(new Error(`${file.name} 读取失败`))
  reader.readAsText(file)
})

const buildImportPayloads = async () => {
  const payloads = []
  const text = importContent.value.trim()

  if (text) {
    try {
      payloads.push(...normalizeImportPayload(JSON.parse(text)))
    } catch {
      throw new Error('粘贴内容不是有效 JSON')
    }
  }

  for (const file of importFiles.value) {
    payloads.push(...await readImportFile(file))
  }

  if (!payloads.length) {
    throw new Error('请先选择 JSON 文件或粘贴 JSON')
  }

  return payloads
}

const handleImport = async () => {
  importing.value = true
  try {
    const payloads = await buildImportPayloads()
    const batchSize = 500
    const summary = { created: 0, updated: 0, failed: 0, skipped: 0 }
    for (let start = 0; start < payloads.length; start += batchSize) {
      const batch = payloads.slice(start, start + batchSize)
      const res = await adminApi.importOpenAIPlusAccounts(JSON.stringify(batch))
      summary.created += res.created || 0
      summary.updated += res.updated || 0
      summary.failed += res.failed || 0
      summary.skipped += res.skipped || 0
      ElMessage.info(`正在导入：${Math.min(start + batch.length, payloads.length)}/${payloads.length}`)
    }
    ElMessage.success(`导入完成：新增 ${summary.created}，更新 ${summary.updated}，跳过 ${summary.skipped}，失败 ${summary.failed}`)
    importContent.value = ''
    importFiles.value = []
    if (importFileInput.value) {
      importFileInput.value.value = ''
    }
    importDialogVisible.value = false
    await loadAccounts()
  } catch (error) {
    ElMessage.error(error.message || '导入失败')
  } finally {
    importing.value = false
  }
}

const handleAccountSelectionChange = (rows) => {
  selectedAccounts.value = rows || []
}

const batchSetAccountsDisabled = async (disabled) => {
  if (!selectedAccounts.value.length) {
    ElMessage.warning('请先选择账号')
    return
  }
  await adminApi.batchUpdateOpenAIPlusAccounts({
    account_ids: selectedAccounts.value.map((item) => item.id),
    disabled,
  })
  ElMessage.success(disabled ? '已批量禁用' : '已批量启用')
  selectedAccounts.value = []
  await loadAccounts()
}

const batchDeleteAccounts = async () => {
  if (!selectedAccounts.value.length) {
    ElMessage.warning('请先选择账号')
    return
  }
  await ElMessageBox.confirm(`确认删除选中的 ${selectedAccounts.value.length} 个 Plus 账号？`, '批量删除 Plus 账号', { type: 'warning' })
  await adminApi.batchDeleteOpenAIPlusAccounts({ account_ids: selectedAccounts.value.map((item) => item.id) })
  ElMessage.success('已批量删除')
  selectedAccounts.value = []
  await loadAccounts()
}

const checkAccount = async (row) => {
  checkingId.value = row.id
  try {
    await adminApi.checkOpenAIPlusAccount(row.id)
    ElMessage.success('检测完成')
    await loadAccounts()
  } catch (error) {
    ElMessage.error(error.message || '检测失败')
  } finally {
    checkingId.value = null
  }
}

const toggleAccount = async (row) => {
  await adminApi.updateOpenAIPlusAccount(row.id, { disabled: !row.disabled })
  await loadAccounts()
}

const deleteAccount = async (row) => {
  await ElMessageBox.confirm(`确认删除 ${row.email || row.name || row.id}？`, '删除 Plus 账号', { type: 'warning' })
  await adminApi.deleteOpenAIPlusAccount(row.id)
  ElMessage.success('已删除')
  await loadAccounts()
}

const copyToClipboard = async (text) => {
  await copyText(text)
  ElMessage.success('已复制')
}

const buildBaseUrl = () => `${window.location.origin}/plus/v1`

const formatTime = (value) => {
  if (!value) return '-'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}


const formatToken = (value) => {
  const num = Number(value || 0)
  if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`
  if (num >= 1000) return `${(num / 1000).toFixed(1)}k`
  return String(num)
}

const toggleAllCards = () => {
  allCardsExpanded.value = !allCardsExpanded.value
}

const isQuotaCardCollapsed = () => !allCardsExpanded.value

const toggleQuotaCard = () => {
  allCardsExpanded.value = !allCardsExpanded.value
}

const getDisplayPlan = (account) => {
  return quotas.value?.[account.id]?.plan_type || account.plan_type || '-'
}

const hasQuotaDetail = (account) => {
  const quota = quotas.value?.[account.id]
  return !!(quota?.available || quota?.primary || quota?.secondary || quota?.credits || getAdditionalLimits(account).length)
}

const getAdditionalLimits = (account) => {
  const limits = quotas.value?.[account.id]?.additional_rate_limits
  return Array.isArray(limits) ? limits : []
}

const unwrapMaybeBox = (value) => {
  if (Array.isArray(value)) return value[0]
  return value
}

const normalizeLimitWindow = (limit, type) => {
  const rateLimit = unwrapMaybeBox(limit?.rate_limit)
  if (!rateLimit || typeof rateLimit !== 'object') return null
  const key = type === 'primary' ? 'primary_window' : 'secondary_window'
  return unwrapMaybeBox(rateLimit[key])
}

const formatSupportedModels = (account) => {
  const limits = getAdditionalLimits(account)
  const names = limits.map(formatLimitName).filter(Boolean)
  if (names.length) return names.join('、')
  return 'gpt-5.5 / gpt-5.4 / gpt-5.3-codex'
}

const formatLimitName = (limit) => {
  return limit?.limit_name || limit?.metered_feature || '未命名限额'
}

const formatPercent = (value) => {
  if (value === undefined || value === null || value === '') return '-'
  const num = Number(value)
  return Number.isFinite(num) ? `${num.toFixed(1)}%` : '-'
}

const formatResetTime = (value) => {
  if (!value) return '重置 -'
  const timestamp = Number(value)
  const date = new Date(timestamp > 10000000000 ? timestamp : timestamp * 1000)
  return `重置 ${date.toLocaleString('zh-CN', { hour12: false })}`
}

const formatCredits = (credits) => {
  if (!credits) return '-'
  if (credits.unlimited) return '无限'
  if (credits.has_credits === false) return '无'
  if (credits.balance !== undefined && credits.balance !== null) return String(credits.balance)
  return credits.has_credits ? '有' : '-'
}

onMounted(() => {
  loadAccounts()
})
</script>

<style scoped>
.openai-plus-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.panel-card {
  border-radius: 12px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.panel-title {
  font-size: 16px;
  font-weight: 700;
  color: #1f3b5d;
}

.panel-subtitle {
  margin-top: 4px;
  color: #6b7c93;
  font-size: 12px;
}

.key-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.key-row span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.unified-box {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 16px;
  margin-bottom: 14px;
  padding: 12px;
  border: 1px solid var(--cpa-panel-border-soft);
  border-radius: 12px;
  background: rgba(37, 99, 235, 0.04);
}

.unified-item {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.unified-label {
  color: #6b7c93;
  font-size: 12px;
  font-weight: 600;
}

.unified-value {
  max-width: 260px;
  overflow: hidden;
  color: #1f3b5d;
  font-size: 12px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.unified-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  color: #40566f;
  font-size: 12px;
}

.quota-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-bottom: 10px;
}

.quota-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.quota-card {
  padding: 12px;
  border: 1px solid var(--cpa-panel-border-soft);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.72);
}

.quota-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  cursor: pointer;
}

.quota-card__header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.quota-card__toggle {
  color: #2563eb;
  font-size: 12px;
  font-weight: 600;
}

.quota-card__name {
  min-width: 0;
  overflow: hidden;
  color: #1f3b5d;
  font-size: 13px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.quota-card__meta,
.quota-card__check {
  margin-top: 8px;
  color: #6b7c93;
  font-size: 12px;
  line-height: 18px;
}

.quota-card__quota {
  display: grid;
  grid-template-columns: repeat(1, minmax(0, 1fr));
  gap: 4px;
  margin-top: 8px;
  color: #2563eb;
  font-size: 12px;
  line-height: 18px;
}

.quota-card__warning {
  color: #d97706;
}
.model-limits {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed rgba(37, 99, 235, 0.24);
}

.model-limits__title {
  color: #1f3b5d;
  font-weight: 700;
}

.model-limits__item {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) auto auto;
  gap: 6px;
  align-items: center;
}

.model-limits__item span:first-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.model-limits__empty {
  margin-top: 4px;
  color: #6b7c93;
}

.quota-card__stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px 10px;
  margin-top: 10px;
  color: #40566f;
  font-size: 12px;
}

.usage-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.account-list-card {
  margin-top: 12px;
}

.account-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.import-file-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 10px;
}

.import-file-input {
  width: 100%;
}

.import-file-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.import-file-list span {
  max-width: 220px;
  padding: 3px 8px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.08);
  color: #1f3b5d;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.form-tip {
  color: #6b7c93;
  font-size: 12px;
  line-height: 18px;
}

.table-actions-row {
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.table-actions-row .el-button + .el-button {
  margin-left: 0;
}

.stats-mini {
  line-height: 18px;
  font-size: 12px;
  color: #40566f;
}
</style>
