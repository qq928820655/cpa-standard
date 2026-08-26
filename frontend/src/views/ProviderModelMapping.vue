<template>
  <div class="provider-model-mapping page-shell">
    <div class="page-header">
      <div class="page-header-main">
        <div class="page-kicker">Model Mapping</div>
        <h2 class="page-title">模型映射</h2>
      </div>
      <div class="header-actions">
        <el-button :loading="exporting" @click="exportMappings">导出配置</el-button>
        <el-button @click="importDialogVisible = true">一键导入</el-button>
        <el-button type="primary" @click="showAddDialog">
          <el-icon><Plus /></el-icon>
          新增映射
        </el-button>
      </div>
    </div>

    <el-card class="filter-card" shadow="never">
      <template #header>
        <div class="card-header-simple">
          <div class="panel-title">筛选与检索</div>
        </div>
      </template>
      <div class="filter-row">
        <el-select v-model="filters.provider" filterable allow-create default-first-option clearable reserve-keyword="false" placeholder="筛选提供商" @change="loadMappings">
          <el-option v-for="item in providerOptions" :key="item" :value="item" :label="item" />
        </el-select>
        <el-input v-model="filters.provider_model" placeholder="查询原始模型" clearable @keyup.enter="loadMappings" @clear="loadMappings" />
        <el-input v-model="filters.real_model" placeholder="查询映射模型" clearable @keyup.enter="loadMappings" @clear="loadMappings" />
        <el-select v-model="filters.enabled" clearable placeholder="启用状态" @change="loadMappings">
          <el-option label="启用" :value="true" />
          <el-option label="停用" :value="false" />
        </el-select>
        <el-button type="primary" @click="loadMappings">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
        <el-button :disabled="!selectedMappings.length" :loading="batchUpdating" @click="batchSetEnabled(true)">批量启用</el-button>
        <el-button :disabled="!selectedMappings.length" :loading="batchUpdating" @click="batchSetEnabled(false)">批量关闭</el-button>
      </div>
    </el-card>

    <el-card v-if="isMobile" shadow="never" class="map-card-card">
      <div class="map-card-toolbar">
        <el-checkbox :model-value="mobileAllMappingsSelected" @change="toggleMobileSelectAllMappings">全选本页</el-checkbox>
        <span class="map-card-count">共 {{ mappings.length }} 条</span>
      </div>
      <div class="map-card-list" v-loading="loading">
        <div v-for="row in mappings" :key="row.id" class="map-card">
          <div class="map-card__head">
            <el-checkbox :model-value="isMappingSelected(row)" @change="() => toggleMappingSelect(row)" />
            <span class="map-card__name">{{ row.provider_model || '-' }}</span>
            <button type="button" class="map-card__toggle" @click="toggleMappingExpand(row.id)">
              <span>{{ isMappingExpanded(row.id) ? '收起' : '详情' }}</span>
              <el-icon :class="{ 'is-open': isMappingExpanded(row.id) }"><ArrowDown /></el-icon>
            </button>
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small" class="status-tag">
              {{ row.enabled ? '启用' : '停用' }}
            </el-tag>
          </div>
          <div class="map-card__meta">
            <el-tag size="small" type="info" effect="plain">{{ row.provider || '-' }}</el-tag>
            <span class="map-card__arrow">→</span>
            <span class="map-card__real">{{ row.real_model || '-' }}</span>
          </div>
          <div v-if="isMappingExpanded(row.id)" class="map-card__detail">
            <div class="map-card__row"><span>ID</span><span>{{ row.id }}</span></div>
            <div class="map-card__row"><span>原始模型</span><span>{{ row.provider_model || '-' }}</span></div>
            <div class="map-card__row"><span>映射模型</span><span>{{ row.real_model || '-' }}</span></div>
            <div class="map-card__row"><span>备注</span><span>{{ row.remark || '-' }}</span></div>
          </div>
          <div class="map-card__actions">
            <el-button type="primary" link @click="copyMapping(row)">复制配置</el-button>
            <el-button type="primary" link @click="duplicateMapping(row)">复制记录</el-button>
            <el-button type="primary" link @click="showEditDialog(row)">编辑</el-button>
            <el-popconfirm title="确定删除此映射？" @confirm="removeMapping(row)">
              <template #reference>
                <el-button type="danger" link>删除</el-button>
              </template>
            </el-popconfirm>
          </div>
        </div>
        <el-empty v-if="!loading && !mappings.length" description="暂无模型映射" :image-size="80" />
      </div>
    </el-card>

    <el-card v-else shadow="never">
      <el-table :data="mappings" stripe border v-loading="loading" height="620" size="small" class="mapping-table" @selection-change="handleSelectionChange">
        <el-table-column type="selection" width="46" align="center" />
        <el-table-column prop="provider" label="提供商" width="120" show-overflow-tooltip />
        <el-table-column prop="provider_model" label="原始模型" width="224" show-overflow-tooltip />
        <el-table-column prop="real_model" label="映射模型" width="199" show-overflow-tooltip />
        <el-table-column prop="enabled" label="状态" width="120" align="center">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small" class="status-tag">
              {{ row.enabled ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" width="262" show-overflow-tooltip />
        <el-table-column label="操作" width="283" fixed="right" class-name="operation-column">
          <template #default="{ row }">
            <div class="action-row">
              <el-dropdown trigger="click">
                <el-button type="primary" link>更多</el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item @click="copyMapping(row)">复制配置</el-dropdown-item>
                    <el-dropdown-item @click="duplicateMapping(row)">复制记录</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
              <el-button type="primary" link @click="showEditDialog(row)">编辑</el-button>
              <el-popconfirm title="确定删除此映射？" @confirm="removeMapping(row)">
                <template #reference>
                  <el-button type="danger" link>删除</el-button>
                </template>
              </el-popconfirm>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="importDialogVisible" title="JSON 批量导入模型映射" :width="isMobile ? '100%' : '760px'" :fullscreen="isMobile" :align-center="!isMobile">
      <div class="import-actions">
        <el-button @click="fillImportTemplate">填充模板</el-button>
        <input ref="importFileRef" type="file" accept=".txt,.json,.jsonl" class="hidden-input" @change="handleImportFile" />
        <el-button @click="openImportFile">选择文件</el-button>
      </div>
      <div class="form-tip">
        支持 JSON 数组或 JSONL 多行对象导入，也支持直接导入“导出配置”生成的内容。
      </div>
      <el-input v-model="importText" type="textarea" :rows="12" placeholder="粘贴 JSON 数组或每行一个 JSON 对象" />
      <template #footer>
        <el-button @click="importDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitImport" :loading="importing">导入</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑模型映射' : '新增模型映射'" :width="isMobile ? '100%' : '620px'" :fullscreen="isMobile" :align-center="!isMobile">
      <el-form :model="form" :rules="rules" ref="formRef" :label-width="isMobile ? 'auto' : '110px'" :label-position="isMobile ? 'top' : 'right'">
        <el-form-item label="提供商" prop="provider">
          <el-select v-model="form.provider" filterable allow-create default-first-option clearable reserve-keyword="false" style="width: 100%">
            <el-option v-for="item in providerOptions" :key="item" :value="item" :label="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="原始模型" prop="provider_model">
          <el-input v-model="form.provider_model" placeholder="该提供商 Key 支持并实际发给上游的模型名" />
        </el-form-item>
        <el-form-item label="映射模型" prop="real_model">
          <el-input v-model="form.real_model" placeholder="CPA 聚合轮询时使用的真实模型名" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button @click="copyCurrentFormConfig">复制配置</el-button>
        <el-button v-if="isEdit" @click="duplicateFromForm">复制记录</el-button>
        <el-button v-if="!isEdit" type="success" @click="submitAndContinue" :loading="submitting">继续添加</el-button>
        <el-button type="primary" @click="submitForm" :loading="submitting">{{ isEdit ? '保存' : '添加' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowDown, Plus } from '@element-plus/icons-vue'
import { adminApi, copyText as copyTextUtil } from '../api'

// 手机竖屏改用卡片流，桌面端保持原表格
const MOBILE_QUERY = '(max-width: 768px)'
const isMobile = ref(false)
let mobileMediaQuery = null
const syncMobile = (event) => {
  isMobile.value = event.matches
}

const expandedMappingIds = ref(new Set())
const isMappingExpanded = (id) => expandedMappingIds.value.has(Number(id))
const toggleMappingExpand = (id) => {
  const next = new Set(expandedMappingIds.value)
  const key = Number(id)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expandedMappingIds.value = next
}

const loading = ref(false)
const submitting = ref(false)
const importing = ref(false)
const exporting = ref(false)
const batchUpdating = ref(false)
const mappings = ref([])
const selectedMappings = ref([])
const providerList = ref([])
const dialogVisible = ref(false)
const importDialogVisible = ref(false)
const isEdit = ref(false)
const editingId = ref(null)
const formRef = ref(null)
const importFileRef = ref(null)
const importText = ref('')

const filters = reactive({
  provider: '',
  provider_model: '',
  real_model: '',
  enabled: null,
})

const form = reactive({
  provider: '',
  provider_model: '',
  real_model: '',
  enabled: true,
  remark: '',
})

const providerOptions = computed(() => {
  const values = [
    'openai',
    'claude',
    'google',
    'deepseek',
    'qwen',
    'azure',
    'custom',
    ...providerList.value,
    ...mappings.value.map((item) => item?.provider),
    filters.provider,
    form.provider,
  ]
  return Array.from(new Set(values.filter((item) => typeof item === 'string' && item.trim()).map((item) => item.trim())))
})

const rules = {
  provider: [{ required: true, message: '请输入提供商', trigger: 'blur' }],
  provider_model: [{ required: true, message: '请输入原始模型', trigger: 'blur' }],
  real_model: [{ required: true, message: '请输入映射模型', trigger: 'blur' }],
}

const buildParams = () => {
  const params = {}
  if (filters.provider) params.provider = filters.provider
  if (filters.provider_model) params.provider_model = filters.provider_model
  if (filters.real_model) params.real_model = filters.real_model
  if (filters.enabled !== null && filters.enabled !== '') params.enabled = filters.enabled
  return params
}

const loadProviders = async () => {
  try {
    const res = await adminApi.getKeyProviders()
    providerList.value = res.items || []
  } catch (_) {
    providerList.value = []
  }
}

const loadMappings = async () => {
  loading.value = true
  try {
    const res = await adminApi.listProviderModelMappings(buildParams())
    mappings.value = res.items || []
    selectedMappings.value = []
  } catch (error) {
    ElMessage.error(error.message || '加载模型映射失败')
  } finally {
    loading.value = false
  }
}

const handleSelectionChange = (rows) => {
  selectedMappings.value = rows || []
}

const selectedMappingIdSet = computed(() => new Set(selectedMappings.value.map((item) => Number(item.id))))
const isMappingSelected = (row) => selectedMappingIdSet.value.has(Number(row.id))
const toggleMappingSelect = (row) => {
  const key = Number(row.id)
  if (selectedMappingIdSet.value.has(key)) {
    selectedMappings.value = selectedMappings.value.filter((item) => Number(item.id) !== key)
  } else {
    selectedMappings.value = [...selectedMappings.value, row]
  }
}
const mobileAllMappingsSelected = computed(
  () => mappings.value.length > 0 && mappings.value.every((item) => selectedMappingIdSet.value.has(Number(item.id))),
)
const toggleMobileSelectAllMappings = () => {
  selectedMappings.value = mobileAllMappingsSelected.value ? [] : [...mappings.value]
}

const batchSetEnabled = async (enabled) => {
  const mappingIds = selectedMappings.value.map((item) => item.id).filter(Boolean)
  if (!mappingIds.length) {
    ElMessage.warning('请先勾选模型映射')
    return
  }
  batchUpdating.value = true
  try {
    const result = await adminApi.batchSetProviderModelMappingsEnabled({ mapping_ids: mappingIds, enabled })
    ElMessage.success(`已${enabled ? '启用' : '关闭'} ${result.count || 0} 条模型映射`)
    await loadMappings()
  } catch (error) {
    ElMessage.error(error.message || '批量更新失败')
  } finally {
    batchUpdating.value = false
  }
}

const resetFilters = () => {
  filters.provider = ''
  filters.provider_model = ''
  filters.real_model = ''
  filters.enabled = null
  loadMappings()
}

const resetForm = () => {
  form.provider = filters.provider || ''
  form.provider_model = ''
  form.real_model = ''
  form.enabled = true
  form.remark = ''
  editingId.value = null
}

const showAddDialog = () => {
  isEdit.value = false
  resetForm()
  dialogVisible.value = true
}

const fillForm = (row) => {
  form.provider = row.provider || ''
  form.provider_model = row.provider_model || ''
  form.real_model = row.real_model || ''
  form.enabled = row.enabled !== false
  form.remark = row.remark || ''
}

const showEditDialog = (row) => {
  isEdit.value = true
  editingId.value = row.id
  fillForm(row)
  dialogVisible.value = true
}

const createDuplicateProviderModel = (value) => {
  const base = value || 'model'
  let candidate = `${base}-copy`
  let index = 2
  const exists = (name) => mappings.value.some((item) => item.provider === form.provider && item.provider_model === name)
  while (exists(candidate)) {
    candidate = `${base}-copy-${index}`
    index += 1
  }
  return candidate
}

const openDuplicateDialog = (row) => {
  isEdit.value = false
  editingId.value = null
  fillForm({
    ...row,
    provider_model: createDuplicateProviderModel(row.provider_model),
  })
  dialogVisible.value = true
}

const splitModelValues = (value) => {
  if (typeof value !== 'string') return []
  return value.replace(/，/g, ',').split(',').map((item) => item.trim()).filter(Boolean)
}

const normalizeImportItem = (item) => ({
  provider: typeof item.provider === 'string' ? item.provider.trim() : '',
  provider_model: typeof item.provider_model === 'string' ? item.provider_model.trim() : '',
  real_model: typeof item.real_model === 'string' ? item.real_model.trim() : '',
  enabled: item.enabled !== false,
  remark: typeof item.remark === 'string' && item.remark.trim() ? item.remark.trim() : null,
})

const expandImportItem = (item) => {
  const normalized = normalizeImportItem(item)
  const providerModels = splitModelValues(normalized.provider_model)
  const realModels = splitModelValues(normalized.real_model)
  if (!providerModels.length || !realModels.length) {
    throw new Error('原始模型和映射模型不能为空')
  }
  if (providerModels.length !== realModels.length) {
    throw new Error(`provider=${normalized.provider || '-'} 的原始模型数量与映射模型数量不一致`)
  }
  return providerModels.map((providerModel, index) => ({
    ...normalized,
    provider_model: providerModel,
    real_model: realModels[index],
  }))
}

const buildPayload = () => normalizeImportItem(form)

const submitForm = async () => {
  await formRef.value?.validate()
  submitting.value = true
  try {
    if (isEdit.value) {
      await adminApi.updateProviderModelMapping(editingId.value, buildPayload())
    } else {
      await adminApi.createProviderModelMapping(buildPayload())
    }
    ElMessage.success('保存成功')
    dialogVisible.value = false
    await loadMappings()
  } catch (error) {
    ElMessage.error(error.message || '保存失败')
  } finally {
    submitting.value = false
  }
}

const submitAndContinue = async () => {
  await formRef.value?.validate()
  submitting.value = true
  try {
    await adminApi.createProviderModelMapping(buildPayload())
    ElMessage.success('添加成功，可继续添加')
    const keepProvider = form.provider
    const keepRealModel = form.real_model
    const keepEnabled = form.enabled
    form.provider_model = createDuplicateProviderModel(form.provider_model)
    form.real_model = keepRealModel
    form.remark = ''
    form.provider = keepProvider
    form.enabled = keepEnabled
    await loadProviders()
    await loadMappings()
  } catch (error) {
    ElMessage.error(error.message || '添加失败')
  } finally {
    submitting.value = false
  }
}

const copyText = async (text) => {
  await copyTextUtil(text)
}

const copyMapping = async (row) => {
  const item = normalizeImportItem(row)
  await copyText(JSON.stringify(item))
  ElMessage.success('已复制映射配置，可直接粘贴到一键导入')
}

const duplicateMapping = (row) => {
  openDuplicateDialog(row)
}

const duplicateFromForm = () => {
  openDuplicateDialog({ ...form })
}

const copyCurrentFormConfig = async () => {
  await copyText(JSON.stringify(buildPayload()))
  ElMessage.success('已复制当前配置，可直接粘贴到一键导入')
}

const exportMappings = async () => {
  exporting.value = true
  try {
    const res = await adminApi.exportProviderModelMappings()
    const text = (res.items || []).map((item) => JSON.stringify(normalizeImportItem(item))).join('\n')
    await copyText(text)
    ElMessage.success(`已复制 ${res.count || 0} 条映射配置`)
  } catch (error) {
    ElMessage.error(error.message || '导出失败')
  } finally {
    exporting.value = false
  }
}

const fillImportTemplate = () => {
  importText.value = [
    JSON.stringify({ provider: 'gettoken', provider_model: '量gpt-5.5', real_model: 'gpt-5.5', enabled: true, remark: '模型映射模板示例' }),
    JSON.stringify({ provider: 'cc', provider_model: 'cc-gpt-5.5,cc-gpt-5.4', real_model: 'gpt-5.5,gpt-5.4', enabled: true, remark: '同一真实模型的另一个提供商模型' }),
  ].join('\n')
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

const parseImportText = () => {
  const text = importText.value.trim()
  if (!text) return []
  if (text.startsWith('[')) {
    const data = JSON.parse(text)
    if (!Array.isArray(data)) throw new Error('JSON 内容必须是数组')
    return data.flatMap(expandImportItem)
  }
  return text
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)
    .flatMap((line) => expandImportItem(JSON.parse(line)))
}

const submitImport = async () => {
  let items = []
  try {
    items = parseImportText()
  } catch (error) {
    ElMessage.error(error.message || '导入内容格式错误')
    return
  }
  if (!items.length) {
    ElMessage.error('请输入要导入的内容')
    return
  }
  importing.value = true
  try {
    const result = await adminApi.importProviderModelMappings(items)
    ElMessage.success(`成功导入 ${result.count} 条映射，新增 ${result.created_count || 0} 条，更新 ${result.updated_count || 0} 条`)
    importDialogVisible.value = false
    importText.value = ''
    await loadProviders()
    await loadMappings()
  } catch (error) {
    ElMessage.error(error.message || '导入失败')
  } finally {
    importing.value = false
  }
}

const removeMapping = async (row) => {
  try {
    await adminApi.deleteProviderModelMapping(row.id)
    ElMessage.success('删除成功')
    await loadMappings()
  } catch (error) {
    ElMessage.error(error.message || '删除失败')
  }
}

onMounted(() => {
  loadProviders()
  loadMappings()
  mobileMediaQuery = window.matchMedia(MOBILE_QUERY)
  isMobile.value = mobileMediaQuery.matches
  mobileMediaQuery.addEventListener('change', syncMobile)
})

onBeforeUnmount(() => {
  mobileMediaQuery?.removeEventListener('change', syncMobile)
})
</script>

<style scoped>
.provider-model-mapping {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.mapping-tip {
  border-radius: 12px;
}

.import-actions {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
}

.hidden-input {
  display: none;
}

.form-tip {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin-bottom: 10px;
}

.mapping-table {
  width: 100%;
  max-width: 100%;
}

.mapping-table :deep(.el-table__body-wrapper .el-table__cell),
.mapping-table :deep(.el-table__body-wrapper .cell) {
  user-select: text;
}

.mapping-table :deep(.el-table__header-wrapper .el-table__cell),
.mapping-table :deep(.action-row),
.mapping-table :deep(.el-button) {
  user-select: none;
}

.mapping-table :deep(.el-table__header-wrapper th .cell) {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 32px;
  width: 100%;
}

.mapping-table :deep(.el-table__column-resize-proxy) {
  background-color: #409eff;
}

.mapping-table :deep(.operation-column .cell) {
  white-space: nowrap;
}

.action-row {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: 10px;
  white-space: nowrap;
}

.action-row :deep(.el-button) {
  flex-shrink: 0;
  margin-left: 0;
  padding-left: 0;
  padding-right: 0;
}

.status-tag {
  min-width: 40px;
}

.filter-row {
  display: grid;
  grid-template-columns: 180px 1fr 1fr 130px auto auto auto auto;
  gap: 10px;
  align-items: center;
}

@media (max-width: 980px) {
  .filter-row {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .filter-row {
    grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
    gap: 8px;
  }

  .filter-row :deep(.el-button) {
    width: 100%;
    margin-left: 0;
  }
}

.map-card-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  margin-bottom: 8px;
}

.map-card-count {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.map-card-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.map-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  padding: 8px 10px;
  background: var(--el-bg-color);
}

.map-card__head {
  display: flex;
  align-items: center;
  gap: 6px;
}

.map-card__name {
  flex: 1 1 auto;
  min-width: 0;
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.map-card__toggle {
  display: flex;
  align-items: center;
  flex: 0 0 auto;
  gap: 2px;
  padding: 2px 0;
  border: none;
  background: none;
  font-size: 11px;
  color: var(--el-text-color-secondary);
  cursor: pointer;
}

.map-card__toggle .el-icon {
  transition: transform 0.2s;
}

.map-card__toggle .el-icon.is-open {
  transform: rotate(180deg);
}

.map-card__meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  font-size: 12px;
  min-width: 0;
}

.map-card__arrow {
  color: var(--el-text-color-secondary);
  flex: 0 0 auto;
}

.map-card__real {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--el-text-color-regular);
}

.map-card__detail {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed var(--el-border-color-lighter);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.map-card__row {
  display: flex;
  gap: 8px;
  font-size: 12px;
}

.map-card__row > span:first-child {
  flex: 0 0 62px;
  color: var(--el-text-color-secondary);
}

.map-card__row > span:last-child {
  flex: 1 1 auto;
  min-width: 0;
  word-break: break-all;
}

.map-card__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.map-card__actions :deep(.el-button) {
  margin-left: 0;
  padding: 0;
  font-size: 12px;
}
</style>
