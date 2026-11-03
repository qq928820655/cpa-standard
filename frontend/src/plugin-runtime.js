import { reactive } from 'vue'

export const pluginMenuItems = reactive([])

export const addPluginMenuItem = (item) => {
  if (!item?.path || !item?.label || pluginMenuItems.some((entry) => entry.path === item.path)) return
  pluginMenuItems.push(item)
}
