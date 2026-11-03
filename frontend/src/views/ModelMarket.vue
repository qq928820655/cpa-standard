<template>
  <div class="model-market page-shell">
    <div class="page-header">
      <div class="page-header-main">
        <div class="page-kicker">Models</div>
        <h2 class="page-title">模型广场</h2>
      </div>
      <div v-if="isAdmin" class="header-actions">
        <el-button @click="importDialogVisible = true">JSON 批量导入</el-button>
        <el-button :loading="exportingAllModels" @click="exportAllModels">导出全部</el-button>
        <el-button :loading="pricingSyncing" @click="syncModelsDevPricing">同步 models.dev 定价</el-button>
        <el-select v-model="pricingConfig.currency" class="price-currency-select" @change="savePricingConfig">
          <el-option label="美元" value="USD" />
          <el-option label="人民币" value="CNY" />
        </el-select>
        <el-button @click="pricingDialogVisible = true">汇率</el-button>
        <el-button :loading="protocolCapabilitiesLoading" @click="openProtocolCapabilities">协议能力</el-button>
        <el-button @click="quickCreateDialogVisible = true">快捷批量创建</el-button>
        <el-button type="primary" @click="showAddDialog">
          <el-icon><Plus /></el-icon>
          添加模型
        </el-button>
      </div>
    </div>

    <el-card class="filter-card" shadow="never">
      <template #header>
        <div class="card-header-simple">
          <div>
            <div class="panel-title">筛选与检索</div>
          </div>
        </div>
      </template>
      <div class="filter-row">
        <el-input v-model="keyword" placeholder="搜索模型 ID / 名称" clearable @input="handleKeywordChange" />
        <el-select v-model="filterProvider" filterable allow-create default-first-option clearable reserve-keyword="false" placeholder="筛选提供商" @change="() => { resetToFirstPage(); loadModels() }">
          <el-option v-for="item in providerOptions" :key="item" :value="item" :label="item" />
        </el-select>
      </div>
    </el-card>

    <el-card shadow="never">
      <!-- 窄屏：9 列表格改卡片流，价格与协议折叠在「详情」里 -->
      <div v-if="isMobile" class="model-card-list" v-loading="loading">
        <div v-if="!sortedFilteredModels.length" class="model-card-empty">暂无数据</div>

        <div v-for="row in sortedFilteredModels" :key="row.model_id" class="model-card">
          <div class="model-card__head">
            <span class="model-card__name">{{ row.model_id }}</span>
            <button type="button" class="model-card__toggle" @click="toggleModelExpand(row.model_id)">
              <span>{{ isModelExpanded(row.model_id) ? '收起' : '详情' }}</span>
              <el-icon :class="{ 'is-open': isModelExpanded(row.model_id) }"><ArrowDown /></el-icon>
            </button>
          </div>

          <div class="model-card__tags">
            <el-tag size="small" type="info">{{ row.provider }}</el-tag>
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
              {{ row.is_active ? '启用' : '停用' }}
            </el-tag>
            <el-tag v-if="row.supports_codex" type="success" size="small">codex</el-tag>
            <el-tag v-if="row.supports_claudecode" type="warning" size="small">claude</el-tag>
            <el-tag v-if="row.supports_gemini" type="info" size="small">gemini</el-tag>
            <el-tag v-if="row.is_recommended" type="primary" size="small">推荐</el-tag>
          </div>

          <div v-show="isModelExpanded(row.model_id)" class="model-card__rows">
            <div class="model-card__row">
              <span class="model-card__label">显示名称</span>
              <span class="model-card__value">{{ row.display_name || '-' }}</span>
            </div>
            <div class="model-card__row">
              <span class="model-card__label">协议</span>
              <span class="model-card__value">{{ row.protocol || '-' }}</span>
            </div>
            <div class="model-card__row">
              <span class="model-card__label">价格</span>
              <span class="model-card__value">入 {{ formatPrice(row.input_price) }} / 出 {{ formatPrice(row.output_price) }}</span>
            </div>
          </div>

          <div v-if="isAdmin" class="model-card__actions">
            <el-button size="small" type="primary" @click="showEditDialog(row)">编辑</el-button>
            <el-popconfirm title="确定删除此模型？" @confirm="removeModel(row)">
              <template #reference>
                <el-button size="small" type="danger" plain>删除</el-button>
              </template>
            </el-popconfirm>
          </div>
        </div>
      </div>

      <el-table v-else :data="sortedFilteredModels" stripe v-loading="loading" height="600" size="small" class="models-table" @sort-change="handleModelSortChange">
        <el-table-column prop="model_id" label="模型 ID" min-width="190" show-overflow-tooltip sortable="custom" />
        <el-table-column prop="display_name" label="显示名称" min-width="150" show-overflow-tooltip sortable="custom" />
        <el-table-column prop="provider" label="提供商" width="100" sortable="custom" />
        <el-table-column prop="protocol" label="协议" width="132" show-overflow-tooltip sortable="custom" />
        <el-table-column prop="input_price" label="输入价格" width="96" align="right" sortable="custom">
          <template #default="{ row }">{{ formatPrice(row.input_price) }}</template>
        </el-table-column>
        <el-table-column prop="output_price" label="输出价格" width="96" align="right" sortable="custom">
          <template #default="{ row }">{{ formatPrice(row.output_price) }}</template>
        </el-table-column>
        <el-table-column label="兼容" min-width="140">
          <template #default="{ row }">
            <div class="compat-tags">
              <el-tag v-if="row.supports_codex" type="success" size="small">codex</el-tag>
              <el-tag v-if="row.supports_claudecode" type="warning" size="small">claude</el-tag>
              <el-tag v-if="row.supports_gemini" type="info" size="small">gemini</el-tag>
              <el-tag v-if="row.is_recommended" type="primary" size="small">推荐</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="is_active" label="状态" width="86" sortable="custom">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
              {{ row.is_active ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="isAdmin" label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link @click="showEditDialog(row)">编辑</el-button>
            <el-popconfirm title="确定删除此模型？" @confirm="removeModel(row)">
              <template #reference>
                <el-button type="danger" link>删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="pageSizeOptions"
          :total="totalModels"
          :small="isMobile"
          :pager-count="isMobile ? 5 : 7"
          :layout="isMobile ? 'prev, pager, next, sizes, total' : 'total, sizes, prev, pager, next'"
          @current-change="handlePageChange"
          @size-change="handlePageSizeChange"
        />
      </div>
    </el-card>

    <el-dialog v-model="importDialogVisible" title="JSON 批量导入模型" width="760px">
      <div class="import-actions">
        <el-button @click="fillImportTemplate">填充模板</el-button>
        <input ref="importFileRef" type="file" accept=".txt,.json,.jsonl" class="hidden-input" @change="handleImportFile" />
        <el-button @click="openImportFile">选择文件</el-button>
      </div>
      <div class="form-tip">
        支持 JSON 数组或 JSONL 多行对象导入，也支持直接导入“导出全部”生成的文件。
      </div>
      <el-input v-model="importText" type="textarea" :rows="12" placeholder="粘贴 JSON 数组或每行一个 JSON 对象" />
      <template #footer>
        <el-button @click="importDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitImport" :loading="importing">导入</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="pricingDialogVisible" title="价格显示与汇率" width="460px">
      <el-form label-width="110px">
        <el-form-item label="显示币种">
          <el-radio-group v-model="pricingConfig.currency">
            <el-radio value="USD">美元</el-radio>
            <el-radio value="CNY">人民币</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="汇率算法">
          <el-radio-group v-model="pricingConfig.exchange_rate_mode">
            <el-radio value="manual">手动汇率</el-radio>
            <el-radio value="fixed">固定汇率</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="美元兑人民币">
          <el-input-number v-model="pricingConfig.usd_cny_rate" :min="0.01" :max="100" :precision="4" :disabled="pricingConfig.exchange_rate_mode === 'fixed'" />
          <span v-if="pricingConfig.exchange_rate_mode === 'fixed'" class="price-rate-hint">固定使用 7.2</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pricingDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="savePricingConfig">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="protocolCapabilitiesDialogVisible" title="协议能力记录" width="min(1180px, 96vw)" top="5vh">
      <div class="capability-toolbar">
        <el-input v-model="protocolCapabilityFilters.provider" placeholder="Provider" clearable />
        <el-input v-model="protocolCapabilityFilters.model" placeholder="Model" clearable />
        <el-input v-model="protocolCapabilityFilters.protocol" placeholder="Protocol" clearable />
        <el-button :loading="protocolCapabilitiesLoading" @click="loadProtocolCapabilities">查询</el-button>
        <el-button type="danger" plain :loading="protocolCapabilitiesClearing" @click="clearProtocolCapabilities">清空</el-button>
      </div>
      <div v-if="isMobile" class="capability-mobile-list" v-loading="protocolCapabilitiesLoading">
        <div v-if="!protocolCapabilities.length" class="capability-empty">暂无能力记录</div>
        <div v-for="row in protocolCapabilities" :key="row.id" class="capability-mobile-item">
          <div class="capability-mobile-head">
            <strong>{{ row.model_id }}</strong>
            <el-tag :type="row.supported ? 'success' : 'danger'" size="small">{{ row.supported ? '支持' : '不支持' }}</el-tag>
          </div>
          <div class="capability-mobile-meta">{{ row.provider }} · {{ row.protocol }} · {{ row.request_profile || 'default' }}</div>
          <div class="capability-mobile-meta">{{ row.base_url || '-' }}</div>
          <div class="capability-mobile-meta">来源 {{ row.source || '-' }} · 状态码 {{ row.status_code || '-' }} · {{ row.updated_at || '-' }}</div>
          <div class="capability-mobile-actions">
            <el-button size="small" type="primary" @click="editProtocolCapability(row)">编辑</el-button>
            <el-button size="small" type="danger" plain @click="removeProtocolCapability(row)">删除</el-button>
          </div>
        </div>
      </div>
      <el-table v-else :data="protocolCapabilities" size="small" border v-loading="protocolCapabilitiesLoading" class="capability-table">
        <el-table-column prop="provider" label="Provider" width="120" />
        <el-table-column prop="base_url" label="Base URL" min-width="220" show-overflow-tooltip />
        <el-table-column prop="model_id" label="Model" min-width="160" />
        <el-table-column prop="protocol" label="Protocol" width="155" />
        <el-table-column prop="request_profile" label="特征" width="90" />
        <el-table-column label="结果" width="78"><template #default="{ row }"><el-tag :type="row.supported ? 'success' : 'danger'" size="small">{{ row.supported ? '支持' : '不支持' }}</el-tag></template></el-table-column>
        <el-table-column prop="source" label="来源" width="86" />
        <el-table-column prop="status_code" label="状态码" width="78" />
        <el-table-column prop="updated_at" label="更新时间" min-width="170" show-overflow-tooltip />
        <el-table-column label="操作" width="105" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="editProtocolCapability(row)">编辑</el-button><el-button link type="danger" @click="removeProtocolCapability(row)">删除</el-button></template></el-table-column>
      </el-table>
      <div class="capability-total">当前记录共 {{ protocolCapabilitiesTotal }} 条</div>
    </el-dialog>

    <el-dialog v-model="protocolCapabilityEditVisible" title="编辑协议能力记录" width="min(620px, 94vw)">
      <el-form :model="protocolCapabilityEditForm" label-width="105px">
        <el-form-item label="Provider"><el-input :model-value="protocolCapabilityEditForm.provider" disabled /></el-form-item>
        <el-form-item label="Base URL"><el-input :model-value="protocolCapabilityEditForm.base_url" disabled /></el-form-item>
        <el-form-item label="Model / 协议"><el-input :model-value="`${protocolCapabilityEditForm.model_id} / ${protocolCapabilityEditForm.protocol}`" disabled /></el-form-item>
        <el-form-item label="请求特征"><el-input v-model="protocolCapabilityEditForm.request_profile" /></el-form-item>
        <el-form-item label="结果"><el-switch v-model="protocolCapabilityEditForm.supported" active-text="支持" inactive-text="不支持" /></el-form-item>
        <el-form-item label="来源"><el-input v-model="protocolCapabilityEditForm.source" /></el-form-item>
        <el-form-item label="状态码"><el-input-number v-model="protocolCapabilityEditForm.status_code" :min="100" :max="599" :controls="false" /></el-form-item>
        <el-form-item label="过期时间"><el-date-picker v-model="protocolCapabilityEditForm.expires_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" placeholder="留空表示不过期" /></el-form-item>
        <el-form-item label="详情"><el-input v-model="protocolCapabilityEditForm.detail" type="textarea" :rows="4" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="protocolCapabilityEditVisible = false">取消</el-button><el-button type="primary" :loading="protocolCapabilitySaving" @click="saveProtocolCapability">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="quickCreateDialogVisible" title="快捷批量创建模型" width="640px">
      <div class="form-tip">
        输入模型名，使用英文逗号分隔，例如：gpt-4o, claude-3-7-sonnet, gemini-2.5-pro
      </div>
      <el-input v-model="quickCreateText" type="textarea" :rows="6" placeholder="输入逗号分隔的模型名" />
      <template #footer>
        <el-button @click="quickCreateDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitQuickCreate" :loading="quickCreating">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑模型' : '添加模型'" width="640px">
      <el-form :model="form" :rules="rules" ref="formRef" label-width="110px">
        <el-form-item label="模型 ID" prop="model_id">
          <el-input v-model="form.model_id" :disabled="isEdit" />
        </el-form-item>
        <el-form-item label="显示名称" prop="display_name">
          <el-input v-model="form.display_name" />
        </el-form-item>
        <el-form-item label="提供商" prop="provider">
          <el-select v-model="form.provider" filterable allow-create default-first-option clearable reserve-keyword="false">
            <el-option v-for="item in providerOptions" :key="item" :value="item" :label="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="协议" prop="protocol">
          <el-select v-model="form.protocol">
            <el-option value="openai_chat" label="openai_chat" />
            <el-option value="openai_responses" label="openai_responses" />
            <el-option value="anthropic_messages" label="anthropic_messages" />
          </el-select>
        </el-form-item>
        <el-form-item label="输入价格">
          <el-input-number v-model="form.input_price" :min="0" :precision="4" />
        </el-form-item>
        <el-form-item label="输出价格">
          <el-input-number v-model="form.output_price" :min="0" :precision="4" />
        </el-form-item>
        <el-form-item label="别名">
          <el-select v-model="form.aliases" multiple filterable allow-create default-first-option placeholder="可回车添加多个别名" />
        </el-form-item>
        <el-form-item label="兼容能力">
          <el-checkbox v-model="form.supports_codex">codex</el-checkbox>
          <el-checkbox v-model="form.supports_claudecode">claude</el-checkbox>
          <el-checkbox v-model="form.supports_gemini">gemini</el-checkbox>
          <el-checkbox v-model="form.is_recommended">推荐</el-checkbox>
          <el-checkbox v-model="form.is_active">启用</el-checkbox>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitForm" :loading="submitting">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'
import { adminApi, authApi } from '../api'

// 普通用户对模型广场只读可见：隐藏所有增删改导入导出入口
const isAdmin = computed(() => !authApi.isLoggedIn() || authApi.isAdmin())

// 手机竖屏改用卡片流，桌面端保持原表格
const MOBILE_QUERY = '(max-width: 768px)'
const isMobile = ref(false)
let mobileMediaQuery = null
const syncMobile = (event) => {
  isMobile.value = event.matches
}

// 卡片次要字段按需展开
const expandedModelIds = ref(new Set())
const isModelExpanded = (id) => expandedModelIds.value.has(String(id))
const toggleModelExpand = (id) => {
  const next = new Set(expandedModelIds.value)
  const key = String(id)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expandedModelIds.value = next
}

const loading = ref(false)
const models = ref([])
const keyword = ref('')
const filterProvider = ref('')
const dialogVisible = ref(false)
const importDialogVisible = ref(false)
const quickCreateDialogVisible = ref(false)
const pricingDialogVisible = ref(false)
const pricingSyncing = ref(false)
const protocolCapabilitiesDialogVisible = ref(false)
const protocolCapabilityEditVisible = ref(false)
const protocolCapabilitiesLoading = ref(false)
const protocolCapabilitiesClearing = ref(false)
const protocolCapabilitySaving = ref(false)
const protocolCapabilities = ref([])
const protocolCapabilitiesTotal = ref(0)
const protocolCapabilityFilters = reactive({ provider: '', model: '', protocol: '' })
const protocolCapabilityEditForm = reactive({
  id: null,
  provider: '',
  base_url: '',
  model_id: '',
  protocol: '',
  request_profile: 'default',
  supported: true,
  source: 'manual',
  status_code: null,
  detail: '',
  expires_at: null,
})
const pricingConfig = reactive({
  currency: 'USD',
  exchange_rate_mode: 'fixed',
  usd_cny_rate: 7.2,
})
const isEdit = ref(false)
const submitting = ref(false)
const importing = ref(false)
const exportingAllModels = ref(false)
const quickCreating = ref(false)
const editingId = ref(null)
const formRef = ref(null)
const importFileRef = ref(null)
const importText = ref('')
const quickCreateText = ref('')
const customProviders = ref([])
const modelProviderOptions = ref([])

const providerOptions = computed(() => {
  const builtins = ['openai', 'claude', 'google', 'xAI', 'deepseek', 'qwen', 'minimax', 'Moonshot', 'Meta', '智谱', 'azure', 'custom']
  const dynamicProviders = [
    ...modelProviderOptions.value,
    ...customProviders.value,
    filterProvider.value,
    form.provider,
    ...models.value.map((item) => item?.provider),
  ]

  return Array.from(new Set([
    ...builtins,
    ...dynamicProviders
      .filter((item) => typeof item === 'string' && item.trim())
      .map((item) => item.trim()),
  ]))
})

const form = reactive({
  model_id: '',
  display_name: '',
  provider: 'openai',
  protocol: 'openai_chat',
  input_price: 0,
  output_price: 0,
  is_active: true,
  is_recommended: false,
  supports_codex: true,
  supports_claudecode: true,
  supports_gemini: true,
  aliases: [],
  remark: '',
})

const rules = {
  model_id: [{ required: true, message: '请输入模型 ID', trigger: 'blur' }],
  display_name: [{ required: true, message: '请输入显示名称', trigger: 'blur' }],
  provider: [{ required: true, message: '请选择提供商', trigger: 'change' }],
}

const filteredModels = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  if (!text) return models.value
  return models.value.filter((item) =>
    item.model_id.toLowerCase().includes(text) || item.display_name.toLowerCase().includes(text)
  )
})

const modelSort = ref({
  prop: '',
  order: null,
})

const compareModelValues = (left, right, prop) => {
  const leftValue = left?.[prop]
  const rightValue = right?.[prop]

  if (typeof leftValue === 'number' || typeof rightValue === 'number') {
    return Number(leftValue || 0) - Number(rightValue || 0)
  }

  if (typeof leftValue === 'boolean' || typeof rightValue === 'boolean') {
    return Number(Boolean(leftValue)) - Number(Boolean(rightValue))
  }

  return String(leftValue || '').localeCompare(String(rightValue || ''), 'zh-CN', { sensitivity: 'base' })
}

const sortedFilteredModels = computed(() => {
  const items = [...filteredModels.value]
  const { prop, order } = modelSort.value
  if (!prop || !order) return items

  items.sort((left, right) => {
    const result = compareModelValues(left, right, prop)
    return order === 'ascending' ? result : -result
  })
  return items
})

const handleModelSortChange = ({ prop, order }) => {
  modelSort.value = { prop, order }
}

const formatPrice = (value) => {
  const usd = Number(value || 0)
  const exchangeRate = pricingConfig.exchange_rate_mode === 'fixed' ? 7.2 : Number(pricingConfig.usd_cny_rate || 0)
  const amount = pricingConfig.currency === 'CNY' ? usd * exchangeRate : usd
  const prefix = pricingConfig.currency === 'CNY' ? '¥' : '$'
  return `${prefix}${amount.toLocaleString('zh-CN', { maximumFractionDigits: 6 })} / 1M`
}

const loadProtocolCapabilities = async () => {
  protocolCapabilitiesLoading.value = true
  try {
    const result = await adminApi.listProtocolCapabilities({ ...protocolCapabilityFilters, limit: 500 })
    protocolCapabilities.value = result?.items || []
    protocolCapabilitiesTotal.value = Number(result?.total || 0)
  } catch (error) {
    ElMessage.error(error.message || '加载协议能力记录失败')
  } finally {
    protocolCapabilitiesLoading.value = false
  }
}

const openProtocolCapabilities = async () => {
  protocolCapabilitiesDialogVisible.value = true
  await loadProtocolCapabilities()
}

const editProtocolCapability = (row) => {
  Object.assign(protocolCapabilityEditForm, {
    ...row,
    status_code: row.status_code || null,
    detail: row.detail || '',
    expires_at: row.expires_at || null,
  })
  protocolCapabilityEditVisible.value = true
}

const saveProtocolCapability = async () => {
  protocolCapabilitySaving.value = true
  try {
    const result = await adminApi.updateProtocolCapability(protocolCapabilityEditForm.id, {
      supported: !!protocolCapabilityEditForm.supported,
      request_profile: protocolCapabilityEditForm.request_profile,
      source: protocolCapabilityEditForm.source,
      status_code: protocolCapabilityEditForm.status_code,
      detail: protocolCapabilityEditForm.detail || null,
      expires_at: protocolCapabilityEditForm.expires_at || null,
    })
    const index = protocolCapabilities.value.findIndex((item) => item.id === result.id)
    if (index >= 0) protocolCapabilities.value[index] = result
    protocolCapabilityEditVisible.value = false
    ElMessage.success('协议能力记录已保存')
  } catch (error) {
    ElMessage.error(error.message || '保存协议能力记录失败')
  } finally {
    protocolCapabilitySaving.value = false
  }
}

const removeProtocolCapability = async (row) => {
  try {
    await ElMessageBox.confirm('确定删除这条协议能力记录吗？', '确认删除', { type: 'warning' })
    await adminApi.clearProtocolCapabilities({ ids: [row.id] })
    await loadProtocolCapabilities()
    ElMessage.success('协议能力记录已删除')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(error.message || '删除协议能力记录失败')
  }
}

const clearProtocolCapabilities = async () => {
  try {
    await ElMessageBox.confirm('确定清空所有协议能力记录吗？', '确认清空', { type: 'warning' })
    protocolCapabilitiesClearing.value = true
    await adminApi.clearProtocolCapabilities({ ids: [] })
    await loadProtocolCapabilities()
    ElMessage.success('协议能力记录已清空')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(error.message || '清空协议能力记录失败')
  } finally {
    protocolCapabilitiesClearing.value = false
  }
}

const loadPricingConfig = async () => {
  if (!isAdmin.value) return
  try {
    Object.assign(pricingConfig, await adminApi.getModelPricingConfig())
  } catch (error) {
    ElMessage.error(error.message || '加载价格配置失败')
  }
}

const savePricingConfig = async () => {
  try {
    const result = await adminApi.updateModelPricingConfig({ ...pricingConfig })
    Object.assign(pricingConfig, result)
    pricingDialogVisible.value = false
    ElMessage.success('价格显示配置已保存')
  } catch (error) {
    ElMessage.error(error.message || '保存价格配置失败')
  }
}

const syncModelsDevPricing = async () => {
  pricingSyncing.value = true
  try {
    const result = await adminApi.syncModelsDevPricing()
    ElMessage.success(`已同步 ${result.updated_count} 个模型定价，未匹配 ${result.unmatched_model_ids?.length || 0} 个`)
    await loadModels()
  } catch (error) {
    ElMessage.error(error.message || '同步 models.dev 定价失败')
  } finally {
    pricingSyncing.value = false
  }
}

const handleKeywordChange = () => {
  resetToFirstPage()
  loadModels()
}

const resetForm = () => {
  Object.assign(form, {
    model_id: '',
    display_name: '',
    provider: 'openai',
    protocol: 'openai_chat',
    input_price: 0,
    output_price: 0,
    is_active: true,
    is_recommended: false,
    supports_codex: true,
    supports_claudecode: true,
    supports_gemini: true,
    aliases: [],
    remark: '',
  })
}

const normalizeNames = (text, separator = ',') => {
  const seen = new Set()
  return text
    .split(separator)
    .map((item) => item.trim())
    .filter((item) => {
      if (!item) return false
      const key = item.toLowerCase()
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
}

const syncCustomProviders = (values) => {
  const normalized = normalizeNames((values || []).join(','))
  customProviders.value = normalizeNames([...(customProviders.value || []), ...normalized].join(','))
}

const currentPage = ref(1)
const pageSize = ref(50)
const totalModels = ref(0)
const pageSizeOptions = [10, 20, 50, 100]

const loadModels = async () => {
  loading.value = true
  try {
    const params = {
      provider: filterProvider.value || undefined,
      page: currentPage.value,
      limit: pageSize.value,
    }
    const result = await adminApi.listModels(params.provider, {
      page: params.page,
      limit: params.limit,
    })

    if (Array.isArray(result)) {
      models.value = result
      totalModels.value = result.length
    } else {
      models.value = result.items || []
      totalModels.value = result.total || 0
    }

    if (!isAdmin.value) {
      const visibleProviders = models.value.map((item) => item.provider).filter(Boolean)
      modelProviderOptions.value = normalizeNames(visibleProviders.join(','))
    }
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

const loadProviderOptions = async () => {
  try {
    const result = await adminApi.getModelProviders()
    modelProviderOptions.value = Array.isArray(result) ? normalizeNames(result.join(',')) : normalizeNames((result.items || []).join(','))
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const handlePageChange = (page) => {
  currentPage.value = page
  loadModels()
}

const handlePageSizeChange = (size) => {
  pageSize.value = size
  currentPage.value = 1
  loadModels()
}

const resetToFirstPage = () => {
  currentPage.value = 1
}


const showAddDialog = () => {
  isEdit.value = false
  editingId.value = null
  resetForm()
  dialogVisible.value = true
}

const showEditDialog = (row) => {
  isEdit.value = true
  editingId.value = row.id
  Object.assign(form, {
    model_id: row.model_id,
    display_name: row.display_name,
    provider: row.provider,
    protocol: row.protocol,
    input_price: row.input_price,
    output_price: row.output_price,
    is_active: row.is_active,
    is_recommended: row.is_recommended,
    supports_codex: row.supports_codex,
    supports_claudecode: row.supports_claudecode,
    supports_gemini: row.supports_gemini,
    aliases: row.aliases || [],
    remark: row.remark || '',
  })
  dialogVisible.value = true
}

const openImportFile = () => {
  importFileRef.value?.click()
}

const handleImportFile = async (event) => {
  const [file] = event.target.files || []
  if (!file) return
  importText.value = await file.text()
  event.target.value = ''
}

const fillImportTemplate = () => {
  importText.value = JSON.stringify([
    {
      model_id: 'gpt-4o-mini',
      display_name: 'gpt-4o-mini',
      provider: 'openai',
      protocol: 'openai_chat',
      input_price: 0,
      output_price: 0,
      is_active: true,
      is_recommended: false,
      supports_codex: true,
      supports_claudecode: true,
      supports_gemini: true,
      aliases: [],
      remark: '模板示例',
    },
    {
      model_id: 'claude-3-7-sonnet-20250219',
      display_name: 'claude-3-7-sonnet-20250219',
      provider: 'claude',
      protocol: 'anthropic_messages',
      input_price: 0,
      output_price: 0,
      is_active: true,
      is_recommended: false,
      supports_codex: true,
      supports_claudecode: true,
      supports_gemini: true,
      aliases: [],
      remark: '模板示例',
    },
  ], null, 2)
}

const parseImportItems = () => {
  const text = importText.value.trim()
  if (!text) {
    throw new Error('请输入要导入的内容')
  }

  if (text.startsWith('[')) {
    const data = JSON.parse(text)
    if (!Array.isArray(data)) {
      throw new Error('JSON 数组格式不正确')
    }
    return data
  }

  return text
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line))
}

const downloadJsonFile = (filename, data) => {
  const text = JSON.stringify(data, null, 2)
  const blob = new Blob([text], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

const exportAllModels = async () => {
  exportingAllModels.value = true
  try {
    const result = await adminApi.exportModels()
    const items = Array.isArray(result.items) ? result.items : []
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
    downloadJsonFile(`cpa-models-all-${timestamp}.json`, items)
    ElMessage.success(`已导出 ${result.count || items.length} 个模型`)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    exportingAllModels.value = false
  }
}

const submitImport = async () => {
  importing.value = true
  try {
    const items = parseImportItems().map((item) => ({
      ...item,
      aliases: Array.isArray(item.aliases) ? item.aliases : [],
    }))
    syncCustomProviders(items.map((item) => item.provider).filter(Boolean))
    const result = await adminApi.importModels(items)
    ElMessage.success(`成功导入 ${result.created_count || result.count} 个模型`)
    importDialogVisible.value = false
    importText.value = ''
    resetToFirstPage()
    await loadProviderOptions()
    loadModels()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    importing.value = false
  }
}

const submitQuickCreate = async () => {
  const names = normalizeNames(quickCreateText.value)
  if (!names.length) {
    ElMessage.error('请输入模型名称')
    return
  }

  quickCreating.value = true
  try {
    const result = await adminApi.quickCreateModels(names)
    ElMessage.success(`已处理 ${result.count} 个模型，新增 ${result.created_count} 个，已存在 ${result.existing_count} 个`)
    quickCreateDialogVisible.value = false
    quickCreateText.value = ''
    await loadProviderOptions()
    loadModels()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    quickCreating.value = false
  }
}

const submitForm = async () => {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    const payload = {
      ...form,
      provider: typeof form.provider === 'string' ? form.provider.trim() : form.provider,
      aliases: Array.isArray(form.aliases) ? form.aliases.map((item) => item.trim()).filter(Boolean) : [],
    }
    syncCustomProviders([payload.provider])
    if (isEdit.value) {
      await adminApi.updateModel(editingId.value, payload)
      ElMessage.success('更新成功')
    } else {
      await adminApi.createModel(payload)
      ElMessage.success('添加成功')
    }
    dialogVisible.value = false
    resetToFirstPage()
    await loadProviderOptions()
    loadModels()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    submitting.value = false
  }
}

const removeModel = async (row) => {
  try {
    await adminApi.deleteModel(row.id)
    ElMessage.success('删除成功')
    resetToFirstPage()
    await loadProviderOptions()
    loadModels()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

onMounted(() => {
  if (isAdmin.value) {
    loadProviderOptions()
    loadPricingConfig()
  }
  loadModels()
  mobileMediaQuery = window.matchMedia(MOBILE_QUERY)
  isMobile.value = mobileMediaQuery.matches
  mobileMediaQuery.addEventListener('change', syncMobile)
})

onBeforeUnmount(() => {
  mobileMediaQuery?.removeEventListener('change', syncMobile)
})
</script>

<style scoped>
.page-header {
  align-items: flex-start;
}

.header-actions {
  gap: 12px;
}

.price-currency-select {
  width: 96px;
}

.price-rate-hint {
  margin-left: 8px;
  color: #8ba0ba;
  font-size: 12px;
}

.import-actions {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
}

.hidden-input {
  display: none;
}

.form-tip {
  margin-bottom: 12px;
  color: #606266;
  font-size: 13px;
}

.capability-toolbar {
  display: grid;
  grid-template-columns: minmax(140px, 1fr) minmax(140px, 1fr) minmax(140px, 1fr) auto auto;
  gap: 8px;
  margin-bottom: 12px;
}

.capability-table {
  width: 100%;
}

.capability-total {
  margin-top: 10px;
  color: #8ba0ba;
  font-size: 12px;
}

.capability-mobile-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.capability-mobile-item {
  padding: 10px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 8px;
  background: #fff;
}

.capability-mobile-head,
.capability-mobile-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.capability-mobile-meta {
  margin-top: 6px;
  color: #60748c;
  font-size: 12px;
  overflow-wrap: anywhere;
}

.capability-mobile-actions {
  justify-content: flex-start;
  margin-top: 10px;
}

.capability-empty {
  padding: 24px 0;
  color: #8ba0ba;
  text-align: center;
}

.page-title {
  margin: 0;
  color: #303133;
}

.filter-card {
  margin-bottom: 0;
}

.filter-row {
  display: grid;
  grid-template-columns: 1fr 220px;
  gap: 12px;
}

.pagination {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}

/* ── 移动端：模型卡片流 ── */
.model-card-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.model-card-empty {
  padding: 20px 0;
  text-align: center;
  color: #8ba0ba;
  font-size: 12px;
}

.model-card {
  padding: 10px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 12px;
  background: #fff;
}

.model-card__head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.model-card__name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  font-weight: 700;
  color: #10233f;
}

.model-card__toggle {
  display: flex;
  align-items: center;
  flex: 0 0 auto;
  gap: 2px;
  padding: 2px 0;
  border: none;
  background: none;
  font-size: 11px;
  color: #7f93ad;
  cursor: pointer;
}

.model-card__toggle .el-icon {
  transition: transform 0.2s;
}

.model-card__toggle .el-icon.is-open {
  transform: rotate(180deg);
}

.model-card__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
}

.model-card__rows {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed rgba(148, 163, 184, 0.24);
}

.model-card__row {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr);
  align-items: start;
  gap: 8px;
  font-size: 11px;
}

.model-card__label {
  color: #8ba0ba;
}

.model-card__value {
  min-width: 0;
  color: #40566f;
  word-break: break-word;
}

.model-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed rgba(148, 163, 184, 0.24);
}

@media (max-width: 768px) {
  /* 搜索框与提供商筛选窄屏各占一行 */
  .filter-row {
    grid-template-columns: 1fr;
  }

  .header-actions {
    flex-wrap: wrap;
    gap: 8px;
  }

  .capability-toolbar {
    grid-template-columns: 1fr 1fr;
  }

  .capability-toolbar .el-button {
    width: 100%;
  }
}

</style>
