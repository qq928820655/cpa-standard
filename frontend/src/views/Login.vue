<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-logo">
        <div class="login-logo__mark">CPA</div>
        <p class="login-logo__subtitle">{{ isSetup ? '初始化管理员账户' : '系统登录' }}</p>
      </div>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        class="login-form"
        @submit.prevent="handleSubmit"
      >
        <el-form-item label="用户名" prop="username">
          <el-input
            v-model="form.username"
            placeholder="请输入用户名"
            size="large"
            :disabled="loading"
            @keyup.enter="handleSubmit"
          />
        </el-form-item>

        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            size="large"
            show-password
            :disabled="loading"
            @keyup.enter="handleSubmit"
          />
        </el-form-item>

        <el-form-item v-if="isSetup" label="确认密码" prop="confirmPassword">
          <el-input
            v-model="form.confirmPassword"
            type="password"
            placeholder="请再次输入密码"
            size="large"
            show-password
            :disabled="loading"
            @keyup.enter="handleSubmit"
          />
        </el-form-item>

        <el-form-item>
          <el-button
            type="primary"
            size="large"
            class="login-submit"
            :loading="loading"
            @click="handleSubmit"
          >
            {{ isSetup ? '创建账户并登录' : '登录' }}
          </el-button>
        </el-form-item>
      </el-form>

      <div class="login-footer">
        <div v-if="!isSetup && loginEnabled" class="login-register-link">
          <router-link to="/register">注册新账户</router-link>
        </div>
        <span>CPA · Central Proxy for APIs</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { authApi, saveSessionUser } from '../api'

const router = useRouter()
const route = useRoute()
const formRef = ref(null)
const loading = ref(false)
const isSetup = ref(false)
const loginEnabled = ref(false)

const form = reactive({
  username: '',
  password: '',
  confirmPassword: '',
})

const validateConfirmPassword = (rule, value, callback) => {
  if (isSetup.value && value !== form.password) {
    callback(new Error('两次输入的密码不一致'))
  } else {
    callback()
  }
}

const rules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 2, message: '用户名至少 2 个字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 个字符', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    { validator: validateConfirmPassword, trigger: 'blur' },
  ],
}

const checkStatus = async () => {
  try {
    const res = await authApi.status()
    loginEnabled.value = res.login_enabled
    // 登录未启用，直接跳转首页
    if (!res.login_enabled) {
      router.replace('/dashboard')
      return
    }
    isSetup.value = !res.initialized
    if (route.query.mode === 'setup' && res.initialized) {
      isSetup.value = false
    }
  } catch {
    isSetup.value = route.query.mode === 'setup'
  }
}

const handleSubmit = async () => {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch {
    return
  }

  loading.value = true
  try {
    let res
    if (isSetup.value) {
      res = await authApi.setup(form.username, form.password)
    } else {
      res = await authApi.login(form.username, form.password)
    }

    if (res.token) {
      saveSessionUser(res)
    }

    ElMessage.success(isSetup.value ? '账户创建成功' : '登录成功')
    router.push('/dashboard')
  } catch (err) {
    ElMessage.error(err.message || '操作失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  checkStatus()
})
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--cpa-page-bg);
  padding: 20px;
}

.login-card {
  width: 100%;
  max-width: 400px;
  padding: 40px 36px 32px;
  border-radius: var(--cpa-radius-lg);
  background: var(--cpa-surface-strong);
  border: 1px solid var(--cpa-border);
  box-shadow: var(--cpa-shadow);
  backdrop-filter: blur(16px);
}

.login-logo {
  text-align: center;
  margin-bottom: 32px;
}

.login-logo__mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 72px;
  height: 72px;
  border-radius: 20px;
  background: var(--cpa-brand-gradient);
  color: #fff;
  font-size: 28px;
  font-weight: 800;
  letter-spacing: 0.02em;
  box-shadow: var(--cpa-brand-shadow);
  margin-bottom: 16px;
}

.login-logo__subtitle {
  font-size: 16px;
  font-weight: 600;
  color: var(--cpa-text);
  margin: 0;
}

.login-form {
  margin-top: 8px;
}

.login-form :deep(.el-form-item__label) {
  font-weight: 600;
  color: var(--cpa-text-secondary);
  font-size: 13px;
  padding-bottom: 4px;
}

.login-form :deep(.el-input__wrapper) {
  border-radius: var(--cpa-radius-sm);
  background: var(--cpa-input-bg);
  border: 1px solid var(--cpa-input-border);
  box-shadow: none;
  padding: 4px 12px;
}

.login-form :deep(.el-input__wrapper:hover) {
  border-color: var(--cpa-primary);
}

.login-form :deep(.el-input__wrapper.is-focus) {
  border-color: var(--cpa-primary);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12);
}

.login-submit {
  width: 100%;
  height: 44px;
  border-radius: var(--cpa-radius-sm);
  font-size: 15px;
  font-weight: 600;
  background: var(--cpa-brand-gradient);
  border: none;
  color: #fff;
  margin-top: 8px;
}

.login-submit:hover {
  opacity: 0.92;
}

.login-footer {
  text-align: center;
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid var(--cpa-border);
}

.login-footer span {
  font-size: 12px;
  color: var(--cpa-text-tertiary);
}

.login-register-link {
  margin-bottom: 8px;
}

.login-register-link a {
  font-size: 13px;
  color: var(--cpa-primary);
  text-decoration: none;
}

.login-register-link a:hover {
  text-decoration: underline;
}
</style>
