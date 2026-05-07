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
      <el-table :data="users" stripe style="width: 100%">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="username" label="用户名" min-width="120" />
        <el-table-column label="角色" width="100">
          <template #default="{ row }">
            <el-tag :type="row.role === 'admin' ? 'danger' : 'info'" size="small">
              {{ row.role === 'admin' ? '管理员' : '普通用户' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="API Key" min-width="240">
          <template #default="{ row }">
            <div v-if="row.api_key" class="api-key-cell">
              <span class="api-key-text">{{ maskApiKey(row.api_key) }}</span>
              <el-button link type="primary" size="small" @click="copyApiKey(row.api_key)">复制</el-button>
            </div>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="可用模型" min-width="200">
          <template #default="{ row }">
            <div v-if="row.supported_models && row.supported_models.length" class="model-tags">
              <el-tag v-for="m in row.supported_models.slice(0, 3)" :key="m" size="small" class="model-tag">{{ m }}</el-tag>
              <el-popover v-if="row.supported_models.length > 3" trigger="hover" width="300">
                <template #reference>
                  <el-tag size="small" class="model-tag">+{{ row.supported_models.length - 3 }}</el-tag>
                </template>
                <div class="model-popover">
                  <el-tag v-for="m in row.supported_models" :key="m" size="small" class="model-tag">{{ m }}</el-tag>
                </div>
              </el-popover>
            </div>
            <span v-else class="text-muted">全部模型</span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">
            {{ row.created_at ? formatTime(row.created_at) : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="showEditDialog(row)">编辑</el-button>
            <el-button link type="primary" size="small" @click="handleRegenerateKey(row)">重置Key</el-button>
            <el-button link type="primary" size="small" @click="showPasswordDialog(row)">改密码</el-button>
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
      width="500px"
      destroy-on-close
    >
      <el-form ref="userFormRef" :model="userForm" :rules="userFormRules" label-width="80px">
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

const copyApiKey = async (key) => {
  try {
    await navigator.clipboard.writeText(key)
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}

const loadUsers = async () => {
  try {
    users.value = await authApi.listUsers()
  } catch (err) {
    ElMessage.error(err.message || '加载用户列表失败')
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
  dialogVisible.value = true
}

const showEditDialog = (row) => {
  isEditing.value = true
  editingUserId.value = row.id
  userForm.username = row.username
  userForm.password = ''
  userForm.role = row.role || 'user'
  userForm.supported_models = [...(row.supported_models || [])]
  dialogVisible.value = true
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
      })
      ElMessage.success('用户已更新')
    } else {
      await authApi.createUser({
        username: userForm.username,
        password: userForm.password,
        supported_models: userForm.supported_models.length ? userForm.supported_models : null,
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
