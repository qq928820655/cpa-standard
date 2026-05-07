<template>
  <div class="settings page-shell">
    <div class="page-header">
      <div class="page-header-main">
        <div class="page-kicker">System</div>
        <h2 class="page-title">系统设置</h2>
        <p class="page-subtitle">集中管理后台认证、代理超时与接入说明，并支持一键导出到 CC Switch 便于本地应用接入。</p>
      </div>
    </div>

    <el-card class="setting-card" shadow="never">
      <template #header>
        <div>
          <div class="panel-title">认证配置</div>
          <div class="panel-subtitle">查看 Master Key、本地保存管理凭证，并快速导出到 CC Switch 完成客户端接入</div>
        </div>
      </template>

      <el-form label-width="120px">
        <el-form-item label="登录验证">
          <el-switch
            v-model="loginEnabled"
            active-text="开启"
            inactive-text="关闭"
            @change="handleLoginToggle"
          />
          <div class="form-tip">开启后访问管理页面需先登录，关闭则直接访问</div>
        </el-form-item>

        <el-form-item label="Master Key">
          <el-input
            v-model="masterKey"
            :type="showMasterKey ? 'text' : 'password'"
            readonly
            style="max-width: 500px"
          >
            <template #append>
              <el-button class="master-key-append-button" @click="showMasterKey = !showMasterKey">
                <el-icon>
                  <View v-if="!showMasterKey" />
                  <Hide v-else />
                </el-icon>
              </el-button>
              <el-button class="master-key-append-button" @click="copyMasterKey">
                <el-icon><CopyDocument /></el-icon>
              </el-button>
            </template>
          </el-input>
          <div class="form-tip">此 Key 用于访问本系统的所有 API，请妥善保管</div>
        </el-form-item>

        <el-form-item label="本地 Key 配置">
          <el-input
            v-model="localMasterKey"
            placeholder="输入 Master Key 以启用管理功能"
            style="max-width: 500px"
          >
            <template #append>
              <el-button type="primary" @click="saveMasterKey">保存</el-button>
            </template>
          </el-input>
          <div class="form-tip">在浏览器本地保存 Master Key，用于调用管理接口</div>
        </el-form-item>

        <el-form-item label="导出到 CC Switch">
          <el-button type="primary" @click="openCcSwitchDialog">导出到 CC Switch</el-button>
          <div class="form-tip">支持 Claude、Codex、Gemini 三种应用导入</div>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="setting-card" shadow="never">
      <template #header>
        <div>
          <div class="panel-title">代理超时配置</div>
          <div class="panel-subtitle">统一设置普通请求与流式请求的超时策略，平衡稳定性与响应体验</div>
        </div>
      </template>

      <el-form label-width="160px" v-loading="proxyTimeoutLoading">
        <el-form-item label="普通请求超时">
          <el-input-number v-model="proxyTimeoutForm.proxy_request_timeout_seconds" :min="1" />
          <div class="form-tip">非流式请求的整体等待时间，单位秒。</div>
        </el-form-item>

        <el-form-item label="流式连接超时">
          <el-input-number v-model="proxyTimeoutForm.proxy_stream_connect_timeout_seconds" :min="1" />
          <div class="form-tip">建立流式连接时的超时时间，单位秒。</div>
        </el-form-item>

        <el-form-item label="流式首包超时">
          <el-input-number v-model="proxyTimeoutForm.proxy_stream_first_byte_timeout_seconds" :min="1" />
          <div class="form-tip">连接建立后等待首个数据块的时间，单位秒。</div>
        </el-form-item>

        <el-form-item label="流式读取超时">
          <el-input-number v-model="proxyTimeoutForm.proxy_stream_read_timeout_seconds" :min="1" />
          <div class="form-tip">流式传输过程中后续数据读取超时，单位秒。</div>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="proxyTimeoutSaving" @click="saveProxyTimeoutConfig">保存超时配置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="setting-card" shadow="never">
      <el-collapse v-model="imageAutoRefreshPanels" class="setting-collapse">
        <el-collapse-item name="image-auto-refresh">
          <template #title>
            <div class="setting-collapse-title">
              <div class="panel-title">图片自动回填配置</div>
              <div class="panel-subtitle">配置 Cloudflare 超时后自动查询上游任务日志的等待、间隔与最大次数</div>
            </div>
          </template>

          <el-form label-width="180px" v-loading="imageAutoRefreshLoading">
            <el-form-item label="初始等待">
              <el-input-number v-model="imageAutoRefreshForm.image_auto_refresh_delay_seconds" :min="0" :max="3600" />
              <div class="form-tip">出现 Cloudflare 类超时后，等待多少秒开始第一次获取。</div>
            </el-form-item>

            <el-form-item label="获取间隔">
              <el-input-number v-model="imageAutoRefreshForm.image_auto_refresh_interval_seconds" :min="1" :max="3600" />
              <div class="form-tip">第一次获取失败后，每隔多少秒再次获取。</div>
            </el-form-item>

            <el-form-item label="最大获取次数">
              <el-input-number v-model="imageAutoRefreshForm.image_auto_refresh_max_attempts" :min="1" :max="100" />
              <div class="form-tip">该次回填最多获取多少次，成功后立即停止。</div>
            </el-form-item>

            <el-form-item>
              <el-button type="primary" :loading="imageAutoRefreshSaving" @click="saveImageAutoRefreshConfig">保存自动回填配置</el-button>
            </el-form-item>
          </el-form>
        </el-collapse-item>
      </el-collapse>
    </el-card>

    <el-card class="setting-card" shadow="never">
      <el-collapse v-model="staleTaskCleanupPanels" class="setting-collapse">
        <el-collapse-item name="stale-task-cleanup">
          <template #title>
            <div class="setting-collapse-title">
              <div class="panel-title">过期任务回收配置</div>
              <div class="panel-subtitle">配置后台定时检查并关闭超时图片任务的间隔</div>
            </div>
          </template>

          <div v-loading="staleTaskCleanupLoading">
            <div class="cleanup-two-col">
              <div class="cleanup-col">
                <div class="cleanup-label">回收间隔（秒）</div>
                <el-input-number v-model="staleTaskCleanupForm.image_stale_task_cleanup_interval_seconds" :min="10" :max="3600" style="width: 100%" />
                <div class="form-tip">每隔多少秒检查一次过期图片任务，范围 10 ~ 3600</div>
              </div>
              <div class="cleanup-col">
                <div class="cleanup-label">历史刷新间隔（秒）</div>
                <el-input-number v-model="staleTaskCleanupForm.image_history_refresh_interval_seconds" :min="1" :max="60" style="width: 100%" />
                <div class="form-tip">点击生成后，历史记录列表自动刷新的间隔，范围 1 ~ 60</div>
              </div>
              <div class="cleanup-col">
                <div class="cleanup-label">元数据清理间隔（秒）</div>
                <el-input-number v-model="staleTaskCleanupForm.image_result_meta_cleanup_interval_seconds" :min="60" :max="86400" style="width: 100%" />
                <div class="form-tip">定时清空超过 3 小时未回填的冗余字段，范围 60 ~ 86400</div>
              </div>
            </div>
            <div style="margin-top: 12px">
              <el-button type="primary" :loading="staleTaskCleanupSaving" @click="saveStaleTaskCleanupConfig">保存回收配置</el-button>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>
    </el-card>

    <el-card class="setting-card" shadow="never">
      <template #header>
        <div>
          <div class="panel-title">默认检测模型</div>
          <div class="panel-subtitle">统一设置 Key 管理页“一键检测”弹窗默认带出的模型名称，留空表示每次手动输入</div>
        </div>
      </template>

      <el-form label-width="160px" v-loading="keyCheckDefaultLoading">
        <el-form-item label="默认检测模型">
          <el-input
            v-model="keyCheckDefaultForm.default_key_check_model"
            clearable
            placeholder="留空表示不预填默认模型"
            style="max-width: 500px"
          />
          <div class="form-tip">保存后，Key 管理页点击“一键检测”会优先带出这里的值，仍可在弹窗里手动修改。</div>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="keyCheckDefaultSaving" @click="saveKeyCheckDefaultConfig">保存默认检测模型</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="setting-card" shadow="never">
      <template #header>
        <div>
          <div class="panel-title">快捷检测模型</div>
          <div class="panel-subtitle">配置 Key 管理页一键检测弹窗的六个快捷按钮，第一项默认来自上面的检测模型</div>
        </div>
      </template>

      <el-form label-width="160px" v-loading="keyCheckShortcutLoading">
        <div class="shortcut-model-input-grid">
          <el-form-item label="快捷模型 1">
            <el-input v-model="keyCheckShortcutForm.shortcut_models[0]" clearable placeholder="默认带出检测模型" style="max-width: 500px" />
          </el-form-item>
          <el-form-item label="快捷模型 2">
            <el-input v-model="keyCheckShortcutForm.shortcut_models[1]" clearable placeholder="第二个快捷模型" style="max-width: 500px" />
          </el-form-item>
          <el-form-item label="快捷模型 3">
            <el-input v-model="keyCheckShortcutForm.shortcut_models[2]" clearable placeholder="第三个快捷模型" style="max-width: 500px" />
          </el-form-item>
          <el-form-item label="快捷模型 4">
            <el-input v-model="keyCheckShortcutForm.shortcut_models[3]" clearable placeholder="第四个快捷模型" style="max-width: 500px" />
          </el-form-item>
          <el-form-item label="快捷模型 5">
            <el-input v-model="keyCheckShortcutForm.shortcut_models[4]" clearable placeholder="第五个快捷模型" style="max-width: 500px" />
          </el-form-item>
          <el-form-item label="快捷模型 6">
            <el-input v-model="keyCheckShortcutForm.shortcut_models[5]" clearable placeholder="第六个快捷模型" style="max-width: 500px" />
          </el-form-item>
        </div>
        <el-form-item>
          <el-button type="primary" :loading="keyCheckShortcutSaving" @click="saveKeyCheckShortcutModels">保存快捷模型</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="setting-card" shadow="never">
      <template #header>
        <div>
          <div class="panel-title">使用说明</div>
          <div class="panel-subtitle">快速获取代理地址、认证方式和接入示例，降低本地应用接入成本</div>
        </div>
      </template>

      <div class="usage-guide">
        <h4>1. 配置 API Key</h4>
        <p>在「Key 管理」页面添加您的 OpenAI 或 Claude API Key。</p>

        <h4>2. 使用代理接口</h4>
        <p>将您的应用配置为使用本系统的代理地址：</p>

        <el-descriptions :column="1" border>
          <el-descriptions-item label="代理地址">
            <code>http://127.0.0.1:8000</code>
          </el-descriptions-item>
          <el-descriptions-item label="认证方式">
            <code>Authorization: Bearer {{ masterKey || 'YOUR_MASTER_KEY' }}</code>
          </el-descriptions-item>
        </el-descriptions>

        <h4>3. 兼容接口</h4>
        <el-table :data="endpoints" stripe size="small">
          <el-table-column prop="method" label="方法" width="80" />
          <el-table-column prop="path" label="路径" />
          <el-table-column prop="description" label="说明" />
        </el-table>

        <h4>4. 示例代码</h4>
        <el-tabs>
          <el-tab-pane label="Python (OpenAI)">
            <pre class="code-block">from openai import OpenAI

client = OpenAI(
    api_key="{{ masterKey || 'YOUR_MASTER_KEY' }}",
    base_url="http://127.0.0.1:8000/v1"
)

response = client.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "{{ usageGuideDefaultContent }}"}]
)</pre>
          </el-tab-pane>
          <el-tab-pane label="Python (Claude)">
            <pre class="code-block">import anthropic

client = anthropic.Anthropic(
    api_key="{{ masterKey || 'YOUR_MASTER_KEY' }}",
    base_url="http://127.0.0.1:8000"
)

message = client.messages.create(
    model="claude-3-sonnet-20240229",
    max_tokens=1024,
    messages=[{"role": "user", "content": "{{ usageGuideDefaultContent }}"}]
)</pre>
          </el-tab-pane>
          <el-tab-pane label="cURL">
            <pre class="code-block">curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer {{ masterKey || 'YOUR_MASTER_KEY' }}" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "{{ usageGuideDefaultContent }}"}]
  }'</pre>
          </el-tab-pane>
        </el-tabs>
      </div>
    </el-card>

    <el-card v-if="loginEnabled && authApi.isLoggedIn()" class="setting-card" shadow="never">
      <template #header>
        <div>
          <div class="panel-title">修改密码</div>
          <div class="panel-subtitle">修改管理后台的登录密码</div>
        </div>
      </template>

      <el-form
        ref="passwordFormRef"
        :model="passwordForm"
        :rules="passwordRules"
        label-width="120px"
      >
        <el-form-item label="旧密码" prop="oldPassword">
          <el-input
            v-model="passwordForm.oldPassword"
            type="password"
            show-password
            placeholder="请输入旧密码"
            style="max-width: 400px"
          />
        </el-form-item>

        <el-form-item label="新密码" prop="newPassword">
          <el-input
            v-model="passwordForm.newPassword"
            type="password"
            show-password
            placeholder="请输入新密码（至少 6 位）"
            style="max-width: 400px"
          />
        </el-form-item>

        <el-form-item label="确认新密码" prop="confirmPassword">
          <el-input
            v-model="passwordForm.confirmPassword"
            type="password"
            show-password
            placeholder="请再次输入新密码"
            style="max-width: 400px"
          />
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="passwordSaving" @click="handleChangePassword">
            修改密码
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-dialog v-model="ccSwitchDialogVisible" title="填入 CC Switch" width="720px">
      <el-form ref="ccSwitchFormRef" :model="ccSwitchForm" :rules="ccSwitchRules" label-position="top">
        <el-form-item label="应用">
          <el-radio-group v-model="selectedApp" @change="handleAppChange">
            <el-radio-button label="claude">Claude</el-radio-button>
            <el-radio-button label="codex">Codex</el-radio-button>
            <el-radio-button label="gemini">Gemini</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="名称" prop="name">
          <el-input v-model="ccSwitchForm.name" @input="nameTouched = true" />
        </el-form-item>

        <el-form-item label="主模型" prop="model" required>
          <div class="model-field-wrap">
            <el-input v-model="mainModelKeyword" clearable placeholder="搜索模型名称 / ID / 别名" />
            <el-select v-model="ccSwitchForm.model" filterable clearable placeholder="请选择模型">
              <el-option
                v-for="item in filteredMainModels"
                :key="item.model_id"
                :label="`${item.display_name || item.model_id} (${item.model_id})`"
                :value="item.model_id"
              />
            </el-select>
          </div>
        </el-form-item>

        <el-form-item>
          <template #label>
            <div class="cc-switch-label-row">
              <span>快捷模型</span>
              <span class="cc-switch-label-tip">支持一键填充，首个按钮来自默认检测模型</span>
            </div>
          </template>
          <div class="shortcut-model-grid">
            <el-button
              v-for="item in shortcutModelButtons"
              :key="item.label"
              :type="ccSwitchForm.model === item.value ? 'primary' : 'default'"
              plain
              class="shortcut-model-button"
              @click="applyShortcutModel(item.value)"
            >
              <span class="shortcut-model-button__label">{{ item.label }}</span>
              <span class="shortcut-model-button__value">{{ item.value || '未配置' }}</span>
            </el-button>
          </div>
        </el-form-item>

        <el-form-item label="API Key">
          <el-input v-model="ccSwitchForm.api_key" />
        </el-form-item>

        <el-form-item label="Base URL">
          <el-input v-model="ccSwitchForm.base_url" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="ccSwitchDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="openingCcSwitch" @click="openCcSwitch">
          打开 CC Switch
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi, authApi } from '../api'

const masterKey = ref('')
const localMasterKey = ref('')
const showMasterKey = ref(false)
const loginEnabled = ref(false)
const modelOptions = ref([])
const exportMeta = ref(null)
const usageGuideDefaultContent = computed(() => exportMeta.value?.usage_guide_default_content || 'hello!')
const proxyTimeoutLoading = ref(false)
const proxyTimeoutSaving = ref(false)
const imageAutoRefreshLoading = ref(false)
const imageAutoRefreshSaving = ref(false)
const imageAutoRefreshPanels = ref([])
const staleTaskCleanupLoading = ref(false)
const staleTaskCleanupSaving = ref(false)
const staleTaskCleanupPanels = ref([])
const keyCheckDefaultLoading = ref(false)
const keyCheckDefaultSaving = ref(false)
const keyCheckShortcutLoading = ref(false)
const keyCheckShortcutSaving = ref(false)
const ccSwitchDialogVisible = ref(false)
const selectedApp = ref('claude')
const openingCcSwitch = ref(false)
const ccSwitchFormRef = ref(null)
const nameTouched = ref(false)
const mainModelKeyword = ref('')
const haikuModelKeyword = ref('')
const sonnetModelKeyword = ref('')
const opusModelKeyword = ref('')

// 修改密码
const passwordFormRef = ref(null)
const passwordSaving = ref(false)
const passwordForm = reactive({
  oldPassword: '',
  newPassword: '',
  confirmPassword: '',
})
const validateConfirmNewPassword = (rule, value, callback) => {
  if (value !== passwordForm.newPassword) {
    callback(new Error('两次输入的密码不一致'))
  } else {
    callback()
  }
}
const passwordRules = {
  oldPassword: [{ required: true, message: '请输入旧密码', trigger: 'blur' }],
  newPassword: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '新密码至少 6 个字符', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    { validator: validateConfirmNewPassword, trigger: 'blur' },
  ],
}

const ccSwitchForm = reactive({
  name: '',
  model: '',
  haikuModel: '',
  sonnetModel: '',
  opusModel: '',
})

const proxyTimeoutForm = reactive({
  proxy_request_timeout_seconds: 60,
  proxy_stream_connect_timeout_seconds: 15,
  proxy_stream_first_byte_timeout_seconds: 15,
  proxy_stream_read_timeout_seconds: 45,
})

const imageAutoRefreshForm = reactive({
  image_auto_refresh_delay_seconds: 60,
  image_auto_refresh_interval_seconds: 30,
  image_auto_refresh_max_attempts: 10,
})

const staleTaskCleanupForm = reactive({
  image_stale_task_cleanup_interval_seconds: 60,
  image_history_refresh_interval_seconds: 5,
  image_result_meta_cleanup_interval_seconds: 1800,
})

const keyCheckDefaultForm = reactive({
  default_key_check_model: '',
})

const keyCheckShortcutForm = reactive({
  shortcut_models: ['', '', '', '', '', ''],
})

const ccSwitchRules = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  model: [{ required: true, message: '请选择主模型', trigger: 'change' }],
}

const endpoints = [
  { method: 'POST', path: '/v1/chat/completions', description: 'OpenAI Chat Completions' },
  { method: 'POST', path: '/v1/completions', description: 'OpenAI Completions' },
  { method: 'POST', path: '/v1/embeddings', description: 'OpenAI Embeddings' },
  { method: 'GET', path: '/v1/models', description: 'OpenAI Models 列表' },
  { method: 'POST', path: '/v1/messages', description: 'Claude Messages' },
]

const defaultNames = computed(() => exportMeta.value?.default_names || {
  claude: 'local Claude',
  codex: 'local Codex',
  gemini: 'local Gemini',
})

const filterModels = (items, keyword) => {
  const text = keyword.trim().toLowerCase()
  if (!text) return items
  return items.filter((item) => {
    const label = `${item.display_name || ''} ${item.model_id || ''} ${(item.aliases || []).join(' ')}`.toLowerCase()
    return label.includes(text)
  })
}

const filteredMainModels = computed(() => filterModels(modelOptions.value, mainModelKeyword.value))
const filteredHaikuModels = computed(() => filterModels(modelOptions.value, haikuModelKeyword.value))
const filteredSonnetModels = computed(() => filterModels(modelOptions.value, sonnetModelKeyword.value))
const filteredOpusModels = computed(() => filterModels(modelOptions.value, opusModelKeyword.value))
const shortcutModelButtons = computed(() => {
  const items = keyCheckShortcutForm.shortcut_models.slice(0, 6)
  return [
    { label: '默认检测模型', value: items[0] || keyCheckDefaultForm.default_key_check_model || '' },
    { label: '快捷模型 2', value: items[1] || '' },
    { label: '快捷模型 3', value: items[2] || '' },
    { label: '快捷模型 4', value: items[3] || '' },
    { label: '快捷模型 5', value: items[4] || '' },
    { label: '快捷模型 6', value: items[5] || '' },
  ]
})

const loadMasterKey = async () => {
  localMasterKey.value = localStorage.getItem('masterKey') || ''
  try {
    const data = await adminApi.getMasterKey()
    masterKey.value = data.master_key
    if (data.master_key) {
      localMasterKey.value = data.master_key
      localStorage.setItem('masterKey', data.master_key)
    }
  } catch (e) {
    masterKey.value = localMasterKey.value
  }
}

const loadModels = async () => {
  try {
    const result = await adminApi.listModels()
    modelOptions.value = Array.isArray(result) ? result : (result.items || [])
  } catch (e) {
    ElMessage.error(e.message)
  }
}

const loadExportMeta = async () => {
  try {
    exportMeta.value = await adminApi.exportConfig()
  } catch (e) {
    ElMessage.error(e.message)
    throw e
  }
}

const loadProxyTimeoutConfig = async () => {
  proxyTimeoutLoading.value = true
  try {
    const data = await adminApi.getProxyTimeoutConfig()
    Object.assign(proxyTimeoutForm, data)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    proxyTimeoutLoading.value = false
  }
}

const loadImageAutoRefreshConfig = async () => {
  imageAutoRefreshLoading.value = true
  try {
    const data = await adminApi.getImageAutoRefreshConfig()
    Object.assign(imageAutoRefreshForm, data)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    imageAutoRefreshLoading.value = false
  }
}

const loadStaleTaskCleanupConfig = async () => {
  staleTaskCleanupLoading.value = true
  try {
    const data = await adminApi.getStaleTaskCleanupConfig()
    Object.assign(staleTaskCleanupForm, data)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    staleTaskCleanupLoading.value = false
  }
}

const loadKeyCheckDefaultConfig = async () => {
  keyCheckDefaultLoading.value = true
  try {
    const data = await adminApi.getKeyCheckDefaultConfig()
    keyCheckDefaultForm.default_key_check_model = data?.default_key_check_model || ''
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    keyCheckDefaultLoading.value = false
  }
}

const loadKeyCheckShortcutModels = async () => {
  keyCheckShortcutLoading.value = true
  try {
    const data = await adminApi.getKeyCheckShortcutModels()
    keyCheckDefaultForm.default_key_check_model = data?.default_key_check_model || keyCheckDefaultForm.default_key_check_model || ''
    keyCheckShortcutForm.shortcut_models = [
      data?.shortcut_models?.[0] || keyCheckDefaultForm.default_key_check_model || '',
      data?.shortcut_models?.[1] || '',
      data?.shortcut_models?.[2] || '',
      data?.shortcut_models?.[3] || '',
      data?.shortcut_models?.[4] || '',
      data?.shortcut_models?.[5] || '',
    ]
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    keyCheckShortcutLoading.value = false
  }
}

const saveMasterKey = () => {
  localStorage.setItem('masterKey', localMasterKey.value)
  ElMessage.success('Master Key 已保存到本地')
  location.reload()
}

const handleLoginToggle = async (val) => {
  try {
    await authApi.updateConfig(val)
    ElMessage.success(val ? '登录验证已开启' : '登录验证已关闭')
  } catch (err) {
    loginEnabled.value = !val
    ElMessage.error(err.message || '配置更新失败')
  }
}

const handleChangePassword = async () => {
  if (!passwordFormRef.value) return
  try {
    await passwordFormRef.value.validate()
  } catch {
    return
  }

  passwordSaving.value = true
  try {
    await authApi.changePassword(passwordForm.oldPassword, passwordForm.newPassword)
    ElMessage.success('密码修改成功，请使用新密码重新登录')
    passwordForm.oldPassword = ''
    passwordForm.newPassword = ''
    passwordForm.confirmPassword = ''
    passwordFormRef.value?.resetFields()
  } catch (err) {
    ElMessage.error(err.message || '密码修改失败')
  } finally {
    passwordSaving.value = false
  }
}

const saveProxyTimeoutConfig = async () => {
  proxyTimeoutSaving.value = true
  try {
    const data = await adminApi.updateProxyTimeoutConfig({ ...proxyTimeoutForm })
    Object.assign(proxyTimeoutForm, data)
    ElMessage.success('代理超时配置已保存')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    proxyTimeoutSaving.value = false
  }
}

const saveImageAutoRefreshConfig = async () => {
  imageAutoRefreshSaving.value = true
  try {
    const data = await adminApi.updateImageAutoRefreshConfig({ ...imageAutoRefreshForm })
    Object.assign(imageAutoRefreshForm, data)
    ElMessage.success('图片自动回填配置已保存')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    imageAutoRefreshSaving.value = false
  }
}

const saveStaleTaskCleanupConfig = async () => {
  staleTaskCleanupSaving.value = true
  try {
    const data = await adminApi.updateStaleTaskCleanupConfig({ ...staleTaskCleanupForm })
    Object.assign(staleTaskCleanupForm, data)
    ElMessage.success('过期任务回收配置已保存')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    staleTaskCleanupSaving.value = false
  }
}

const saveKeyCheckDefaultConfig = async () => {
  keyCheckDefaultSaving.value = true
  try {
    const data = await adminApi.updateKeyCheckDefaultConfig({
      default_key_check_model: keyCheckDefaultForm.default_key_check_model,
    })
    keyCheckDefaultForm.default_key_check_model = data?.default_key_check_model || ''
    keyCheckShortcutForm.shortcut_models[0] = keyCheckDefaultForm.default_key_check_model || ''
    await saveKeyCheckShortcutModels()
    ElMessage.success('默认检测模型已保存')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    keyCheckDefaultSaving.value = false
  }
}

const saveKeyCheckShortcutModels = async () => {
  keyCheckShortcutSaving.value = true
  try {
    const data = await adminApi.updateKeyCheckShortcutModels({
      default_key_check_model: keyCheckDefaultForm.default_key_check_model,
      shortcut_models: keyCheckShortcutForm.shortcut_models,
    })
    keyCheckDefaultForm.default_key_check_model = data?.default_key_check_model || ''
    keyCheckShortcutForm.shortcut_models = [
      data?.shortcut_models?.[0] || keyCheckDefaultForm.default_key_check_model || '',
      data?.shortcut_models?.[1] || '',
      data?.shortcut_models?.[2] || '',
      data?.shortcut_models?.[3] || '',
      data?.shortcut_models?.[4] || '',
      data?.shortcut_models?.[5] || '',
    ]
    ElMessage.success('已保存快捷模型')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    keyCheckShortcutSaving.value = false
  }
}

const copyMasterKey = () => {
  navigator.clipboard.writeText(masterKey.value)
  ElMessage.success('已复制到剪贴板')
}

const setDefaultName = () => {
  if (nameTouched.value) return
  ccSwitchForm.name = defaultNames.value[selectedApp.value] || `local ${selectedApp.value}`
}

const pickDefaultModel = () => {
  if (!modelOptions.value.length) {
    ccSwitchForm.model = ''
    return
  }
  const preferred = exportMeta.value?.default_model
  const matched = modelOptions.value.find((item) => item.model_id === preferred)
  ccSwitchForm.model = matched?.model_id || modelOptions.value[0].model_id
}

const resetClaudeExtraModels = () => {
  ccSwitchForm.haikuModel = ''
  ccSwitchForm.sonnetModel = ''
  ccSwitchForm.opusModel = ''
  haikuModelKeyword.value = ''
  sonnetModelKeyword.value = ''
  opusModelKeyword.value = ''
}

const handleAppChange = () => {
  setDefaultName()
  if (!modelOptions.value.some((item) => item.model_id === ccSwitchForm.model)) {
    pickDefaultModel()
  }
  if (selectedApp.value !== 'claude') {
    resetClaudeExtraModels()
  }
}

const openCcSwitchDialog = async () => {
  if (!exportMeta.value) {
    await loadExportMeta()
  }

  selectedApp.value = 'claude'
  nameTouched.value = false
  mainModelKeyword.value = ''
  resetClaudeExtraModels()
  setDefaultName()
  pickDefaultModel()
  ccSwitchDialogVisible.value = true
}

const applyShortcutModel = (value) => {
  if (!value) return
  ccSwitchForm.model = value
  mainModelKeyword.value = value
}

const buildCcSwitchLink = () => {
  const endpointMap = {
    claude: exportMeta.value?.claude_endpoint,
    codex: exportMeta.value?.codex_endpoint,
    gemini: exportMeta.value?.gemini_endpoint,
  }
  const homepage = exportMeta.value?.homepage || 'https://www.wishyouhappy.hahaha'
  const params = new URLSearchParams({
    resource: 'provider',
    app: selectedApp.value,
    name: ccSwitchForm.name,
    endpoint: endpointMap[selectedApp.value] || '',
    apiKey: exportMeta.value?.api_key || masterKey.value,
    model: ccSwitchForm.model,
    homepage,
    enabled: 'true',
  })

  if (selectedApp.value === 'claude') {
    if (ccSwitchForm.haikuModel) params.set('haikuModel', ccSwitchForm.haikuModel)
    if (ccSwitchForm.sonnetModel) params.set('sonnetModel', ccSwitchForm.sonnetModel)
    if (ccSwitchForm.opusModel) params.set('opusModel', ccSwitchForm.opusModel)
  }

  return `ccswitch://v1/import?${params.toString()}`
}

const openCcSwitch = async () => {
  const valid = await ccSwitchFormRef.value.validate().catch(() => false)
  if (!valid) return

  if (!exportMeta.value) {
    await loadExportMeta().catch(() => false)
    if (!exportMeta.value) return
  }

  openingCcSwitch.value = true
  try {
    window.location.href = buildCcSwitchLink()
  } catch (e) {
    ElMessage.error(e.message || '打开 CC Switch 失败，请检查是否已安装并注册协议')
  } finally {
    openingCcSwitch.value = false
  }
}

const loadLoginConfig = async () => {
  try {
    const res = await authApi.getConfig()
    loginEnabled.value = !!res.login_enabled
  } catch {
    loginEnabled.value = false
  }
}

onMounted(async () => {
  await loadMasterKey()
  await loadLoginConfig()
  await loadModels()
  await loadProxyTimeoutConfig()
  await loadImageAutoRefreshConfig()
  await loadStaleTaskCleanupConfig()
  await loadKeyCheckDefaultConfig()
  await loadExportMeta().catch(() => false)
  await loadKeyCheckShortcutModels()
})
</script>

<style scoped>
.page-title {
  margin-bottom: 12px;
  color: #303133;
}

.setting-card {
  margin-bottom: 0;
}

.setting-collapse {
  border-top: 0;
  border-bottom: 0;
}

.setting-collapse :deep(.el-collapse-item__header) {
  height: auto;
  min-height: 56px;
  line-height: 1.4;
  border-bottom: 0;
}

.setting-collapse :deep(.el-collapse-item__wrap) {
  border-bottom: 0;
}

.setting-collapse :deep(.el-collapse-item__content) {
  padding-bottom: 0;
}

.setting-collapse-title {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.form-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 5px;
}

.cleanup-two-col {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 20px;
  max-width: 780px;
}

.cleanup-col {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.cleanup-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--cpa-text-secondary);
}

.usage-guide h4 {
  margin: 16px 0 8px;
  color: #303133;
}

.usage-guide h4:first-child {
  margin-top: 0;
}

.usage-guide p {
  color: #606266;
  margin-bottom: 8px;
}

code {
  background: #f5f7fa;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: monospace;
}

.code-block {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 15px;
  border-radius: 4px;
  overflow-x: auto;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 13px;
  line-height: 1.5;
}

.model-field-wrap {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}

.master-key-append-button {
  width: 48px;
  min-width: 48px;
  padding: 0;
  color: #6b7280;
}

.cc-switch-label-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}

.cc-switch-label-tip {
  color: #909399;
  font-size: 12px;
}

.shortcut-model-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  width: 100%;
}

.shortcut-model-input-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 24px;
  width: 100%;
}

.shortcut-model-button {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 4px;
  min-height: 54px;
  padding: 10px 12px;
}

.shortcut-model-button__label {
  font-size: 12px;
  color: #6b7280;
}

.shortcut-model-button__value {
  font-size: 13px;
  font-weight: 600;
}

:deep(.el-input-group__append) {
  display: inline-flex;
  align-items: center;
  padding: 0 6px;
}

:deep(.el-input-group__append .el-button) {
  margin: 0;
}

:deep(.el-input-group__append .el-button + .el-button) {
  margin-left: 4px;
}

:deep(.el-input-group__append .el-button--primary) {
  color: #fff;
}

.el-table {
  margin-bottom: 14px;
}
</style>
