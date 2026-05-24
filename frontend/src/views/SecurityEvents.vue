<template>
  <div class="security-events page-shell">
    <div class="page-header">
      <div class="page-header-main">
        <div class="page-kicker">Security</div>
        <h2 class="page-title">安全事件</h2>
        <p class="page-subtitle">集中查看上游返回中的广告推广、危险代码与可疑内容，便于定位污染来源和整理问题。</p>
      </div>
      <div class="header-actions">
        <el-button @click="openConfigDialog">规则/策略配置</el-button>
        <el-button :loading="loading" @click="loadEvents">刷新</el-button>
      </div>
    </div>

    <el-card class="filter-card" shadow="never">
      <template #header>
        <div class="card-header-simple">
          <div>
            <div class="panel-title">筛选条件</div>
          </div>
        </div>
      </template>
      <div class="filter-grid">
        <el-input v-model="filters.keyword" clearable placeholder="搜索 Key / URL / 模型 / 可疑内容 / 说明" @keyup.enter="handleSearch" />
        <el-input v-model="filters.key_id" clearable placeholder="Key ID" @keyup.enter="handleSearch" />
        <el-select v-model="filters.provider" clearable filterable placeholder="提供商" @change="handleSearch">
          <el-option v-for="item in providerOptions" :key="item" :label="item" :value="item" />
        </el-select>
        <el-select v-model="filters.category" clearable placeholder="类型" @change="handleSearch">
          <el-option value="dangerous_code" label="危险代码" />
          <el-option value="advertisement" label="广告推广" />
          <el-option value="unknown" label="未知" />
        </el-select>
        <el-select v-model="filters.action" clearable placeholder="处理动作" @change="handleSearch">
          <el-option value="recorded" label="仅记录" />
          <el-option value="sanitized" label="已删除广告" />
          <el-option value="blocked" label="已阻断" />
          <el-option value="downgraded" label="已降权" />
          <el-option value="disabled" label="已关闭 Key" />
        </el-select>
        <div class="filter-actions">
          <el-button type="primary" @click="handleSearch">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </div>
      </div>
    </el-card>

    <el-card shadow="never">
      <el-table :data="events" stripe border v-loading="loading" height="640" size="small">
        <el-table-column prop="id" label="ID" width="76" />
        <el-table-column prop="created_at" label="时间" width="172" />
        <el-table-column prop="provider" label="提供商" width="110" show-overflow-tooltip />
        <el-table-column label="Key" width="170" show-overflow-tooltip>
          <template #default="{ row }">#{{ row.api_key_id }} {{ row.key_name || '' }}</template>
        </el-table-column>
        <el-table-column prop="model" label="模型" width="130" show-overflow-tooltip />
        <el-table-column prop="category" label="类型" width="118">
          <template #default="{ row }">
            <el-tag :type="categoryTagType(row.category)" size="small">{{ categoryLabel(row.category) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="action" label="处理" width="110">
          <template #default="{ row }">
            <el-tag :type="actionTagType(row.action)" size="small">{{ actionLabel(row.action) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="snippet" label="可疑内容" min-width="280" show-overflow-tooltip />
        <el-table-column prop="explanation" label="说明" min-width="260" show-overflow-tooltip />
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link @click="openDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="limit"
          :page-sizes="[20, 50, 100, 200]"
          :total="total"
          layout="total, sizes, prev, pager, next"
          @current-change="loadEvents"
          @size-change="handleSizeChange"
        />
      </div>
    </el-card>

    <el-dialog v-model="configVisible" title="安全规则与策略配置" width="860px">
      <el-form label-width="180px" v-loading="configLoading">
        <el-form-item label="启用防护">
          <el-switch v-model="configForm.enabled" active-text="开启" inactive-text="关闭" />
          <div class="form-tip">开启后 CPA 会在普通响应与缓冲流式短响应返回前扫描上游内容。</div>
        </el-form-item>
        <el-form-item label="检测类型">
          <el-checkbox v-model="configForm.check_ads">广告推广</el-checkbox>
          <el-checkbox v-model="configForm.check_dangerous_code">危险代码</el-checkbox>
        </el-form-item>
        <el-form-item label="广告处理策略">
          <el-radio-group v-model="configForm.ad_action">
            <el-radio-button value="record">仅记录</el-radio-button>
            <el-radio-button value="sanitize">删除广告后放行</el-radio-button>
            <el-radio-button value="block">阻断响应</el-radio-button>
          </el-radio-group>
          <div class="form-tip">广告在中间时可用正则扩大匹配范围；删除后放行会尽量只清理命中的广告片段。</div>
        </el-form-item>
        <el-form-item label="危险代码命中后阻断">
          <el-switch v-model="configForm.block_on_violation" active-text="阻断" inactive-text="仅记录" />
          <div class="form-tip">该开关只影响非广告类风险，如危险命令、可疑代码等。</div>
        </el-form-item>
        <el-form-item label="Key 处理策略">
          <div class="config-inline">
            <span>降权到</span>
            <el-input-number v-model="configForm.downgrade_weight" :min="0" :max="100" />
            <span>违规</span>
            <el-input-number v-model="configForm.disable_threshold" :min="1" :max="100" />
            <span>次后</span>
            <el-switch v-model="configForm.auto_disable_key" active-text="自动关闭 Key" inactive-text="不自动关闭" />
          </div>
          <div class="form-tip">降权值为 0 表示不改权重；自动关闭默认关闭，避免误杀。</div>
        </el-form-item>
        <el-form-item label="广告普通匹配词">
          <el-input v-model="adPatternsText" type="textarea" :rows="5" placeholder="每行一个关键词，例如：优惠码、邀请码、加群" />
        </el-form-item>
        <el-form-item label="广告正则匹配词">
          <el-input v-model="adRegexPatternsText" type="textarea" :rows="6" placeholder="每行一个正则，例如：欢迎访问[\\s\\S]{0,40}example\\.com" />
          <div class="form-tip">适合广告夹在回答中间、格式不固定的场景。正则写得过宽会误删正常内容。</div>
        </el-form-item>
        <el-form-item label="危险代码规则">
          <el-input v-model="dangerousPatternsText" type="textarea" :rows="6" placeholder="每行一个正则表达式" />
          <div class="form-tip">内置危险代码规则会继续生效；这里可追加自定义正则。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="configVisible = false">取消</el-button>
        <el-button type="primary" :loading="configSaving" @click="saveConfig">保存配置</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailVisible" title="安全事件详情" width="820px">
      <el-descriptions v-if="currentEvent" :column="2" border>
        <el-descriptions-item label="事件 ID">{{ currentEvent.id }}</el-descriptions-item>
        <el-descriptions-item label="时间">{{ currentEvent.created_at }}</el-descriptions-item>
        <el-descriptions-item label="提供商">{{ currentEvent.provider || '-' }}</el-descriptions-item>
        <el-descriptions-item label="Key">#{{ currentEvent.api_key_id }} {{ currentEvent.key_name || '' }}</el-descriptions-item>
        <el-descriptions-item label="模型">{{ currentEvent.model || '-' }}</el-descriptions-item>
        <el-descriptions-item label="路径">{{ currentEvent.path || '-' }}</el-descriptions-item>
        <el-descriptions-item label="Base URL" :span="2">{{ currentEvent.base_url || '-' }}</el-descriptions-item>
        <el-descriptions-item label="命中规则" :span="2">{{ currentEvent.rule || '-' }}</el-descriptions-item>
        <el-descriptions-item label="说明" :span="2">{{ currentEvent.explanation || '-' }}</el-descriptions-item>
      </el-descriptions>
      <div class="detail-block-title">可疑内容</div>
      <pre class="detail-snippet">{{ currentEvent?.snippet || '-' }}</pre>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button type="primary" @click="copyDetail">复制详情</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '../api'

const loading = ref(false)
const events = ref([])
const total = ref(0)
const page = ref(1)
const limit = ref(20)
const detailVisible = ref(false)
const configVisible = ref(false)
const configLoading = ref(false)
const configSaving = ref(false)
const currentEvent = ref(null)
const filters = reactive({ keyword: '', key_id: '', provider: '', category: '', action: '' })
const configForm = reactive({ enabled: false, check_ads: true, check_dangerous_code: true, block_on_violation: true, ad_action: 'record', auto_disable_key: false, disable_threshold: 3, downgrade_weight: 1 })
const adPatternsText = ref('')
const adRegexPatternsText = ref('')
const dangerousPatternsText = ref('')

const providerOptions = computed(() => {
  return Array.from(new Set(events.value.map((item) => item.provider).filter(Boolean))).sort()
})

const buildParams = () => {
  const params = { page: page.value, limit: limit.value }
  if (filters.keyword.trim()) params.keyword = filters.keyword.trim()
  if (filters.key_id) params.key_id = filters.key_id
  if (filters.provider) params.provider = filters.provider
  if (filters.category) params.category = filters.category
  if (filters.action) params.action = filters.action
  return params
}

const loadEvents = async () => {
  loading.value = true
  try {
    const data = await adminApi.listContentGuardEvents(buildParams())
    events.value = data?.items || []
    total.value = data?.total || 0
  } catch (e) {
    ElMessage.error(e.message || '加载安全事件失败')
  } finally {
    loading.value = false
  }
}

const handleSearch = () => {
  page.value = 1
  loadEvents()
}

const resetFilters = () => {
  Object.assign(filters, { keyword: '', key_id: '', provider: '', category: '', action: '' })
  handleSearch()
}

const handleSizeChange = () => {
  page.value = 1
  loadEvents()
}

const openDetail = (row) => {
  currentEvent.value = row
  detailVisible.value = true
}

const categoryLabel = (value) => ({ dangerous_code: '危险代码', advertisement: '广告推广', unknown: '未知' }[value] || value || '-')
const categoryTagType = (value) => (value === 'dangerous_code' ? 'danger' : value === 'advertisement' ? 'warning' : 'info')
const actionLabel = (value) => ({ recorded: '仅记录', sanitized: '已删除广告', blocked: '已阻断', downgraded: '已降权', disabled: '已关闭' }[value] || value || '-')
const actionTagType = (value) => (value === 'disabled' || value === 'blocked' ? 'danger' : value === 'downgraded' || value === 'sanitized' ? 'warning' : 'info')

const assignConfig = (data = {}) => {
  Object.assign(configForm, {
    enabled: !!data.enabled,
    check_ads: data.check_ads !== false,
    check_dangerous_code: data.check_dangerous_code !== false,
    block_on_violation: data.block_on_violation !== false,
    ad_action: data.ad_action || 'record',
    auto_disable_key: !!data.auto_disable_key,
    disable_threshold: data.disable_threshold ?? 3,
    downgrade_weight: data.downgrade_weight ?? 1,
  })
  adPatternsText.value = (data.ad_patterns || []).join('\n')
  adRegexPatternsText.value = (data.ad_regex_patterns || []).join('\n')
  dangerousPatternsText.value = (data.dangerous_patterns || []).join('\n')
}

const loadConfig = async () => {
  configLoading.value = true
  try {
    const data = await adminApi.getContentGuardConfig()
    assignConfig(data)
  } catch (e) {
    ElMessage.error(e.message || '加载安全配置失败')
  } finally {
    configLoading.value = false
  }
}

const openConfigDialog = async () => {
  configVisible.value = true
  await loadConfig()
}

const saveConfig = async () => {
  configSaving.value = true
  try {
    const payload = {
      ...configForm,
      ad_patterns: adPatternsText.value.split('\n').map((s) => s.trim()).filter(Boolean),
      ad_regex_patterns: adRegexPatternsText.value.split('\n').map((s) => s.trim()).filter(Boolean),
      dangerous_patterns: dangerousPatternsText.value.split('\n').map((s) => s.trim()).filter(Boolean),
    }
    const data = await adminApi.updateContentGuardConfig(payload)
    assignConfig(data)
    configVisible.value = false
    ElMessage.success('安全规则与策略已保存')
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    configSaving.value = false
  }
}

const copyDetail = async () => {
  if (!currentEvent.value) return
  const item = currentEvent.value
  const text = [
    `事件 ID: ${item.id}`,
    `时间: ${item.created_at}`,
    `提供商: ${item.provider || '-'}`,
    `Key: #${item.api_key_id} ${item.key_name || ''}`,
    `模型: ${item.model || '-'}`,
    `路径: ${item.path || '-'}`,
    `类型: ${categoryLabel(item.category)}`,
    `处理: ${actionLabel(item.action)}`,
    `规则: ${item.rule || '-'}`,
    `说明: ${item.explanation || '-'}`,
    `可疑内容: ${item.snippet || '-'}`,
  ].join('\n')
  await navigator.clipboard.writeText(text)
  ElMessage.success('已复制事件详情')
}

onMounted(() => {
  loadEvents()
  loadConfig()
})
</script>

<style scoped>
.filter-grid {
  display: grid;
  grid-template-columns: 2fr 120px 150px 150px 150px auto;
  gap: 10px;
  align-items: center;
}

.filter-actions {
  display: flex;
  gap: 8px;
}

.form-tip {
  margin-top: 5px;
  font-size: 12px;
  color: #909399;
}

.config-inline {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

.detail-block-title {
  margin: 16px 0 8px;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.detail-snippet {
  max-height: 240px;
  overflow: auto;
  padding: 12px;
  border-radius: 8px;
  background: #111827;
  color: #e5e7eb;
  white-space: pre-wrap;
  word-break: break-word;
}

@media (max-width: 1280px) {
  .filter-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
