<template>
  <div class="user-manage page-shell">
    <div class="page-header">
      <div class="page-header-main">
        <div class="page-kicker">Users</div>
        <h2 class="page-title">用户管理</h2>
      </div>
      <div v-if="isAdmin" class="header-actions">
        <el-button type="primary" @click="showAddDialog">新增用户</el-button>
      </div>
    </div>

    <!-- 管理员视图：完整用户表格 -->
    <el-card v-if="isAdmin" shadow="never" class="table-card">
      <el-table :data="users" stripe style="width: 100%" size="small">
        <el-table-column prop="id" label="ID" width="52" />
        <el-table-column prop="username" label="用户名" width="130" show-overflow-tooltip />
        <el-table-column label="角色" width="80">
          <template #default="{ row }">
            <el-tag :type="row.role === 'admin' ? 'danger' : 'info'" size="small">
              {{ row.role === 'admin' ? '管理员' : '普通用户' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="API Key" width="150">
          <template #default="{ row }">
            <div v-if="row.api_key" class="api-key-cell">
              <span class="api-key-text">{{ maskApiKey(row.api_key) }}</span>
              <el-button link type="primary" size="small" @click="copyApiKey(row.api_key)">复制</el-button>
            </div>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="可用模型" width="90">
          <template #default="{ row }">
            <div v-if="row.supported_models && row.supported_models.length" class="model-tags">
              <el-tag v-for="m in row.supported_models.slice(0, 1)" :key="m" size="small" class="model-tag">{{ m }}</el-tag>
              <el-popover v-if="row.supported_models.length > 1" trigger="hover" width="300">
                <template #reference>
                  <el-tag size="small" class="model-tag">+{{ row.supported_models.length - 1 }}</el-tag>
                </template>
                <div class="model-popover">
                  <el-tag v-for="m in row.supported_models" :key="m" size="small" class="model-tag">{{ m }}</el-tag>
                </div>
              </el-popover>
            </div>
            <span v-else class="text-muted">全部</span>
          </template>
        </el-table-column>
        <el-table-column label="Token 限额 (M)" width="180">
          <template #default="{ row }">
            <div v-if="row.daily_token_limit || row.weekly_token_limit || row.monthly_token_limit" style="font-size: 11px; line-height: 1.7; color: #606266">
              <div v-if="row.daily_token_limit">
                日: {{ formatQuotaUsageM(quotaUsageMap[row.id]?.daily_used, row.daily_token_limit) }}
              </div>
              <div v-if="row.weekly_token_limit">
                周: {{ formatQuotaUsageM(quotaUsageMap[row.id]?.weekly_used, row.weekly_token_limit) }}
              </div>
              <div v-if="row.monthly_token_limit">
                月: {{ formatQuotaUsageM(quotaUsageMap[row.id]?.monthly_used, row.monthly_token_limit) }}
              </div>
            </div>
            <span v-else style="color: #909399; font-size: 11px">不限制</span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="112">
          <template #default="{ row }">
            <span style="font-size: 11px">{{ row.created_at ? formatShortTime(row.created_at) : '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="showEditDialog(row)">编辑</el-button>
            <el-button link type="primary" size="small" @click="handleRegenerateKey(row)">重置Key</el-button>
            <el-button link type="primary" size="small" @click="showPasswordDialog(row)">改密码</el-button>
            <el-button
              v-if="row.daily_token_limit || row.weekly_token_limit || row.monthly_token_limit"
              link type="warning" size="small"
              @click="handleResetQuota(row)"
            >重置额度</el-button>
            <el-popconfirm
              v-if="!row.role || row.role !== 'admin' || adminCount > 1"
              title="确定删除该用户？"
              @confirm="handleDeleteUser(row)"
            >
              <template #reference>
                <el-button link type="danger" size="small">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 普通用户视图：个人信息卡 -->
    <el-card v-else-if="myInfo" shadow="never" class="profile-card">
      <div class="profile-row">
        <span class="profile-label">用户名</span>
        <span class="profile-value">{{ myInfo.username }}</span>
      </div>
      <div class="profile-row">
        <span class="profile-label">角色</span>
        <span class="profile-value">
          <el-tag :type="myInfo.role === 'admin' ? 'danger' : 'info'" size="small">
            {{ myInfo.role === 'admin' ? '管理员' : '普通用户' }}
          </el-tag>
        </span>
      </div>
      <div class="profile-row">
        <span class="profile-label">API Key</span>
        <span class="profile-value">
          <div v-if="myInfo.api_key" class="api-key-cell">
            <span class="api-key-text">{{ maskApiKey(myInfo.api_key) }}</span>
            <el-button link type="primary" size="small" @click="copyApiKey(myInfo.api_key)">复制</el-button>
          </div>
          <span v-else class="text-muted">-</span>
        </span>
      </div>
      <div class="profile-row">
        <span class="profile-label">可用模型</span>
        <span class="profile-value">
          <div v-if="myInfo.supported_models && myInfo.supported_models.length" class="model-tags">
            <el-tag v-for="m in myInfo.supported_models" :key="m" size="small" class="model-tag">{{ m }}</el-tag>
          </div>
          <span v-else class="text-muted">全部模型</span>
        </span>
      </div>
      <div class="profile-row">
        <span class="profile-label">创建时间</span>
        <span class="profile-value">{{ myInfo.created_at ? formatTime(myInfo.created_at) : '-' }}</span>
      </div>
      <div class="profile-actions">
        <el-button type="primary" @click="handleMyRegenerateKey">重新生成 API Key</el-button>
        <el-button @click="showMyPasswordDialog">修改密码</el-button>
      </div>
    </el-card>

    <!-- 新增/编辑用户对话框（管理员） -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEditing ? '编辑用户' : '新增用户'"
      width="860px"
      destroy-on-close
    >
      <el-form ref="userFormRef" :model="userForm" :rules="userFormRules" label-position="top">
        <!-- 第一行：用户名、角色、可用模型 -->
        <div class="form-grid-3">
          <el-form-item label="用户名" prop="username">
            <el-input v-model="userForm.username" placeholder="请输入用户名" />
          </el-form-item>
          <el-form-item v-if="!isEditing" label="密码" prop="password">
            <el-input v-model="userForm.password" type="password" placeholder="请输入密码" show-password />
          </el-form-item>
          <el-form-item v-if="isEditing" label="角色">
            <el-select v-model="userForm.role" style="width: 100%">
              <el-option label="管理员" value="admin" />
              <el-option label="普通用户" value="user" />
            </el-select>
          </el-form-item>
          <el-form-item label="可用模型">
            <el-select
              v-model="userForm.supported_models"
              multiple
              filterable
              allow-create
              default-first-option
              clearable
              placeholder="留空表示可用全部模型"
              style="width: 100%"
            >
              <el-option v-for="m in availableModels" :key="m" :value="m" :label="m" />
            </el-select>
          </el-form-item>
        </div>
        <!-- 第二行：日限额、周限额、月限额 -->
        <div class="form-grid-3">
          <el-form-item label="日限额 (M tokens)">
            <el-input-number
              v-model="userForm.daily_token_limit_m"
              :min="0"
              :precision="2"
              :step="1"
              placeholder="留空不限制"
              style="width: 100%"
              controls-position="right"
            />
          </el-form-item>
          <el-form-item label="周限额 (M tokens)">
            <el-input-number
              v-model="userForm.weekly_token_limit_m"
              :min="0"
              :precision="2"
              :step="5"
              placeholder="留空不限制"
              style="width: 100%"
              controls-position="right"
            />
          </el-form-item>
          <el-form-item label="月限额 (M tokens)">
            <el-input-number
              v-model="userForm.monthly_token_limit_m"
              :min="0"
              :precision="2"
              :step="10"
              placeholder="留空不限制"
              style="width: 100%"
              controls-position="right"
            />
          </el-form-item>
        </div>
        <!-- 超限配置 -->
        <div class="form-grid-2">
          <el-form-item label="超限返回模式">
            <el-radio-group v-model="userForm.quota_exceeded_mode">
              <el-radio value="normal">正常提示</el-radio>
              <el-radio value="disguise">伪装成 401 错误</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="超限提示内容">
            <el-input
              v-model="userForm.quota_exceeded_message"
              type="textarea"
              :rows="2"
              placeholder="留空使用默认提示"
              style="width: 100%"
            />
          </el-form-item>
        </div>
        <el-form-item label="用户可见限额">
          <el-switch v-model="userForm.show_quota_to_user" active-text="开启" inactive-text="关闭" />
          <div class="form-tip">开启后，用户本人可在个人信息页看到限额配置和已用量</div>
        </el-form-item>
        <!-- 模型映射 -->
        <el-form-item label="模型映射">
          <div style="width: 100%">
            <div
              v-for="(item, idx) in userForm.model_mapping_list"
              :key="idx"
              class="model-mapping-item"
            >
              <div style="display: flex; gap: 8px; align-items: center; margin-bottom: 4px">
                <el-input v-model="item.from" placeholder="用户请求的模型" size="small" style="flex: 1" />
                <el-select v-model="item.mode" size="small" style="width: 90px; flex-shrink: 0" @change="onMappingModeChange(item)">
                  <el-option value="simple" label="直接映射" />
                  <el-option value="tiered" label="阶梯映射" />
                </el-select>
                <el-input v-if="item.mode === 'simple'" v-model="item.to" placeholder="实际转发的模型" size="small" style="flex: 1" />
                <el-button type="danger" link size="small" @click="removeModelMapping(idx)">删除</el-button>
              </div>
              <!-- 阶梯配置 -->
              <div v-if="item.mode === 'tiered'" style="margin-left: 16px; margin-bottom: 8px">
                <div
                  v-for="(tier, tidx) in item.tiers"
                  :key="tidx"
                  style="display: flex; gap: 6px; align-items: center; margin-bottom: 4px"
                >
                  <el-input-number v-model="tier.from" :min="0" :precision="2" :step="1" size="small" style="width: 90px" placeholder="从(M)" controls-position="right" />
                  <span style="color: #909399; font-size: 12px; flex-shrink: 0">M ~</span>
                  <el-input-number v-model="tier.to" :min="0" :precision="2" :step="1" size="small" style="width: 120px" placeholder="到(留空无限)" controls-position="right" />
                  <span style="color: #909399; font-size: 12px; flex-shrink: 0">M →</span>
                  <el-input v-model="tier.model" placeholder="实际模型" size="small" style="flex: 1" />
                  <el-button type="danger" link size="small" @click="removeTier(item, tidx)">×</el-button>
                </div>
                <el-button size="small" @click="addTier(item)">添加阶梯</el-button>
                <span style="font-size: 11px; color: #909399; margin-left: 8px">用量按日累计，单位 M tokens</span>
              </div>
            </div>
            <el-button size="small" @click="addModelMapping">添加映射</el-button>
          </div>
          <div class="form-tip">用户请求指定模型时，实际转发到映射后的模型，对用户透明；阶梯映射按日累计用量动态切换</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleUserSubmit">确定</el-button>
      </template>
    </el-dialog>

    <!-- 修改密码对话框 -->
    <el-dialog v-model="passwordDialogVisible" title="修改密码" width="400px" destroy-on-close>
      <el-form ref="passwordFormRef" :model="passwordForm" :rules="passwordFormRules" label-width="80px">
        <el-form-item label="新密码" prop="password">
          <el-input v-model="passwordForm.password" type="password" placeholder="请输入新密码" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="passwordDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handlePasswordSubmit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { authApi, adminApi } from '../api'

const users = ref([])
const availableModels = ref([])
const dialogVisible = ref(false)
const passwordDialogVisible = ref(false)
const isEditing = ref(false)
const submitting = ref(false)
const editingUserId = ref(null)
const passwordUserId = ref(null)

const isAdmin = computed(() => authApi.isAdmin())
const myInfo = computed(() => (!isAdmin.value && users.value.length ? users.value[0] : null))

const userFormRef = ref(null)
const passwordFormRef = ref(null)

const userForm = reactive({
  username: '',
  password: '',
  role: 'user',
  supported_models: [],
  daily_token_limit: null,
  weekly_token_limit: null,
  monthly_token_limit: null,
  // M 单位的显示值（前端用，提交时转回 token 数）
  daily_token_limit_m: null,
  weekly_token_limit_m: null,
  monthly_token_limit_m: null,
  quota_exceeded_mode: 'normal',
  quota_exceeded_message: '',
  model_mapping_list: [],
  show_quota_to_user: false,
})

const passwordForm = reactive({
  password: '',
})

const userFormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 2, message: '用户名至少 2 个字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 个字符', trigger: 'blur' },
  ],
}

const passwordFormRules = {
  password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 个字符', trigger: 'blur' },
  ],
}

const adminCount = computed(() => users.value.filter((u) => u.role === 'admin').length)

const maskApiKey = (key) => {
  if (!key) return ''
  if (key.length <= 12) return '*'.repeat(key.length)
  return `${key.slice(0, 8)}...${key.slice(-4)}`
}

const formatTime = (t) => {
  if (!t) return '-'
  const d = new Date(t)
  if (isNaN(d.getTime())) return t
  return d.toLocaleString('zh-CN', { hour12: false })
}

const formatShortTime = (t) => {
  if (!t) return '-'
  const d = new Date(t)
  if (isNaN(d.getTime())) return t
  const pad = (v) => String(v).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const copyApiKey = async (key) => {
  try {
    await navigator.clipboard.writeText(key)
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}

const quotaUsageMap = ref({})

const loadUsers = async () => {
  try {
    users.value = await authApi.listUsers()
    // 异步加载有限额用户的用量
    loadQuotaUsages()
  } catch (err) {
    ElMessage.error(err.message || '加载用户列表失败')
  }
}

const loadQuotaUsages = async () => {
  const usersWithQuota = users.value.filter(
    (u) => u.daily_token_limit || u.weekly_token_limit || u.monthly_token_limit
  )
  await Promise.all(
    usersWithQuota.map(async (u) => {
      try {
        const data = await adminApi.getUserQuotaUsage(u.id)
        quotaUsageMap.value = { ...quotaUsageMap.value, [u.id]: data }
      } catch { /* 静默失败 */ }
    })
  )
}

const formatQuotaUsage = (used, limit) => {
  if (used === undefined || used === null) return Number(limit).toLocaleString('zh-CN')
  const pct = limit ? Math.round((used / limit) * 100) : 0
  return `${Number(used).toLocaleString('zh-CN')} / ${Number(limit).toLocaleString('zh-CN')}`
}

const formatQuotaUsageM = (used, limit) => {
  const toM = (v) => v != null ? (Math.round(v / M * 100) / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 2 }) : '0'
  if (used === undefined || used === null) return `${toM(limit)} M`
  return `${toM(used)} / ${toM(limit)} M`
}

const handleResetQuota = async (row) => {
  try {
    await adminApi.resetUserQuota(row.id)
    ElMessage.success(`已重置 ${row.username} 的额度计数`)
    // 刷新该用户用量
    const data = await adminApi.getUserQuotaUsage(row.id)
    quotaUsageMap.value = { ...quotaUsageMap.value, [row.id]: data }
  } catch (e) {
    ElMessage.error(e.message || '重置失败')
  }
}

const loadModels = async () => {
  try {
    const res = await adminApi.listModels(null, { limit: 500 })
    const items = Array.isArray(res) ? res : (res?.items || [])
    availableModels.value = items.map((m) => m.model_id || m.name).filter(Boolean)
  } catch {
    // 模型列表加载失败不影响用户管理
  }
}

const showAddDialog = () => {
  isEditing.value = false
  editingUserId.value = null
  userForm.username = ''
  userForm.password = ''
  userForm.role = 'user'
  userForm.supported_models = []
  userForm.daily_token_limit = null
  userForm.weekly_token_limit = null
  userForm.monthly_token_limit = null
  userForm.daily_token_limit_m = null
  userForm.weekly_token_limit_m = null
  userForm.monthly_token_limit_m = null
  userForm.quota_exceeded_mode = 'normal'
  userForm.quota_exceeded_message = ''
  userForm.model_mapping_list = []
  userForm.show_quota_to_user = false
  dialogVisible.value = true
}

const showEditDialog = (row) => {
  isEditing.value = true
  editingUserId.value = row.id
  userForm.username = row.username
  userForm.password = ''
  userForm.role = row.role || 'user'
  userForm.supported_models = [...(row.supported_models || [])]
  userForm.daily_token_limit = row.daily_token_limit ?? null
  userForm.weekly_token_limit = row.weekly_token_limit ?? null
  userForm.monthly_token_limit = row.monthly_token_limit ?? null
  userForm.daily_token_limit_m = tokensToM(row.daily_token_limit)
  userForm.weekly_token_limit_m = tokensToM(row.weekly_token_limit)
  userForm.monthly_token_limit_m = tokensToM(row.monthly_token_limit)
  userForm.quota_exceeded_mode = row.quota_exceeded_mode || 'normal'
  userForm.quota_exceeded_message = row.quota_exceeded_message || ''
  userForm.model_mapping_list = Object.entries(row.model_mapping || {}).map(([from, rule]) => {
    if (Array.isArray(rule)) {
      return {
        from,
        to: '',
        mode: 'tiered',
        tiers: rule.map((t) => ({
          from: tokensToM(t.from ?? 0),
          to: t.to != null ? tokensToM(t.to) : null,
          model: t.model || '',
        })),
      }
    }
    return { from, to: rule || '', mode: 'simple', tiers: [] }
  })
  userForm.show_quota_to_user = !!row.show_quota_to_user
  dialogVisible.value = true
}

const M = 1_000_000
const tokensToM = (v) => (v != null ? Math.round(v / M * 100) / 100 : null)
const mToTokens = (v) => (v != null && v !== '' ? Math.round(Number(v) * M) : null)

const addModelMapping = () => {
  userForm.model_mapping_list.push({ from: '', to: '', mode: 'simple', tiers: [] })
}

const removeModelMapping = (idx) => {
  userForm.model_mapping_list.splice(idx, 1)
}

const onMappingModeChange = (item) => {
  if (item.mode === 'tiered' && !item.tiers.length) {
    item.tiers = [{ from: 0, to: null, model: '' }]
  }
}

const addTier = (item) => {
  const lastTier = item.tiers[item.tiers.length - 1]
  const nextFrom = lastTier?.to != null ? lastTier.to : 0
  item.tiers.push({ from: nextFrom, to: null, model: '' })
}

const removeTier = (item, tidx) => {
  item.tiers.splice(tidx, 1)
}

const buildModelMapping = () => {
  const mapping = {}
  userForm.model_mapping_list.forEach(({ from, to, mode, tiers }) => {
    const f = (from || '').trim()
    if (!f) return
    if (mode === 'tiered') {
      const validTiers = (tiers || [])
        .filter((t) => t.model && t.model.trim())
        .map((t) => ({
          from: Math.round((Number(t.from) || 0) * M),
          to: t.to != null && t.to !== '' ? Math.round(Number(t.to) * M) : null,
          model: t.model.trim(),
        }))
      if (validTiers.length) mapping[f] = validTiers
    } else {
      const t = (to || '').trim()
      if (t) mapping[f] = t
    }
  })
  return Object.keys(mapping).length ? mapping : null
}

const showPasswordDialog = (row) => {
  passwordUserId.value = row.id
  passwordForm.password = ''
  passwordDialogVisible.value = true
}

const handleUserSubmit = async () => {
  if (!userFormRef.value) return
  try {
    await userFormRef.value.validate()
  } catch {
    return
  }

  submitting.value = true
  try {
    if (isEditing.value) {
      await authApi.updateUser(editingUserId.value, {
        username: userForm.username,
        role: userForm.role,
        supported_models: userForm.supported_models.length ? userForm.supported_models : null,
        daily_token_limit: mToTokens(userForm.daily_token_limit_m),
        weekly_token_limit: mToTokens(userForm.weekly_token_limit_m),
        monthly_token_limit: mToTokens(userForm.monthly_token_limit_m),
        clear_daily_limit: userForm.daily_token_limit_m === null,
        clear_weekly_limit: userForm.weekly_token_limit_m === null,
        clear_monthly_limit: userForm.monthly_token_limit_m === null,
        quota_exceeded_mode: userForm.quota_exceeded_mode,
        quota_exceeded_message: userForm.quota_exceeded_message || null,
        model_mapping: buildModelMapping(),
        show_quota_to_user: userForm.show_quota_to_user,
      })
      ElMessage.success('用户已更新')
    } else {
      await authApi.createUser({
        username: userForm.username,
        password: userForm.password,
        supported_models: userForm.supported_models.length ? userForm.supported_models : null,
        daily_token_limit: mToTokens(userForm.daily_token_limit_m),
        weekly_token_limit: mToTokens(userForm.weekly_token_limit_m),
        monthly_token_limit: mToTokens(userForm.monthly_token_limit_m),
        quota_exceeded_mode: userForm.quota_exceeded_mode,
        quota_exceeded_message: userForm.quota_exceeded_message || null,
        model_mapping: buildModelMapping(),
        show_quota_to_user: userForm.show_quota_to_user,
      })
      ElMessage.success('用户已创建')
    }
    dialogVisible.value = false
    await loadUsers()
  } catch (err) {
    ElMessage.error(err.message || '操作失败')
  } finally {
    submitting.value = false
  }
}

const handlePasswordSubmit = async () => {
  if (!passwordFormRef.value) return
  try {
    await passwordFormRef.value.validate()
  } catch {
    return
  }

  submitting.value = true
  try {
    await authApi.updateUser(passwordUserId.value, { password: passwordForm.password })
    ElMessage.success('密码已修改')
    passwordDialogVisible.value = false
  } catch (err) {
    ElMessage.error(err.message || '修改失败')
  } finally {
    submitting.value = false
  }
}

const handleRegenerateKey = async (row) => {
  try {
    const res = await authApi.regenerateUserKey(row.id)
    if (res.api_key) {
      ElMessage.success('API Key 已重新生成')
      await loadUsers()
    }
  } catch (err) {
    ElMessage.error(err.message || '操作失败')
  }
}

const handleDeleteUser = async (row) => {
  try {
    await authApi.deleteUser(row.id)
    ElMessage.success('用户已删除')
    await loadUsers()
  } catch (err) {
    ElMessage.error(err.message || '删除失败')
  }
}

const handleMyRegenerateKey = async () => {
  try {
    const res = await authApi.regenerateMyKey()
    if (res.api_key) {
      ElMessage.success('API Key 已重新生成')
      await loadUsers()
    }
  } catch (err) {
    ElMessage.error(err.message || '操作失败')
  }
}

const showMyPasswordDialog = () => {
  if (!myInfo.value) return
  passwordUserId.value = myInfo.value.id
  passwordForm.password = ''
  passwordDialogVisible.value = true
}

onMounted(() => {
  loadUsers()
  loadModels()
})
</script>

<style scoped>
.user-manage {
  max-width: 1200px;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.form-grid-3 {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0 20px;
}

.form-grid-2 {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0 20px;
}

.form-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

.page-header-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.page-kicker {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--cpa-primary);
  font-weight: 700;
}

.page-title {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: var(--cpa-text);
}

.header-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.table-card {
  border-radius: var(--cpa-radius-lg);
  background: var(--cpa-surface-strong);
  border: 1px solid var(--cpa-border);
}

.api-key-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.api-key-text {
  font-family: monospace;
  font-size: 12px;
  color: var(--cpa-text-secondary);
}

.model-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.model-tag {
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.text-muted {
  color: var(--cpa-text-tertiary);
  font-size: 12px;
}

.profile-card {
  max-width: 600px;
  border-radius: var(--cpa-radius-lg);
  background: var(--cpa-surface-strong);
  border: 1px solid var(--cpa-border);
}

.profile-row {
  display: flex;
  align-items: center;
  padding: 14px 0;
  border-bottom: 1px solid var(--cpa-border);
}

.profile-row:last-of-type {
  border-bottom: none;
}

.profile-label {
  width: 100px;
  flex-shrink: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--cpa-text-secondary);
}

.profile-value {
  flex: 1;
  font-size: 13px;
  color: var(--cpa-text);
}

.profile-actions {
  display: flex;
  gap: 10px;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--cpa-border);
}
</style>
