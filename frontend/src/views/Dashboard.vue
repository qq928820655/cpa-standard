<template>
  <div class="dashboard page-shell">
    <div class="page-header">
      <div class="page-header-main">
        <div class="page-kicker">Overview</div>
        <h2 class="page-title">仪表盘</h2>
      </div>
    </div>

    <div class="dashboard-metrics-grid">
      <el-card v-for="item in metricCards" :key="item.label" class="metric-card" shadow="never">
        <div class="metric-card__inner">
          <div class="metric-card__icon" :style="{ background: item.gradient }">
            <el-icon :size="22"><component :is="item.icon" /></el-icon>
          </div>
          <div class="metric-card__content">
            <span class="metric-card__label">{{ item.label }}</span>
            <strong class="metric-card__value">{{ item.value }}</strong>
            <span class="metric-card__hint">{{ item.hint }}</span>
          </div>
        </div>
      </el-card>
    </div>

    <el-row :gutter="20" class="chart-row">
      <el-col :xs="24" :lg="16">
        <el-card class="dashboard-panel trend-panel" shadow="never">
          <template #header>
            <div class="card-header">
              <div>
                <div class="panel-title">每日请求趋势</div>
              </div>
              <el-select v-model="days" size="small" class="trend-range-select" @change="loadData">
                <el-option :value="7" label="最近 7 天" />
                <el-option :value="14" label="最近 14 天" />
                <el-option :value="30" label="最近 30 天" />
              </el-select>
            </div>
          </template>
          <v-chart :option="chartOption" class="chart-view" autoresize />
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="8">
        <el-card class="dashboard-panel distribution-panel" shadow="never">
          <template #header>
            <div>
              <div class="panel-title">Key 用量分布</div>
            </div>
          </template>
          <v-chart :option="pieOption" class="chart-view chart-view--compact" autoresize />
        </el-card>
      </el-col>
    </el-row>

    <el-card class="key-list-card" shadow="never">
      <template #header>
        <div class="dashboard-key-sticky">
          <div class="card-header card-header--inline">
            <div class="dashboard-key-title">
              <div class="panel-title">API Key 状态</div>
            </div>
            <div class="dashboard-filters">
              <template v-if="isNarrowScreen">
                <div class="dashboard-filter-row dashboard-filter-row--primary">
                  <el-tooltip content="刷新" placement="top" :show-after="300">
                    <el-button
                      :icon="Refresh"
                      circle
                      size="small"
                      :loading="keyStatsRefreshing"
                      class="dashboard-refresh-btn"
                      @click="handleKeyStatsRefresh"
                    />
                  </el-tooltip>
                  <el-select
                    v-model="keyStatsDays"
                    class="dashboard-filter dashboard-filter--quick-range"
                    placeholder="时间范围"
                    @change="handleKeyStatsQuickRangeChange"
                  >
                    <el-option :value="7" label="最近 7 天" />
                    <el-option :value="14" label="最近 14 天" />
                    <el-option :value="30" label="最近 30 天" />
                    <el-option :value="90" label="最近 90 天" />
                  </el-select>
                  <el-select
                    v-model="providerFilters"
                    class="dashboard-filter dashboard-filter--provider"
                    multiple
                    filterable
                    allow-create
                    collapse-tags
                    clearable
                    placeholder="筛选提供商"
                    @change="handleFilterChange"
                  >
                    <el-option v-for="item in providerOptions" :key="item" :label="item" :value="item" />
                  </el-select>
                  <el-select
                    v-model="modelFilters"
                    class="dashboard-filter dashboard-filter--model"
                    multiple
                    filterable
                    allow-create
                    collapse-tags
                    clearable
                    placeholder="筛选模型"
                    @visible-change="handleModelFilterVisibleChange"
                    @change="handleFilterChange"
                  >
                    <el-option
                      v-for="item in modelOptions"
                      :key="item.model_id"
                      :label="`${item.display_name || item.model_id} (${item.model_id})`"
                      :value="item.model_id"
                    />
                  </el-select>
                </div>
                <div class="dashboard-filter-row dashboard-filter-row--dates">
                  <el-date-picker
                    v-model="mobileKeyStatsStartTime"
                    type="datetime"
                    format="MM-DD HH:mm"
                    value-format="YYYY-MM-DDTHH:mm:ss"
                    placeholder="开始时间"
                    clearable
                    @change="handleMobileKeyStatsDateChange"
                  />
                  <el-date-picker
                    v-model="mobileKeyStatsEndTime"
                    type="datetime"
                    format="MM-DD HH:mm"
                    value-format="YYYY-MM-DDTHH:mm:ss"
                    placeholder="结束时间"
                    clearable
                    @change="handleMobileKeyStatsDateChange"
                  />
                </div>
              </template>
              <template v-else>
              <el-tooltip content="刷新" placement="top" :show-after="300">
                <el-button
                  :icon="Refresh"
                  circle
                  size="small"
                  :loading="keyStatsRefreshing"
                  class="dashboard-refresh-btn"
                  @click="handleKeyStatsRefresh"
                />
              </el-tooltip>
              <el-select
                v-model="keyStatsDays"
                class="dashboard-filter dashboard-filter--quick-range"
                placeholder="时间范围"
                @change="handleKeyStatsQuickRangeChange"
              >
                <el-option :value="7" label="最近 7 天" />
                <el-option :value="14" label="最近 14 天" />
                <el-option :value="30" label="最近 30 天" />
                <el-option :value="90" label="最近 90 天" />
              </el-select>
              <el-date-picker
                v-model="keyStatsDateRange"
                class="dashboard-filter dashboard-filter--date-range"
                :style="{ width: '260px', flex: '0 0 260px', maxWidth: '260px' }"
                type="datetimerange"
                format="MM-DD HH:mm"
                range-separator="至"
                start-placeholder="开始时间"
                end-placeholder="结束时间"
                value-format="YYYY-MM-DDTHH:mm:ss"
                clearable
                @change="handleKeyStatsDateRangeChange"
              />
              <el-select
                v-model="providerFilters"
                class="dashboard-filter dashboard-filter--provider"
                multiple
                filterable
                allow-create
                collapse-tags
                collapse-tags-tooltip
                clearable
                placeholder="筛选提供商"
                @change="handleFilterChange"
              >
                <el-option
                  v-for="item in providerOptions"
                  :key="item"
                  :label="item"
                  :value="item"
                />
              </el-select>
              <el-select
                v-model="modelFilters"
                class="dashboard-filter dashboard-filter--model"
                multiple
                filterable
                allow-create
                collapse-tags
                collapse-tags-tooltip
                clearable
                placeholder="筛选模型"
                @visible-change="handleModelFilterVisibleChange"
                @change="handleFilterChange"
              >
                <el-option
                  v-for="item in modelOptions"
                  :key="item.model_id"
                  :label="`${item.display_name || item.model_id} (${item.model_id})`"
                  :value="item.model_id"
                />
              </el-select>
              <el-select
                v-if="showUserFilter"
                v-model="userIdFilter"
                class="dashboard-filter dashboard-filter--user"
                clearable
                filterable
                placeholder="筛选用户"
                @change="handleFilterChange"
              >
                <el-option
                  v-for="item in userOptions"
                  :key="item.id"
                  :label="item.username"
                  :value="item.id"
                />
              </el-select>
              </template>
            </div>
            <div class="key-status-sort-actions" aria-label="Key 排序">
              <button
                type="button"
                class="key-status-sort-button"
                :class="{ 'is-active': keyTimeSortOrder }"
                :title="keyTimeSortOrder ? `按最后操作时间${keyTimeSortOrder === 'descending' ? '从新到旧' : '从旧到新'}` : '按最后操作时间排序'"
                @click="toggleKeyStatusSort('time')"
              >
                <el-icon class="key-status-sort-type"><Timer /></el-icon>
                <el-icon><component :is="keyTimeSortOrder === 'ascending' ? SortUp : SortDown" /></el-icon>
              </button>
              <button
                type="button"
                class="key-status-sort-button"
                :class="{ 'is-active': keyUsageSortOrder }"
                :title="keyUsageSortOrder ? `按用量${keyUsageSortOrder === 'descending' ? '从高到低' : '从低到高'}` : '按用量排序'"
                @click="toggleKeyStatusSort('usage')"
              >
                <el-icon class="key-status-sort-type"><Coin /></el-icon>
                <el-icon><component :is="keyUsageSortOrder === 'ascending' ? SortUp : SortDown" /></el-icon>
              </button>
            </div>
          </div>
        </div>
      </template>

      <!-- 窄屏：6 列排行榜改卡片流，次要指标折叠在「详情」里 -->
      <div v-if="isNarrowScreen" class="key-rank-list">
        <div v-if="!sortedKeyUsage.length" class="key-rank-empty">暂无数据</div>

        <div v-for="row in sortedKeyUsage" :key="row.api_key_id" class="key-rank-card">
          <div class="key-rank-card__head">
            <button v-if="showUserFilter" type="button" class="key-rank-card__name" @click="openKeyDetail(row.api_key_id)">
              {{ row.api_key_name }}
            </button>
            <span v-else class="key-rank-card__name key-rank-card__name--static">
              {{ row.api_key_name }}
            </span>
            <button type="button" class="key-rank-card__toggle" @click="toggleKeyRowExpand(row.api_key_id)">
              <span>{{ isKeyRowExpanded(row.api_key_id) ? '收起' : '详情' }}</span>
              <el-icon :class="{ 'is-open': isKeyRowExpanded(row.api_key_id) }"><ArrowDown /></el-icon>
            </button>
          </div>

          <div class="key-rank-card__tags">
            <el-tag :type="row.provider === 'claude' ? 'warning' : 'primary'" size="small">
              {{ row.provider }}
            </el-tag>
            <el-tag size="small" type="info">{{ Number(row.total_requests || 0).toLocaleString('zh-CN') }} 次</el-tag>
            <el-tag size="small" type="info">历史 {{ formatNumber(row.lifetime_total_tokens) }} token</el-tag>
          </div>

          <div v-show="isKeyRowExpanded(row.api_key_id)" class="key-rank-card__rows">
            <div class="key-rank-card__row">
              <span class="key-rank-card__label">成功率</span>
              <span class="key-rank-card__value">
                <el-progress :percentage="getSuccessRate(row)" :stroke-width="10" />
              </span>
            </div>
            <div class="key-rank-card__row">
              <span class="key-rank-card__label">平均延迟</span>
              <span class="key-rank-card__value">{{ formatLatency(row.avg_latency_ms) }}</span>
            </div>
          </div>
        </div>
      </div>

      <div v-else class="dashboard-key-table-wrap">
        <el-table
          :data="sortedKeyUsage"
          stripe
          border
          class="dashboard-key-table"
          :max-height="keyTableMaxHeight"
          @sort-change="handleKeyUsageSortChange"
        >
          <el-table-column prop="api_key_name" label="名称" min-width="160" sortable="custom">
            <template #default="{ row }">
              <el-button v-if="showUserFilter" link type="primary" class="key-name-link" @click="openKeyDetail(row.api_key_id)">
                {{ row.api_key_name }}
              </el-button>
              <span v-else class="key-name-static">{{ row.api_key_name }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="provider" label="提供商" width="120" sortable="custom">
            <template #default="{ row }">
              <el-tag :type="row.provider === 'claude' ? 'warning' : 'primary'" size="small">
                {{ row.provider }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="total_requests" label="请求数" width="120" sortable="custom">
            <template #default="{ row }">
              {{ Number(row.total_requests || 0).toLocaleString('zh-CN') }}
            </template>
          </el-table-column>
          <el-table-column prop="lifetime_total_tokens" label="历史 Token" min-width="140" sortable="custom">
            <template #default="{ row }">
              {{ formatNumber(row.lifetime_total_tokens) }}
            </template>
          </el-table-column>
          <el-table-column prop="success_rate" label="成功率" min-width="180" sortable="custom">
            <template #default="{ row }">
              <el-progress :percentage="getSuccessRate(row)" :stroke-width="10" />
            </template>
          </el-table-column>
          <el-table-column prop="avg_latency_ms" label="平均延迟" width="140" sortable="custom">
            <template #default="{ row }">
              {{ formatLatency(row.avg_latency_ms) }}
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>

    <el-dialog
      v-model="keyDetailDialogVisible"
      title="Key 详情"
      width="960px"
      @closed="handleKeyDetailDialogClosed"
    >
      <div v-loading="keyDetailLoading" class="key-detail-dialog">
        <el-descriptions :column="isNarrowScreen ? 1 : 2" border>
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
          <el-descriptions-item label="请求地址">
            <a v-if="keyDetail.base_url" :href="keyDetail.base_url" target="_blank" rel="noopener noreferrer" style="color:var(--el-color-primary);word-break:break-all;">{{ keyDetail.base_url }}</a>
            <span v-else>-</span>
          </el-descriptions-item>
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
          <el-descriptions-item label="历史总请求数">{{ Number(keyDetail.request_count || 0).toLocaleString('zh-CN') }}</el-descriptions-item>
          <el-descriptions-item label="历史成功率">{{ getSuccessRate({ total_requests: keyDetail.request_count, success_requests: keyDetail.success_count }) }}%</el-descriptions-item>
          <el-descriptions-item label="历史总 Token">{{ formatNumber(keyDetail.total_tokens || 0) }}</el-descriptions-item>
          <el-descriptions-item label="历史输入 Token">{{ formatNumber(keyDetail.prompt_tokens || 0) }}</el-descriptions-item>
          <el-descriptions-item label="历史缓存 Token">{{ formatNumber(keyDetail.cache_tokens || 0) }}</el-descriptions-item>
          <el-descriptions-item label="历史输出 Token">{{ formatNumber(keyDetail.completion_tokens || 0) }}</el-descriptions-item>
          <el-descriptions-item label="平均上游耗时">{{ formatLatency(keyDetailSummary.avg_upstream_latency_ms) }}</el-descriptions-item>
          <el-descriptions-item label="CPA 额外耗时">{{ formatLatency(keyDetailSummary.avg_cpa_overhead_ms) }}</el-descriptions-item>
          <el-descriptions-item label="账户余额" :span="isNarrowScreen ? 1 : 2">
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
            <div class="card-header">
              <div>
                <div class="panel-title">最近请求记录</div>
                <div class="panel-subtitle">查看该 Key 最近命中的请求明细</div>
              </div>
            </div>
          </template>

          <el-table :data="keyDetailLogs" stripe border size="small" v-loading="keyDetailLogsLoading" max-height="360" class="dashboard-key-detail-table">
            <el-table-column prop="id" label="ID" width="72" />
            <el-table-column prop="model" label="模型" min-width="140">
              <template #default="{ row }">
                <el-tooltip v-if="row.model" effect="dark" placement="top" :show-after="80">
                  <template #content>{{ row.actual_model ? `${row.model} / ${row.actual_model}` : row.model }}</template>
                  <div class="model-cell" style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
                    <span>{{ row.model }}</span>
                    <span v-if="row.actual_model" style="color: #909399; font-size: 10px"> /{{ row.actual_model }}</span>
                  </div>
                </el-tooltip>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column prop="prompt_tokens" label="输入 Token" width="90" align="right">
              <template #default="{ row }">
                {{ formatNumber(row.prompt_tokens || 0) }}
              </template>
            </el-table-column>
            <el-table-column prop="completion_tokens" label="输出 Token" width="90" align="right">
              <template #default="{ row }">
                {{ formatNumber(row.completion_tokens || 0) }}
              </template>
            </el-table-column>
            <el-table-column prop="cache_tokens" label="缓存 Token" width="90" align="right">
              <template #default="{ row }">
                {{ row.cache_tokens ? formatNumber(row.cache_tokens) : '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="total_tokens" label="总 Token" width="90" align="right">
              <template #default="{ row }">
                {{ formatNumber(row.total_tokens || 0) }}
              </template>
            </el-table-column>
            <el-table-column prop="latency_ms" label="总耗时" width="90" align="right">
              <template #default="{ row }">
                {{ formatLatency(row.latency_ms) }}
              </template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="72" align="center">
              <template #default="{ row }">
                <el-tag :type="getStatusTagType(row.status)" size="small">
                  {{ getStatusLabel(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="request_time" label="请求时间" width="118" show-overflow-tooltip />
          </el-table>

          <div class="pagination key-detail-pagination">
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
        <el-button @click="keyDetailDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, PieChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { ElMessage } from 'element-plus'
import { Coin, SortDown, SortUp, Timer } from '@element-plus/icons-vue'
import { ArrowDown, Refresh, View } from '@element-plus/icons-vue'
import { adminApi, statsApi, authApi, copyText } from '../api'
import { useDisplaySettings } from '../stores/displaySettings'

const { formatToken } = useDisplaySettings()
const formatNumber = (value) => formatToken.value(value)

use([CanvasRenderer, LineChart, PieChart, GridComponent, TooltipComponent, LegendComponent])

const DASHBOARD_STATE_STORAGE_KEY = 'dashboardViewState'

const restoreDashboardState = () => {
  try {
    const raw = localStorage.getItem(DASHBOARD_STATE_STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return typeof parsed === 'object' && parsed ? parsed : {}
  } catch {
    return {}
  }
}

const savedState = restoreDashboardState()
const route = useRoute()

// 窄屏下饼图图例条目过多会压住图形，改为滚动型图例
const MOBILE_CHART_QUERY = '(max-width: 768px)'
const isNarrowScreen = ref(false)
let chartMediaQuery = null
const syncNarrowScreen = (event) => {
  isNarrowScreen.value = event.matches
}

// 窄屏 Key 排行榜改卡片流，次要字段折叠在「详情」里
const expandedKeyIds = ref(new Set())
const isKeyRowExpanded = (id) => expandedKeyIds.value.has(Number(id))
const toggleKeyRowExpand = (id) => {
  const next = new Set(expandedKeyIds.value)
  const key = Number(id)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expandedKeyIds.value = next
}

const days = ref([7, 14, 30].includes(Number(savedState.days)) ? Number(savedState.days) : 7)
const keyStatsDays = ref([7, 14, 30, 90].includes(Number(savedState.keyStatsDays)) ? Number(savedState.keyStatsDays) : 7)
const keyStatsDateRange = ref(
  Array.isArray(savedState.keyStatsDateRange) && savedState.keyStatsDateRange.length === 2
    ? savedState.keyStatsDateRange
    : []
)
const mobileKeyStatsStartTime = ref(keyStatsDateRange.value[0] || '')
const mobileKeyStatsEndTime = ref(keyStatsDateRange.value[1] || '')
const providerFilters = ref(Array.isArray(savedState.providerFilters) ? savedState.providerFilters.filter(Boolean) : [])
const modelFilters = ref(Array.isArray(savedState.modelFilters) ? savedState.modelFilters.filter(Boolean) : [])
const providerOptions = ref([])
const modelOptions = ref([])
const userIdFilter = ref(null)
const userOptions = ref([])
const showUserFilter = computed(() => authApi.isAdmin() && authApi.isLoggedIn())
const keyDetailDialogVisible = ref(false)
const keyDetailLoading = ref(false)
const keyDetail = ref({})
const keyDetailSummary = ref({})
const keyDetailLogs = ref([])
const keyDetailLogsLoading = ref(false)
const keyDetailLogsPage = ref(1)
const keyDetailLogsPageSize = ref(20)
const keyDetailLogsTotal = ref(0)
const keyDetailBalance = ref(null)       // { balance_usd, used_usd } 或 null
const keyDetailBalanceLoading = ref(false)
const keyDetailToggling = ref(false)
const summary = ref({
  total_requests: 0,
  success_requests: 0,
  error_requests: 0,
  total_tokens: 0,
  prompt_tokens: 0,
  completion_tokens: 0,
  avg_latency_ms: 0,
})
const dailyUsage = ref([])
const keyUsage = ref([])
const keyUsageSort = ref({
  timeOrder: ['ascending', 'descending'].includes(savedState.keyUsageSort?.timeOrder) ? savedState.keyUsageSort.timeOrder : null,
  usageOrder: ['ascending', 'descending'].includes(savedState.keyUsageSort?.usageOrder) ? savedState.keyUsageSort.usageOrder : null,
})

const keyTimeSortOrder = computed(() => keyUsageSort.value.timeOrder)
const keyUsageSortOrder = computed(() => keyUsageSort.value.usageOrder)

const toggleKeyStatusSort = (type) => {
  const key = type === 'time' ? 'timeOrder' : 'usageOrder'
  const currentOrder = keyUsageSort.value[key]
  const nextOrder = currentOrder === null
    ? 'descending'
    : currentOrder === 'descending'
      ? 'ascending'
      : null
  keyUsageSort.value = {
    ...keyUsageSort.value,
    [key]: nextOrder,
  }
}

const normalizeText = (value) => String(value || '').trim().toLowerCase()

const normalizeModelTokens = (value) => {
  const normalized = normalizeText(value)
  if (!normalized) return []

  const tokens = new Set([normalized])
  const slashIndex = normalized.indexOf('/')
  if (slashIndex >= 0 && slashIndex < normalized.length - 1) {
    tokens.add(normalized.slice(slashIndex + 1))
  }
  return [...tokens]
}

const filteredKeyUsage = computed(() => {
  const providers = providerFilters.value.map(normalizeText).filter(Boolean)
  const models = modelFilters.value.flatMap(normalizeModelTokens).filter(Boolean)

  return keyUsage.value.filter((item) => {
    if (providers.length && !providers.includes(normalizeText(item.provider))) {
      return false
    }

    if (!models.length) {
      return true
    }

    const supportedModels = Array.isArray(item.supported_models)
      ? item.supported_models.flatMap(normalizeModelTokens).filter(Boolean)
      : []

    if (!supportedModels.length) {
      return true
    }

    return supportedModels.some((name) => models.includes(name))
  })
})

const getSuccessRate = (row) => {
  const totalRequests = Number(row?.total_requests || 0)
  const successRequests = Number(row?.success_requests || 0)
  if (!totalRequests) return 0
  return Math.round((successRequests / totalRequests) * 100)
}

const compareKeyUsageValues = (left, right, prop) => {
  if (prop === 'success_rate') {
    return getSuccessRate(left) - getSuccessRate(right)
  }

  const leftValue = left?.[prop]
  const rightValue = right?.[prop]

  if (typeof leftValue === 'number' || typeof rightValue === 'number') {
    return Number(leftValue || 0) - Number(rightValue || 0)
  }

  return String(leftValue || '').localeCompare(String(rightValue || ''), 'zh-CN', { sensitivity: 'base' })
}

const sortedKeyUsage = computed(() => {
  const items = [...filteredKeyUsage.value]
  const { timeOrder, usageOrder } = keyUsageSort.value

  const compareByOrder = (left, right, prop, order) => {
    if (prop === 'last_request_time') {
      const leftTime = left?.last_request_time ? new Date(left.last_request_time).getTime() : null
      const rightTime = right?.last_request_time ? new Date(right.last_request_time).getTime() : null
      if (leftTime === null && rightTime === null) return 0
      if (leftTime === null) return 1
      if (rightTime === null) return -1
      const result = leftTime - rightTime
      return order === 'ascending' ? result : -result
    }
    const result = compareKeyUsageValues(left, right, prop)
    return order === 'ascending' ? result : -result
  }

  items.sort((left, right) => {
    if (timeOrder) {
      const timeResult = compareByOrder(left, right, 'last_request_time', timeOrder)
      if (timeResult) return timeResult
    }
    if (usageOrder) {
      const usageResult = compareByOrder(left, right, 'lifetime_total_tokens', usageOrder)
      if (usageResult) return usageResult
    }
    return compareByOrder(left, right, 'lifetime_total_tokens', 'descending')
  })
  return items
})

const handleKeyUsageSortChange = ({ prop, order }) => {
  if (prop === 'last_request_time') {
    keyUsageSort.value = { ...keyUsageSort.value, timeOrder: order || null }
  } else if (prop === 'total_tokens') {
    keyUsageSort.value = { ...keyUsageSort.value, usageOrder: order || null }
  }
}

const handleFilterChange = () => {
  loadData()
}

const handleKeyStatsRefresh = async () => {
  if (keyStatsRefreshing.value) return
  keyStatsRefreshing.value = true
  try {
    const userParam = userIdFilter.value ? { user_id: userIdFilter.value } : {}
    const keyParams = {
      ...buildKeyStatsTimeParams(),
      providers: providerFilters.value,
      models: buildEffectiveModelFilters(),
      ...userParam,
    }
    const keyData = await statsApi.getByKey(keyParams)
    keyUsage.value = Array.isArray(keyData) ? keyData : []
  } catch (e) {
    ElMessage.error(e.message || '刷新 Key 状态失败')
  } finally {
    keyStatsRefreshing.value = false
  }
}

const buildKeyStatsTimeParams = () => {
  const hasDateRange = Array.isArray(keyStatsDateRange.value) && keyStatsDateRange.value.length === 2
  if (hasDateRange) {
    return {
      start_time: keyStatsDateRange.value[0],
      end_time: keyStatsDateRange.value[1],
    }
  }

  return {
    days: keyStatsDays.value,
  }
}

const handleKeyStatsQuickRangeChange = () => {
  keyStatsDateRange.value = []
  mobileKeyStatsStartTime.value = ''
  mobileKeyStatsEndTime.value = ''
  loadData()
}

const handleKeyStatsDateRangeChange = (value) => {
  if (!Array.isArray(value) || value.length !== 2) {
    keyStatsDateRange.value = []
  }
  mobileKeyStatsStartTime.value = keyStatsDateRange.value[0] || ''
  mobileKeyStatsEndTime.value = keyStatsDateRange.value[1] || ''
  loadData()
}

const handleMobileKeyStatsDateChange = () => {
  if (mobileKeyStatsStartTime.value && mobileKeyStatsEndTime.value) {
    keyStatsDateRange.value = [mobileKeyStatsStartTime.value, mobileKeyStatsEndTime.value]
    loadData()
    return
  }
  if (!mobileKeyStatsStartTime.value && !mobileKeyStatsEndTime.value) {
    keyStatsDateRange.value = []
    loadData()
  }
}

const formatLatency = (value) => {
  const ms = Math.round(Number(value || 0))
  return `${ms.toLocaleString('zh-CN')} ms`
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

const handleKeyDetailLogsPageChange = (page) => {
  keyDetailLogsPage.value = page
  loadKeyDetailLogs()
}

const handleKeyDetailLogsPageSizeChange = (size) => {
  keyDetailLogsPageSize.value = size
  keyDetailLogsPage.value = 1
  loadKeyDetailLogs()
}

const handleKeyDetailDialogClosed = () => {
  keyDetail.value = {}
  keyDetailSummary.value = {}
  keyDetailLogs.value = []
  keyDetailLogsTotal.value = 0
  keyDetailLogsPage.value = 1
  keyDetailBalance.value = null
}

const loadKeyDetailLogs = async (keyId = keyDetail.value?.id) => {
  if (!keyId) return
  keyDetailLogsLoading.value = true
  try {
    const result = await statsApi.getLogs({
      api_key_id: keyId,
      ...buildKeyStatsTimeParams(),
      page: keyDetailLogsPage.value,
      limit: keyDetailLogsPageSize.value,
    })
    keyDetailLogs.value = Array.isArray(result) ? result : (result.items || [])
    keyDetailLogsTotal.value = Array.isArray(result) ? result.length : (result.total || 0)
  } catch (e) {
    ElMessage.error(e.message || '加载 Key 请求记录失败')
  } finally {
    keyDetailLogsLoading.value = false
  }
}

const loadProviderOptions = async () => {
  try {
    const result = await adminApi.getKeyProviders()
    const items = Array.isArray(result) ? result : (result.items || [])
    providerOptions.value = items.filter(Boolean)
  } catch (e) {
    ElMessage.error(e.message || '加载提供商列表失败')
  }
}

const openKeyDetail = async (apiKeyId) => {
  if (!apiKeyId) return
  keyDetailDialogVisible.value = true
  keyDetailLoading.value = true
  keyDetailBalance.value = null
  try {
    const keyData = await adminApi.getKey(apiKeyId)
    keyDetail.value = keyData || {}
    keyDetailSummary.value = {}
    keyDetailLogsPage.value = 1
    await loadKeyDetailLogs(apiKeyId)
    // 异步加载余额（不阻塞弹窗打开）
    loadKeyDetailBalance(apiKeyId)
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
    // 余额查询失败不报错，静默处理
    keyDetailBalance.value = null
  } finally {
    keyDetailBalanceLoading.value = false
  }
}

const toggleKeyDetailActive = async () => {
  const keyId = keyDetail.value?.id
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
    await copyText(password)
    ElMessage.success('密码已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}

const metricCards = computed(() => [
  {
    label: '总请求数',
    value: Number(summary.value.total_requests || 0).toLocaleString('zh-CN'),
    hint: '当前时间窗累计进入代理的请求规模',
    icon: 'Connection',
    gradient: 'linear-gradient(135deg, #3b82f6, #06b6d4)',
  },
  {
    label: '成功请求',
    value: Number(summary.value.success_requests || 0).toLocaleString('zh-CN'),
    hint: '请求成功返回的总次数',
    icon: 'CircleCheck',
    gradient: 'linear-gradient(135deg, #10b981, #34d399)',
  },
  {
    label: '总 Token 数',
    value: formatNumber(summary.value.total_tokens),
    hint: '累计消耗的输入与输出 Token',
    icon: 'Coin',
    gradient: 'linear-gradient(135deg, #8b5cf6, #6366f1)',
  },
  {
    label: '平均延迟',
    value: formatLatency(summary.value.avg_latency_ms),
    hint: '请求从进入到完成的平均耗时',
    icon: 'Timer',
    gradient: 'linear-gradient(135deg, #f59e0b, #fb7185)',
  },
])

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
    left: 12,
    right: 12,
    top: 52,
    bottom: 12,
    containLabel: true,
  },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    axisLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.24)' } },
    axisLabel: { color: '#6b7f99' },
    splitLine: { show: false },
    data: dailyUsage.value.map((item) => item.date),
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
      type: 'line',
      smooth: true,
      symbol: 'circle',
      symbolSize: 8,
      lineStyle: { width: 3 },
      areaStyle: {
        color: 'rgba(59, 130, 246, 0.10)',
      },
      data: dailyUsage.value.map((item) => item.total_requests),
    },
    {
      name: 'Token 数',
      type: 'line',
      yAxisIndex: 1,
      smooth: true,
      symbol: 'circle',
      symbolSize: 8,
      lineStyle: { width: 3 },
      areaStyle: {
        color: 'rgba(6, 182, 212, 0.10)',
      },
      data: dailyUsage.value.map((item) => item.total_tokens),
    },
  ],
}))

const pieOption = computed(() => ({
  color: ['#3b82f6', '#06b6d4', '#10b981', '#8b5cf6', '#f59e0b', '#fb7185'],
  tooltip: {
    trigger: 'item',
    backgroundColor: 'rgba(15, 23, 42, 0.84)',
    borderWidth: 0,
    textStyle: { color: '#f8fafc' },
  },
  legend: isNarrowScreen.value
    ? {
        type: 'scroll',
        orient: 'horizontal',
        bottom: 0,
        left: 'center',
        width: '92%',
        itemGap: 10,
        itemWidth: 12,
        itemHeight: 8,
        pageIconSize: 10,
        textStyle: { color: '#59708f', fontSize: 11 },
      }
    : {
        bottom: 0,
        textStyle: { color: '#59708f' },
      },
  series: [
    {
      type: 'pie',
      center: isNarrowScreen.value ? ['50%', '42%'] : ['50%', '50%'],
      radius: isNarrowScreen.value ? ['42%', '62%'] : ['48%', '74%'],
      padAngle: 2,
      itemStyle: {
        borderRadius: 10,
        borderColor: 'rgba(255,255,255,0.9)',
        borderWidth: 3,
      },
      label: isNarrowScreen.value ? { show: false } : { color: '#35506f' },
      labelLine: isNarrowScreen.value ? { show: false } : undefined,
      data: filteredKeyUsage.value.map((item) => ({
        name: item.api_key_name,
        value: item.total_tokens,
      })),
    },
  ],
}))

const loadModelOptions = async () => {
  try {
    const result = await adminApi.listModels()
    modelOptions.value = Array.isArray(result) ? result : (result.items || [])
  } catch (e) {
    ElMessage.error(e.message || '加载模型列表失败')
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

const handleModelFilterVisibleChange = async (visible) => {
  if (!visible || modelOptions.value.length) return
  await loadModelOptions()
}

const buildEffectiveModelFilters = () => {
  if (!modelFilters.value.length) {
    return []
  }

  const optionIds = new Set(
    modelOptions.value
      .map((item) => normalizeText(item?.model_id))
      .filter(Boolean)
  )

  return modelFilters.value
    .map((item) => String(item || '').trim())
    .filter((item) => item && !optionIds.has(normalizeText(item)))
}

const loadData = async () => {
  try {
    const userParam = userIdFilter.value ? { user_id: userIdFilter.value } : {}
    const keyParams = {
      ...buildKeyStatsTimeParams(),
      providers: providerFilters.value,
      models: buildEffectiveModelFilters(),
      ...userParam,
    }
    const [summaryData, dailyData, keyData] = await Promise.all([
      statsApi.getSummary({ days: days.value, ...userParam }),
      statsApi.getDaily({ days: days.value, ...userParam }),
      statsApi.getByKey(keyParams),
    ])
    summary.value = summaryData || {}
    dailyUsage.value = Array.isArray(dailyData) ? dailyData : []
    keyUsage.value = Array.isArray(keyData) ? keyData : []
  } catch (e) {
    ElMessage.error(e.message || '加载仪表盘数据失败')
  }
}

const saveDashboardState = () => {
  localStorage.setItem(DASHBOARD_STATE_STORAGE_KEY, JSON.stringify({
    days: days.value,
    keyStatsDays: keyStatsDays.value,
    keyStatsDateRange: keyStatsDateRange.value,
    providerFilters: providerFilters.value,
    modelFilters: modelFilters.value,
    keyUsageSort: keyUsageSort.value,
  }))
}

watch([days, keyStatsDays, keyStatsDateRange, providerFilters, modelFilters, keyUsageSort], saveDashboardState, { deep: true })
watch(
  () => route.path,
  (path) => {
    if (path === '/dashboard') {
      saveDashboardState()
    }
  }
)

onMounted(async () => {
  if (typeof window !== 'undefined' && window.matchMedia) {
    chartMediaQuery = window.matchMedia(MOBILE_CHART_QUERY)
    isNarrowScreen.value = chartMediaQuery.matches
    chartMediaQuery.addEventListener('change', syncNarrowScreen)
  }
  const adminLoads = showUserFilter.value
    ? [loadProviderOptions(), loadModelOptions(), loadUserOptions()]
    : []
  await Promise.all([...adminLoads, loadData()])
})

onUnmounted(() => {
  if (chartMediaQuery) {
    chartMediaQuery.removeEventListener('change', syncNarrowScreen)
    chartMediaQuery = null
  }
})
</script>

<style scoped>
.dashboard-header-card {
  min-width: 220px;
  padding: 16px 18px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 20px;
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.10), rgba(6, 182, 212, 0.08));
  box-shadow: 0 18px 30px rgba(59, 130, 246, 0.10);
}

.dashboard-header-label {
  display: inline-block;
  margin-bottom: 8px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #2563eb;
}

.dashboard-header-card strong {
  display: block;
  font-size: 24px;
  color: #10233f;
}

.dashboard-header-card span:last-child {
  display: block;
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.6;
  color: #6b7f99;
}

.dashboard-metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
}

.metric-card :deep(.el-card__body) {
  padding: 0;
}

.metric-card__inner {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 20px;
}

.metric-card__icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 54px;
  height: 54px;
  border-radius: 18px;
  color: #fff;
  box-shadow: 0 16px 28px rgba(59, 130, 246, 0.18);
}

.metric-card__content {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.metric-card__label {
  font-size: 13px;
  font-weight: 700;
  color: #6b7f99;
}

.metric-card__value {
  font-size: 28px;
  line-height: 1.1;
  color: #10233f;
}

.metric-card__hint {
  font-size: 12px;
  line-height: 1.6;
  color: #8ba0ba;
}

.chart-row {
  margin: 0;
}

.dashboard-panel,
.key-list-card {
  height: 100%;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.card-header--inline {
  position: relative;
  align-items: center;
  flex-wrap: nowrap;
}

.dashboard-key-title {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 0 0 auto;
  min-width: 0;
  white-space: nowrap;
}

.key-status-sort-actions {
  position: absolute;
  top: 50%;
  right: 0;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  gap: 2px;
  transform: translateY(-50%);
}

.key-status-sort-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 0;
  background: transparent;
  color: #a8b5c6;
  cursor: pointer;
}

.key-status-sort-button:hover,
.key-status-sort-button.is-active {
  color: var(--cpa-primary);
}

.key-status-sort-button .el-icon {
  font-size: 14px;
}

.key-status-sort-button .key-status-sort-type {
  margin-right: -3px;
  font-size: 13px;
}

.dashboard-filters {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  width: 100%;
  min-width: 0;
  flex-wrap: nowrap;
}

.dashboard-refresh-btn {
  flex: 0 0 auto;
}

.dashboard-filter {
  flex: 0 0 auto;
}

.dashboard-filter--quick-range {
  width: 112px;
  flex: 0 0 112px;
  max-width: 112px;
}

.dashboard-filter--date-range {
  width: 260px;
  flex: 0 0 260px;
  max-width: 260px;
}

.dashboard-filter--date-range :deep(.el-range-editor.el-input__wrapper) {
  width: 260px;
  flex: 0 0 260px;
  max-width: 260px;
}

.dashboard-filter--date-range :deep(.el-range-input) {
  min-width: 0;
}

.dashboard-filter--date-range :deep(.el-range-separator) {
  padding: 0 4px;
}

.dashboard-filter--provider {
  width: 148px;
  flex: 0 0 148px;
  max-width: 148px;
}

.dashboard-filter--model {
  width: 156px;
  flex: 0 0 156px;
  max-width: 156px;
}

.dashboard-filter--user {
  width: 140px;
  flex: 0 0 140px;
  max-width: 140px;
}


.trend-range-select {
  width: 120px;
}

.panel-title {
  font-size: 17px;
  font-weight: 700;
  color: #10233f;
}

.panel-subtitle {
  margin-top: 6px;
  font-size: 13px;
  color: #7f93ad;
}

.chart-view {
  height: 340px;
}

.chart-view--compact {
  height: 340px;
}

.key-name-link {
  padding: 0;
}

.dashboard-key-table-wrap {
  position: relative;
}

.key-detail-logs-card :deep(.el-card__body) {
  padding-top: 0;
}

.key-detail-pagination {
  margin-top: 12px;
}

@media (max-width: 768px) {
  .dashboard-header-card {
    width: 100%;
  }

  .metric-card__inner {
    align-items: center;
    gap: 8px;
    padding: 10px;
  }

  .metric-card__icon {
    flex: 0 0 40px;
    width: 40px;
    height: 40px;
    border-radius: 13px;
  }

  .metric-card__icon :deep(.el-icon) {
    font-size: 18px !important;
  }

  .metric-card__content {
    gap: 3px;
  }

  .metric-card__label {
    font-size: 11px;
    white-space: nowrap;
  }

  .card-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .card-header--inline {
    display: block;
  }

  .dashboard-key-title {
    min-height: 32px;
    padding-right: 58px;
  }

  .key-status-sort-actions {
    top: 4px;
    right: 0;
    transform: none;
  }

  .dashboard-filters {
    display: flex;
    flex-direction: column;
    flex-wrap: nowrap;
    width: 100%;
    gap: 8px;
  }

  .dashboard-filter-row {
    display: grid;
    width: 100%;
    gap: 6px;
  }

  .dashboard-filter-row--primary {
    grid-template-columns: 32px minmax(0, 0.9fr) minmax(0, 1fr) minmax(0, 1fr);
  }

  .dashboard-filter-row--dates {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .dashboard-filter-row .dashboard-filter,
  .dashboard-filter-row :deep(.el-date-editor) {
    width: 100% !important;
    min-width: 0 !important;
    max-width: none !important;
  }

  .dashboard-filter-row--primary .dashboard-refresh-btn {
    width: 32px;
    height: 32px;
    margin: 0;
  }

  .dashboard-filter-row--primary :deep(.el-select__wrapper),
  .dashboard-filter-row--dates :deep(.el-input__wrapper) {
    min-height: 32px;
    padding-left: 7px;
    padding-right: 7px;
  }

  .dashboard-filter-row--primary :deep(.el-select__placeholder),
  .dashboard-filter-row--primary :deep(.el-select__selected-item),
  .dashboard-filter-row--dates :deep(.el-input__inner) {
    font-size: 11px;
  }

  .dashboard-filter,
  .dashboard-filter--quick-range,
  .dashboard-filter--date-range,
  .dashboard-filter--provider,
  .dashboard-filter--model,
  .dashboard-filter--user {
    width: 100%;
    min-width: 0;
  }

  /* 指标卡一行两个，避免竖排把首屏顶掉 */
  .dashboard-metrics-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }

  .metric-card :deep(.el-card__body) {
    padding: 10px;
  }

  .metric-card__value {
    font-size: 15px;
  }

  .metric-card__hint {
    display: none;
  }
}

/* ── 移动端：API Key 状态卡片流 ── */
.key-rank-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.key-rank-empty {
  padding: 20px 0;
  text-align: center;
  color: var(--cpa-text-tertiary, #8ba0ba);
  font-size: 12px;
}

.key-rank-card {
  padding: 10px;
  border: 1px solid var(--cpa-border-soft, rgba(148, 163, 184, 0.24));
  border-radius: 12px;
  background: var(--cpa-surface, #fff);
}

.key-rank-card__head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.key-rank-card__name {
  flex: 1;
  min-width: 0;
  padding: 0;
  border: none;
  background: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: left;
  font-size: 13px;
  font-weight: 700;
  color: var(--cpa-primary, #3b82f6);
  cursor: pointer;
}

.key-rank-card__toggle {
  display: flex;
  align-items: center;
  flex: 0 0 auto;
  gap: 2px;
  padding: 2px 0;
  border: none;
  background: none;
  font-size: 11px;
  color: var(--cpa-text-tertiary, #7f93ad);
  cursor: pointer;
}

.key-rank-card__toggle .el-icon {
  transition: transform 0.2s;
}

.key-rank-card__toggle .el-icon.is-open {
  transform: rotate(180deg);
}

.key-rank-card__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
}

.key-rank-card__rows {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--cpa-border-soft, rgba(148, 163, 184, 0.24));
}

.key-rank-card__row {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  font-size: 11px;
}

.key-rank-card__label {
  color: var(--cpa-text-tertiary, #8ba0ba);
}

.key-rank-card__value {
  min-width: 0;
  color: var(--cpa-text-secondary, #40566f);
  word-break: break-word;
}
</style>
