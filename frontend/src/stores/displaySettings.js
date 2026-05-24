/**
 * 全局显示设置 store
 * 使用 Vue reactive 实现，修改后所有引用页面立即响应
 */
import { reactive, computed } from 'vue'

const STORAGE_KEY = 'cpaDisplaySettings'

const loadFromStorage = () => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return typeof parsed === 'object' && parsed ? parsed : {}
  } catch {
    return {}
  }
}

const saved = loadFromStorage()

const state = reactive({
  // token 超过百万时是否切换为 M 单位，默认开启
  tokenUnitAutoM: saved.tokenUnitAutoM !== undefined ? Boolean(saved.tokenUnitAutoM) : true,
})

const saveToStorage = () => {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({
    tokenUnitAutoM: state.tokenUnitAutoM,
  }))
}

/**
 * 格式化 token 数值
 * - tokenUnitAutoM=true：>= 1,000,000 时显示 x,xxx.xx M，否则千分符整数
 * - tokenUnitAutoM=false：始终千分符整数
 */
const formatToken = computed(() => (value) => {
  const num = Number(value || 0)
  if (state.tokenUnitAutoM && num >= 1_000_000) {
    const m = num / 1_000_000
    return `${m.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} M`
  }
  return num.toLocaleString('zh-CN')
})

/**
 * 紧凑格式（用于表格列）
 * - tokenUnitAutoM=true：>= 1,000,000 → x,xxx.xx M；>= 1,000 → x.xk
 * - tokenUnitAutoM=false：>= 1,000 → x.xk；否则原值
 */
const formatTokenCompact = computed(() => (value) => {
  const num = Number(value || 0)
  if (state.tokenUnitAutoM && num >= 1_000_000) {
    const m = num / 1_000_000
    return `${m.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} M`
  }
  if (num >= 1_000) return `${(num / 1_000).toFixed(1)}k`
  return `${num}`
})

export const useDisplaySettings = () => ({
  state,
  formatToken,
  formatTokenCompact,
  setTokenUnitAutoM(val) {
    state.tokenUnitAutoM = Boolean(val)
    saveToStorage()
  },
})
