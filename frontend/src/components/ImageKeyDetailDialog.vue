<template>
  <el-dialog
    v-model="visible"
    title="Key 详情"
    width="1040px"
    @closed="handleClosed"
  >
    <div v-loading="loading" class="key-detail-dialog">
      <el-descriptions :column="isMobile ? 1 : 2" border>
        <el-descriptions-item label="Key ID">{{ detail.id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="名称">
          <span>{{ detail.name || '-' }}</span>
          <el-button
            v-if="detail.password"
            link
            size="small"
            style="margin-left: 6px; padding: 0"
            title="复制登录密码"
            @click="copyPassword(detail.password)"
          ><el-icon><View /></el-icon></el-button>
        </el-descriptions-item>
        <el-descriptions-item label="提供商">{{ detail.provider || '-' }}</el-descriptions-item>
        <el-descriptions-item label="启用状态">
          <el-button
            :type="detail.is_active ? 'success' : 'danger'"
            size="small"
            :loading="toggling"
            @click="toggleActive"
          >
            {{ detail.is_active ? '已启用' : '已关闭' }}
          </el-button>
        </el-descriptions-item>
        <el-descriptions-item label="API Key">{{ detail.api_key_masked || '-' }}</el-descriptions-item>
        <el-descriptions-item label="请求地址">
          <a v-if="detail.base_url" :href="detail.base_url" target="_blank" rel="noopener noreferrer" style="color:var(--el-color-primary);word-break:break-all;">{{ detail.base_url }}</a>
          <span v-else>-</span>
        </el-descriptions-item>
        <el-descriptions-item label="独立 fake IP">
          <el-tag :type="detail.enable_fake_ip ? 'success' : 'info'" size="small">
            {{ detail.enable_fake_ip ? '已启用' : '未启用' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="fake IP">{{ detail.fake_ip || '-' }}</el-descriptions-item>
        <el-descriptions-item label="生图总次数">{{ formatNumber(imageStats.total_count || 0) }}</el-descriptions-item>
        <el-descriptions-item label="生图成功率">{{ successRate }}%</el-descriptions-item>
        <el-descriptions-item label="成功次数">{{ formatNumber(imageStats.success_count || 0) }}</el-descriptions-item>
        <el-descriptions-item label="失败次数">{{ formatNumber(imageStats.error_count || 0) }}</el-descriptions-item>
        <el-descriptions-item label="当前余额">
          <span v-if="balanceLoading" style="color: #909399; font-size: 13px">查询中...</span>
          <span v-else-if="balance">
            <span style="color: #10b981; font-weight: 600">${{ balance.balance_usd.toFixed(4) }}</span>
            <span style="color: #909399; font-size: 12px; margin-left: 8px">已用 ${{ balance.used_usd.toFixed(4) }}</span>
          </span>
          <span v-else style="color: #909399; font-size: 13px">-</span>
        </el-descriptions-item>
        <el-descriptions-item label="生图记录数">{{ formatNumber(tasksTotal) }}</el-descriptions-item>
      </el-descriptions>

      <el-card shadow="never" class="key-detail-history-card">
        <template #header>
          <div class="card-header">
            <div>
              <div class="panel-title">生图历史</div>
              <div class="panel-subtitle">查看该 Key 命中的图片生成任务</div>
            </div>
          </div>
        </template>

        <el-table :data="tasks" stripe border size="small" v-loading="tasksLoading" max-height="360">
          <el-table-column prop="id" label="任务" width="72">
            <template #default="{ row }">#{{ row.id }}</template>
          </el-table-column>
          <el-table-column prop="model" label="模型" min-width="210" show-overflow-tooltip />
          <el-table-column label="模式" width="110">
            <template #default="{ row }">
              <div class="mode-cell">
                <el-tag :type="row.request_params?.mode === 'image_to_image' ? 'warning' : 'info'" size="small">
                  {{ row.request_params?.mode === 'image_to_image' ? '图生图' : '文生图' }}
                </el-tag>
                <span v-if="Number(row.request_params?.input_images_count || 0)">参考图 {{ Number(row.request_params.input_images_count) }} 张</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="86" align="center">
            <template #default="{ row }">
              <el-tag :type="statusType(row.status)" size="small">{{ statusText(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="结果" width="82" align="center">
            <template #default="{ row }">{{ row.success_count }} / {{ row.total_count }}</template>
          </el-table-column>
          <el-table-column label="用时" width="92" align="center">
            <template #default="{ row }">{{ formatDuration(row.duration_ms) }}</template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" width="180">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column v-if="showViewAction" label="操作" width="76" fixed="right" align="center">
            <template #default="{ row }">
              <el-button link type="primary" @click="$emit('view-task', row.id)">查看</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="pagination key-detail-pagination">
          <el-pagination
            v-model:current-page="tasksPage"
            v-model:page-size="tasksPageSize"
            :page-sizes="[10, 20, 50]"
            :total="tasksTotal"
            layout="total, sizes, prev, pager, next"
            @current-change="handlePageChange"
            @size-change="handleSizeChange"
          />
        </div>
      </el-card>
    </div>
    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { View } from '@element-plus/icons-vue'
import { adminApi, copyText } from '../api'

const props = defineProps({
  showViewAction: { type: Boolean, default: true },
})

const emit = defineEmits(['view-task', 'key-toggled'])

const MOBILE_QUERY = '(max-width: 768px)'
const isMobile = ref(window.matchMedia(MOBILE_QUERY).matches)
let mobileMediaQuery = window.matchMedia(MOBILE_QUERY)
const syncMobile = (event) => { isMobile.value = event.matches }
mobileMediaQuery.addEventListener('change', syncMobile)
onBeforeUnmount(() => {
  mobileMediaQuery?.removeEventListener('change', syncMobile)
})

const visible = ref(false)
const loading = ref(false)
const detail = ref({})
const toggling = ref(false)
const balance = ref(null)
const balanceLoading = ref(false)
const imageStats = ref({})
const tasks = ref([])
const tasksLoading = ref(false)
const tasksPage = ref(1)
const tasksPageSize = ref(10)
const tasksTotal = ref(0)

const successRate = computed(() => {
  const total = Number(imageStats.value?.total_count || 0)
  if (!total) return '0.00'
  return ((Number(imageStats.value?.success_count || 0) / total) * 100).toFixed(2)
})

const hasTimezone = (value) => /(?:z|[+-]\d{2}:?\d{2})$/i.test(value)

const parseBackendTime = (value) => {
  if (!value) return null
  if (value instanceof Date) return value
  let text = String(value).trim()
  text = text.replace(/(\.\d{3})\d+/, '$1')
  const normalized = hasTimezone(text) ? text : `${text}Z`
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

const formatTime = (value) => {
  const date = parseBackendTime(value)
  if (!date) return '-'
  return date.toLocaleString('zh-CN', { hour12: false })
}

const formatDuration = (value) => {
  const duration = Number(value || 0)
  if (!Number.isFinite(duration) || duration <= 0) return '-'
  if (duration < 1000) return `${duration}ms`
  return `${(duration / 1000).toFixed(duration < 10000 ? 1 : 0)}秒`
}

const formatNumber = (value) => Number(value || 0).toLocaleString('zh-CN')

const statusType = (status) => {
  if (status === 'success') return 'success'
  if (status === 'error') return 'danger'
  if (status === 'running') return 'warning'
  return 'info'
}

const statusText = (status) => {
  const map = {
    pending: '等待中',
    running: '生成中',
    success: '成功',
    error: '失败',
  }
  return map[status] || status || '-'
}

const loadStats = async (apiKeyId) => {
  const res = await adminApi.getImageKeyStats()
  imageStats.value = (res.items || []).find((item) => Number(item.api_key_id) === Number(apiKeyId)) || {}
}

const loadTasks = async (apiKeyId = detail.value?.id) => {
  if (!apiKeyId) return
  tasksLoading.value = true
  try {
    const res = await adminApi.listImageTasks({
      api_key_id: apiKeyId,
      page: tasksPage.value,
      limit: tasksPageSize.value,
    })
    tasks.value = res.items || []
    tasksTotal.value = res.total || 0
  } catch (error) {
    ElMessage.error(error.message || '加载 Key 生图历史失败')
  } finally {
    tasksLoading.value = false
  }
}

const loadBalance = async (keyId) => {
  balanceLoading.value = true
  try {
    balance.value = await adminApi.getProviderBalance(keyId)
  } catch {
    balance.value = null
  } finally {
    balanceLoading.value = false
  }
}

const open = async (apiKeyId) => {
  if (!apiKeyId) return
  visible.value = true
  loading.value = true
  balance.value = null
  try {
    detail.value = (await adminApi.getKey(apiKeyId)) || {}
    tasksPage.value = 1
    await Promise.all([loadStats(apiKeyId), loadTasks(apiKeyId)])
    loadBalance(apiKeyId)
  } catch (error) {
    ElMessage.error(error.message || '加载 Key 详情失败')
  } finally {
    loading.value = false
  }
}

const toggleActive = async () => {
  const keyId = detail.value?.id
  if (!keyId || toggling.value) return
  toggling.value = true
  try {
    const updated = await adminApi.toggleKey(keyId)
    detail.value = { ...detail.value, is_active: updated.is_active }
    ElMessage.success(updated.is_active ? 'Key 已启用' : 'Key 已关闭')
    emit('key-toggled', keyId)
  } catch (e) {
    ElMessage.error(e.message || '操作失败')
  } finally {
    toggling.value = false
  }
}

const copyPassword = async (password) => {
  if (!password) return
  try {
    await copyText(password)
    ElMessage.success('密码已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}

const handlePageChange = (page) => {
  tasksPage.value = page
  loadTasks()
}

const handleSizeChange = (size) => {
  tasksPageSize.value = size
  tasksPage.value = 1
  loadTasks()
}

const handleClosed = () => {
  detail.value = {}
  imageStats.value = {}
  tasks.value = []
  tasksTotal.value = 0
  tasksPage.value = 1
  tasksPageSize.value = 10
  balance.value = null
}

defineExpose({ open })
</script>

<style scoped>
.key-detail-dialog {
  min-height: 220px;
}

.key-detail-history-card {
  margin-top: 14px;
}

.key-detail-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
