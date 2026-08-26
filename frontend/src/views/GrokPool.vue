<template>
  <div class="page-container grok-page">
    <div class="page-header compact-header">
      <div>
        <h1>Grok 账户池</h1>
        <p>xAI API Key 与 Grok OAuth session 独立管理，不影响通用 CPA 和 OpenAI Plus。</p>
      </div>
      <div class="header-actions">
        <el-button @click="loadAll" :loading="loading">刷新</el-button>
        <el-upload
          class="session-upload"
          :auto-upload="false"
          :show-file-list="false"
          :multiple="true"
          accept=".json,.jsonl,.txt"
          :on-change="handleSessionFileChange"
        >
          <el-button :loading="importing">导入文件</el-button>
        </el-upload>
        <el-button @click="createAuthUrl" :loading="authUrlLoading">生成授权链接</el-button>
        <el-button type="primary" @click="openCreateDialog">新增账号</el-button>
      </div>
    </div>

    <el-card class="content-card">
      <div class="endpoint-row">
        <span>统一入口</span>
        <code>/grok/v1</code>
        <span>统一 Key</span>
        <code>{{ unifiedApiKey || '-' }}</code>
        <span>上游地址</span>
        <code>{{ upstreamBaseUrl }}</code>
        <el-button size="small" :disabled="!pagedAccounts.length" :loading="batchChecking" @click="batchCheckVisibleAccounts">批量巡检本页</el-button>
        <el-button size="small" :disabled="!selectedAccounts.length" :loading="batchChecking" @click="batchCheckSelectedAccounts">巡检勾选</el-button>
        <el-button class="delete-button" size="small" type="danger" plain :disabled="!selectedAccounts.length" :loading="batchDeleting" @click="batchDeleteSelectedAccounts">删除勾选</el-button>
        <span class="selection-tip">已选 {{ selectedAccounts.length }} / 共 {{ accounts.length }}</span>
      </div>
      <!-- 窄屏：账号表格改卡片流，详细字段折叠在「详情」里 -->
      <div v-if="isMobile" class="acct-card-list" v-loading="loading">
        <div class="acct-card-toolbar">
          <el-checkbox :model-value="mobileAllAccountsSelected" @change="toggleMobileSelectAllAccounts">
            全选本页
          </el-checkbox>
          <span class="acct-card-toolbar__count">共 {{ accounts.length }} 个</span>
        </div>

        <div v-if="!pagedAccounts.length" class="acct-card-empty">暂无数据</div>

        <div
          v-for="row in pagedAccounts"
          :key="row.id"
          class="acct-card"
          :class="{ 'is-selected': isAccountSelected(row) }"
        >
          <div class="acct-card__head">
            <el-checkbox :model-value="isAccountSelected(row)" @change="() => toggleAccountSelect(row)" />
            <span class="acct-card__name">{{ getAccountName(row) }}</span>
            <button type="button" class="acct-card__toggle" @click="toggleAccountExpand(row.id)">
              <span>{{ isAccountExpanded(row.id) ? '收起' : '详情' }}</span>
              <el-icon :class="{ 'is-open': isAccountExpanded(row.id) }"><ArrowDown /></el-icon>
            </button>
          </div>

          <div class="acct-card__tags">
            <el-tag size="small" type="info">#{{ row.id }}</el-tag>
            <el-tag :type="row.disabled ? 'danger' : 'success'" size="small">
              {{ row.disabled ? '禁用' : '启用' }}
            </el-tag>
            <el-tag size="small" type="info">{{ formatNumber(row.total_tokens) }} tokens</el-tag>
          </div>

          <div v-show="isAccountExpanded(row.id)" class="acct-card__rows">
            <div v-if="shouldShowEmail(row)" class="acct-card__row">
              <span class="acct-card__label">邮箱</span>
              <span class="acct-card__value">{{ row.email }}</span>
            </div>
            <div class="acct-card__row">
              <span class="acct-card__label">Token 过期</span>
              <span class="acct-card__value">{{ formatDate(row.expires_at) }}</span>
            </div>
            <div class="acct-card__row">
              <span class="acct-card__label">巡检</span>
              <span class="acct-card__value">
                <el-link
                  v-if="row.last_check_message"
                  :type="row.last_check_status === 'ok' ? 'success' : 'danger'"
                  :underline="false"
                  @click="showCheckDetail(row)"
                >
                  {{ summarizeCheckMessage(row.last_check_message, row.last_check_status) }}
                </el-link>
                <template v-else>-</template>
              </span>
            </div>
          </div>

          <div class="acct-card__actions">
            <el-button size="small" :loading="checkingId === row.id" @click="checkAccount(row)">巡检</el-button>
            <el-button size="small" :loading="refreshingId === row.id" @click="refreshAccount(row)">刷新 token</el-button>
            <el-button size="small" @click="toggleAccount(row)">{{ row.disabled ? '启用' : '禁用' }}</el-button>
            <el-popconfirm title="确定删除该 Grok 账号？" @confirm="deleteAccount(row)">
              <template #reference>
                <el-button class="delete-button" size="small" type="danger" plain>删除</el-button>
              </template>
            </el-popconfirm>
          </div>
        </div>
      </div>

      <el-table v-else :data="pagedAccounts" v-loading="loading" stripe height="560" @selection-change="handleSelectionChange">
        <el-table-column type="selection" width="46" />
        <el-table-column prop="id" label="ID" width="72" />
        <el-table-column label="名称" min-width="220">
          <template #default="{ row }">
            <el-tooltip :content="getAccountName(row)" placement="top-start" :show-after="300">
              <span class="account-field">{{ getAccountName(row) }}</span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column v-if="showEmailColumn" label="邮箱" min-width="240">
          <template #default="{ row }">
            <el-tooltip v-if="shouldShowEmail(row)" :content="row.email" placement="top-start" :show-after="300">
              <span class="account-field">{{ row.email }}</span>
            </el-tooltip>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.disabled ? 'danger' : 'success'">{{ row.disabled ? '禁用' : '启用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Token 过期" width="170" show-overflow-tooltip>
          <template #default="{ row }">
            {{ formatDate(row.expires_at) }}
          </template>
        </el-table-column>
        <el-table-column label="巡检" width="150">
          <template #default="{ row }">
            <el-link
              v-if="row.last_check_message"
              :type="row.last_check_status === 'ok' ? 'success' : 'danger'"
              :underline="false"
              @click="showCheckDetail(row)"
            >
              {{ summarizeCheckMessage(row.last_check_message, row.last_check_status) }}
            </el-link>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="累计用量" width="160">
          <template #default="{ row }">
            {{ formatNumber(row.total_tokens) }} tokens
          </template>
        </el-table-column>
        <el-table-column label="操作" width="360">
          <template #default="{ row }">
            <el-button size="small" @click="checkAccount(row)" :loading="checkingId === row.id">巡检</el-button>
            <el-button size="small" @click="refreshAccount(row)" :loading="refreshingId === row.id">刷新 token</el-button>
            <el-button size="small" @click="toggleAccount(row)">{{ row.disabled ? '启用' : '禁用' }}</el-button>
            <el-popconfirm title="确定删除该 Grok 账号？" @confirm="deleteAccount(row)">
              <template #reference>
                <el-button class="delete-button" size="small" type="danger" plain>删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
      <div class="pagination-row">
        <el-pagination
          v-model:current-page="accountPage"
          v-model:page-size="accountPageSize"
          :page-sizes="[10, 20, 50, 100]"
          :small="isMobile"
          :pager-count="isMobile ? 5 : 7"
          :layout="isMobile ? 'prev, pager, next, sizes, total' : 'total, sizes, prev, pager, next'"
          :total="accounts.length"
        />
      </div>
    </el-card>

    <el-card class="content-card">
      <template #header>调用日志</template>
      <el-table :data="usageLogs" v-loading="logsLoading" stripe>
        <el-table-column prop="created_at" label="时间" width="180" />
        <el-table-column prop="account_email" label="账号" min-width="180" show-overflow-tooltip />
        <el-table-column prop="model" label="模型" width="140" show-overflow-tooltip />
        <el-table-column prop="endpoint" label="入口" width="130" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.success ? 'success' : 'danger'">{{ row.status_code || '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="输入" width="90"><template #default="{ row }">{{ formatNumber(row.prompt_tokens) }}</template></el-table-column>
        <el-table-column label="缓存" width="90"><template #default="{ row }">{{ formatNumber(row.cache_tokens) }}</template></el-table-column>
        <el-table-column label="输出" width="90"><template #default="{ row }">{{ formatNumber(row.completion_tokens) }}</template></el-table-column>
        <el-table-column prop="error_message" label="错误" min-width="220" show-overflow-tooltip />
      </el-table>
    </el-card>

    <el-dialog v-model="authDialogVisible" title="Grok OAuth 授权" width="760px">
      <el-alert title="打开授权链接完成登录后，将回调 URL 或 code 粘贴到下方完成账号创建。" type="info" :closable="false" />
      <el-form label-width="110px" class="oauth-form">
        <el-form-item label="授权链接">
          <el-input v-model="authUrl" type="textarea" :rows="4" readonly />
        </el-form-item>
        <el-form-item label="回调/code">
          <el-input v-model="exchangeForm.code" type="textarea" :rows="4" placeholder="粘贴完整回调 URL 或 code" />
        </el-form-item>
        <el-form-item label="账号名称">
          <el-input v-model="exchangeForm.name" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="authDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="exchanging" @click="exchangeCode">创建账号</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailDialogVisible" title="巡检详情" width="720px">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="账号">{{ detailRow?.email || detailRow?.name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ detailRow?.last_check_status || '-' }}</el-descriptions-item>
        <el-descriptions-item label="Token 过期">{{ formatDate(detailRow?.expires_at) }}</el-descriptions-item>
      </el-descriptions>
      <el-input class="detail-message" :model-value="detailRow?.last_check_message || ''" type="textarea" :rows="8" readonly />
      <template #footer>
        <el-button @click="detailDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dialogVisible" title="新增 Grok 账号" width="720px">
      <el-form label-width="110px">
        <el-form-item label="账号名称">
          <el-input v-model="form.name" placeholder="例如 grok-session-1" />
        </el-form-item>
        <el-form-item label="账号类型">
          <el-radio-group v-model="form.account_type">
            <el-radio value="oauth">OAuth Session</el-radio>
            <el-radio value="api_key">xAI API Key</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="上游地址">
          <el-input v-model="form.base_url" :placeholder="form.account_type === 'api_key' ? 'https://api.x.ai/v1' : 'https://cli-chat-proxy.grok.com/v1'" />
        </el-form-item>
        <template v-if="form.account_type === 'api_key'">
          <el-form-item label="API Key">
            <el-input v-model="form.api_key" type="textarea" :rows="4" placeholder="输入 xAI API Key" />
          </el-form-item>
        </template>
        <template v-else>
          <el-form-item label="Session">
            <el-input
              v-model="form.session_content"
              type="textarea"
              :rows="10"
              placeholder='粘贴 JSON 或 key=value 格式，至少包含 access_token 或 refresh_token'
            />
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitAccount">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'
import { adminApi } from '../api'

// 手机竖屏改用卡片流，桌面端保持原表格
const MOBILE_QUERY = '(max-width: 768px)'
const isMobile = ref(false)
let mobileMediaQuery = null
const syncMobile = (event) => {
  isMobile.value = event.matches
}

// 账号卡片的详细字段按需展开
const expandedAccountIds = ref(new Set())
const isAccountExpanded = (id) => expandedAccountIds.value.has(Number(id))
const toggleAccountExpand = (id) => {
  const next = new Set(expandedAccountIds.value)
  const key = Number(id)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expandedAccountIds.value = next
}

const loading = ref(false)
const logsLoading = ref(false)
const submitting = ref(false)
const checkingId = ref(null)
const refreshingId = ref(null)
const batchChecking = ref(false)
const batchDeleting = ref(false)
const authUrlLoading = ref(false)
const exchanging = ref(false)
const importing = ref(false)
const dialogVisible = ref(false)
const authDialogVisible = ref(false)
const detailDialogVisible = ref(false)
const detailRow = ref(null)
const accounts = ref([])
const selectedAccounts = ref([])
const accountPage = ref(1)
const accountPageSize = ref(10)
const usageLogs = ref([])
const unifiedApiKey = ref('')
const authUrl = ref('')
const authState = ref('')

const exchangeForm = reactive({
  code: '',
  name: '',
})

const form = reactive({
  name: '',
  account_type: 'oauth',
  base_url: 'https://cli-chat-proxy.grok.com/v1',
  api_key: '',
  session_content: '',
})

watch(() => form.account_type, (value) => {
  form.base_url = value === 'api_key' ? 'https://api.x.ai/v1' : 'https://cli-chat-proxy.grok.com/v1'
})

watch([accounts, accountPageSize], () => {
  const maxPage = Math.max(Math.ceil(accounts.value.length / accountPageSize.value), 1)
  if (accountPage.value > maxPage) accountPage.value = maxPage
})

const pagedAccounts = computed(() => {
  const start = (accountPage.value - 1) * accountPageSize.value
  return accounts.value.slice(start, start + accountPageSize.value)
})

const upstreamBaseUrl = computed(() => accounts.value.find((item) => item.base_url)?.base_url || 'https://cli-chat-proxy.grok.com/v1')
const showEmailColumn = computed(() => accounts.value.some((item) => shouldShowEmail(item)))

const formatNumber = (value) => Number(value || 0).toLocaleString('zh-CN')
const formatDate = (value) => value ? String(value).replace('T', ' ').slice(0, 19) : '-'
const normalizeAccountText = (value) => String(value || '').trim().toLowerCase()
const getAccountName = (row) => row?.name || row?.email || '-'
const shouldShowEmail = (row) => {
  const email = normalizeAccountText(row?.email)
  const name = normalizeAccountText(row?.name)
  return !!email && email !== name
}

const handleSelectionChange = (rows) => {
  selectedAccounts.value = rows || []
}

// 卡片流没有 el-table 的多选，这里复用同一份 selectedAccounts
const selectedAccountIdSet = computed(() => new Set(selectedAccounts.value.map((item) => item.id)))
const isAccountSelected = (row) => selectedAccountIdSet.value.has(row.id)
const toggleAccountSelect = (row) => {
  selectedAccounts.value = isAccountSelected(row)
    ? selectedAccounts.value.filter((item) => item.id !== row.id)
    : [...selectedAccounts.value, row]
}
const mobileAllAccountsSelected = computed(
  () => pagedAccounts.value.length > 0 && pagedAccounts.value.every((row) => isAccountSelected(row))
)
const toggleMobileSelectAllAccounts = () => {
  if (mobileAllAccountsSelected.value) {
    const pageIds = new Set(pagedAccounts.value.map((item) => item.id))
    selectedAccounts.value = selectedAccounts.value.filter((item) => !pageIds.has(item.id))
  } else {
    const merged = new Map(selectedAccounts.value.map((item) => [item.id, item]))
    pagedAccounts.value.forEach((item) => merged.set(item.id, item))
    selectedAccounts.value = [...merged.values()]
  }
}

const summarizeCheckMessage = (message, status) => {
  if (status === 'ok') return '正常'
  const text = String(message || '')
  if (/Refresh token has been revoked|invalid_grant/i.test(text)) return '授权已失效'
  if (/no auth context/i.test(text)) return '认证上下文无效'
  const httpMatch = text.match(/HTTP\s*\d+/i)
  if (httpMatch) return httpMatch[0].toUpperCase()
  if (/timeout/i.test(text)) return '请求超时'
  return '异常'
}

const showCheckDetail = (row) => {
  detailRow.value = row
  detailDialogVisible.value = true
}

const extractJsonObjects = (content) => {
  const items = []
  let start = -1
  let depth = 0
  let inString = false
  let escaped = false
  for (let index = 0; index < content.length; index++) {
    const char = content[index]
    if (inString) {
      if (escaped) {
        escaped = false
      } else if (char === '\\') {
        escaped = true
      } else if (char === '"') {
        inString = false
      }
      continue
    }
    if (char === '"') {
      inString = true
      continue
    }
    if (char === '{') {
      if (depth === 0) start = index
      depth++
      continue
    }
    if (char === '}') {
      depth--
      if (depth === 0 && start >= 0) {
        const value = content.slice(start, index + 1)
        try {
          items.push(JSON.parse(value))
        } catch (_) {
          // 跳过无法解析的片段
        }
        start = -1
      }
    }
  }
  return items
}

const splitJsonPayloads = (text) => {
  const content = (text || '').trim()
  if (!content) return []
  try {
    const parsed = JSON.parse(content)
    return Array.isArray(parsed) ? parsed : [parsed]
  } catch (_) {
    const lineItems = []
    content.split(/\r?\n/).forEach((line) => {
      const value = line.trim()
      if (!value) return
      try {
        lineItems.push(JSON.parse(value))
      } catch (_) {
        // 忽略非 JSON 行，允许文件内带说明文本
      }
    })
    return lineItems.length ? lineItems : extractJsonObjects(content)
  }
}

const readFileText = (file) => new Promise((resolve, reject) => {
  const reader = new FileReader()
  reader.onload = () => resolve(String(reader.result || ''))
  reader.onerror = () => reject(reader.error || new Error('读取文件失败'))
  reader.readAsText(file.raw || file)
})

const importSessionPayloads = async (payloads) => {
  let successCount = 0
  let failCount = 0
  let skippedCount = 0
  const existingKeys = new Set(accounts.value.map((item) => `${item.email || ''}:${item.account_type || ''}`))
  const importingKeys = new Set()
  for (const payload of payloads) {
    if (!payload || typeof payload !== 'object') {
      failCount++
      continue
    }
    const email = payload.email || ''
    const uniqueKey = `${email}:oauth`
    if (email && (existingKeys.has(uniqueKey) || importingKeys.has(uniqueKey))) {
      skippedCount++
      continue
    }
    try {
      await adminApi.createGrokAccount({
        name: payload.name || payload.email || payload.sub || '',
        account_type: 'oauth',
        base_url: payload.base_url || '',
        session_content: JSON.stringify(payload),
      })
      importingKeys.add(uniqueKey)
      successCount++
    } catch (_) {
      failCount++
    }
  }
  return { successCount, failCount, skippedCount }
}

const handleSessionFileChange = async (file, fileList) => {
  if (importing.value) return
  importing.value = true
  try {
    const selectedFiles = fileList.length ? fileList : [file]
    const payloads = []
    for (const item of selectedFiles) {
      const text = await readFileText(item)
      payloads.push(...splitJsonPayloads(text))
    }
    if (!payloads.length) {
      ElMessage.warning('未识别到可导入的 JSON session')
      return
    }
    const { successCount, failCount, skippedCount } = await importSessionPayloads(payloads)
    if (successCount) {
      ElMessage.success(`已导入 ${successCount} 个 Grok session${skippedCount ? `，跳过重复 ${skippedCount} 个` : ''}${failCount ? `，失败 ${failCount} 个` : ''}`)
      await loadAll()
    } else if (skippedCount) {
      ElMessage.warning(`未导入新账号，已跳过重复 ${skippedCount} 个`)
    } else {
      ElMessage.error('导入失败，未成功创建账号')
    }
  } catch (error) {
    ElMessage.error(error.message || '导入文件失败')
  } finally {
    importing.value = false
  }
}

const resetForm = () => {
  Object.assign(form, {
    name: '',
    account_type: 'oauth',
    base_url: 'https://cli-chat-proxy.grok.com/v1',
    api_key: '',
    session_content: '',
  })
}

const loadAccounts = async () => {
  loading.value = true
  try {
    const data = await adminApi.listGrokAccounts()
    accounts.value = data.items || []
    unifiedApiKey.value = data.unified_api_key || ''
  } catch (error) {
    ElMessage.error(error.message || '加载 Grok 账户失败')
  } finally {
    loading.value = false
  }
}

const loadLogs = async () => {
  logsLoading.value = true
  try {
    const data = await adminApi.listGrokUsageLogs({ page: 1, page_size: 50 })
    usageLogs.value = data.items || []
  } catch (error) {
    ElMessage.error(error.message || '加载 Grok 日志失败')
  } finally {
    logsLoading.value = false
  }
}

const loadAll = async () => {
  await Promise.all([loadAccounts(), loadLogs()])
}

const createAuthUrl = async () => {
  authUrlLoading.value = true
  try {
    const data = await adminApi.createGrokOAuthAuthUrl({})
    authUrl.value = data.auth_url || ''
    authState.value = data.state || ''
    exchangeForm.code = ''
    exchangeForm.name = ''
    authDialogVisible.value = true
  } catch (error) {
    ElMessage.error(error.message || '生成授权链接失败')
  } finally {
    authUrlLoading.value = false
  }
}

const exchangeCode = async () => {
  if (!exchangeForm.code.trim()) {
    ElMessage.warning('请粘贴回调 URL 或 code')
    return
  }
  exchanging.value = true
  try {
    await adminApi.exchangeGrokOAuthCode({ code: exchangeForm.code, state: authState.value, name: exchangeForm.name })
    ElMessage.success('Grok OAuth 账号已创建')
    authDialogVisible.value = false
    await loadAccounts()
  } catch (error) {
    ElMessage.error(error.message || '创建 OAuth 账号失败')
  } finally {
    exchanging.value = false
  }
}

const openCreateDialog = () => {
  resetForm()
  dialogVisible.value = true
}

const submitAccount = async () => {
  if (form.account_type === 'api_key' && !form.api_key.trim()) {
    ElMessage.warning('请输入 API Key')
    return
  }
  if (form.account_type === 'oauth' && !form.session_content.trim()) {
    ElMessage.warning('请输入 Session')
    return
  }
  submitting.value = true
  try {
    await adminApi.createGrokAccount({ ...form })
    ElMessage.success('Grok 账号已保存')
    dialogVisible.value = false
    await loadAccounts()
  } catch (error) {
    ElMessage.error(error.message || '保存失败')
  } finally {
    submitting.value = false
  }
}

const toggleAccount = async (row) => {
  try {
    await adminApi.updateGrokAccountStatus(row.id, { disabled: !row.disabled })
    ElMessage.success(row.disabled ? '已启用' : '已禁用')
    await loadAccounts()
  } catch (error) {
    ElMessage.error(error.message || '操作失败')
  }
}

const checkAccount = async (row) => {
  checkingId.value = row.id
  try {
    const result = await adminApi.checkGrokAccount(row.id, { model: 'grok-4.5' })
    if (result.status === 'ok') {
      ElMessage.success(result.message || '巡检成功')
    } else {
      ElMessage.error(summarizeCheckMessage(result.message, result.status))
    }
    await loadAccounts()
  } catch (error) {
    ElMessage.error(error.message || '巡检失败')
  } finally {
    checkingId.value = null
  }
}

const refreshAccount = async (row) => {
  refreshingId.value = row.id
  try {
    await adminApi.refreshGrokAccount(row.id)
    ElMessage.success('token 已刷新')
    await loadAccounts()
  } catch (error) {
    ElMessage.error(error.message || '刷新 token 失败')
    await loadAccounts()
  } finally {
    refreshingId.value = null
  }
}

const runBatchCheck = async (rows) => {
  if (!rows.length || batchChecking.value) return
  batchChecking.value = true
  let successCount = 0
  let failCount = 0
  try {
    for (const row of rows) {
      checkingId.value = row.id
      try {
        const result = await adminApi.checkGrokAccount(row.id, { model: 'grok-4.5' })
        if (result.status === 'ok') successCount++
        else failCount++
      } catch (_) {
        failCount++
      }
    }
    ElMessage.success(`批量巡检完成：成功 ${successCount} 个，异常 ${failCount} 个`)
    await loadAccounts()
  } finally {
    checkingId.value = null
    batchChecking.value = false
  }
}

const batchCheckVisibleAccounts = () => runBatchCheck(pagedAccounts.value)
const batchCheckSelectedAccounts = () => runBatchCheck(selectedAccounts.value)

const batchDeleteSelectedAccounts = async () => {
  if (!selectedAccounts.value.length || batchDeleting.value) return
  try {
    await ElMessageBox.confirm(
      `确定删除已勾选的 ${selectedAccounts.value.length} 个 Grok 账号？此操作不可恢复。`,
      '批量删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch (_) {
    return
  }
  batchDeleting.value = true
  try {
    const result = await adminApi.batchDeleteGrokAccounts(selectedAccounts.value.map((item) => item.id))
    ElMessage.success(`已删除 ${result.deleted || selectedAccounts.value.length} 个 Grok 账号`)
    selectedAccounts.value = []
    await loadAccounts()
  } catch (error) {
    ElMessage.error(error.message || '批量删除失败')
  } finally {
    batchDeleting.value = false
  }
}

const deleteAccount = async (row) => {
  try {
    await adminApi.deleteGrokAccount(row.id)
    ElMessage.success('已删除')
    await loadAccounts()
  } catch (error) {
    ElMessage.error(error.message || '删除失败')
  }
}

onMounted(() => {
  loadAll()
  mobileMediaQuery = window.matchMedia(MOBILE_QUERY)
  isMobile.value = mobileMediaQuery.matches
  mobileMediaQuery.addEventListener('change', syncMobile)
})

onBeforeUnmount(() => {
  mobileMediaQuery?.removeEventListener('change', syncMobile)
})
</script>

<style scoped>
.grok-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.endpoint-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
  font-size: 14px;
}

.selection-tip {
  color: var(--el-text-color-secondary);
}

.account-field {
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: default;
}

.pagination-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.endpoint-row code {
  padding: 4px 8px;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  background: var(--el-fill-color-light);
}

.oauth-form {
  margin-top: 12px;
}

.detail-message {
  margin-top: 12px;
}

.status-ok {
  color: #16a34a;
}

.status-error {
  color: #dc2626;
}

/* ── 移动端：账号卡片流 ── */
.acct-card-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.acct-card-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 0 2px 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.acct-card-empty {
  padding: 24px 0;
  text-align: center;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.acct-card {
  padding: 10px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px;
  background: var(--el-bg-color);
}

.acct-card.is-selected {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}

.acct-card__head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.acct-card__name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-color-primary);
}

.acct-card__toggle {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 2px;
  padding: 2px 4px;
  border: none;
  background: none;
  font-size: 11px;
  color: var(--el-text-color-secondary);
  cursor: pointer;
}

.acct-card__toggle .el-icon {
  transition: transform 0.2s;
}

.acct-card__toggle .el-icon.is-open {
  transform: rotate(180deg);
}

.acct-card__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
}

.acct-card__rows {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-top: 6px;
  padding-top: 8px;
  border-top: 1px dashed var(--el-border-color-lighter);
}

.acct-card__row {
  display: grid;
  grid-template-columns: 68px minmax(0, 1fr);
  align-items: start;
  gap: 8px;
  font-size: 11px;
}

.acct-card__label {
  color: var(--el-text-color-secondary);
}

.acct-card__value {
  min-width: 0;
  overflow-wrap: anywhere;
  color: var(--el-text-color-primary);
}

.acct-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--el-border-color-lighter);
}

@media (max-width: 768px) {
  /* 顶部入口信息与按钮在窄屏换行，避免横向溢出 */
  .endpoint-row {
    font-size: 12px;
    gap: 6px;
  }

  .endpoint-row code {
    overflow-wrap: anywhere;
  }

  .header-actions {
    flex-wrap: wrap;
    row-gap: 6px;
  }

  .pagination-row {
    justify-content: flex-start;
  }
}
</style>
