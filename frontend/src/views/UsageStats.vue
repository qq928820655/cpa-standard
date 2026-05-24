<template>
  <div class="usage-stats page-shell">
    <div class="page-header">
      <div class="page-header-main">
        <div class="page-kicker">Analytics</div>
        <h2 class="page-title">用量统计</h2>
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
      <el-row :gutter="20">
        <el-col :xs="24" :sm="12" :lg="4">
          <el-select v-model="filterDays" placeholder="时间范围" @change="handleQuickRangeChange">
            <el-option :value="7" label="最近 7 天" />
            <el-option :value="14" label="最近 14 天" />
            <el-option :value="30" label="最近 30 天" />
            <el-option :value="90" label="最近 90 天" />
          </el-select>
        </el-col>
        <el-col :xs="24" :sm="12" :lg="8">
          <el-date-picker
            v-model="filterDateRange"
            type="datetimerange"
            range-separator="至"
            start-placeholder="开始时间"
            end-placeholder="结束时间"
            value-format="YYYY-MM-DDTHH:mm:ss"
            clearable
            @change="handleDateRangeChange"
          />
        </el-col>
        <el-col :xs="24" :sm="12" :lg="4">
          <el-select
            v-model="filterKeyId"
            placeholder="筛选 Key / 输入 Key ID"
            filterable
            allow-create
            default-first-option
            clearable
            @change="() => loadData({ resetLogsPage: true })"
          >
            <el-option
              v-for="k in keyOptions"
              :key="k.id"
              :value="k.id"
              :label="`${k.name} (ID: ${k.id})`"
            />
          </el-select>
        </el-col>
        <el-col :xs="24" :sm="12" :lg="4">
          <el-select v-model="filterStatus" placeholder="筛选状态" clearable @change="() => { resetToFirstPage(); loadLogs() }">
            <el-option value="success" label="成功" />
            <el-option value="error" label="失败" />
            <el-option value="in_progress" label="进行中" />
          </el-select>
        </el-col>
        <el-col v-if="showUserFilter" :xs="24" :sm="12" :lg="4">
          <el-select v-model="userIdFilter" placeholder="筛选用户" clearable filterable @change="() => loadData({ resetLogsPage: true })">
            <el-option
              v-for="item in userOptions"
              :key="item.id"
              :label="item.username"
              :value="item.id"
            />
          </el-select>
        </el-col>
      </el-row>
    </el-card>

    <div class="summary-grid">
      <div v-for="item in summaryCards" :key="item.label" class="summary-card">
        <span class="summary-card__label">{{ item.label }}</span>
        <strong class="summary-card__value">{{ item.value }}</strong>
        <span class="summary-card__hint">{{ item.hint }}</span>
      </div>
    </div>

    <el-card class="chart-card" shadow="never">
      <template #header>
        <div class="card-header-simple">
          <div>
            <div class="panel-title">用量趋势</div>
          </div>
        </div>
      </template>
      <v-chart :option="chartOption" class="chart-view" autoresize />
    </el-card>

    <el-card class="logs-card" shadow="never">
      <template #header>
        <div class="logs-header">
          <div>
            <div class="panel-title">请求记录</div>
            <div class="panel-subtitle">仅保留最近 7 天实时明细，历史区间统计基于按天汇总</div>
          </div>
        </div>
      </template>
      <el-table :data="logs" stripe border v-loading="loadingLogs" height="600" class="logs-table" size="small">
        <el-table-column prop="id" label="ID" width="64" />
        <el-table-column prop="api_key_id" label="Key ID" width="60">
          <template #default="{ row }">
            <el-button link type="primary" class="key-id-link" @click="openKeyDetail(row.api_key_id)">
              {{ row.api_key_id }}
            </el-button>
          </template>
        </el-table-column>
        <el-table-column prop="api_key_name" label="Key 名称" width="90">
          <template #default="{ row }">
            <el-tooltip
              v-if="getLogKeyName(row)"
              effect="dark"
              placement="top"
              :show-after="80"
              :content="getLogKeyName(row)"
            >
              <div class="model-cell">{{ getLogKeyName(row) }}</div>
            </el-tooltip>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="model" label="模型" width="90">
          <template #default="{ row }">
            <el-tooltip
              v-if="row.model"
              effect="dark"
              placement="top"
              popper-class="model-tooltip"
              :show-after="80"
              :offset="4"
              :teleported="true"
              :popper-options="modelTooltipPopperOptions"
            >
              <template #content>
                <div class="model-tooltip__content">
                  {{ row.actual_model ? `${row.model} / ${row.actual_model}` : row.model }}
                </div>
              </template>
              <div class="model-cell">
                <span>{{ row.model }}</span>
                <span v-if="row.actual_model" style="color: #909399; font-size: 10px"> /{{ row.actual_model }}</span>
              </div>
            </el-tooltip>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="prompt_tokens" label="输入 Token" width="88" align="right">
          <template #default="{ row }">
            {{ formatCompactTokenValue(row.prompt_tokens) }}
          </template>
        </el-table-column>
        <el-table-column prop="completion_tokens" label="输出 Token" width="88" align="right">
          <template #default="{ row }">
            {{ formatCompactTokenValue(row.completion_tokens) }}
          </template>
        </el-table-column>
        <el-table-column prop="cache_tokens" label="缓存 Token" width="88" align="right">
          <template #default="{ row }">
            {{ row.cache_tokens ? formatCompactTokenValue(row.cache_tokens) : '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="total_tokens" label="总 Token" width="88" align="right">
          <template #default="{ row }">
            {{ formatCompactTokenValue(row.total_tokens) }}
          </template>
        </el-table-column>
        <el-table-column prop="latency_ms" label="总耗时" width="88" align="right">
          <template #default="{ row }">
            {{ formatCompactLatency(row.latency_ms) }}
          </template>
        </el-table-column>
        <el-table-column prop="upstream_latency_ms" label="上游耗时" width="88" align="right">
          <template #default="{ row }">
            {{ formatCompactLatency(row.upstream_latency_ms) }}
          </template>
        </el-table-column>
        <el-table-column prop="cpa_overhead_ms" label="CPA 耗时" width="88" align="right">
          <template #default="{ row }">
            {{ formatCompactLatency(row.cpa_overhead_ms) }}
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="64" align="center">
          <template #default="{ row }">
            <el-tag :type="getStatusTagType(row.status)" size="small">
              {{ getStatusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="request_time" label="请求时间" width="108">
          <template #default="{ row }">
            {{ formatTableTime(row.request_time) }}
          </template>
        </el-table-column>
        <el-table-column prop="error_message" label="错误信息" min-width="120">
          <template #default="{ row }">
            <el-tooltip
              v-if="row.error_message"
              effect="dark"
              placement="top"
              popper-class="error-message-tooltip"
              :show-after="150"
            >
              <template #content>
                <div class="error-message-tooltip__content">{{ row.error_message }}</div>
              </template>
              <div class="error-message-cell">{{ row.error_message }}</div>
            </el-tooltip>
            <span v-else>-</span>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="pageSizeOptions"
          :total="totalLogs"
          layout="total, sizes, prev, pager, next"
          @current-change="handlePageChange"
          @size-change="handlePageSizeChange"
        />
      </div>
    </el-card>

    <el-dialog
      v-model="keyDetailDialogVisible"
      title="Key 详情"
      width="960px"
      @closed="handleKeyDetailDialogClosed"
    >
      <div v-loading="keyDetailLoading" class="key-detail-dialog">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="Key ID">{{ keyDetail.id || '-' }}</el-descriptions-item>
          <el-descriptions-item label="名称">
            <span>{{ keyDetail.name || '-' }}</span>
            <el-button
              v-if="keyDetail.password"
              link
              size="small"
              style="margin-left: 6px; padding: 0"
              title="复制登录密码"
              @click="copyKeyPassword(keyDetail.password)"
            ><el-icon><View /></el-icon></el-button>
          </el-descriptions-item>
          <el-descriptions-item label="提供商">{{ keyDetail.provider || '-' }}</el-descriptions-item>
          <el-descriptions-item label="API Key">{{ keyDetail.api_key_masked || '-' }}</el-descriptions-item>
          <el-descriptions-item label="请求地址">{{ keyDetail.base_url || '-' }}</el-descriptions-item>
          <el-descriptions-item label="启用状态">
            <el-button
              :type="keyDetail.is_active ? 'success' : 'danger'"
              size="small"
              :loading="keyDetailToggling"
              @click="toggleKeyDetailActive"
            >
              {{ keyDetail.is_active ? '已启用' : '已关闭' }}
            </el-button>
          </el-descriptions-item>
          <el-descriptions-item label="权重">{{ keyDetail.weight ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="总请求数">{{ Number(keyDetailSummary.total_requests || 0).toLocaleString('zh-CN') }}</el-descriptions-item>
          <el-descriptions-item label="成功率">{{ getSuccessRate(keyDetailSummary) }}%</el-descriptions-item>
          <el-descriptions-item label="总 Token">{{ formatTokenValue(keyDetailSummary.total_tokens) }}</el-descriptions-item>
          <el-descriptions-item label="输入 Token">{{ formatTokenValue(keyDetailSummary.prompt_tokens) }}</el-descriptions-item>
          <el-descriptions-item label="缓存 Token">{{ formatTokenValue(keyDetailSummary.cache_tokens) }}</el-descriptions-item>
          <el-descriptions-item label="输出 Token">{{ formatTokenValue(keyDetailSummary.completion_tokens) }}</el-descriptions-item>
          <el-descriptions-item label="平均上游耗时">{{ formatLatency(keyDetailSummary.avg_upstream_latency_ms) }}</el-descriptions-item>
          <el-descriptions-item label="CPA 额外耗时">{{ formatLatency(keyDetailSummary.avg_cpa_overhead_ms) }}</el-descriptions-item>
          <el-descriptions-item label="账户余额" :span="2">
            <span v-if="keyDetailBalanceLoading" style="color: #909399; font-size: 13px">查询中...</span>
            <span v-else-if="keyDetailBalance">
              <span style="color: #10b981; font-weight: 600">${{ keyDetailBalance.balance_usd.toFixed(4) }}</span>
              <span style="color: #909399; font-size: 12px; margin-left: 8px">已用 ${{ keyDetailBalance.used_usd.toFixed(4) }}</span>
            </span>
            <span v-else style="color: #909399; font-size: 13px">-</span>
          </el-descriptions-item>
        </el-descriptions>

        <el-card shadow="never" class="key-detail-logs-card">
          <template #header>
            <div class="card-header-simple">
              <div>
                <div class="panel-title">最近请求记录</div>
                <div class="panel-subtitle">查看该 Key 最近命中的请求明细</div>
              </div>
            </div>
          </template>

          <el-table :data="keyDetailLogs" stripe border size="small" v-loading="keyDetailLogsLoading" max-height="360" class="usage-key-detail-table">
            <el-table-column prop="id" label="ID" width="72" />
            <el-table-column prop="model" label="模型" min-width="140">
              <template #default="{ row }">
                <el-tooltip v-if="row.model" effect="dark" placement="top" :show-after="80">
                  <template #content>{{ row.actual_model ? `${row.model} / ${row.actual_model}` : row.model }}</template>
                  <div class="model-cell">
                    <span>{{ row.model }}</span>
                    <span v-if="row.actual_model" style="color: #909399; font-size: 10px"> /{{ row.actual_model }}</span>
                  </div>
                </el-tooltip>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column prop="prompt_tokens" label="输入 Token" width="90" align="right">
              <template #default="{ row }">
                {{ formatCompactTokenValue(row.prompt_tokens) }}
              </template>
            </el-table-column>
            <el-table-column prop="completion_tokens" label="输出 Token" width="90" align="right">
              <template #default="{ row }">
                {{ formatCompactTokenValue(row.completion_tokens) }}
              </template>
            </el-table-column>
            <el-table-column prop="cache_tokens" label="缓存 Token" width="90" align="right">
              <template #default="{ row }">
                {{ row.cache_tokens ? formatCompactTokenValue(row.cache_tokens) : '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="total_tokens" label="总 Token" width="90" align="right">
              <template #default="{ row }">
                {{ formatCompactTokenValue(row.total_tokens) }}
              </template>
            </el-table-column>
            <el-table-column prop="latency_ms" label="总耗时" width="90" align="right">
              <template #default="{ row }">
                {{ formatCompactLatency(row.latency_ms) }}
              </template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="72" align="center">
              <template #default="{ row }">
                <el-tag :type="getKeyDetailStatusType(row.status)" size="small">
                  {{ getKeyDetailStatusLabel(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="request_time" label="请求时间" width="118">
              <template #default="{ row }">
                {{ formatTime(row.request_time) }}
              </template>
            </el-table-column>
          </el-table>

          <div class="pagination">
            <el-pagination
              v-model:current-page="keyDetailLogsPage"
              v-model:page-size="keyDetailLogsPageSize"
              :page-sizes="[10, 20, 50, 100]"
              :total="keyDetailLogsTotal"
              layout="total, sizes, prev, pager, next"
              @current-change="handleKeyDetailLogsPageChange"
              @size-change="handleKeyDetailLogsPageSizeChange"
            />
          </div>
        </el-card>
      </div>
      <template #footer>
        <el-button @click="closeKeyDetailDialog">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute } from 'vue-router'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { ElMessage } from 'element-plus'
import { View } from '@element-plus/icons-vue'
import { statsApi, adminApi, authApi } from '../api'
import { useDisplaySettings } from '../stores/displaySettings'

const { formatToken, formatTokenCompact } = useDisplaySettings()

use([CanvasRenderer, LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent])

const USAGE_STATS_STATE_STORAGE_KEY = 'usageStatsViewState'

const restoreUsageStatsState = () => {
  try {
    const raw = localStorage.getItem(USAGE_STATS_STATE_STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return typeof parsed === 'object' && parsed ? parsed : {}
  } catch {
    return {}
  }
}

const savedState = restoreUsageStatsState()
const route = useRoute()

const filterDays = ref([7, 14, 30, 90].includes(Number(savedState.filterDays)) ? Number(savedState.filterDays) : 7)
const filterDateRange = ref([])
const isCustomDateRange = ref(savedState.dateRangeMode === 'custom' && Array.isArray(savedState.filterDateRange) && savedState.filterDateRange.length === 2)
if (isCustomDateRange.value) {
  filterDateRange.value = savedState.filterDateRange
}
const filterKeyId = ref(savedState.filterKeyId || null)
const filterStatus = ref(typeof savedState.filterStatus === 'string' ? savedState.filterStatus : '')
const keyOptions = ref([])

const keyNameMap = computed(() => {
  const map = {}
  keyOptions.value.forEach((k) => { map[k.id] = k.name })
  return map
})
const getLogKeyName = (row) => row?.api_key_name || keyNameMap.value[row?.api_key_id] || ''
const userIdFilter = ref(null)
const userOptions = ref([])
const showUserFilter = computed(() => authApi.isAdmin() && authApi.isLoggedIn())
const modelTooltipPopperOptions = {
  modifiers: [
    {
      name: 'offset',
      options: {
        offset: [0, 4],
      },
    },
    {
      name: 'preventOverflow',
      options: {
        boundary: 'viewport',
        padding: 8,
      },
    },
    {
      name: 'flip',
      options: {
        fallbackPlacements: ['top-start', 'top-end', 'bottom'],
      },
    },
  ],
}
const keyDetailDialogVisible = ref(false)
const keyDetailLoading = ref(false)
const keyDetail = ref({})
const keyDetailSummary = ref({})
const keyDetailLogs = ref([])
const keyDetailLogsLoading = ref(false)
const keyDetailLogsPage = ref(1)
const keyDetailLogsPageSize = ref(20)
const keyDetailLogsTotal = ref(0)
const keyDetailBalance = ref(null)
const keyDetailBalanceLoading = ref(false)
const keyDetailToggling = ref(false)

const normalizeKeyId = (value) => {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

const formatDateTimeParam = (date) => {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return null
  const pad = (value) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

const buildQuickDateRange = (days) => {
  const end = new Date()
  const start = new Date(end)
  start.setDate(start.getDate() - Number(days || 7))
  return [formatDateTimeParam(start), formatDateTimeParam(end)]
}

const buildStatsParams = () => {
  const params = {}
  const normalizedKeyId = normalizeKeyId(filterKeyId.value)
  const [startTime, endTime] = filterDateRange.value || []

  if (normalizedKeyId) params.api_key_id = normalizedKeyId
  if (filterDays.value) params.days = filterDays.value
  if (isCustomDateRange.value) {
    if (startTime) params.start_time = startTime
    if (endTime) params.end_time = endTime
  }
  if (userIdFilter.value) params.user_id = userIdFilter.value

  return params
}

const formatTokenValue = (value) => formatToken.value(value)

const formatCompactTokenValue = (value) => formatTokenCompact.value(value)

const formatLatencyValue = (value) => {
  const ms = Number(value || 0)
  return `${ms.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ms`
}

const formatCompactLatency = (value) => {
  const ms = Math.round(Number(value || 0))
  return `${ms.toLocaleString('zh-CN')}ms`
}
const formatLatency = (value) => {
  const ms = Math.round(Number(value || 0))
  return `${ms.toLocaleString('zh-CN')} ms`
}

const getSuccessRate = (row) => {
  const totalRequests = Number(row?.total_requests || 0)
  const successRequests = Number(row?.success_requests || 0)
  if (!totalRequests) return 0
  return Math.round((successRequests / totalRequests) * 100)
}

const openKeyDetail = async (apiKeyId) => {
  const keyId = normalizeKeyId(apiKeyId)
  if (!keyId) return

  keyDetailDialogVisible.value = true
  keyDetailLoading.value = true
  keyDetailBalance.value = null
  try {
    const [keyData, summaryData] = await Promise.all([
      adminApi.getKey(keyId),
      statsApi.getSummary({ api_key_id: keyId, days: filterDays.value }),
    ])
    keyDetail.value = keyData || {}
    keyDetailSummary.value = summaryData || {}
    keyDetailLogsPage.value = 1
    await loadKeyDetailLogs(keyId)
    loadKeyDetailBalance(keyId)
  } catch (e) {
    ElMessage.error(e.message || '加载 Key 详情失败')
  } finally {
    keyDetailLoading.value = false
  }
}

const loadKeyDetailBalance = async (keyId) => {
  keyDetailBalanceLoading.value = true
  try {
    const data = await adminApi.getProviderBalance(keyId)
    keyDetailBalance.value = data
  } catch {
    keyDetailBalance.value = null
  } finally {
    keyDetailBalanceLoading.value = false
  }
}

const toggleKeyDetailActive = async () => {
  const keyId = normalizeKeyId(keyDetail.value?.id)
  if (!keyId || keyDetailToggling.value) return
  keyDetailToggling.value = true
  try {
    const updated = await adminApi.toggleKey(keyId)
    keyDetail.value = { ...keyDetail.value, is_active: updated.is_active }
    ElMessage.success(updated.is_active ? 'Key 已启用' : 'Key 已关闭')
  } catch (e) {
    ElMessage.error(e.message || '操作失败')
  } finally {
    keyDetailToggling.value = false
  }
}

const copyKeyPassword = async (password) => {
  if (!password) return
  try {
    await navigator.clipboard.writeText(password)
    ElMessage.success('密码已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}

const loadKeyDetailLogs = async (keyId = normalizeKeyId(keyDetail.value?.id)) => {
  if (!keyId) return
  keyDetailLogsLoading.value = true
  try {
    const result = await statsApi.getLogs({
      api_key_id: keyId,
      days: filterDays.value,
      page: keyDetailLogsPage.value,
      limit: keyDetailLogsPageSize.value,
    })
    keyDetailLogs.value = Array.isArray(result) ? result : (result.items || [])
    keyDetailLogsTotal.value = Array.isArray(result) ? result.length : (result.total || 0)
  } catch (e) {
    ElMessage.error(e.message || '加载 Key 用量明细失败')
  } finally {
    keyDetailLogsLoading.value = false
  }
}

const handleKeyDetailLogsPageChange = (page) => {
  keyDetailLogsPage.value = page
  loadKeyDetailLogs()
}

const handleKeyDetailLogsPageSizeChange = (size) => {
  keyDetailLogsPageSize.value = size
  keyDetailLogsPage.value = 1
  loadKeyDetailLogs()
}

const getKeyDetailStatusType = (status) => {
  if (status === 'success') return 'success'
  if (status === 'error') return 'danger'
  if (status === 'in_progress') return 'warning'
  return 'info'
}

const getKeyDetailStatusLabel = (status) => {
  if (status === 'success') return '成功'
  if (status === 'error') return '失败'
  if (status === 'in_progress') return '进行中'
  return status || '-'
}

const closeKeyDetailDialog = () => {
  keyDetailDialogVisible.value = false
}

const handleKeyDetailDialogClosed = () => {
  keyDetail.value = {}
  keyDetailSummary.value = {}
  keyDetailLogs.value = []
  keyDetailLogsTotal.value = 0
  keyDetailLogsPage.value = 1
  keyDetailBalance.value = null
}

const getStatusLabel = (status) => {
  if (status === 'success') return '成功'
  if (status === 'error') return '失败'
  if (status === 'in_progress') return '进行中'
  return status || '-'
}

const getStatusTagType = (status) => {
  if (status === 'success') return 'success'
  if (status === 'error') return 'danger'
  if (status === 'in_progress') return 'warning'
  return 'info'
}

const summary = ref({
  total_requests: 0,
  success_requests: 0,
  error_requests: 0,
  in_progress_requests: 0,
  total_tokens: 0,
  prompt_tokens: 0,
  completion_tokens: 0,
  cache_tokens: 0,
  avg_latency_ms: 0,
  avg_upstream_latency_ms: 0,
  avg_cpa_overhead_ms: 0,
})

const summaryCards = computed(() => [
  {
    label: '总请求数',
    value: Number(summary.value.total_requests || 0).toLocaleString('zh-CN'),
    hint: '选定时间窗内累计请求次数',
  },
  {
    label: '成功请求',
    value: Number(summary.value.success_requests || 0).toLocaleString('zh-CN'),
    hint: '返回成功响应的请求数量',
  },
  {
    label: '失败请求',
    value: Number(summary.value.error_requests || 0).toLocaleString('zh-CN'),
    hint: '命中错误状态的请求数量',
  },
  {
    label: '进行中请求',
    value: Number(summary.value.in_progress_requests || 0).toLocaleString('zh-CN'),
    hint: '仍在处理或尚未完成的请求',
  },
  {
    label: '总 Token',
    value: Number(summary.value.total_tokens || 0).toLocaleString('zh-CN'),
    hint: '输入与输出 Token 总和',
  },
  {
    label: '输入 Token',
    value: Number(summary.value.prompt_tokens || 0).toLocaleString('zh-CN'),
    hint: '请求侧累计输入 Token',
  },
  {
    label: '输出 Token',
    value: Number(summary.value.completion_tokens || 0).toLocaleString('zh-CN'),
    hint: '响应侧累计输出 Token',
  },
  {
    label: '缓存 Token',
    value: Number(summary.value.cache_tokens || 0).toLocaleString('zh-CN'),
    hint: '命中缓存的输入 Token 数',
  },
  {
    label: '平均上游耗时',
    value: formatLatencyValue(summary.value.avg_upstream_latency_ms),
    hint: '请求在上游处理的平均耗时',
  },
  {
    label: 'CPA 额外耗时',
    value: formatLatencyValue(summary.value.avg_cpa_overhead_ms),
    hint: '系统内部额外处理耗时',
  },
])

const dailyUsage = ref([])
const logs = ref([])
const loadingLogs = ref(false)
const currentPage = ref(Number(savedState.currentPage) > 0 ? Number(savedState.currentPage) : 1)
const pageSize = ref([10, 20, 50, 100].includes(Number(savedState.pageSize)) ? Number(savedState.pageSize) : 50)
const totalLogs = ref(0)
const pageSizeOptions = [10, 20, 50, 100]
const AUTO_REFRESH_INTERVAL = 5000
let refreshTimer = null

const parseServerTime = (time) => {
  if (!time) return null
  if (time instanceof Date) return time
  if (typeof time !== 'string') return new Date(time)

  const normalized = /[zZ]|[+\-]\d{2}:\d{2}$/.test(time) ? time : `${time}Z`
  return new Date(normalized)
}

const formatTime = (time) => {
  const date = parseServerTime(time)
  if (!date || Number.isNaN(date.getTime())) {
    return String(time)
  }
  return date.toLocaleString('zh-CN', { hour12: false })
}

const formatTableTime = (time) => {
  const date = parseServerTime(time)
  if (!date || Number.isNaN(date.getTime())) {
    return String(time)
  }
  const pad = (value) => String(value).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

const chartOption = computed(() => ({
  color: ['#3b82f6', '#06b6d4'],
  tooltip: {
    trigger: 'axis',
    backgroundColor: 'rgba(15, 23, 42, 0.84)',
    borderWidth: 0,
    textStyle: { color: '#f8fafc' },
  },
  legend: {
    data: ['请求数', 'Token 数'],
    top: 0,
    textStyle: { color: '#59708f' },
  },
  grid: {
    left: 10,
    right: 10,
    top: 56,
    bottom: 8,
    containLabel: true,
  },
  xAxis: {
    type: 'category',
    data: dailyUsage.value.map((d) => d.date),
    axisLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.22)' } },
    axisLabel: { color: '#6b7f99' },
  },
  yAxis: [
    {
      type: 'value',
      name: '请求数',
      nameTextStyle: { color: '#6b7f99' },
      axisLabel: { color: '#6b7f99' },
      splitLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.14)' } },
    },
    {
      type: 'value',
      name: 'Token 数',
      nameTextStyle: { color: '#6b7f99' },
      axisLabel: { color: '#6b7f99' },
      splitLine: { show: false },
    },
  ],
  series: [
    {
      name: '请求数',
      type: 'bar',
      barMaxWidth: 28,
      itemStyle: {
        borderRadius: [10, 10, 0, 0],
      },
      data: dailyUsage.value.map((d) => d.total_requests),
    },
    {
      name: 'Token 数',
      type: 'line',
      yAxisIndex: 1,
      smooth: true,
      symbol: 'circle',
      symbolSize: 7,
      lineStyle: { width: 3 },
      areaStyle: {
        color: 'rgba(6, 182, 212, 0.10)',
      },
      data: dailyUsage.value.map((d) => d.total_tokens),
    },
  ],
}))

const loadSummaryAndDaily = async () => {
  const params = buildStatsParams()
  const [summaryData, dailyData] = await Promise.all([
    statsApi.getSummary(params),
    statsApi.getDaily(params),
  ])
  summary.value = summaryData
  dailyUsage.value = dailyData
}

const loadData = async ({ resetLogsPage = false } = {}) => {
  try {
    await loadSummaryAndDaily()
  } catch (e) {
    ElMessage.error(e.message || '加载统计数据失败')
  }
  if (resetLogsPage) {
    resetToFirstPage()
  }
  loadLogs()
}

const loadLogs = async () => {
  loadingLogs.value = true
  try {
    const params = {
      ...buildStatsParams(),
      page: currentPage.value,
      limit: pageSize.value,
    }
    if (filterStatus.value) params.status = filterStatus.value

    const result = await statsApi.getLogs(params)

    if (Array.isArray(result)) {
      logs.value = result
      totalLogs.value = result.length
    } else {
      logs.value = result.items || []
      totalLogs.value = result.total || 0
    }
  } catch (e) {
    ElMessage.error(e.message || '加载日志失败')
  } finally {
    loadingLogs.value = false
  }
}

const loadKeyOptions = async () => {
  try {
    const result = await adminApi.listKeys({ page: 1, limit: 500 })
    const items = Array.isArray(result) ? result : (result.items || [])
    keyOptions.value = items.map((item) => ({
      id: item.id,
      name: item.name || `Key ${item.id}`,
    }))
  } catch (e) {
    ElMessage.error(e.message || '加载 Key 列表失败')
  }
}

const loadUserOptions = async () => {
  if (!showUserFilter.value) return
  try {
    const users = await authApi.listUsers()
    userOptions.value = Array.isArray(users) ? users : []
  } catch {
    // 忽略
  }
}

const handleQuickRangeChange = (days) => {
  isCustomDateRange.value = false
  filterDateRange.value = []
  loadData({ resetLogsPage: true })
}

const handleDateRangeChange = (value) => {
  isCustomDateRange.value = Boolean(value && value.length)
  if (!isCustomDateRange.value) {
    filterDateRange.value = []
  }
  loadData({ resetLogsPage: true })
}

const handlePageChange = (page) => {
  currentPage.value = page
  loadLogs()
}

const handlePageSizeChange = (size) => {
  pageSize.value = size
  currentPage.value = 1
  loadLogs()
}

const stopAutoRefresh = () => {
  if (!refreshTimer) return
  clearInterval(refreshTimer)
  refreshTimer = null
}

const refreshDataSilently = async () => {
  if (document.hidden || loadingLogs.value) return
  try {
    await loadSummaryAndDaily()
    await loadLogs()
  } catch {
    // ignore background refresh errors
  }
}

const startAutoRefresh = () => {
  stopAutoRefresh()
  refreshTimer = window.setInterval(refreshDataSilently, AUTO_REFRESH_INTERVAL)
}

const handleVisibilityChange = () => {
  if (document.hidden) {
    stopAutoRefresh()
    return
  }
  refreshDataSilently()
  startAutoRefresh()
}

const resetToFirstPage = () => {
  currentPage.value = 1
}

const saveUsageStatsState = () => {
  localStorage.setItem(USAGE_STATS_STATE_STORAGE_KEY, JSON.stringify({
    filterDays: filterDays.value,
    filterDateRange: isCustomDateRange.value ? filterDateRange.value : [],
    dateRangeMode: isCustomDateRange.value ? 'custom' : 'quick',
    filterKeyId: filterKeyId.value,
    filterStatus: filterStatus.value,
    currentPage: currentPage.value,
    pageSize: pageSize.value,
  }))
}

watch([filterDays, filterDateRange, isCustomDateRange, filterKeyId, filterStatus, currentPage, pageSize], saveUsageStatsState, { deep: true })
watch(
  () => route.path,
  (path) => {
    if (path === '/usage') {
      saveUsageStatsState()
    }
  }
)

onMounted(() => {
  loadKeyOptions()
  loadUserOptions()
  loadData()
  document.addEventListener('visibilitychange', handleVisibilityChange)
  startAutoRefresh()
})

onBeforeUnmount(() => {
  stopAutoRefresh()
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})
</script>

<style scoped>
.card-header-simple {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.panel-title {
  font-size: 17px;
  font-weight: 700;
  color: #10233f;
}

.panel-subtitle {
  margin-top: 12px;
  font-size: 13px;
  line-height: 1.6;
  color: #7f93ad;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
}

.summary-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
}

.summary-card__label {
  font-size: 13px;
  font-weight: 700;
  color: #6b7f99;
}

.summary-card__value {
  font-size: 26px;
  line-height: 1.2;
  color: #10233f;
}

.summary-card__hint {
  font-size: 12px;
  line-height: 1.6;
  color: #8ba0ba;
}

.chart-view {
  height: 340px;
}

.logs-card {
  min-height: 0;
}

.logs-table :deep(.el-table__cell),
.usage-key-detail-table :deep(.el-table__cell) {
  padding: 8px 0;
}

.logs-table :deep(th.el-table__cell > .cell),
.logs-table :deep(td.el-table__cell > .cell),
.usage-key-detail-table :deep(th.el-table__cell > .cell),
.usage-key-detail-table :deep(td.el-table__cell > .cell) {
  padding: 0 6px;
}

.model-cell {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:deep(.model-tooltip) {
  max-width: min(720px, calc(100vw - 48px));
}

.model-tooltip__content {
  max-width: min(720px, calc(100vw - 48px));
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
  user-select: text;
}

.error-message-cell {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:deep(.error-message-tooltip) {
  max-width: min(720px, calc(100vw - 48px));
}

.error-message-tooltip__content {
  max-width: min(720px, calc(100vw - 48px));
  max-height: 60vh;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
}

.pagination {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}

.logs-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}

.logs-table :deep(.el-table__column-resize-proxy),
.usage-key-detail-table :deep(.el-table__column-resize-proxy) {
  background-color: #409eff;
}

@media (max-width: 768px) {
  .summary-grid {
    grid-template-columns: 1fr;
  }
}
</style>
