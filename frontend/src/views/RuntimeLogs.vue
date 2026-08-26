<template>
  <div class="runtime-logs page-shell">
    <div class="page-header">
      <div class="page-header-main">
        <div class="page-kicker">Runtime</div>
        <h2 class="page-title">运行日志</h2>
      </div>
    </div>

    <el-card class="log-console-card" shadow="never">
      <div class="log-toolbar">
        <div class="toolbar-lead">
          <div class="toolbar-field line-limit-field">
            <span>行数</span>
            <el-select v-model="lineLimit" @change="resetAndRefresh">
              <el-option v-for="item in lineOptions" :key="item" :label="item" :value="item" />
            </el-select>
          </div>
          <el-button class="toolbar-btn" @click="paused = !paused">{{ paused ? '继续' : '暂停' }}</el-button>
          <el-button class="toolbar-btn" @click="scrollToBottom">底部</el-button>
        </div>
        <el-input
          v-model="keyword"
          class="keyword-input"
          clearable
          placeholder="筛选关键词..."
          @keyup.enter="resetAndRefresh"
          @clear="resetAndRefresh"
        />
        <el-switch v-model="autoScroll" active-text="自动滚屏" />
        <div class="toolbar-spacer"></div>
        <span class="buffer-status">{{ formatBytes(totalBytes) }} / {{ formatBytes(maxBytes) }}</span>
        <span class="update-time">更新 {{ lastUpdated || '--:--:--' }}（UTC+8）</span>
      </div>

      <el-alert
        v-if="!enabled"
        title="运行日志显示未开启，请先在系统设置中开启。"
        type="warning"
        :closable="false"
        show-icon
      />

      <div ref="consoleRef" class="log-console" :class="{ 'is-disabled': !enabled, 'is-wrap': wrapLines }">
        <div v-if="loading && !logs.length" class="console-empty">正在加载日志...</div>
        <div v-else-if="!logs.length" class="console-empty">暂无运行日志</div>
        <div v-for="item in logs" :key="item.id" class="log-line" :class="{ 'is-http-error': isHttpError(item) }">
          <span class="log-time">{{ formatLogTime(item.timestamp) }}</span>
          <span class="log-message" :class="levelClass(item)">{{ formatMessage(item) }}</span>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '../api'

const lineOptions = [100, 200, 500, 1000, 2000, 5000]
const lineLimit = ref(500)
const keyword = ref('')
const paused = ref(false)
const autoScroll = ref(true)
const wrapLines = ref(false)
const enabled = ref(false)
const loading = ref(false)
const logs = ref([])
const totalBytes = ref(0)
const maxBytes = ref(3 * 1024 * 1024)
const lastUpdated = ref('')
const consoleRef = ref(null)
let refreshTimer = null
let requestRunning = false
let latestId = 0

const formatBytes = (value) => {
  const bytes = Number(value || 0)
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(2)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}

const formatLogTime = (value) => {
  const text = String(value || '')
  return text.length >= 19 ? text.slice(11, 19) : text
}

const formatMessage = (item) => {
  const logger = item.logger && item.logger !== 'root' ? `${item.logger}: ` : ''
  return `${item.level}: ${logger}${item.message}`
}

const isHttpError = (item) => /(^|\D)[45]\d{2}(\D|$)/.test(String(item.message || ''))

const levelClass = (item) => {
  const normalized = String(item.level || '').toLowerCase()
  if (normalized === 'error' || normalized === 'critical' || isHttpError(item)) return 'is-error'
  if (normalized === 'warning') return 'is-warning'
  if (normalized === 'debug') return 'is-debug'
  return 'is-info'
}

const scrollToBottom = async () => {
  await nextTick()
  if (consoleRef.value) consoleRef.value.scrollTop = consoleRef.value.scrollHeight
}

const loadWrapConfig = async () => {
  try {
    const data = await adminApi.getRuntimeLogConfig()
    wrapLines.value = !!data.wrap
  } catch {
    // 读取失败时保持默认单行显示
  }
}

const handleConfigChanged = (event) => {
  if (event?.detail && 'wrap' in event.detail) wrapLines.value = !!event.detail.wrap
}

const refreshLogs = async () => {
  if (paused.value || requestRunning) return
  requestRunning = true
  loading.value = true
  try {
    const data = await adminApi.listRuntimeLogs({
      limit: lineLimit.value,
      keyword: keyword.value.trim(),
      after_id: latestId,
    })
    enabled.value = !!data.enabled
    if (typeof data.wrap === 'boolean') wrapLines.value = data.wrap
    const incoming = data.items || []
    logs.value = latestId > 0
      ? [...logs.value, ...incoming].slice(-lineLimit.value)
      : incoming
    latestId = Number(data.latest_id || latestId)
    totalBytes.value = Number(data.total_bytes || 0)
    maxBytes.value = Number(data.max_bytes || 3 * 1024 * 1024)
    lastUpdated.value = new Intl.DateTimeFormat('zh-CN', {
      timeZone: 'Asia/Shanghai',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }).format(new Date())
    if (autoScroll.value) await scrollToBottom()
  } catch (error) {
    ElMessage.error(error.message || '加载运行日志失败')
    stopRefresh()
  } finally {
    loading.value = false
    requestRunning = false
  }
}

const resetAndRefresh = () => {
  latestId = 0
  logs.value = []
  refreshLogs()
}

const startRefresh = () => {
  stopRefresh()
  resetAndRefresh()
  refreshTimer = window.setInterval(refreshLogs, 1000)
}

const stopRefresh = () => {
  if (refreshTimer) {
    window.clearInterval(refreshTimer)
    refreshTimer = null
  }
}

watch(paused, (value) => {
  if (!value) refreshLogs()
})

onMounted(() => {
  loadWrapConfig()
  window.addEventListener('runtime-log-config-changed', handleConfigChanged)
  startRefresh()
})
onActivated(() => {
  loadWrapConfig()
  startRefresh()
})
onDeactivated(stopRefresh)
onBeforeUnmount(() => {
  window.removeEventListener('runtime-log-config-changed', handleConfigChanged)
  stopRefresh()
})
</script>

<style scoped>
.runtime-logs {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 44px);
  overflow: hidden;
}

.log-console-card {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  border-color: #24375d;
  background: #11182c;
}

.log-console-card :deep(.el-card__body) {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  padding: 0;
}

.log-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 58px;
  padding: 9px 14px;
  border-bottom: 1px solid #24456f;
  background: #142342;
  color: #91a4c7;
}

.toolbar-lead {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
}

.toolbar-field {
  display: flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
}

.line-limit-field :deep(.el-select) {
  width: 94px;
}

.toolbar-btn {
  min-width: 64px;
}

.keyword-input {
  width: 275px;
}

.log-toolbar :deep(.el-input__wrapper),
.log-toolbar :deep(.el-select__wrapper) {
  background: #111b33;
  box-shadow: 0 0 0 1px #284b7a inset;
}

.log-toolbar :deep(.el-input__inner),
.log-toolbar :deep(.el-select__placeholder),
.log-toolbar :deep(.el-select__selected-item) {
  color: #d7e2f7;
}

.log-toolbar :deep(.el-button) {
  border-color: #285185;
  background: #122442;
  color: #e3ebfa;
}

.toolbar-spacer {
  flex: 1;
}

.buffer-status,
.update-time {
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
  white-space: nowrap;
}

.log-console {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 10px 0 20px;
  background: #17182b;
  font-family: Consolas, Monaco, "Courier New", monospace;
  font-size: 13px;
  line-height: 1.75;
}

.log-line {
  display: grid;
  grid-template-columns: 92px minmax(max-content, 1fr);
  min-width: max-content;
  padding: 0 10px;
}

.log-line:hover {
  background: rgba(59, 130, 246, 0.08);
}

.log-time {
  color: #52e3a4;
}

.log-message {
  padding-left: 16px;
  white-space: pre;
  color: #f4f7ff;
}

/* 自动换行模式：日志按控制台宽度折行，取消横向滚动 */
.log-console.is-wrap .log-line {
  grid-template-columns: 92px minmax(0, 1fr);
  min-width: 0;
}

.log-console.is-wrap .log-message {
  white-space: pre-wrap;
  word-break: break-word;
  overflow-wrap: anywhere;
}

.log-message.is-warning {
  color: #ffb600;
}

.log-message.is-error,
.log-line.is-http-error .log-time {
  color: #ff6b82;
}

.log-message.is-debug {
  color: #8b9ab8;
}

.console-empty {
  padding: 48px 20px;
  text-align: center;
  color: #6f7f9f;
}

@media (max-width: 768px) {
  /* 顶部栏(58)+主壳底距(10)+面板内距(24)+底部标签栏(58)=150，留 6px 余量防止舍入出现第二层滚动条 */
  .runtime-logs {
    height: calc(100vh - 156px);
  }

  .log-toolbar {
    flex-wrap: wrap;
    min-height: 0;
  }

  .toolbar-lead {
    width: 100%;
    justify-content: space-between;
  }

  .line-limit-field {
    flex: 1;
  }

  .toolbar-btn {
    flex: 0 0 auto;
  }

  .keyword-input {
    flex: 1;
    width: auto;
  }

  .toolbar-spacer,
  .buffer-status,
  .update-time {
    display: none;
  }

  .log-console {
    font-size: 11px;
  }

  .log-line {
    grid-template-columns: 62px minmax(max-content, 1fr);
    padding: 0 6px;
  }

  .log-message {
    padding-left: 6px;
  }
}
</style>
