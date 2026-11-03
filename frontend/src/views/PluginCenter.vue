<template>
  <div class="plugin-center">
    <header class="page-header"><div><div class="page-kicker">Extension Center</div><h1>插件中心</h1><p>核心 CPA 默认不安装影视界。插件从 GitHub Release 下载并校验后启用。</p></div></header>
    <el-card class="source-card">
      <template #header><strong>GitHub 插件源</strong></template>
      <el-alert type="info" :closable="false" title="默认使用 CPA 项目仓库的 Release；管理员可按需覆盖。" />
      <div class="source-form"><el-input v-model="githubRepo" placeholder="owner/repo" /><el-button type="primary" :loading="saving" @click="saveSource">保存插件源</el-button><el-button :loading="loadingReleases" @click="loadReleases">查询 Release</el-button><el-upload :show-file-list="false" accept=".zip" :before-upload="importPlugin"><el-button :loading="importing">导入插件 ZIP</el-button></el-upload></div>
    </el-card>
    <el-card class="plugin-card">
      <template #header><strong>已安装插件</strong></template>
      <el-alert v-if="pluginLoadError" :title="pluginLoadError" type="error" :closable="false" />
      <el-empty v-else-if="!installed.length" description="当前未安装可选插件" />
      <div v-else class="plugin-list"><article v-for="item in installed" :key="item.id"><div><strong>{{ item.id }}</strong><span>版本 {{ item.version }} · {{ item.enabled ? '已启用' : '已禁用' }}</span></div><div class="plugin-actions"><el-tag :type="item.load_error ? 'danger' : item.restart_required ? 'warning' : 'success'">{{ item.load_error || (item.restart_required ? '等待重启' : '正常') }}</el-tag><el-button size="small" :loading="toggling === item.id" @click="togglePlugin(item)">{{ item.enabled ? '禁用' : '启用' }}</el-button><el-button size="small" text type="danger" :loading="uninstalling === item.id" @click="uninstallPlugin(item)">卸载</el-button></div></article></div>
    </el-card>
    <el-card class="release-card">
      <template #header><strong>可用 Release</strong></template>
      <el-empty v-if="releaseLoaded && !releases.length" description="当前仓库没有可用 Release" />
      <div v-else class="release-list"><article v-for="item in releases" :key="item.tag_name"><div><strong>{{ item.name }}</strong><span>{{ item.tag_name }} · {{ formatTime(item.published_at) }}</span></div><div class="release-actions"><el-tag v-for="asset in item.assets" :key="asset.name" size="small">{{ asset.name }}</el-tag><el-button v-if="item.assets.some((asset) => asset.name.includes('cpa-video-world-plugin-') && asset.name.endsWith('.zip'))" size="small" type="primary" :loading="installing === item.tag_name" @click="installRelease(item.tag_name)">安装影视界</el-button></div></article></div>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { adminApi } from '../api'

const githubRepo = ref('')
const installed = ref([])
const pluginLoadError = ref('')
const releases = ref([])
const saving = ref(false)
const loadingReleases = ref(false)
const importing = ref(false)
const installing = ref('')
const toggling = ref('')
const uninstalling = ref('')
const releaseLoaded = ref(false)
const formatTime = (value) => value ? new Date(value).toLocaleString() : '-'
const loadPlugins = async () => { try { const data = await adminApi.listPlugins(); githubRepo.value = data.source?.github_repo || ''; installed.value = data.installed || []; pluginLoadError.value = '' } catch (error) { pluginLoadError.value = error.response?.status === 404 ? '当前后端不支持插件中心，请更新后端程序并重启。' : (error.message || '无法读取插件列表'); throw error } }
const saveSource = async () => { if (!githubRepo.value.trim()) return ElMessage.warning('请填写 owner/repo'); saving.value = true; try { const data = await adminApi.updatePluginSource({ github_repo: githubRepo.value.trim() }); githubRepo.value = data.github_repo; ElMessage.success('插件源已保存') } catch (error) { ElMessage.error(error.message) } finally { saving.value = false } }
const loadReleases = async () => { loadingReleases.value = true; try { const data = await adminApi.listPluginReleases(); releases.value = data.items || []; releaseLoaded.value = true } catch (error) { ElMessage.error(error.message) } finally { loadingReleases.value = false } }
const restartMessage = (result) => result.restart_scheduled ? '插件状态已更新，CPA 正在自动重启' : result.restart_required ? `插件状态已更新，${result.message || '请重启 CPA'}` : '插件状态已更新'
const togglePlugin = async (item) => { toggling.value = item.id; try { const result = await adminApi.setPluginEnabled(item.id, !item.enabled); ElMessage.success(restartMessage(result)); await loadPlugins() } catch (error) { ElMessage.error(error.message) } finally { toggling.value = '' } }
const uninstallPlugin = async (item) => { try { await ElMessageBox.confirm('卸载只会移除插件代码。影视项目、任务、媒体、字幕和导出数据都会保留，重新安装后可继续使用。', `卸载 ${item.id}`, { confirmButtonText: '确认卸载', cancelButtonText: '取消', type: 'warning' }) } catch { return }; uninstalling.value = item.id; try { const result = await adminApi.uninstallPlugin(item.id); ElMessage.success(restartMessage(result)); await loadPlugins() } catch (error) { ElMessage.error(error.message) } finally { uninstalling.value = '' } }
const installRelease = async (tagName) => { installing.value = tagName; try { const result = await adminApi.installPlugin({ tag_name: tagName }); ElMessage.success(restartMessage(result)); await loadPlugins() } catch (error) { ElMessage.error(error.message) } finally { installing.value = '' } }
const importPlugin = async (file) => { importing.value = true; try { const result = await adminApi.importPlugin(file); ElMessage.success(restartMessage(result)); await loadPlugins() } catch (error) { ElMessage.error(error.message) } finally { importing.value = false }; return false }
onMounted(() => loadPlugins().catch(() => {}))
</script>

<style scoped>
.plugin-center { max-width:1100px; margin:0 auto; }.page-header { margin-bottom:16px; }.page-kicker { color:var(--cpa-primary,#2563eb); font-size:12px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; }.page-header h1 { margin:4px 0; }.page-header p, article span { color:var(--cpa-text-secondary); }.source-card, .plugin-card, .release-card { margin-bottom:14px; }.source-form { display:flex; gap:10px; margin-top:14px; }.source-form .el-input { flex:1; }.plugin-list, .release-list { display:flex; flex-direction:column; gap:8px; }.plugin-list article, .release-list article { display:flex; align-items:center; justify-content:space-between; gap:10px; padding:12px; border:1px solid var(--cpa-panel-border-soft); border-radius:10px; }.plugin-list article > div:first-child, .release-list article div { display:flex; min-width:0; flex-direction:column; gap:4px; }.plugin-actions, .release-actions { display:flex; align-items:center; justify-content:flex-end; flex-wrap:wrap; gap:6px; }@media (max-width:768px) { .source-form { flex-direction:column; }.source-form .el-button { min-height:42px; margin:0; }.plugin-list article, .release-list article { align-items:flex-start; flex-direction:column; }.plugin-actions, .release-actions { justify-content:flex-start; width:100%; }.plugin-actions .el-button, .release-actions .el-button { flex:1; min-height:42px; margin:0; } }
</style>
