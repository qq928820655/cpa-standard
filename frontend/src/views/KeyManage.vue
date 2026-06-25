<template>
  <div class="key-manage page-shell">
    <div class="page-header">
      <div class="page-header-main">
        <div class="page-kicker">Keys</div>
        <h2 class="page-title">API Key 管理</h2>
      </div>
      <div class="header-actions">
        <el-button class="header-action-wide" :loading="exportingAllKeys" @click="exportConfigs">导出配置</el-button>
        <el-button @click="importDialogVisible = true">一键导入</el-button>
        <el-button class="header-action-wide" :loading="batchChecking" @click="openCheckDialog">一键检测</el-button>
        <el-button class="header-action-wide" @click="showBatchDialog">keys调整</el-button>
        <el-popconfirm title="确定删除当前勾选的 Key？" @confirm="batchDeleteSelectedKeys">
          <template #reference>
            <el-button class="header-action-wide" :disabled="!selectedKeys.length" :loading="batchDeleting">一键删除</el-button>
          </template>
        </el-popconfirm>
        <el-button @click="showCooldownDialog">冷却设置</el-button>
        <el-button :disabled="!selectedKeys.length" :loading="batchCooldownSubmitting" @click="batchClearCooldown">解除冷却</el-button>
        <el-button :disabled="!selectedKeys.length" :loading="batchActiveSubmitting" @click="batchSetActive(true)">批量启用</el-button>
        <el-button :disabled="!selectedKeys.length" :loading="batchActiveSubmitting" @click="batchSetActive(false)">批量关闭</el-button>
        <el-button type="primary" @click="showAddDialog">新增key</el-button>
      </div>
    </div>

    <!-- 筛选 -->
    <el-card class="filter-card" :class="{ 'is-collapsed': filtersCollapsed }" shadow="never">
      <template #header>
        <div class="card-header-simple">
          <div>
            <div class="panel-title">筛选条件</div>
          </div>
          <div class="filter-header-actions">
            <div class="filter-summary-text">
              提供商 {{ filterProviders.length }} 项，模型 {{ filterModels.length }} 项，Key ID / 名称 {{ filterKeyIds.length + filterKeyNames.length }} 项，状态 {{ filterActiveLabel }}
            </div>
            <el-button link type="primary" @click="toggleFilters">
              {{ filtersCollapsed ? '展开' : '折叠' }}
            </el-button>
          </div>
        </div>
      </template>

      <div v-show="!filtersCollapsed" class="filter-row">
        <div class="filter-grid">
          <div class="filter-item">
            <el-select
              v-model="filterProviders"
              multiple
              filterable
              allow-create
              default-first-option
              clearable
              collapse-tags
              collapse-tags-tooltip
              placeholder="筛选提供商（可多选）"
              @change="() => { resetToFirstPage(); loadKeys() }"
            >
              <el-option
                v-for="item in providerOptions"
                :key="item.value"
                :value="item.value"
                :label="item.label"
              />
            </el-select>
          </div>
          <div class="filter-item">
            <el-select
              v-model="filterActive"
              clearable
              placeholder="筛选是否启用"
              @change="() => { resetToFirstPage(); loadKeys() }"
            >
              <el-option :value="true" label="已启用" />
              <el-option :value="false" label="已关闭" />
            </el-select>
          </div>
          <div class="filter-item quick-filter-item">
            <div class="quick-filter-row">
              <el-input
                v-model="filterProviderInput"
                clearable
                placeholder="快速输入提供商，使用英文逗号分隔"
                @keyup.enter="applyFilterProviders"
              />
              <el-button @click="applyFilterProviders">加入</el-button>
            </div>
          </div>
          <div class="filter-item quick-filter-item">
            <div class="quick-filter-row">
              <el-input
                v-model="filterKeyIdsInput"
                clearable
                placeholder="输入 Key ID / 名称，支持中英文逗号分隔"
                @keyup.enter="applyFilterKeyIds"
              />
              <el-button @click="applyFilterKeyIds">查询</el-button>
            </div>
          </div>
          <div class="filter-item">
            <el-select
              v-model="filterModels"
              multiple
              filterable
              allow-create
              default-first-option
              clearable
              collapse-tags
              collapse-tags-tooltip
              placeholder="筛选模型（命中任一即可）"
              @change="() => { resetToFirstPage(); loadKeys() }"
            >
              <el-option
                v-for="item in filteredFilterModelOptions"
                :key="item.model_id"
                :label="`${item.display_name || item.model_id} (${item.model_id})`"
                :value="item.model_id"
              />
            </el-select>
          </div>
          <div class="filter-item quick-filter-item">
            <div class="quick-filter-row">
              <el-input
                v-model="filterModelInput"
                clearable
                placeholder="快速输入模型，使用英文逗号分隔"
                @keyup.enter="applyFilterModels"
              />
              <el-button @click="applyFilterModels">加入</el-button>
            </div>
          </div>
        </div>
      </div>
    </el-card>

    <!-- Key 列表 -->
    <div class="keys-table-sticky">
      <el-card class="keys-table-card" shadow="never">
        <el-table
          ref="tableRef"
          :data="keysTableData"
          :row-key="(row) => Number(row.id)"
          stripe
          border
          v-loading="loading"
          size="small"
          class="keys-table"
          height="calc(100vh - 320px)"
          @selection-change="handleSelectionChange"
          @sort-change="handleKeySortChange"
        >
        <el-table-column type="selection" width="34" />
        <el-table-column prop="id" label="ID" width="62" sortable="custom" />
        <el-table-column prop="name" label="名称" width="102" show-overflow-tooltip sortable="custom">
          <template #default="{ row }">
            <el-button link type="primary" style="padding: 0; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap" @click="openKeyDetail(row.id)">
              {{ row.name }}
            </el-button>
          </template>
        </el-table-column>
        <el-table-column prop="provider" label="提供商" width="91" sortable="custom">
          <template #default="{ row }">
            <el-tag :type="getProviderType(row.provider)" size="small">
              {{ row.provider }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="api_type" label="类型" width="80" align="center">
          <template #default="{ row }">
            <el-tag :type="getApiTypeTagType(row.api_type)" size="small">
              {{ getApiTypeLabel(row.api_type) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="api_key_masked" label="API Key" width="127" show-overflow-tooltip>
          <template #default="{ row }">
            <code class="code-cell">{{ row.api_key_masked }}</code>
          </template>
        </el-table-column>
        <el-table-column prop="base_url" label="请求地址" width="152">
          <template #default="{ row }">
            <el-tooltip
              v-if="row.base_url"
              effect="dark"
              placement="top"
              popper-class="base-url-tooltip"
              :show-after="80"
              :offset="4"
              :teleported="true"
            >
              <template #content>
                <div class="base-url-tooltip__content">{{ row.base_url }}</div>
              </template>
              <div class="base-url-cell">{{ row.base_url }}</div>
            </el-tooltip>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="weight" label="权重" width="74" align="center" sortable="custom" />
        <el-table-column label="支持模型" width="141">
          <template #default="{ row }">
            <span v-if="!row.supported_models?.length">全部模型</span>
            <div v-else class="model-cell">
              <el-tag
                v-for="item in getVisibleModels(row.supported_models)"
                :key="item"
                size="small"
                class="model-tag"
              >
                {{ item }}
              </el-tag>
              <el-tooltip
                v-if="row.supported_models.length > visibleModelCount"
                effect="dark"
                placement="top"
                :content="row.supported_models.join('、')"
              >
                <el-tag size="small" type="info" class="model-tag more-tag">
                  +{{ row.supported_models.length - visibleModelCount }}
                </el-tag>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="is_active" label="状态" width="75" align="center" sortable="custom">
          <template #default="{ row }">
            <div class="status-cell">
              <el-switch
                v-model="row.is_active"
                @change="toggleKey(row)"
                :loading="row.toggling"
              />
              <el-tooltip
                v-if="row.is_cooled_down"
                effect="dark"
                placement="top"
                :content="`冷却中 ${formatCooldownSeconds(row.cooldown_remaining_seconds)}`"
              >
                <el-tag size="small" type="warning" class="status-cooldown-tag">
                  冷却
                </el-tag>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="检测" width="137">
          <template #default="{ row }">
            <div class="check-result-cell">
              <span v-if="row.check_state === 'checking'" class="check-result-pending">检测中...</span>
              <template v-else-if="row.check_state === 'success'">
                <span v-if="row.check_mode === 'balance'" class="check-result-success">
                  ${{ Number(row.check_balance_usd || 0).toFixed(4) }}
                </span>
                <span v-else class="check-result-success">{{ formatCheckLatency(row.check_latency_ms) }}</span>
              </template>
              <el-button
                v-else-if="row.check_state === 'error'"
                type="danger"
                link
                class="check-result-link"
                @click="showCheckFailureDetail(row)"
              >
                {{ getCheckFailureLabel(row.check_error_category) }}
              </el-button>
              <span v-else class="check-result-idle">-</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="132" fixed="right">
          <template #default="{ row }">
            <div class="action-row">
              <el-dropdown trigger="click">
                <el-button type="primary" link>
                  更多
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item @click="copyApiKey(row)">复制 Key</el-dropdown-item>
                    <el-dropdown-item @click="copyKeyConfig(row)">复制配置</el-dropdown-item>
                    <el-dropdown-item @click="duplicateKey(row)">复制记录</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
              <el-button v-if="row.is_cooled_down" type="warning" link :loading="row.clearingCooldown" @click="clearCooldown(row)">解除冷却</el-button>
              <el-button type="primary" link @click="showEditDialog(row)">编辑</el-button>
              <el-popconfirm title="确定删除此 Key？" @confirm="deleteKey(row)">
                <template #reference>
                  <el-button type="danger" link>删除</el-button>
                </template>
              </el-popconfirm>
            </div>
          </template>
        </el-table-column>
        </el-table>
      </el-card>
    </div>

    <div class="pagination key-manage-pagination">
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="pageSizeOptions"
        :total="totalKeys"
        layout="total, sizes, prev, pager, next"
        @current-change="handlePageChange"
        @size-change="handlePageSizeChange"
      />
    </div>

    <el-dialog v-model="importDialogVisible" title="一键导入 API Key" width="760px">
      <div class="import-actions">
        <el-button @click="fillImportTemplate">填充模板</el-button>
        <input ref="importFileRef" type="file" accept=".txt,.json,.jsonl" class="hidden-input" @change="handleImportFile" />
        <el-button @click="openImportFile">选择文件</el-button>
      </div>
      <div class="form-tip">
        支持粘贴多行 JSON，或导入 .txt / .json / .jsonl 文件；每行一个对象；也支持直接导入“导出全部”生成的文件。
      </div>
      <el-input v-model="importText" type="textarea" :rows="12" placeholder="粘贴多行 JSON 数据" />
      <template #footer>
        <el-button @click="importDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitImport" :loading="importing">导入</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="batchDialogVisible" title="批量调整地址和模型" width="620px">
      <el-form label-width="110px">
        <el-form-item label="作用范围">
          <el-radio-group v-model="batchScope">
            <el-radio value="filtered">当前筛选结果</el-radio>
            <el-radio value="selected">当前勾选项</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="范围说明">
          <div class="form-tip no-margin">
            <template v-if="batchScope === 'filtered'">
              <span v-if="(filterProviders?.length || 0) + (filterModels?.length || 0) + (filterKeyIds?.length || 0) + (filterKeyNames?.length || 0) || typeof filterActive === 'boolean'">
                已筛选：提供商 {{ filterProviders.length }} 项，模型 {{ filterModels.length }} 项，Key ID / 名称 {{ filterKeyIds.length + filterKeyNames.length }} 项，状态 {{ filterActiveLabel }}
              </span>
              <span v-else>请先设置筛选条件</span>
            </template>
            <template v-else>
              已勾选 {{ selectedKeys.length }} 个 Key
            </template>
          </div>
        </el-form-item>
        <el-form-item label="请求地址">
          <el-input
            v-model="batchBaseUrl"
            clearable
            placeholder="留空表示不修改请求地址"
          />
        </el-form-item>
        <el-form-item label="提供商">
          <el-select
            v-model="batchNewProvider"
            clearable
            filterable
            allow-create
            placeholder="留空表示不修改提供商"
            style="width: 100%"
          >
            <el-option v-for="item in providerOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="API 类型">
          <el-radio-group v-model="batchApiTypeMode" class="batch-mode-group">
            <el-radio value="keep">不修改</el-radio>
            <el-radio value="newapi">改为 New API</el-radio>
            <el-radio value="sub2api">改为 sub2api</el-radio>
            <el-radio value="other">改为其他</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="模型调整">
          <el-radio-group v-model="batchModelMode" class="batch-mode-group">
            <el-radio value="keep">不修改</el-radio>
            <el-radio value="append">追加指定模型</el-radio>
            <el-radio value="replace">替换为指定模型</el-radio>
            <el-radio value="clear">清空为全部模型</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="独立 fake IP">
          <el-radio-group v-model="batchFakeIpMode" class="batch-mode-group">
            <el-radio value="keep">不修改</el-radio>
            <el-radio value="enable">开启并分配</el-radio>
            <el-radio value="disable">关闭并清空</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="batchFakeIpMode !== 'keep'" label="fake IP 说明">
          <div class="form-tip no-margin">
            <template v-if="batchFakeIpMode === 'enable'">
              将为当前勾选的每个 Key 自动分配不同的 fake IP。
            </template>
            <template v-else>
              将关闭当前勾选 Key 的 fake IP，并清空已保存的 fake IP。
            </template>
          </div>
        </el-form-item>
        <el-form-item v-if="batchWeightMode === 'set'" label="调度权重">
          <el-input-number v-model="batchWeight" :min="0" :step="1" style="width: 100%" />
          <div class="form-tip">0 表示该 Key 保留在管理列表中，但不参与调度轮询。</div>
        </el-form-item>
        <el-form-item v-if="batchModelMode === 'replace' || batchModelMode === 'append'" label="支持模型">
          <div class="model-select-wrap">
            <el-input
              v-model="batchModelKeyword"
              clearable
              placeholder="输入模型名称 / ID / 别名进行模糊搜索"
            />
            <div class="quick-model-row">
              <el-input
                v-model="batchQuickModelInput"
                clearable
                placeholder="快捷输入模型，使用英文逗号分隔"
                @keyup.enter="applyBatchQuickModels"
              />
              <el-button @click="applyBatchQuickModels">加入</el-button>
            </div>
            <el-select
              v-model="batchSupportedModels"
              multiple
              filterable
              allow-create
              default-first-option
              clearable
              collapse-tags
              collapse-tags-tooltip
              :placeholder="batchModelMode === 'append' ? '选择要追加的支持模型' : '选择要替换成的支持模型'"
              style="width: 100%"
            >
              <el-option
                v-for="item in filteredBatchModelOptions"
                :key="item.model_id"
                :label="`${item.display_name || item.model_id} (${item.model_id})`"
                :value="item.model_id"
              />
            </el-select>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="batchDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitBatchUpdate" :loading="batchSubmitting">确认调整</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="checkDialogVisible" title="检测配置" width="740px">
      <el-form label-width="110px" @submit.prevent>
        <el-form-item label="作用范围">
          <el-radio-group v-model="batchScope">
            <el-radio value="filtered">当前筛选结果</el-radio>
            <el-radio value="selected">当前勾选项</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="范围说明">
          <div class="form-tip no-margin">
            <template v-if="batchScope === 'filtered'">
              <span v-if="(filterProviders?.length || 0) + (filterModels?.length || 0) + (filterKeyIds?.length || 0) + (filterKeyNames?.length || 0) || typeof filterActive === 'boolean'">
                已筛选：提供商 {{ filterProviders.length }} 项，模型 {{ filterModels.length }} 项，Key ID / 名称 {{ filterKeyIds.length + filterKeyNames.length }} 项，状态 {{ filterActiveLabel }}
              </span>
              <span v-else>请先设置筛选条件</span>
            </template>
            <template v-else>
              已勾选 {{ selectedKeys.length }} 个 Key
            </template>
          </div>
        </el-form-item>
        <el-form-item label="检测模式">
          <el-radio-group v-model="checkMode">
            <el-radio value="model">模型检测</el-radio>
            <el-radio value="balance">余额检测</el-radio>
          </el-radio-group>
          <div class="form-tip no-margin" style="margin-top: 4px">
            <span v-if="checkMode === 'model'">发起真实请求验证模型可用性</span>
            <span v-else>登录上游账户查询余额（需在系统设置中配置供应商密码）</span>
          </div>
        </el-form-item>
        <el-form-item v-if="checkMode === 'model'" label="检测模型" required>
          <el-input
            v-model="checkTargetModel"
            clearable
            placeholder="请输入要检测的模型名称"
            @keydown.enter.prevent="submitBatchCheck"
          />
            <div class="check-shortcut-buttons">
              <div
                v-for="item in shortcutModelButtons"
                :key="item.key"
                class="check-shortcut-cell"
                :class="{ 'is-empty': !item.value }"
                @click="item.value && applyShortcutCheckModel(item.value)"
              >
                {{ item.value || '' }}
              </div>
            </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="checkDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="batchChecking" @click="submitBatchCheck">开始检测</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="checkFailureDialogVisible" title="检测失败详情" width="700px">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="Key 名称">{{ checkFailureDetail.name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="请求地址">
          <a v-if="checkFailureDetail.base_url" :href="checkFailureDetail.base_url" target="_blank" rel="noopener noreferrer" style="color:var(--el-color-primary);word-break:break-all;">{{ checkFailureDetail.base_url }}</a>
          <span v-else>-</span>
        </el-descriptions-item>
        <el-descriptions-item label="检测模型">{{ checkFailureDetail.target_model || '-' }}</el-descriptions-item>
        <el-descriptions-item label="失败分类">{{ getCheckFailureLabel(checkFailureDetail.failure_category) }}</el-descriptions-item>
        <el-descriptions-item label="详细原因">
          <div class="check-failure-detail-text">{{ checkFailureDetail.failure_detail || '-' }}</div>
        </el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button type="primary" @click="checkFailureDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="checkTaskResultsVisible" title="检测任务结果" width="980px">
      <div class="check-task-results-toolbar">
        <div class="check-task-results-summary" v-if="activeCheckTaskSummary">
          <span>任务 #{{ activeCheckTaskSummary.id }}</span>
          <span>模型 {{ activeCheckTaskSummary.target_model || '-' }}</span>
          <span>进度 {{ activeCheckTaskSummary.completed_count }}/{{ activeCheckTaskSummary.total_count }}</span>
          <span>成功 {{ activeCheckTaskSummary.success_count }}</span>
          <span>失败 {{ activeCheckTaskSummary.error_count }}</span>
          <el-tag size="small" :type="getCheckTaskStatusType(activeCheckTaskSummary.status)">
            {{ getCheckTaskStatusLabel(activeCheckTaskSummary.status) }}
          </el-tag>
        </div>
        <el-button text @click="refreshActiveCheckTaskResults" :loading="checkTaskResultsLoading">刷新</el-button>
      </div>
      <el-table :data="checkTaskResults" border v-loading="checkTaskResultsLoading" max-height="520">
        <el-table-column prop="name" label="名称" min-width="120" />
        <el-table-column prop="provider" label="提供商" width="100" />
        <el-table-column prop="base_url" label="请求地址" min-width="200" show-overflow-tooltip />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="getCheckTaskStatusType(row.status)">{{ getCheckTaskStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="检测结果" min-width="160">
          <template #default="{ row }">
            <div class="check-result-cell">
              <span v-if="row.status === 'pending'" class="check-result-pending">等待中...</span>
              <span v-else-if="row.status === 'success'" class="check-result-success">{{ formatCheckLatency(row.response_time_ms) }}</span>
              <el-button
                v-else
                type="danger"
                link
                class="check-result-link"
                @click="showCheckFailureDetailFromResult(row)"
              >
                {{ getCheckFailureLabel(row.failure_category) }}
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <div class="pagination">
        <el-pagination
          v-model:current-page="checkTaskResultPage"
          v-model:page-size="checkTaskResultPageSize"
          :page-sizes="[20, 50, 100]"
          :total="checkTaskResultTotal"
          layout="total, sizes, prev, pager, next"
          @current-change="loadActiveCheckTaskResults"
          @size-change="handleCheckTaskResultPageSizeChange"
        />
      </div>
      <template #footer>
        <el-button type="primary" @click="checkTaskResultsVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="priorityDialogVisible" title="模型优先Key" width="980px">
      <div class="priority-toolbar">
        <el-select
          v-model="priorityProvider"
          filterable
          clearable
          placeholder="请选择提供商"
          style="width: 260px"
          @change="handlePriorityProviderChange"
        >
          <el-option
            v-for="item in providerOptions"
            :key="item.value"
            :value="item.value"
            :label="item.label"
          />
        </el-select>
        <div class="form-tip no-margin">
          调度顺序：会话粘滞 Key → 模型优先 Key → 通用加权轮询
        </div>
      </div>

      <el-table :data="priorityItems" border v-loading="priorityLoading" max-height="520">
        <el-table-column prop="model_display_name" label="模型" min-width="250">
          <template #default="{ row }">
            <div class="priority-model-cell">
              <div>{{ row.model_display_name || row.model }}</div>
              <div class="priority-model-id">{{ row.model }}</div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="当前优先Key" min-width="220">
          <template #default="{ row }">
            <div class="priority-current-cell">
              <span v-if="row.priority_key_name">{{ row.priority_key_name }}</span>
              <span v-else class="check-result-idle">未设置</span>
              <el-tag v-if="row.binding_enabled && row.issue" type="warning" size="small">{{ row.issue }}</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="可选 Key" min-width="320">
          <template #default="{ row }">
            <el-select
              v-model="row.priority_selected_key_id"
              clearable
              filterable
              placeholder="请选择优先 Key"
              style="width: 100%"
            >
              <el-option
                v-for="item in getPriorityKeyOptionsForModel(row.model)"
                :key="item.id"
                :label="formatPriorityKeyOptionLabel(item)"
                :value="item.id"
              />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <div class="action-row">
              <el-button type="primary" link :loading="row.priority_saving" @click="savePriorityItem(row)">保存</el-button>
              <el-button type="danger" link :loading="row.priority_clearing" @click="clearPriorityItem(row)">清空</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="cooldownDialogVisible" title="冷却设置" width="620px">
      <el-form :model="cooldownForm" label-width="170px">
        <el-form-item label="429 冷却秒数">
          <el-input-number v-model="cooldownForm.rate_limit_cooldown_seconds" :min="0" :step="30" style="width: 100%" />
        </el-form-item>
        <el-form-item label="401/403 冷却秒数">
          <el-input-number v-model="cooldownForm.auth_failure_cooldown_seconds" :min="0" :step="30" style="width: 100%" />
        </el-form-item>
        <el-form-item label="5xx 冷却秒数">
          <el-input-number v-model="cooldownForm.upstream_error_cooldown_seconds" :min="0" :step="30" style="width: 100%" />
        </el-form-item>
        <el-form-item label="524 自动继续提供商">
          <el-select
            v-model="cooldownForm.cloudflare_524_auto_continue_providers"
            multiple
            filterable
            allow-create
            default-first-option
            clearable
            placeholder="默认关闭，可输入或选择提供商"
            style="width: 100%"
          >
            <el-option v-for="item in providerOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <div class="form-tip">仅高级场景使用：命中 Cloudflare 524 时使用当前 Key 追加“继续”重试一次；仍失败后再按默认策略冷却并换 Key。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="cooldownDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="cooldownSubmitting" @click="submitCooldownConfig">保存</el-button>
      </template>
    </el-dialog>

    <!-- 添加/编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑 API Key' : '添加 API Key'"
      width="500px"
      align-center
    >
      <el-form :model="form" :rules="rules" ref="formRef" label-width="100px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="输入名称标识" />
        </el-form-item>
        <el-form-item label="提供商" prop="provider">
          <el-select
            v-model="form.provider"
            filterable
            allow-create
            default-first-option
            clearable
            reserve-keyword="false"
            placeholder="选择或输入提供商"
            @change="onProviderChange"
          >
            <el-option
              v-for="item in providerOptions"
              :key="item.value"
              :value="item.value"
              :label="item.label"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="API 类型">
          <el-select v-model="form.api_type" placeholder="选择 API 类型" style="width: 100%">
            <el-option label="New API" value="newapi" />
            <el-option label="sub2api" value="sub2api" />
            <el-option label="其他" value="other" />
          </el-select>
        </el-form-item>
        <el-form-item label="API Key" prop="api_key">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            placeholder="输入 API Key"
          />
        </el-form-item>
        <el-form-item label="请求地址" prop="base_url">
          <el-input v-model="form.base_url" placeholder="输入 API 请求地址" />
        </el-form-item>
        <el-form-item label="调度权重">
          <el-input-number v-model="form.weight" :min="0" :step="1" style="width: 100%" />
        </el-form-item>
        <el-form-item label="独立代理">
          <div class="proxy-config-wrap">
            <el-switch v-model="form.enable_proxy" />
          </div>
        </el-form-item>
        <template v-if="form.enable_proxy">
          <el-form-item label="代理地址" prop="proxy_url">
            <el-input v-model="form.proxy_url" placeholder="输入代理地址，例如 http://host:port" />
          </el-form-item>
          <el-form-item label="代理账号">
            <el-input v-model="form.proxy_username" placeholder="可选，输入代理账号" />
          </el-form-item>
          <el-form-item label="代理密码">
            <el-input v-model="form.proxy_password" type="password" show-password placeholder="可选，输入代理密码" />
          </el-form-item>
        </template>
        <el-form-item label="伪装 IP">
          <div class="proxy-config-wrap">
            <el-switch v-model="form.enable_fake_ip" />
          </div>
        </el-form-item>
        <template v-if="form.enable_fake_ip">
          <el-form-item label="IP 地址" prop="fake_ip">
            <el-input v-model="form.fake_ip" placeholder="输入要附带的 IPv4 或 IPv6 地址" />
          </el-form-item>
        </template>
        <el-form-item label="支持模型">
          <div class="model-select-wrap">
            <el-input
              v-model="modelKeyword"
              clearable
              placeholder="输入模型名称 / ID / 别名进行模糊搜索"
            />
            <div class="quick-model-row">
              <el-input
                v-model="quickModelInput"
                clearable
                placeholder="快捷输入模型，使用英文逗号分隔"
                @keyup.enter="applyQuickModels"
              />
              <el-button @click="applyQuickModels">加入</el-button>
            </div>
            <el-select
              v-model="form.supported_models"
              multiple
              filterable
              allow-create
              default-first-option
              clearable
              collapse-tags
              collapse-tags-tooltip
              placeholder="留空表示支持全部模型"
              style="width: 100%"
            >
              <el-option
                v-for="item in filteredModelOptions"
                :key="item.model_id"
                :label="`${item.display_name || item.model_id} (${item.model_id})`"
                :value="item.model_id"
              />
            </el-select>
          </div>
        </el-form-item>
        <el-collapse class="form-extra-collapse">
          <el-collapse-item name="extra">
            <template #title>
              <span style="font-size: 13px; color: var(--cpa-text-secondary)">高级配置（备注 / 登录密码 / 网页网址）</span>
            </template>
            <el-form-item label="登录密码" style="margin-top: 8px">
              <el-input v-model="form.password" type="password" show-password placeholder="留空则使用系统设置中的供应商默认密码" />
            </el-form-item>
            <el-form-item label="网页网址">
              <el-input v-model="form.wz_url" placeholder="留空则使用请求地址（余额查询、图片回填等）" />
            </el-form-item>
            <el-form-item label="备注">
              <el-input v-model="form.remark" type="textarea" rows="2" placeholder="可选备注" />
            </el-form-item>
          </el-collapse-item>
        </el-collapse>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button @click="copyCurrentFormConfig">复制配置</el-button>
        <el-button v-if="isEdit" @click="duplicateFromForm">另存为副本</el-button>
        <el-button v-if="!isEdit" type="success" @click="submitAndContinue" :loading="submitting">
          继续添加
        </el-button>
        <el-button type="primary" @click="submitForm" :loading="submitting">
          {{ isEdit ? '保存' : '添加' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- Key 详情弹窗 -->
    <el-dialog
      v-model="keyDetailDialogVisible"
      title="Key 详情"
      width="960px"
      @closed="handleKeyDetailDialogClosed"
    >
      <div v-loading="keyDetailLoading" class="key-detail-dialog">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="Key ID">{{ keyDetailData.id || '-' }}</el-descriptions-item>
          <el-descriptions-item label="名称">
            <span>{{ keyDetailData.name || '-' }}</span>
            <el-button
              v-if="keyDetailData.password"
              link
              size="small"
              style="margin-left: 6px; padding: 0"
              :title="'复制登录密码'"
              @click="copyText(keyDetailData.password).then(() => ElMessage.success('密码已复制')).catch(() => ElMessage.error('复制失败'))"
            >
              <el-icon><View /></el-icon>
            </el-button>
          </el-descriptions-item>
          <el-descriptions-item label="提供商">{{ keyDetailData.provider || '-' }}</el-descriptions-item>
          <el-descriptions-item label="API 类型">{{ getApiTypeLabel(keyDetailData.api_type) }}</el-descriptions-item>
          <el-descriptions-item label="API Key">{{ keyDetailData.api_key_masked || '-' }}</el-descriptions-item>
          <el-descriptions-item label="请求地址">
            <a v-if="keyDetailData.base_url" :href="keyDetailData.base_url" target="_blank" rel="noopener noreferrer" style="color:var(--el-color-primary);word-break:break-all;">{{ keyDetailData.base_url }}</a>
            <span v-else>-</span>
          </el-descriptions-item>
          <el-descriptions-item label="启用状态">
            <el-button
              :type="keyDetailData.is_active ? 'success' : 'danger'"
              size="small"
              :loading="keyDetailToggling"
              @click="toggleKeyDetailActive"
            >
              {{ keyDetailData.is_active ? '已启用' : '已关闭' }}
            </el-button>
          </el-descriptions-item>
          <el-descriptions-item label="权重">{{ keyDetailData.weight ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="总请求数">{{ Number(keyDetailSummary.total_requests || 0).toLocaleString('zh-CN') }}</el-descriptions-item>
          <el-descriptions-item label="成功率">{{ getKeyDetailSuccessRate() }}%</el-descriptions-item>
          <el-descriptions-item label="总 Token">{{ formatKeyDetailToken(keyDetailSummary.total_tokens) }}</el-descriptions-item>
          <el-descriptions-item label="输入 Token">{{ formatKeyDetailToken(keyDetailSummary.prompt_tokens) }}</el-descriptions-item>
          <el-descriptions-item label="缓存 Token">{{ formatKeyDetailToken(keyDetailSummary.cache_tokens) }}</el-descriptions-item>
          <el-descriptions-item label="输出 Token">{{ formatKeyDetailToken(keyDetailSummary.completion_tokens) }}</el-descriptions-item>
          <el-descriptions-item label="平均上游耗时">{{ formatKeyDetailLatency(keyDetailSummary.avg_upstream_latency_ms) }}</el-descriptions-item>
          <el-descriptions-item label="CPA 额外耗时">{{ formatKeyDetailLatency(keyDetailSummary.avg_cpa_overhead_ms) }}</el-descriptions-item>
          <el-descriptions-item label="账户余额" :span="2">
            <span v-if="keyDetailBalanceLoading" style="color: #909399; font-size: 13px">查询中...</span>
            <span v-else-if="keyDetailBalance">
              <span style="color: #10b981; font-weight: 600">${{ keyDetailBalance.balance_usd.toFixed(4) }}</span>
              <span style="color: #909399; font-size: 12px; margin-left: 8px">已用 ${{ keyDetailBalance.used_usd.toFixed(4) }}</span>
            </span>
            <span v-else style="color: #909399; font-size: 13px">-</span>
          </el-descriptions-item>
        </el-descriptions>

        <el-card shadow="never" style="margin-top: 16px">
          <template #header>
            <div>
              <div class="panel-title">最近请求记录</div>
              <div class="panel-subtitle">查看该 Key 最近命中的请求明细</div>
            </div>
          </template>
          <el-table :data="keyDetailLogs" stripe border size="small" v-loading="keyDetailLogsLoading" max-height="360">
            <el-table-column prop="id" label="ID" width="72" />
            <el-table-column prop="model" label="模型" min-width="140" show-overflow-tooltip />
            <el-table-column prop="prompt_tokens" label="输入 Token" width="90" align="right">
              <template #default="{ row }">{{ formatKeyDetailCompactToken(row.prompt_tokens) }}</template>
            </el-table-column>
            <el-table-column prop="completion_tokens" label="输出 Token" width="90" align="right">
              <template #default="{ row }">{{ formatKeyDetailCompactToken(row.completion_tokens) }}</template>
            </el-table-column>
            <el-table-column prop="cache_tokens" label="缓存 Token" width="90" align="right">
              <template #default="{ row }">{{ row.cache_tokens ? formatKeyDetailCompactToken(row.cache_tokens) : '-' }}</template>
            </el-table-column>
            <el-table-column prop="total_tokens" label="总 Token" width="90" align="right">
              <template #default="{ row }">{{ formatKeyDetailCompactToken(row.total_tokens) }}</template>
            </el-table-column>
            <el-table-column prop="latency_ms" label="总耗时" width="90" align="right">
              <template #default="{ row }">{{ formatKeyDetailLatency(row.latency_ms) }}</template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="72" align="center">
              <template #default="{ row }">
                <el-tag :type="row.status === 'success' ? 'success' : row.status === 'error' ? 'danger' : 'warning'" size="small">
                  {{ row.status === 'success' ? '成功' : row.status === 'error' ? '失败' : '进行中' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="request_time" label="请求时间" width="118" show-overflow-tooltip />
          </el-table>
          <div style="margin-top: 12px; display: flex; justify-content: flex-end">
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
import { computed, ref, reactive, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { View } from '@element-plus/icons-vue'
import { adminApi, statsApi, copyText as copyTextUtil } from '../api'

const KEY_MANAGE_STATE_STORAGE_KEY = 'keyManageViewState'
const FILTERS_COLLAPSED_KEY = 'keyManageFiltersCollapsed'
const KEY_MANAGE_PAGE_SIZE_OPTIONS = [10, 20, 50, 100, 200, 300, 400, 500]

const restoreKeyManageState = () => {
  try {
    const raw = localStorage.getItem(KEY_MANAGE_STATE_STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return typeof parsed === 'object' && parsed ? parsed : {}
  } catch {
    return {}
  }
}

const isIpAddress = (value) => {
  if (typeof value !== 'string') return false
  const text = value.trim()
  if (!text) return false
  const ipv4Pattern = /^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$/
  if (ipv4Pattern.test(text)) return true
  if (!text.includes(':')) return false
  const parts = text.split('::')
  if (parts.length > 2) return false
  const isValidPart = (part) => /^[0-9a-fA-F]{1,4}$/.test(part)
  const countSegments = (segment) => segment ? segment.split(':').filter(Boolean) : []
  const left = countSegments(parts[0])
  const right = countSegments(parts[1] || '')
  if ([...left, ...right].some((part) => !isValidPart(part))) return false
  return parts.length === 2 ? (left.length + right.length) < 8 : left.length === 8
}

const savedKeyManageState = restoreKeyManageState()
const keys = ref([])
const modelOptions = ref([])
const modelKeyword = ref('')
const quickModelInput = ref('')
const batchModelKeyword = ref('')
const batchQuickModelInput = ref('')
const keyCheckShortcutModels = ref(['', '', '', '', '', ''])

const normalizeStringList = (values) => {
  const seen = new Set()
  return Array.isArray(values)
    ? values
        .filter((item) => typeof item === 'string')
        .map((item) => item.trim())
        .filter((item) => {
          if (!item) return false
          const key = item.toLowerCase()
          if (seen.has(key)) return false
          seen.add(key)
          return true
        })
    : []
}

const filterProviders = ref(Array.isArray(savedKeyManageState.filterProviders) ? savedKeyManageState.filterProviders.filter(Boolean) : [])
const filterProviderInput = ref('')
const filterKeyIds = ref(Array.isArray(savedKeyManageState.filterKeyIds) ? savedKeyManageState.filterKeyIds.filter((item) => Number.isInteger(Number(item)) && Number(item) > 0).map((item) => Number(item)) : [])
const filterKeyNames = ref(normalizeStringList(savedKeyManageState.filterKeyNames))
const filterKeyIdsInput = ref([...filterKeyIds.value, ...filterKeyNames.value].join(','))
const filterModels = ref(Array.isArray(savedKeyManageState.filterModels) ? savedKeyManageState.filterModels.filter(Boolean) : [])
const filterModelInput = ref('')
const filterModelKeyword = ref('')
const filterActive = ref(typeof savedKeyManageState.filterActive === 'boolean' ? savedKeyManageState.filterActive : null)
const filtersCollapsed = ref(localStorage.getItem(FILTERS_COLLAPSED_KEY) === '1')

const dialogVisible = ref(false)
const importDialogVisible = ref(false)
const batchDialogVisible = ref(false)
const cooldownDialogVisible = ref(false)
const checkDialogVisible = ref(false)
const checkFailureDialogVisible = ref(false)
const checkTaskResultsVisible = ref(false)
const priorityDialogVisible = ref(false)
const isEdit = ref(false)
const loading = ref(false)
const submitting = ref(false)
const importing = ref(false)
const exportingAllKeys = ref(false)
const batchSubmitting = ref(false)
const batchChecking = ref(false)
const batchDeleting = ref(false)
const batchActiveSubmitting = ref(false)
const batchCooldownSubmitting = ref(false)
const cooldownSubmitting = ref(false)
const priorityLoading = ref(false)
const checkTaskListLoading = ref(false)
const checkTaskResultsLoading = ref(false)
const importText = ref('')
const importFileRef = ref(null)
const formRef = ref(null)
const tableRef = ref(null)
const cooldownTimer = ref(null)
const restoringTableSelection = ref(false)
const editingId = ref(null)
const batchScope = ref('filtered')
const batchBaseUrl = ref('')
const batchModelMode = ref('keep')
const batchWeightMode = ref('keep')
const batchFakeIpMode = ref('keep')
const batchApiTypeMode = ref('keep')
const batchNewProvider = ref('')
const batchWeight = ref(1)
const batchSupportedModels = ref([])
const customProviders = ref([])
const keyProviderOptions = ref([])
const checkTargetModel = ref('')
const defaultCheckTargetModel = ref('')
const checkMode = ref('model')  // 'model' | 'balance'
const latestCheckTasks = ref([])
const activeCheckTaskId = ref(null)
const activeCheckTaskSummary = ref(null)
const activeCheckTaskPollTimer = ref(null)
const currentCheckBatchToken = ref('')
const checkTaskResults = ref([])
const checkTaskResultPage = ref(1)
const checkTaskResultPageSize = ref(20)
const checkTaskResultTotal = ref(0)
const priorityProvider = ref('')
const priorityItems = ref([])
const priorityKeyOptions = ref([])
const checkFailureDetail = reactive({
  name: '',
  base_url: '',
  target_model: '',
  failure_category: '',
  failure_detail: '',
})

const builtinProviderOptions = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'claude', label: 'Claude' },
  { value: 'google', label: 'Google' },
  { value: 'xAI', label: 'xAI' },
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'qwen', label: 'Qwen' },
  { value: 'minimax', label: 'MiniMax' },
  { value: 'Moonshot', label: 'Moonshot' },
  { value: 'Meta', label: 'Meta' },
  { value: '智谱', label: '智谱' },
  { value: 'azure', label: 'Azure' },
  { value: 'custom', label: '自定义' },
]

const providerOptions = computed(() => {
  const optionMap = new Map()

  builtinProviderOptions.forEach((item) => {
    optionMap.set(item.value, item)
  })

  const dynamicProviders = [
    ...keyProviderOptions.value,
    ...modelOptions.value.map((item) => item?.provider),
    ...customProviders.value,
    ...filterProviders.value,
    form.provider,
  ]

  normalizeModelNames(dynamicProviders)
    .forEach((value) => {
      if (!optionMap.has(value)) {
        optionMap.set(value, { value, label: value })
      }
    })

  return Array.from(optionMap.values())
})

const defaultUrls = {
  openai: 'https://api.openai.com',
  claude: 'https://api.anthropic.com',
  google: 'https://generativelanguage.googleapis.com',
  xAI: 'https://api.x.ai',
  deepseek: 'https://api.deepseek.com',
  qwen: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  minimax: 'https://api.minimax.chat',
  Moonshot: 'https://api.moonshot.cn',
  Meta: '',
  智谱: 'https://open.bigmodel.cn/api/paas/v4',
  azure: 'https://YOUR_RESOURCE.openai.azure.com',
  custom: '',
}

const form = reactive({
  name: '',
  provider: 'openai',
  api_type: 'other',
  api_key: '',
  base_url: defaultUrls.openai,
  weight: 1,
  enable_proxy: false,
  proxy_url: '',
  proxy_username: '',
  proxy_password: '',
  enable_fake_ip: true,
  fake_ip: '',
  supported_models: [],
  remark: '',
  password: '',
  wz_url: '',
})

const cooldownForm = reactive({
  rate_limit_cooldown_seconds: 300,
  auth_failure_cooldown_seconds: 600,
  upstream_error_cooldown_seconds: 120,
  cloudflare_524_auto_continue_providers: [],
})

const rules = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  provider: [{ required: true, message: '请选择提供商', trigger: 'change' }],
  api_key: [{ required: true, message: '请输入 API Key', trigger: 'blur' }],
  base_url: [{ required: true, message: '请输入请求地址', trigger: 'blur' }],
  proxy_url: [{
    validator: (_rule, value, callback) => {
      if (!form.enable_proxy) {
        callback()
        return
      }
      if (typeof value === 'string' && value.trim()) {
        callback()
        return
      }
      callback(new Error('启用独立代理时请输入代理地址'))
    },
    trigger: 'blur',
  }],
  fake_ip: [{
    validator: (_rule, value, callback) => {
      if (!form.enable_fake_ip) {
        callback()
        return
      }
      // 留空时提交自动分配，无需校验
      if (!value || !value.trim()) {
        callback()
        return
      }
      if (typeof value === 'string' && isIpAddress(value)) {
        callback()
        return
      }
      callback(new Error('请输入合法的 IPv4 或 IPv6 地址，或留空自动分配'))
    },
    trigger: 'blur',
  }],
}

const getProviderType = (provider) => {
  const types = {
    openai: 'primary',
    claude: 'warning',
    azure: 'success',
    custom: 'info',
  }
  return types[provider] || 'info'
}

const normalizeApiType = (value) => {
  const normalized = typeof value === 'string' ? value.trim().toLowerCase() : ''
  return ['newapi', 'sub2api', 'other'].includes(normalized) ? normalized : 'other'
}

const getApiTypeLabel = (value) => {
  const labels = {
    newapi: 'New API',
    sub2api: 'sub2api',
    other: '其他',
  }
  return labels[normalizeApiType(value)] || labels.other
}

const getApiTypeTagType = (value) => {
  const types = {
    newapi: 'primary',
    sub2api: 'success',
    other: 'info',
  }
  return types[normalizeApiType(value)] || 'primary'
}

const buildFilteredModelOptions = (keywordValue) => {
  const keyword = keywordValue.trim().toLowerCase()
  const options = modelOptions.value.filter((item) => item?.model_id)
  if (!keyword) return options
  return options.filter((item) => {
    const label = `${item.display_name || item.model_id} ${item.model_id} ${Array.isArray(item.aliases) ? item.aliases.join(' ') : ''}`.toLowerCase()
    return label.includes(keyword)
  })
}

const filteredModelOptions = computed(() => buildFilteredModelOptions(modelKeyword.value))
const filteredBatchModelOptions = computed(() => buildFilteredModelOptions(batchModelKeyword.value))
const filteredFilterModelOptions = computed(() => buildFilteredModelOptions(filterModelKeyword.value))
const priorityKeyOptionMap = computed(() => {
  const map = new Map()
  priorityKeyOptions.value.forEach((item) => {
    map.set(Number(item.id), item)
  })
  return map
})
const shortcutModelButtons = computed(() => {
  const values = keyCheckShortcutModels.value.filter((value) => Boolean(value))
  const paddedValues = [...values]
  while (paddedValues.length < 6) {
    paddedValues.push('')
  }
  return paddedValues.map((value, index) => ({
    key: `${index}-${value || 'empty'}`,
    value,
  }))
})

const filterActiveLabel = computed(() => {
  if (filterActive.value === true) return '已启用'
  if (filterActive.value === false) return '已关闭'
  return '全部'
})
const visibleModelCount = 1
const hasFilteredConditions = computed(() => {
  return Boolean(
    filterProviders.value?.length ||
    filterModels.value?.length ||
    filterKeyIds.value?.length ||
    filterKeyNames.value?.length ||
    typeof filterActive.value === 'boolean'
  )
})

const saveKeyManageState = () => {
  localStorage.setItem(KEY_MANAGE_STATE_STORAGE_KEY, JSON.stringify({
    filterProviders: filterProviders.value,
    filterKeyIds: filterKeyIds.value,
    filterKeyNames: filterKeyNames.value,
    filterModels: filterModels.value,
    filterActive: filterActive.value,
    currentPage: currentPage.value,
    pageSize: pageSize.value,
    keySort: keySort.value,
    selectedKeyIds: selectedKeyIds.value,
  }))
}

const clearMissingSelectedKeys = () => {
  const availableIdSet = new Set(keys.value.map((item) => Number(item?.id)).filter((id) => Number.isInteger(id) && id > 0))
  selectedKeyIds.value = selectedKeyIds.value.filter((id) => availableIdSet.has(id))
}

const restoreTableSelection = async () => {
  clearMissingSelectedKeys()
  await syncTableSelectionByIds()
}

const applyShortcutCheckModel = (value) => {
  if (!value) return
  checkTargetModel.value = value
}
const randomFakeIpSegment = () => Math.floor(Math.random() * 254) + 1
const randomFakeIp = () => `${randomFakeIpSegment()}.${randomFakeIpSegment()}.${randomFakeIpSegment()}.${randomFakeIpSegment()}`

const createDuplicateName = (name = '') => {
  const trimmed = name.trim()
  return trimmed ? `${trimmed}-copy` : 'key-copy'
}

const normalizeModelNames = (values) => {
  const seen = new Set()
  return values
    .filter((item) => typeof item === 'string')
    .map((item) => item.trim())
    .filter((item) => {
      if (!item) return false
      const key = item.toLowerCase()
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
}

const parseKeyIdentityFilterInput = (value) => {
  const text = typeof value === 'string' ? value.replaceAll('，', ',') : ''
  const parts = text.split(',').map((item) => item.trim()).filter(Boolean)
  const ids = []
  const names = []
  const seenIds = new Set()
  const seenNames = new Set()

  for (const part of parts) {
    if (/^\d+$/.test(part)) {
      const id = Number(part)
      if (!Number.isInteger(id) || id <= 0) {
        throw new Error('Key ID 仅支持正整数')
      }
      if (!seenIds.has(id)) {
        seenIds.add(id)
        ids.push(id)
      }
      continue
    }

    const nameKey = part.toLowerCase()
    if (seenNames.has(nameKey)) continue
    seenNames.add(nameKey)
    names.push(part)
  }

  return { ids, names }
}

const createDefaultCheckState = () => ({
  check_state: 'idle',
  check_latency_ms: null,
  check_error_category: '',
  check_error_detail: '',
  check_target_model: '',
  check_batch_token: '',
  check_mode: 'model',
  check_balance_usd: null,
})

const normalizeCheckTask = (task) => ({
  ...task,
  id: Number(task?.id) || 0,
  total_count: Number(task?.total_count) || 0,
  completed_count: Number(task?.completed_count) || 0,
  success_count: Number(task?.success_count) || 0,
  error_count: Number(task?.error_count) || 0,
  progress_percent: Number(task?.progress_percent) || 0,
})

const mergeCheckTask = (task) => {
  const normalizedTask = normalizeCheckTask(task || {})
  if (!normalizedTask.id) return normalizedTask
  const index = latestCheckTasks.value.findIndex((item) => Number(item.id) === normalizedTask.id)
  if (index >= 0) {
    latestCheckTasks.value.splice(index, 1, normalizedTask)
  } else {
    latestCheckTasks.value.unshift(normalizedTask)
    latestCheckTasks.value = latestCheckTasks.value.slice(0, 10)
  }
  if (Number(activeCheckTaskId.value) === normalizedTask.id) {
    activeCheckTaskSummary.value = normalizedTask
  }
  return normalizedTask
}

const getCurrentPageRowsForCheck = (payload) => {
  const selectedIdSet = new Set((payload?.key_ids || []).map((item) => Number(item)))
  return keys.value.filter((row) => {
    if (payload?.scope === 'selected') {
      return selectedIdSet.has(Number(row.id))
    }
    return true
  })
}

const applyCheckTaskToCurrentPage = async (taskId, targetModel = '') => {
  const result = await adminApi.listKeyCheckTaskResults(taskId, {
    page: 1,
    limit: pageSize.value,
  })
  const items = Array.isArray(result?.items) ? result.items : []
  applyCheckResultsToCurrentPage(items, targetModel)
}

const stopActiveCheckTaskPolling = () => {
  if (!activeCheckTaskPollTimer.value) return
  window.clearInterval(activeCheckTaskPollTimer.value)
  activeCheckTaskPollTimer.value = null
}

const getCheckTaskStatusType = (status) => {
  const typeMap = {
    pending: 'info',
    running: 'warning',
    completed: 'success',
    failed: 'danger',
    cancelled: 'info',
    success: 'success',
    error: 'danger',
  }
  return typeMap[status] || 'info'
}

const getCheckTaskStatusLabel = (status) => {
  const labelMap = {
    pending: '等待中',
    running: '执行中',
    completed: '已完成',
    failed: '已失败',
    cancelled: '已取消',
    success: '成功',
    error: '失败',
  }
  return labelMap[status] || '未知'
}

const loadCheckTasks = async () => {
  checkTaskListLoading.value = true
  try {
    const result = await adminApi.listKeyCheckTasks({ page: 1, limit: 10 })
    latestCheckTasks.value = Array.isArray(result?.items)
      ? result.items.map((item) => normalizeCheckTask(item))
      : []
    if (activeCheckTaskId.value) {
      const matchedTask = latestCheckTasks.value.find((item) => Number(item.id) === Number(activeCheckTaskId.value))
      if (matchedTask) {
        activeCheckTaskSummary.value = matchedTask
      }
    }
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    checkTaskListLoading.value = false
  }
}

const loadActiveCheckTaskResults = async () => {
  if (!activeCheckTaskId.value) return
  checkTaskResultsLoading.value = true
  try {
    const result = await adminApi.listKeyCheckTaskResults(activeCheckTaskId.value, {
      page: checkTaskResultPage.value,
      limit: checkTaskResultPageSize.value,
    })
    checkTaskResults.value = Array.isArray(result?.items) ? result.items : []
    checkTaskResultTotal.value = Number(result?.total) || 0
    if (Number(checkTaskResultPage.value) === 1) {
      applyCheckResultsToCurrentPage(checkTaskResults.value, activeCheckTaskSummary.value?.target_model || '')
    }
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    checkTaskResultsLoading.value = false
  }
}

const handleCheckTaskResultPageSizeChange = (size) => {
  checkTaskResultPageSize.value = size
  checkTaskResultPage.value = 1
  loadActiveCheckTaskResults()
}

const refreshActiveCheckTaskResults = async () => {
  await loadActiveCheckTaskResults()
}

const pollActiveCheckTask = async () => {
  if (!activeCheckTaskId.value) return
  try {
    const task = await adminApi.getKeyCheckTask(activeCheckTaskId.value)
    const normalizedTask = mergeCheckTask(task)
    activeCheckTaskSummary.value = normalizedTask
    if (checkTaskResultsVisible.value) {
      await loadActiveCheckTaskResults()
    } else if (normalizedTask.status === 'completed') {
      await applyCheckTaskToCurrentPage(normalizedTask.id, normalizedTask.target_model || '')
    }
    if (!['pending', 'running'].includes(normalizedTask.status)) {
      stopActiveCheckTaskPolling()
    }
  } catch (e) {
    stopActiveCheckTaskPolling()
    ElMessage.error(e.message)
  }
}

const startActiveCheckTaskPolling = () => {
  stopActiveCheckTaskPolling()
  if (!activeCheckTaskId.value) return
  activeCheckTaskPollTimer.value = window.setInterval(() => {
    pollActiveCheckTask()
  }, 2000)
}

const openCheckTaskResults = async (task) => {
  const normalizedTask = mergeCheckTask(task)
  activeCheckTaskId.value = normalizedTask.id
  activeCheckTaskSummary.value = normalizedTask
  checkTaskResultPage.value = 1
  checkTaskResultsVisible.value = true
  await loadActiveCheckTaskResults()
  if (['pending', 'running'].includes(normalizedTask.status)) {
    startActiveCheckTaskPolling()
  }
}

const showCheckFailureDetailFromResult = (row) => {
  Object.assign(checkFailureDetail, {
    name: row?.name || '',
    base_url: row?.base_url || '',
    target_model: row?.target_model || '',
    failure_category: row?.failure_category || '',
    failure_detail: row?.failure_detail || '',
  })
  checkFailureDialogVisible.value = true
}

const buildCheckFailureDetail = (result = {}, targetModel = '') => {
  const details = []
  const pushDetail = (title, value) => {
    const text = typeof value === 'string' ? value.trim() : value
    if (!text) return
    details.push(`${title}：${text}`)
  }

  pushDetail('总体错误', result?.failure_detail)
  pushDetail('地址探测', result?.address_check?.error_message)
  pushDetail('模型检测', result?.model_check?.error_message)

  return {
    status: result?.status === 'success' ? 'success' : 'error',
    response_time_ms: Number(result?.response_time_ms) || 0,
    failure_category: result?.failure_category || '',
    failure_detail: details.join('\n\n') || result?.failure_detail || '请求失败',
    target_model: result?.target_model || targetModel,
  }
}

const applyCheckResultToRow = (row, result, batchToken = '') => {
  if (batchToken && row?.check_batch_token !== batchToken) {
    return
  }
  const normalizedResult = buildCheckFailureDetail(result, row?.check_target_model || '')
  Object.assign(row, {
    check_state: normalizedResult.status === 'success' ? 'success' : 'error',
    check_latency_ms: normalizedResult.response_time_ms,
    check_error_category: normalizedResult.failure_category,
    check_error_detail: normalizedResult.failure_detail,
    check_target_model: normalizedResult.target_model || '',
  })
}

const buildCheckErrorResult = (error, targetModel) => {
  const message = error?.message || '请求失败'
  const normalizedMessage = String(message).toLowerCase()
  const isTimeout = normalizedMessage.includes('timeout') || normalizedMessage.includes('timed out') || normalizedMessage.includes('超时')
  return {
    status: 'error',
    response_time_ms: 0,
    failure_category: isTimeout ? 'timeout' : 'request_error',
    failure_detail: message,
    target_model: targetModel,
  }
}

const runBatchCheckWithConcurrency = async (rows, targetModel, batchToken, concurrency = 4) => {
  if (!rows.length) return

  const workerCount = Math.max(1, Math.min(Number(concurrency) || 1, rows.length))
  let cursor = 0

  const worker = async () => {
    while (cursor < rows.length) {
      const currentIndex = cursor
      cursor += 1
      const row = rows[currentIndex]
      if (!row || row.check_batch_token !== batchToken) continue

      try {
        const result = await adminApi.checkKey(row.id, { target_model: targetModel })
        applyCheckResultToRow(row, result, batchToken)
      } catch (error) {
        applyCheckResultToRow(row, buildCheckErrorResult(error, targetModel), batchToken)
      }
    }
  }

  await Promise.all(Array.from({ length: workerCount }, () => worker()))
}

const prepareRowsForChecking = (rows, targetModel, batchToken) => {
  rows.forEach((row) => {
    Object.assign(row, {
      ...createDefaultCheckState(),
      check_state: 'checking',
      check_target_model: targetModel,
      check_batch_token: batchToken,
    })
  })
}

const applyCheckResultsToCurrentPage = (items = [], targetModel = '') => {
  const rowMap = new Map(keys.value.map((row) => [Number(row.id), row]))
  items.forEach((item) => {
    const row = rowMap.get(Number(item?.key_id))
    if (!row || row.check_batch_token === currentCheckBatchToken.value) return
    applyCheckResultToRow(row, item)
    if (!item?.target_model && targetModel) {
      row.check_target_model = targetModel
    }
  })
}

const syncCustomProviders = (values) => {
  const normalized = normalizeModelNames(values)
  customProviders.value = normalizeModelNames([...(customProviders.value || []), ...normalized])
}

const getPriorityKeyOptionsForModel = (model) => {
  return priorityKeyOptions.value.filter((item) => {
    const supportedModels = Array.isArray(item.supported_models) ? item.supported_models : []
    return !supportedModels.length || supportedModels.some((name) => String(name).trim().toLowerCase() === String(model).trim().toLowerCase())
  })
}

const formatPriorityKeyOptionLabel = (item) => {
  const statusText = item.is_active ? '启用' : '关闭'
  const modelText = item.supported_models?.length ? `${item.supported_models.length} 个模型` : '全部模型'
  return `${item.name}（权重 ${item.weight}，${statusText}，${modelText}）`
}

const normalizePriorityItems = (items = []) => {
  return items.map((item) => ({
    ...item,
    priority_selected_key_id: item.priority_key_id || null,
    priority_saving: false,
    priority_clearing: false,
  }))
}

const getVisibleModels = (models = []) => models.slice(0, visibleModelCount)

const formatCooldownSeconds = (seconds) => {
  const value = Number(seconds) || 0
  if (value <= 0) return '0s'
  if (value < 60) return `${value}s`
  const minutes = Math.floor(value / 60)
  const remainSeconds = value % 60
  return remainSeconds ? `${minutes}m ${remainSeconds}s` : `${minutes}m`
}

const updateRowCooldownState = (row) => {
  if (!row?.cooldown_until) {
    row.is_cooled_down = false
    row.cooldown_remaining_seconds = 0
    return
  }

  const cooldownUntil = new Date(row.cooldown_until).getTime()
  if (Number.isNaN(cooldownUntil)) {
    row.is_cooled_down = false
    row.cooldown_remaining_seconds = 0
    row.cooldown_until = null
    return
  }

  const remaining = Math.max(Math.ceil((cooldownUntil - Date.now()) / 1000), 0)
  row.cooldown_remaining_seconds = remaining
  row.is_cooled_down = remaining > 0
  if (!row.is_cooled_down) {
    row.cooldown_until = null
  }
}

const refreshCooldowns = () => {
  keys.value.forEach((row) => {
    if (row?.is_cooled_down || row?.cooldown_until) {
      updateRowCooldownState(row)
    }
  })
}

const ensureCooldownTimer = () => {
  if (cooldownTimer.value) return
  cooldownTimer.value = window.setInterval(() => {
    refreshCooldowns()
  }, 1000)
}

const stopCooldownTimer = () => {
  if (!cooldownTimer.value) return
  window.clearInterval(cooldownTimer.value)
  cooldownTimer.value = null
}

const fillForm = (data) => {
  Object.assign(form, {
    name: data.name || '',
    provider: data.provider || 'openai',
    api_type: normalizeApiType(data.api_type),
    api_key: data.api_key || '',
    base_url: data.base_url || defaultUrls[data.provider] || '',
    weight: Number.isFinite(Number(data.weight)) ? Number(data.weight) : 1,
    enable_proxy: Boolean(data.enable_proxy),
    proxy_url: data.proxy_url || '',
    proxy_username: data.proxy_username || '',
    proxy_password: data.proxy_password || '',
    enable_fake_ip: Boolean(data.enable_fake_ip),
    fake_ip: data.fake_ip || '',
    supported_models: Array.isArray(data.supported_models) ? [...data.supported_models] : [],
    remark: data.remark || '',
    password: data.password || '',
    wz_url: data.wz_url || '',
  })
}

const buildKeyConfig = (data) => {
  const config = {
    name: data.name || '',
    provider: data.provider || 'openai',
    api_type: normalizeApiType(data.api_type),
    api_key: data.api_key || '',
    base_url: data.base_url || defaultUrls[data.provider] || '',
    is_active: typeof data.is_active === 'boolean' ? data.is_active : true,
    enable_proxy: Boolean(data.enable_proxy),
    proxy_url: data.enable_proxy ? (data.proxy_url || '') : null,
    proxy_username: data.enable_proxy ? (data.proxy_username || '') : null,
    proxy_password: data.enable_proxy ? (data.proxy_password || '') : null,
    enable_fake_ip: Boolean(data.enable_fake_ip),
    fake_ip: data.enable_fake_ip ? (data.fake_ip || '') : null,
    supported_models: Array.isArray(data.supported_models) && data.supported_models.length
      ? [...data.supported_models]
      : null,
    remark: data.remark || '',
    password: data.password || null,
    wz_url: data.wz_url || null,
  }

  if (data.weight !== undefined && data.weight !== null && data.weight !== '') {
    const weight = Number(data.weight)
    if (Number.isFinite(weight)) {
      config.weight = weight
    }
  }

  return config
}

const copyText = async (text) => {
  if (!text) {
    throw new Error('没有可复制的内容')
  }
  await copyTextUtil(text)
}

const downloadTextFile = (filename, text) => {
  const blob = new Blob([text], { type: 'application/jsonl;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

const buildBatchScopePayload = () => ({
  scope: batchScope.value,
  providers: batchScope.value === 'filtered' ? normalizeModelNames(filterProviders.value) : null,
  models: batchScope.value === 'filtered' ? normalizeModelNames(filterModels.value) : null,
  is_active: batchScope.value === 'filtered' && typeof filterActive.value === 'boolean' ? filterActive.value : null,
  key_ids: batchScope.value === 'filtered'
    ? [...filterKeyIds.value]
    : selectedKeys.value.map((item) => item.id),
  key_names: batchScope.value === 'filtered' ? [...filterKeyNames.value] : null,
})

const validateBatchScope = () => {
  if (batchScope.value === 'filtered' && !hasFilteredConditions.value) {
    ElMessage.warning('请先设置筛选条件')
    return false
  }
  if (batchScope.value === 'selected' && !selectedKeys.value.length) {
    ElMessage.warning('请先勾选要操作的 Key')
    return false
  }
  return true
}

const hasBatchBaseUpdate = () => typeof batchBaseUrl.value === 'string' && Boolean(batchBaseUrl.value.trim())

const hasBatchModelUpdate = () => batchModelMode.value !== 'keep'

const hasBatchWeightUpdate = () => batchWeightMode.value === 'set'

const hasBatchFakeIpUpdate = () => batchFakeIpMode.value !== 'keep'

const submitBatchFakeIpUpdate = async () => {
  if (batchScope.value !== 'selected') {
    throw new Error('fake IP 批量操作仅支持当前勾选项')
  }
  const keyIds = selectedKeys.value.map((item) => Number(item?.id)).filter((id) => Number.isInteger(id) && id > 0)
  if (!keyIds.length) {
    throw new Error('请先勾选要操作的 Key')
  }
  return await adminApi.batchSetKeysFakeIp({
    key_ids: keyIds,
    enabled: batchFakeIpMode.value === 'enable',
  })
}

const onProviderChange = (provider) => {
  syncCustomProviders([provider])
  if (!isEdit.value) {
    form.base_url = defaultUrls[provider] || ''
  }
}

const toggleFilters = () => {
  filtersCollapsed.value = !filtersCollapsed.value
  localStorage.setItem(FILTERS_COLLAPSED_KEY, filtersCollapsed.value ? '1' : '0')
}

const loadModelOptions = async () => {
  try {
    const result = await adminApi.listModels()
    modelOptions.value = Array.isArray(result) ? result : (result.items || [])
  } catch (e) {
    ElMessage.error(e.message)
  }
}

const loadProviderOptions = async () => {
  try {
    const result = await adminApi.getKeyProviders()
    keyProviderOptions.value = Array.isArray(result) ? normalizeModelNames(result) : normalizeModelNames(result.items || [])
  } catch (e) {
    ElMessage.error(e.message)
  }
}

const loadCooldownConfig = async () => {
  const result = await adminApi.getKeyCooldownConfig()
  Object.assign(cooldownForm, {
    rate_limit_cooldown_seconds: Number(result.rate_limit_cooldown_seconds) || 0,
    auth_failure_cooldown_seconds: Number(result.auth_failure_cooldown_seconds) || 0,
    upstream_error_cooldown_seconds: Number(result.upstream_error_cooldown_seconds) || 0,
    cloudflare_524_auto_continue_providers: Array.isArray(result.cloudflare_524_auto_continue_providers)
      ? result.cloudflare_524_auto_continue_providers.filter(Boolean)
      : [],
  })
}

const loadKeyCheckDefaultConfig = async () => {
  try {
    const result = await adminApi.getKeyCheckDefaultConfig()
    defaultCheckTargetModel.value = result?.default_key_check_model || ''
  } catch (e) {
    defaultCheckTargetModel.value = ''
    ElMessage.error(e.message)
  }
}

const loadKeyCheckShortcutModels = async () => {
  try {
    const result = await adminApi.getKeyCheckShortcutModels()
    const shortcutModels = Array.isArray(result?.shortcut_models) ? result.shortcut_models : []
    defaultCheckTargetModel.value = result?.default_key_check_model || defaultCheckTargetModel.value || ''
    keyCheckShortcutModels.value = [0, 1, 2, 3, 4, 5].map((index) => shortcutModels[index] || (index === 0 ? defaultCheckTargetModel.value : ''))
  } catch (e) {
    keyCheckShortcutModels.value = [defaultCheckTargetModel.value || '', '', '', '', '', '']
    const message = e?.message || ''
    if (!message.includes('默认检测模型')) {
      ElMessage.error(message)
    }
  }
}

const loadPriorityData = async (provider) => {
  const providerValue = typeof provider === 'string' ? provider.trim() : ''
  if (!providerValue) {
    priorityItems.value = []
    priorityKeyOptions.value = []
    return
  }

  priorityLoading.value = true
  try {
    const [itemsResult, keyOptionsResult] = await Promise.all([
      adminApi.listProviderModelPriorities(providerValue),
      adminApi.listProviderModelPriorityKeyOptions(providerValue),
    ])
    priorityItems.value = normalizePriorityItems(itemsResult?.items || [])
    priorityKeyOptions.value = Array.isArray(keyOptionsResult) ? keyOptionsResult : []
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    priorityLoading.value = false
  }
}

const handlePriorityProviderChange = async (provider) => {
  priorityProvider.value = typeof provider === 'string' ? provider.trim() : ''
  await loadPriorityData(priorityProvider.value)
}

const showPriorityDialog = async () => {
  priorityDialogVisible.value = true
  if (!priorityProvider.value) {
    priorityProvider.value = filterProviders.value[0] || keyProviderOptions.value[0] || providerOptions.value[0]?.value || ''
  }
  await loadPriorityData(priorityProvider.value)
}

const savePriorityItem = async (row) => {
  const keyId = Number(row.priority_selected_key_id)
  if (!priorityProvider.value) {
    ElMessage.warning('请先选择提供商')
    return
  }
  if (!Number.isInteger(keyId) || keyId <= 0) {
    ElMessage.warning('请先选择优先 Key')
    return
  }

  row.priority_saving = true
  try {
    await adminApi.saveProviderModelPriority({
      provider: priorityProvider.value,
      model: row.model,
      key_id: keyId,
    })
    const selectedOption = priorityKeyOptionMap.value.get(keyId)
    row.priority_key_id = keyId
    row.priority_key_name = selectedOption?.name || row.priority_key_name || ''
    row.priority_key_active = Boolean(selectedOption?.is_active)
    row.priority_key_weight = Number(selectedOption?.weight) || 0
    row.priority_key_supported = true
    row.binding_enabled = true
    row.issue = null
    ElMessage.success(`已保存 ${row.model} 的优先 Key`)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    row.priority_saving = false
  }
}

const clearPriorityItem = async (row) => {
  if (!priorityProvider.value) {
    ElMessage.warning('请先选择提供商')
    return
  }

  row.priority_clearing = true
  try {
    await adminApi.clearProviderModelPriority({
      provider: priorityProvider.value,
      model: row.model,
    })
    row.priority_selected_key_id = null
    row.priority_key_id = null
    row.priority_key_name = null
    row.priority_key_active = false
    row.priority_key_weight = 0
    row.priority_key_supported = false
    row.binding_enabled = false
    row.issue = null
    ElMessage.success(`已清空 ${row.model} 的优先 Key`)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    row.priority_clearing = false
  }
}

const currentPage = ref(Number.isInteger(Number(savedKeyManageState.currentPage)) && Number(savedKeyManageState.currentPage) > 0 ? Number(savedKeyManageState.currentPage) : 1)
const pageSize = ref(KEY_MANAGE_PAGE_SIZE_OPTIONS.includes(Number(savedKeyManageState.pageSize)) ? Number(savedKeyManageState.pageSize) : 100)
const totalKeys = ref(0)
const pageSizeOptions = KEY_MANAGE_PAGE_SIZE_OPTIONS
const keySort = ref({
  prop: typeof savedKeyManageState.keySort?.prop === 'string' ? savedKeyManageState.keySort.prop : 'id',
  order: ['ascending', 'descending', null].includes(savedKeyManageState.keySort?.order) ? (savedKeyManageState.keySort.order || 'ascending') : 'ascending',
})
const selectedKeyIds = ref(Array.isArray(savedKeyManageState.selectedKeyIds) ? savedKeyManageState.selectedKeyIds.filter((item) => Number.isInteger(Number(item)) && Number(item) > 0).map((item) => Number(item)) : [])
const selectedKeyIdSet = computed(() => new Set(selectedKeyIds.value))
const selectedKeys = computed(() => keys.value.filter((item) => selectedKeyIdSet.value.has(Number(item?.id))))

const keysTableData = ref([])

const compareKeyValues = (left, right, prop) => {
  if (prop === 'is_active') {
    return Number(Boolean(left?.is_active)) - Number(Boolean(right?.is_active))
  }

  const leftValue = left?.[prop]
  const rightValue = right?.[prop]

  if (typeof leftValue === 'number' || typeof rightValue === 'number') {
    return Number(leftValue || 0) - Number(rightValue || 0)
  }

  return String(leftValue || '').localeCompare(String(rightValue || ''), 'zh-CN', { sensitivity: 'base' })
}

const sortKeys = (items) => {
  // 排序已下推到后端，直接返回后端返回的顺序
  return [...items]
}

const syncKeysTableData = () => {
  keysTableData.value = sortKeys(keys.value)
}

const syncTableSelectionByIds = async () => {
  await nextTick()
  const table = tableRef.value
  if (!table) return
  const selectedIdSet = selectedKeyIdSet.value
  restoringTableSelection.value = true
  try {
    keysTableData.value.forEach((row) => {
      table.toggleRowSelection(row, selectedIdSet.has(Number(row?.id)), false)
    })
  } finally {
    await nextTick()
    restoringTableSelection.value = false
  }
}

const handleKeySortChange = ({ prop, order }) => {
  keySort.value = { prop, order }
  resetToFirstPage()
  loadKeys()
}

let _loadKeysDebounceTimer = null
const loadKeysDebounced = (delay = 300) => {
  if (_loadKeysDebounceTimer) clearTimeout(_loadKeysDebounceTimer)
  _loadKeysDebounceTimer = setTimeout(() => {
    _loadKeysDebounceTimer = null
    loadKeys()
  }, delay)
}

const loadKeys = async () => {
  loading.value = true
  try {
    const params = {
      page: currentPage.value,
      limit: pageSize.value,
      sort_by: keySort.value.prop || 'id',
      sort_order: keySort.value.order || 'ascending',
    }
    const providers = normalizeModelNames(filterProviders.value)
    const models = normalizeModelNames(filterModels.value)
    const keyIds = [...filterKeyIds.value]
    const keyNames = normalizeModelNames(filterKeyNames.value)
    if (providers.length) {
      params.providers = providers
    }
    if (models.length) params.models = models
    if (keyIds.length) params.key_ids = keyIds
    if (keyNames.length) params.key_names = keyNames
    if (typeof filterActive.value === 'boolean') params.is_active = filterActive.value

    const result = await adminApi.listKeys(params)

    if (Array.isArray(result)) {
      keys.value = result
      totalKeys.value = result.length
    } else {
      keys.value = result.items || []
      totalKeys.value = result.total || 0
    }

    keys.value = keys.value.map((item) => ({
      ...createDefaultCheckState(),
      ...item,
    }))
    syncKeysTableData()

    refreshCooldowns()
    ensureCooldownTimer()
    await restoreTableSelection()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

const handlePageChange = (page) => {
  currentPage.value = page
  loadKeys()
}

const handlePageSizeChange = (size) => {
  pageSize.value = size
  currentPage.value = 1
  loadKeys()
}

const resetToFirstPage = () => {
  currentPage.value = 1
}

const handleSelectionChange = (rows) => {
  if (restoringTableSelection.value) {
    return
  }
  selectedKeyIds.value = rows.map((item) => Number(item?.id)).filter((id) => Number.isInteger(id) && id > 0)
}

watch(
  [filterProviders, filterKeyIds, filterKeyNames, filterModels, filterActive, currentPage, pageSize, keySort, selectedKeyIds],
  saveKeyManageState,
  { deep: true }
)

const showAddDialog = () => {
  isEdit.value = false
  editingId.value = null
  modelKeyword.value = ''
  quickModelInput.value = ''
  fillForm({
    name: '',
    provider: 'openai',
    api_type: 'other',
    api_key: '',
    base_url: defaultUrls.openai,
    weight: 1,
    enable_proxy: false,
    proxy_url: '',
    proxy_username: '',
    proxy_password: '',
    enable_fake_ip: true,
    fake_ip: '',
    supported_models: [],
    remark: '',
    password: '',
    wz_url: '',
  })
  dialogVisible.value = true
}

const showEditDialog = (row) => {
  isEdit.value = true
  editingId.value = row.id
  modelKeyword.value = ''
  quickModelInput.value = ''
  fillForm({
    name: row.name,
    provider: row.provider,
    api_type: normalizeApiType(row.api_type),
    api_key: row.api_key,
    base_url: row.base_url,
    weight: row.weight,
    enable_proxy: row.enable_proxy,
    proxy_url: row.proxy_url || '',
    proxy_username: row.proxy_username || '',
    proxy_password: row.proxy_password || '',
    enable_fake_ip: row.enable_fake_ip,
    fake_ip: row.fake_ip || '',
    supported_models: row.supported_models || [],
    remark: row.remark || '',
    password: row.password || '',
    wz_url: row.wz_url || '',
  })
  dialogVisible.value = true
}

const openDuplicateDialog = (row) => {
  isEdit.value = false
  editingId.value = null
  modelKeyword.value = ''
  quickModelInput.value = ''
  fillForm({
    name: createDuplicateName(row.name),
    provider: row.provider,
    api_type: normalizeApiType(row.api_type),
    api_key: row.api_key,
    base_url: row.base_url,
    weight: row.weight,
    enable_proxy: row.enable_proxy,
    proxy_url: row.proxy_url || '',
    proxy_username: row.proxy_username || '',
    proxy_password: row.proxy_password || '',
    enable_fake_ip: row.enable_fake_ip,
    fake_ip: row.fake_ip || '',
    supported_models: row.supported_models || [],
    remark: row.remark || '',
    password: row.password || '',
    wz_url: row.wz_url || '',
  })
  dialogVisible.value = true
}

const copyApiKey = async (row) => {
  try {
    await copyText(row.api_key)
    ElMessage.success(`已复制 ${row.name} 的 API Key`)
  } catch (e) {
    ElMessage.error(e.message || '复制失败')
  }
}

const copyKeyConfig = async (row) => {
  try {
    const configText = JSON.stringify(buildKeyConfig(row))
    await copyText(configText)
    ElMessage.success(`已复制 ${row.name} 的配置，可直接粘贴到一键导入`)
  } catch (e) {
    ElMessage.error(e.message || '复制失败')
  }
}

const duplicateKey = (row) => {
  openDuplicateDialog(row)
}

const duplicateFromForm = () => {
  openDuplicateDialog({ ...form })
}

const copyCurrentFormConfig = async () => {
  try {
    const configText = JSON.stringify(buildKeyConfig(form))
    await copyText(configText)
    ElMessage.success('已复制当前配置，可直接粘贴到一键导入')
  } catch (e) {
    ElMessage.error(e.message || '复制失败')
  }
}

const exportConfigs = async () => {
  if (selectedKeys.value.length) {
    const content = selectedKeys.value
      .map((item) => JSON.stringify(buildKeyConfig(item)))
      .join('\n')

    const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
    downloadTextFile(`cpa-api-keys-${timestamp}.jsonl`, content)
    ElMessage.success(`已导出 ${selectedKeys.value.length} 个 Key 配置`)
    return
  }

  exportingAllKeys.value = true
  try {
    const result = await adminApi.exportKeys()
    const items = Array.isArray(result.items) ? result.items : []
    const content = items
      .map((item) => JSON.stringify(buildKeyConfig(item)))
      .join('\n')
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
    downloadTextFile(`cpa-api-keys-all-${timestamp}.jsonl`, content)
    ElMessage.success(`已导出 ${result.count || items.length} 个 Key 配置`)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    exportingAllKeys.value = false
  }
}

const resetBatchForm = () => {
  batchScope.value = selectedKeys.value.length ? 'selected' : (hasFilteredConditions.value ? 'filtered' : 'selected')
  batchBaseUrl.value = ''
  batchNewProvider.value = ''
  batchModelMode.value = 'keep'
  batchWeightMode.value = 'keep'
  batchFakeIpMode.value = 'keep'
  batchApiTypeMode.value = 'keep'
  batchWeight.value = 1
  batchSupportedModels.value = []
  batchModelKeyword.value = ''
  batchQuickModelInput.value = ''
}

const showBatchDialog = () => {
  resetBatchForm()
  batchDialogVisible.value = true
}

const openCheckDialog = () => {
  batchScope.value = selectedKeys.value.length ? 'selected' : 'filtered'
  checkTargetModel.value = defaultCheckTargetModel.value || ''
  checkDialogVisible.value = true
}

const showCheckFailureDetail = (row) => {
  Object.assign(checkFailureDetail, {
    name: row?.name || '',
    base_url: row?.base_url || '',
    target_model: row?.check_target_model || '',
    failure_category: row?.check_error_category || '',
    failure_detail: row?.check_error_detail || '',
  })
  checkFailureDialogVisible.value = true
}

const getCheckFailureLabel = (category) => {
  const labelMap = {
    timeout: '超时',
    '401_403': '401/403',
    '404': '404',
    '429': '429',
    '502': '502',
    '503': '503',
    '5xx_other': '5xx',
    request_error: '请求错误',
    unknown: '未知错误',
  }
  return labelMap[category] || '检测失败'
}

const formatCheckLatency = (latency) => {
  const value = Number(latency)
  if (!Number.isFinite(value) || value < 0) return '-'
  return `${value} ms`
}

const showCooldownDialog = async () => {
  try {
    await loadCooldownConfig()
    cooldownDialogVisible.value = true
  } catch (e) {
    ElMessage.error(e.message)
  }
}

const applyQuickModels = () => {
  const names = normalizeModelNames((quickModelInput.value || '').split(','))
  if (!names.length) {
    ElMessage.warning('请输入模型名称')
    return
  }
  form.supported_models = normalizeModelNames([...(form.supported_models || []), ...names])
  quickModelInput.value = ''
}

const applyBatchQuickModels = () => {
  if (batchModelMode.value !== 'append' && batchModelMode.value !== 'replace') {
    batchModelMode.value = 'append'
  }
  const names = normalizeModelNames((batchQuickModelInput.value || '').split(','))
  if (!names.length) {
    ElMessage.warning('请输入模型名称')
    return
  }
  batchSupportedModels.value = normalizeModelNames([...(batchSupportedModels.value || []), ...names])
  batchQuickModelInput.value = ''
}

const applyFilterProviders = () => {
  const names = normalizeModelNames((filterProviderInput.value || '').split(','))
  if (!names.length) {
    ElMessage.warning('请输入提供商')
    return
  }
  syncCustomProviders(names)
  filterProviders.value = normalizeModelNames([...(filterProviders.value || []), ...names])
  filterProviderInput.value = ''
  resetToFirstPage()
  loadKeys()
}

const applyFilterModels = () => {
  const names = normalizeModelNames((filterModelInput.value || '').split(','))
  if (!names.length) {
    ElMessage.warning('请输入模型名称')
    return
  }
  filterModels.value = normalizeModelNames([...(filterModels.value || []), ...names])
  filterModelInput.value = ''
  resetToFirstPage()
  loadKeys()
}

const applyFilterKeyIds = () => {
  try {
    const { ids, names } = parseKeyIdentityFilterInput(filterKeyIdsInput.value || '')
    filterKeyIds.value = ids
    filterKeyNames.value = names
    filterKeyIdsInput.value = [...ids, ...names].join(',')
    resetToFirstPage()
    loadKeys()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

const batchCheckEndpoints = async () => {
  if (!validateBatchScope()) return

  const targetModel = (checkTargetModel.value || '').trim()
  if (!targetModel) {
    ElMessage.warning('请输入检测模型')
    return
  }

  const payload = {
    ...buildBatchScopePayload(),
    target_model: targetModel,
  }
  const currentPageRows = getCurrentPageRowsForCheck(payload)

  if (!currentPageRows.length) {
    ElMessage.warning('当前页没有可检测的 Key')
    return
  }

  const batchToken = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  currentCheckBatchToken.value = batchToken
  activeCheckTaskId.value = null
  activeCheckTaskSummary.value = null
  stopActiveCheckTaskPolling()

  checkDialogVisible.value = false
  batchChecking.value = true
  prepareRowsForChecking(currentPageRows, targetModel, batchToken)

  try {
    await runBatchCheckWithConcurrency(currentPageRows, targetModel, batchToken, 10)
    const completedRows = currentPageRows.filter((row) => row.check_batch_token === batchToken && row.check_state !== 'checking')
    const successCount = completedRows.filter((row) => row.check_state === 'success').length
    const errorCount = completedRows.filter((row) => row.check_state === 'error').length
    ElMessage.success(`检测完成：成功 ${successCount} 个，失败 ${errorCount} 个`)
  } catch (e) {
    currentPageRows.forEach((row) => {
      if (row.check_batch_token === batchToken && row.check_state === 'checking') {
        applyCheckResultToRow(row, buildCheckErrorResult(e, targetModel), batchToken)
      }
    })
    ElMessage.error(e.message || '批量检测失败')
  } finally {
    if (currentCheckBatchToken.value === batchToken) {
      currentCheckBatchToken.value = ''
    }
    batchChecking.value = false
  }
}

const batchCheckBalance = async () => {
  if (!validateBatchScope()) return

  const payload = buildBatchScopePayload()
  const currentPageRows = getCurrentPageRowsForCheck(payload)

  if (!currentPageRows.length) {
    ElMessage.warning('当前页没有可检测的 Key')
    return
  }

  const batchToken = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  currentCheckBatchToken.value = batchToken
  checkDialogVisible.value = false
  batchChecking.value = true

  // 标记为检测中
  currentPageRows.forEach((row) => {
    Object.assign(row, {
      ...createDefaultCheckState(),
      check_state: 'checking',
      check_mode: 'balance',
      check_batch_token: batchToken,
    })
  })

  const concurrency = 4
  let cursor = 0

  const worker = async () => {
    while (cursor < currentPageRows.length) {
      const idx = cursor++
      const row = currentPageRows[idx]
      if (!row || row.check_batch_token !== batchToken) continue
      try {
        const data = await adminApi.getProviderBalance(row.id)
        if (row.check_batch_token !== batchToken) return
        Object.assign(row, {
          check_state: 'success',
          check_mode: 'balance',
          check_balance_usd: data.balance_usd,
          check_latency_ms: 0,
          check_error_category: '',
          check_error_detail: '',
        })
      } catch (e) {
        if (row.check_batch_token !== batchToken) return
        const msg = e?.response?.data?.detail || e?.message || '查询失败'
        Object.assign(row, {
          check_state: 'error',
          check_mode: 'balance',
          check_balance_usd: null,
          check_error_category: 'request_error',
          check_error_detail: msg,
        })
      }
    }
  }

  try {
    await Promise.all(Array.from({ length: Math.min(concurrency, currentPageRows.length) }, () => worker()))
    const completedRows = currentPageRows.filter((r) => r.check_batch_token === batchToken)
    const successCount = completedRows.filter((r) => r.check_state === 'success').length
    const errorCount = completedRows.filter((r) => r.check_state === 'error').length
    ElMessage.success(`余额检测完成：成功 ${successCount} 个，失败 ${errorCount} 个`)
  } catch (e) {
    ElMessage.error(e.message || '余额检测失败')
  } finally {
    if (currentCheckBatchToken.value === batchToken) currentCheckBatchToken.value = ''
    batchChecking.value = false
  }
}

const submitBatchCheck = async () => {
  if (checkMode.value === 'balance') {
    await batchCheckBalance()
  } else {
    await batchCheckEndpoints()
  }
}

const submitBatchUpdate = async () => {
  if (!validateBatchScope()) return

  const normalizedBaseUrl = typeof batchBaseUrl.value === 'string' ? batchBaseUrl.value.trim() : ''
  const normalizedNewProvider = typeof batchNewProvider.value === 'string' ? batchNewProvider.value.trim() : ''
  const normalizedBatchModels = normalizeModelNames(batchSupportedModels.value || [])
  const shouldUpdateBaseUrl = hasBatchBaseUpdate()
  const shouldUpdateModels = hasBatchModelUpdate()
  const shouldUpdateWeight = hasBatchWeightUpdate()
  const shouldUpdateFakeIp = hasBatchFakeIpUpdate()
  const shouldUpdateProvider = !!normalizedNewProvider
  const shouldUpdateApiType = batchApiTypeMode.value !== 'keep'
  const modelActionLabelMap = {
    append: '追加模型',
    replace: '替换模型',
    clear: '清空模型',
  }
  const modelActionLabel = shouldUpdateModels ? modelActionLabelMap[batchModelMode.value] : ''
  const normalizedWeight = shouldUpdateWeight ? Number(batchWeight.value) : null

  if (!shouldUpdateBaseUrl && !shouldUpdateModels && !shouldUpdateWeight && !shouldUpdateFakeIp && !shouldUpdateProvider && !shouldUpdateApiType) {
    ElMessage.warning('请至少选择一项要调整的内容')
    return
  }

  if (shouldUpdateModels && (batchModelMode.value === 'replace' || batchModelMode.value === 'append') && !normalizedBatchModels.length) {
    ElMessage.warning('请先选择支持模型，如需恢复全部模型请使用清空')
    return
  }

  if (shouldUpdateWeight && (!Number.isInteger(normalizedWeight) || normalizedWeight < 0)) {
    ElMessage.warning('请输入有效的非负整数权重')
    return
  }

  if (shouldUpdateFakeIp && batchScope.value !== 'selected') {
    ElMessage.warning('fake IP 批量操作仅支持当前勾选项')
    return
  }

  batchSubmitting.value = true
  try {
    let modelResult = null
    let fakeIpResult = null

    if (shouldUpdateBaseUrl || shouldUpdateModels || shouldUpdateWeight || shouldUpdateProvider || shouldUpdateApiType) {
      const payload = buildBatchScopePayload()
      if (shouldUpdateBaseUrl) {
        payload.base_url = normalizedBaseUrl
      }
      if (shouldUpdateProvider) {
        payload.new_provider = normalizedNewProvider
      }
      if (shouldUpdateWeight) {
        payload.weight = normalizedWeight
      }
      if (shouldUpdateApiType) {
        payload.api_type = normalizeApiType(batchApiTypeMode.value)
      }
      if (batchModelMode.value === 'replace' || batchModelMode.value === 'append') {
        payload.supported_models = normalizedBatchModels
        payload.supported_models_mode = batchModelMode.value
      } else if (batchModelMode.value === 'clear') {
        payload.supported_models = null
        payload.supported_models_mode = 'clear'
      }
      modelResult = await adminApi.batchUpdateKeyModels(payload)
    }

    if (shouldUpdateFakeIp) {
      fakeIpResult = await submitBatchFakeIpUpdate()
    }

    const successMessages = []
    if (modelResult) {
      const modelActionSuffix = modelActionLabel ? `，${modelActionLabel}` : ''
      successMessages.push(`已批量更新 ${modelResult.count} 个 Key${modelActionSuffix}${modelResult.auto_created_model_count ? `，自动创建 ${modelResult.auto_created_model_count} 个模型` : ''}`)
    }
    if (fakeIpResult) {
      successMessages.push(`已为 ${fakeIpResult.count} 个 Key${fakeIpResult.enabled ? '开启独立 fake IP' : '关闭 fake IP'}`)
    }
    ElMessage.success(successMessages.join('；'))
    batchDialogVisible.value = false
    resetToFirstPage()
    await loadKeys()
    if (modelResult) {
      await loadModelOptions()
    }
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    batchSubmitting.value = false
  }
}

const batchDeleteSelectedKeys = async () => {
  const keyIds = selectedKeys.value.map((item) => Number(item?.id)).filter((id) => Number.isInteger(id) && id > 0)
  if (!keyIds.length) {
    ElMessage.warning('请先勾选要删除的 Key')
    return
  }

  batchDeleting.value = true
  try {
    const result = await adminApi.batchDeleteKeys({ key_ids: keyIds })
    selectedKeyIds.value = selectedKeyIds.value.filter((id) => !keyIds.includes(id))
    ElMessage.success(`已删除 ${result.count || keyIds.length} 个 Key`)
    resetToFirstPage()
    await loadKeys()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    batchDeleting.value = false
  }
}

const submitCooldownConfig = async () => {
  cooldownSubmitting.value = true
  try {
    await adminApi.updateKeyCooldownConfig({
      rate_limit_cooldown_seconds: Number(cooldownForm.rate_limit_cooldown_seconds) || 0,
      auth_failure_cooldown_seconds: Number(cooldownForm.auth_failure_cooldown_seconds) || 0,
      upstream_error_cooldown_seconds: Number(cooldownForm.upstream_error_cooldown_seconds) || 0,
      cloudflare_524_auto_continue_providers: normalizeModelNames(cooldownForm.cloudflare_524_auto_continue_providers),
    })
    ElMessage.success('冷却设置已保存')
    cooldownDialogVisible.value = false
    loadKeys()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    cooldownSubmitting.value = false
  }
}

const submitForm = async () => {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    const enableProxy = Boolean(form.enable_proxy)
    const enableFakeIp = Boolean(form.enable_fake_ip)
    const data = {
      ...form,
      provider: typeof form.provider === 'string' ? form.provider.trim() : form.provider,
      api_type: normalizeApiType(form.api_type),
      base_url: typeof form.base_url === 'string' ? form.base_url.trim() : form.base_url,
      weight: Number.isFinite(Number(form.weight)) ? Number(form.weight) : 1,
      enable_proxy: enableProxy,
      proxy_url: enableProxy ? (typeof form.proxy_url === 'string' ? form.proxy_url.trim() : form.proxy_url) : null,
      proxy_username: enableProxy ? (typeof form.proxy_username === 'string' ? form.proxy_username.trim() : form.proxy_username) : null,
      proxy_password: enableProxy ? (form.proxy_password || null) : null,
      enable_fake_ip: enableFakeIp,
      fake_ip: enableFakeIp ? ((typeof form.fake_ip === 'string' ? form.fake_ip.trim() : form.fake_ip) || randomFakeIp()) : null,
      supported_models: form.supported_models?.length ? normalizeModelNames(form.supported_models) : null,
      wz_url: (typeof form.wz_url === 'string' ? form.wz_url.trim() : form.wz_url) || null,
    }
    syncCustomProviders([data.provider])
    if (isEdit.value) {
      await adminApi.updateKey(editingId.value, data)
      ElMessage.success('更新成功')
    } else {
      await adminApi.createKey(data)
      ElMessage.success('添加成功')
    }
    dialogVisible.value = false
    resetToFirstPage()
    await loadProviderOptions()
    await loadModelOptions()
    loadKeys()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    submitting.value = false
  }
}

const submitAndContinue = async () => {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  // 校验 name + provider 联合唯一性（仅新增）
  const trimmedName = (form.name || '').trim()
  const trimmedProvider = typeof form.provider === 'string' ? form.provider.trim() : form.provider
  const duplicate = keys.value.find(
    (k) => k.name === trimmedName && k.provider === trimmedProvider
  )
  if (duplicate) {
    ElMessage.warning(`已存在相同名称「${trimmedName}」和提供商「${trimmedProvider}」的记录`)
    return
  }

  submitting.value = true
  try {
    const enableProxy = Boolean(form.enable_proxy)
    const enableFakeIp = Boolean(form.enable_fake_ip)
    const data = {
      ...form,
      provider: trimmedProvider,
      api_type: normalizeApiType(form.api_type),
      base_url: typeof form.base_url === 'string' ? form.base_url.trim() : form.base_url,
      weight: Number.isFinite(Number(form.weight)) ? Number(form.weight) : 1,
      enable_proxy: enableProxy,
      proxy_url: enableProxy ? (typeof form.proxy_url === 'string' ? form.proxy_url.trim() : form.proxy_url) : null,
      proxy_username: enableProxy ? (typeof form.proxy_username === 'string' ? form.proxy_username.trim() : form.proxy_username) : null,
      proxy_password: enableProxy ? (form.proxy_password || null) : null,
      enable_fake_ip: enableFakeIp,
      fake_ip: enableFakeIp ? ((typeof form.fake_ip === 'string' ? form.fake_ip.trim() : form.fake_ip) || randomFakeIp()) : null,
      supported_models: form.supported_models?.length ? normalizeModelNames(form.supported_models) : null,
      wz_url: (typeof form.wz_url === 'string' ? form.wz_url.trim() : form.wz_url) || null,
    }
    syncCustomProviders([data.provider])
    await adminApi.createKey(data)
    ElMessage.success('添加成功，可继续添加')
    // 重置表单，保留 provider 和 base_url 便于连续添加
    const keepProvider = form.provider
    const keepApiType = form.api_type
    const keepBaseUrl = form.base_url
    const keepFakeIp = form.fake_ip
    formRef.value.resetFields()
    form.name = createDuplicateName(trimmedName)
    form.provider = keepProvider
    form.api_type = keepApiType
    form.base_url = keepBaseUrl
    form.fake_ip = keepFakeIp
    resetToFirstPage()
    await loadProviderOptions()
    await loadModelOptions()
    loadKeys()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    submitting.value = false
  }
}

const fillImportTemplate = () => {
  importText.value = [
    JSON.stringify({ name: 'openai-1', provider: 'openai', api_type: 'newapi', api_key: 'sk-xxx', base_url: 'https://api.openai.com', remark: 'New API 模板示例' }),
    JSON.stringify({ name: 'sub2api-1', provider: 'openai', api_type: 'sub2api', api_key: 'sk-xxx', base_url: 'https://api.example.com', password: 'login-password', wz_url: 'https://example.com', remark: 'sub2api 模板示例' }),
    JSON.stringify({ name: 'openai-proxy-1', provider: 'openai', api_type: 'newapi', api_key: 'sk-xxx', base_url: 'https://api.openai.com', enable_proxy: true, proxy_url: 'http://127.0.0.1:7890', proxy_username: '', proxy_password: '', remark: '代理模板示例' }),
    JSON.stringify({ name: 'openai-fake-ip-1', provider: 'openai', api_type: 'newapi', api_key: 'sk-xxx', base_url: 'https://api.openai.com', enable_fake_ip: true, fake_ip: '203.0.113.10', remark: '伪装 IP 模板示例' }),
    JSON.stringify({ name: 'openai-auto-fake-ip-1', provider: 'openai', api_type: 'newapi', api_key: 'sk-xxx', base_url: 'https://api.openai.com', enable_fake_ip: true, fake_ip: null, remark: '自动分配伪装 IP 示例' }),
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

const submitImport = async () => {
  const lines = importText.value
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)

  if (!lines.length) {
    ElMessage.error('请输入要导入的内容')
    return
  }

  importing.value = true
  try {
    const items = lines.map((line) => {
      const item = JSON.parse(line)
      const supportedModels = Array.isArray(item.supported_models)
        ? normalizeModelNames(item.supported_models)
        : null
      const enableProxy = Boolean(item.enable_proxy)
      const enableFakeIp = Boolean(item.enable_fake_ip)
      const rawWzUrl = item.wz_url ?? item.wzurl ?? item.wzUrl ?? item.web_url ?? item.webUrl
      return {
        ...item,
        api_type: normalizeApiType(item.api_type),
        enable_proxy: enableProxy,
        proxy_url: enableProxy ? (typeof item.proxy_url === 'string' ? item.proxy_url.trim() : item.proxy_url) : null,
        proxy_username: enableProxy ? (typeof item.proxy_username === 'string' ? item.proxy_username.trim() : item.proxy_username) : null,
        proxy_password: enableProxy ? (item.proxy_password || null) : null,
        enable_fake_ip: enableFakeIp,
        fake_ip: enableFakeIp ? (typeof item.fake_ip === 'string' ? item.fake_ip.trim() : item.fake_ip) : null,
        supported_models: supportedModels?.length ? supportedModels : null,
        wz_url: typeof rawWzUrl === 'string' ? rawWzUrl.trim() || null : rawWzUrl || null,
      }
    })
    const result = await adminApi.importKeys(items)
    ElMessage.success(`成功导入 ${result.count} 个 Key，自动创建 ${result.auto_created_model_count || 0} 个模型`)
    importDialogVisible.value = false
    importText.value = ''
    resetToFirstPage()
    await loadProviderOptions()
    await loadModelOptions()
    loadKeys()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    importing.value = false
  }
}

const toggleKey = async (row) => {
  row.toggling = true
  try {
    await adminApi.toggleKey(row.id)
  } catch (e) {
    row.is_active = !row.is_active
    ElMessage.error(e.message)
  } finally {
    row.toggling = false
  }
}

const clearCooldown = async (row) => {
  row.clearingCooldown = true
  try {
    const updated = await adminApi.clearKeyCooldown(row.id)
    Object.assign(row, updated)
    updateRowCooldownState(row)
    ElMessage.success('已解除冷却')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    row.clearingCooldown = false
  }
}

const batchClearCooldown = async () => {
  if (!selectedKeys.value.length) {
    ElMessage.warning('请先勾选要操作的 Key')
    return
  }

  batchCooldownSubmitting.value = true
  try {
    const result = await adminApi.batchClearKeysCooldown({
      key_ids: selectedKeys.value.map((item) => item.id),
    })
    ElMessage.success(`已批量解除 ${result.count} 个 Key 的冷却`)
    loadKeys()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    batchCooldownSubmitting.value = false
  }
}

const batchSetActive = async (isActive) => {
  if (!selectedKeys.value.length) {
    ElMessage.warning('请先勾选要操作的 Key')
    return
  }

  batchActiveSubmitting.value = true
  try {
    const payload = {
      key_ids: selectedKeys.value.map((item) => item.id),
      is_active: isActive,
    }
    const result = await adminApi.batchSetKeysActive(payload)
    ElMessage.success(`已批量${result.is_active ? '启用' : '关闭'} ${result.count} 个 Key`)
    resetToFirstPage()
    loadKeys()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    batchActiveSubmitting.value = false
  }
}

const deleteKey = async (row) => {
  try {
    await adminApi.deleteKey(row.id)
    const deletedId = Number(row?.id)
    selectedKeyIds.value = selectedKeyIds.value.filter((id) => id !== deletedId)
    ElMessage.success('删除成功')
    resetToFirstPage()
    await loadProviderOptions()
    await loadKeys()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

onMounted(() => {
  loadProviderOptions()
  loadModelOptions()
  loadCheckTasks()
  loadKeyCheckShortcutModels()
  resetBatchForm()
  loadKeys()
  loadCooldownConfig().catch(() => {})
  loadKeyCheckDefaultConfig().catch(() => {})
  ensureCooldownTimer()
})

onBeforeUnmount(() => {
  stopActiveCheckTaskPolling()
  stopCooldownTimer()
})

// ── Key 详情弹窗 ──────────────────────────────────────────
const keyDetailDialogVisible = ref(false)
const keyDetailLoading = ref(false)
const keyDetailData = ref({})
const keyDetailSummary = ref({})
const keyDetailLogs = ref([])
const keyDetailLogsLoading = ref(false)
const keyDetailLogsPage = ref(1)
const keyDetailLogsPageSize = ref(20)
const keyDetailLogsTotal = ref(0)
const keyDetailBalance = ref(null)
const keyDetailBalanceLoading = ref(false)
const keyDetailToggling = ref(false)

const formatKeyDetailToken = (value) => {
  const num = Number(value || 0)
  if (num >= 1_000_000) {
    return `${(num / 1_000_000).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} M`
  }
  return num.toLocaleString('zh-CN')
}

const formatKeyDetailCompactToken = (value) => {
  const num = Number(value || 0)
  if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`
  if (num >= 1_000) return `${(num / 1_000).toFixed(1)}k`
  return `${num}`
}

const formatKeyDetailLatency = (value) => {
  const ms = Math.round(Number(value || 0))
  return `${ms.toLocaleString('zh-CN')} ms`
}

const getKeyDetailSuccessRate = () => {
  const total = Number(keyDetailSummary.value?.total_requests || 0)
  const success = Number(keyDetailSummary.value?.success_requests || 0)
  if (!total) return 0
  return Math.round((success / total) * 100)
}

const loadKeyDetailLogs = async (keyId) => {
  if (!keyId) return
  keyDetailLogsLoading.value = true
  try {
    const result = await statsApi.getLogs({
      api_key_id: keyId,
      days: 7,
      page: keyDetailLogsPage.value,
      limit: keyDetailLogsPageSize.value,
    })
    keyDetailLogs.value = Array.isArray(result) ? result : (result.items || [])
    keyDetailLogsTotal.value = Array.isArray(result) ? result.length : (result.total || 0)
  } catch (e) {
    ElMessage.error(e.message || '加载请求记录失败')
  } finally {
    keyDetailLogsLoading.value = false
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

const openKeyDetail = async (keyId) => {
  if (!keyId) return
  keyDetailDialogVisible.value = true
  keyDetailLoading.value = true
  keyDetailBalance.value = null
  try {
    const [keyData, summaryData] = await Promise.all([
      adminApi.getKey(keyId),
      statsApi.getSummary({ api_key_id: keyId, days: 7 }),
    ])
    keyDetailData.value = keyData || {}
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

const toggleKeyDetailActive = async () => {
  const keyId = keyDetailData.value?.id
  if (!keyId || keyDetailToggling.value) return
  keyDetailToggling.value = true
  try {
    const updated = await adminApi.toggleKey(keyId)
    keyDetailData.value = { ...keyDetailData.value, is_active: updated.is_active }
    // 同步主表数据
    const idx = keys.value.findIndex((k) => k.id === keyId)
    if (idx >= 0) keys.value[idx] = { ...keys.value[idx], is_active: updated.is_active }
    syncKeysTableData()
    ElMessage.success(updated.is_active ? 'Key 已启用' : 'Key 已关闭')
  } catch (e) {
    ElMessage.error(e.message || '操作失败')
  } finally {
    keyDetailToggling.value = false
  }
}

const handleKeyDetailLogsPageChange = (page) => {
  keyDetailLogsPage.value = page
  loadKeyDetailLogs(keyDetailData.value?.id)
}

const handleKeyDetailLogsPageSizeChange = (size) => {
  keyDetailLogsPageSize.value = size
  keyDetailLogsPage.value = 1
  loadKeyDetailLogs(keyDetailData.value?.id)
}

const handleKeyDetailDialogClosed = () => {
  keyDetailData.value = {}
  keyDetailSummary.value = {}
  keyDetailLogs.value = []
  keyDetailLogsTotal.value = 0
  keyDetailLogsPage.value = 1
  keyDetailBalance.value = null
}
// ─────────────────────────────────────────────────────────
</script>

<style scoped>
.key-manage.page-shell {
  gap: 12px;
  width: 100%;
  min-width: 0;
  max-width: 100%;
  overflow-x: hidden;
}

.page-header {
  display: flex;
  justify-content: flex-start;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 0;
  width: 100%;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
}

.page-header-main {
  min-width: 0;
  flex: 0 0 220px;
}

.page-header-note {
  font-size: 13px;
  line-height: 1.5;
  color: #6f86a3;
}

.status-cell {
  display: inline-flex;
  align-items: center;
  justify-content: flex-start;
  gap: 3px;
}

.status-cooldown-tag {
  cursor: help;
  flex-shrink: 0;
}

.filter-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  width: 100%;
}

.filter-item.quick-filter-item {
  max-width: 420px;
}

.filter-item.quick-filter-item :deep(.el-input) {
  flex: 1;
  min-width: 0;
}

.quick-filter-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
}

.quick-filter-row :deep(.el-button) {
  min-width: 68px;
}

.check-shortcut-buttons {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  grid-template-rows: repeat(2, 40px);
  gap: 10px;
  margin-top: 10px;
  width: 100%;
}

.check-shortcut-cell {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 40px;
  line-height: 1;
  padding: 0 10px;
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  text-align: center;
  cursor: pointer;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  background: var(--el-bg-color);
  color: var(--el-text-color-regular);
  transition: all 0.2s;
  user-select: none;
}

.check-shortcut-cell:hover {
  color: var(--el-color-primary);
  border-color: var(--el-color-primary-light-5);
  background: var(--el-color-primary-light-9);
}

.check-shortcut-cell.is-empty {
  visibility: hidden;
  pointer-events: none;
}

.keys-table-card {
  width: 100%;
  min-width: 0;
  max-width: 100%;
  margin-bottom: 0;
  overflow: hidden;
}

.keys-table-card :deep(.el-card__body) {
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  padding-bottom: 0;
}

.keys-table-sticky {
  position: sticky;
  top: 0;
  z-index: 20;
  width: 100%;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  background: var(--el-bg-color);
}

.keys-table-sticky :deep(.el-table) {
  width: 100%;
  max-width: 100%;
}

.keys-table-sticky :deep(.el-table__inner-wrapper) {
  max-width: 100%;
}

.keys-table-sticky :deep(.el-table__header-wrapper) {
  position: sticky;
  top: 0;
  z-index: 21;
}

.keys-table-sticky :deep(.el-table__header-wrapper th.el-table__cell) {
  background: var(--el-fill-color-blank);
}

.key-manage-pagination {
  margin-top: 12px;
}

.keys-table :deep(.el-table__body-wrapper .el-table__cell),
.keys-table :deep(.el-table__body-wrapper .cell) {
  user-select: text;
}

.keys-table :deep(.el-table__header-wrapper .el-table__cell),
.keys-table :deep(.el-table-column--selection .cell),
.keys-table :deep(.action-row),
.keys-table :deep(.el-button),
.keys-table :deep(.el-switch) {
  user-select: none;
}

.keys-table :deep(.el-table__header-wrapper th .cell) {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 32px;
  width: 100%;
}

.keys-table :deep(.caret-wrapper) {
  display: inline-flex;
  flex-direction: column;
  justify-content: center;
  margin-left: 0;
}

.keys-table :deep(.el-table__column-resize-proxy) {
  background-color: #409eff;
}

.header-actions {
  flex: 1;
  min-width: 0;
  margin-left: auto;
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px 10px;
  align-items: center;
  align-content: flex-start;
}

.header-actions :deep(.el-button) {
  margin: 0;
}

.header-action-wide {
  min-width: 104px;
}

.import-actions {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
}

.hidden-input {
  display: none;
}

.page-title {
  color: #303133;
  margin: 0;
  font-size: 26px;
  line-height: 1.08;
  white-space: nowrap;
}

.filter-card {
  width: 100%;
  min-width: 0;
  max-width: 100%;
  margin-bottom: 0;
  overflow: hidden;
}

.filter-card.is-collapsed :deep(.el-card__body) {
  padding-top: 8px;
  padding-bottom: 8px;
}

.filter-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.filter-summary-text {
  color: #909399;
  font-size: 12px;
}

.filter-row {
  width: 100%;
}

.filter-row :deep(.el-input__wrapper),
.filter-row :deep(.el-select__wrapper) {
  min-height: 34px;
}

.check-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.check-result-cell {
  display: flex;
  align-items: center;
  min-height: 24px;
}

.check-result-pending {
  color: #909399;
}

.check-result-success {
  color: #67c23a;
  font-weight: 600;
}

.check-result-link {
  padding: 0;
  min-height: auto;
  font-weight: 600;
}

.check-result-idle {
  color: #c0c4cc;
}

.check-failure-detail-text {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
}

.priority-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.priority-model-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.priority-model-id {
  color: #909399;
  font-size: 12px;
}

.priority-current-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

@media (max-width: 1400px) {
  .page-header-main {
    flex-basis: 200px;
  }
}

@media (max-width: 1200px) {
  .filter-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .page-header-main {
    flex-basis: 180px;
  }
}

@media (max-width: 768px) {
  .page-header {
    flex-direction: column;
  }

  .page-header-main {
    flex-basis: auto;
  }

  .page-title {
    white-space: normal;
  }

  .filter-grid {
    grid-template-columns: 1fr;
  }

  .filter-header-actions {
    width: 100%;
    justify-content: flex-start;
  }

  .header-actions {
    flex-wrap: wrap;
    width: 100%;
    margin-left: 0;
    justify-content: flex-start;
  }

  .header-action-wide {
    min-width: 0;
  }
}

.model-select-wrap {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}

.quick-model-row {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
}

.no-margin {
  margin: 0;
}

.batch-mode-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
}

code {
  background: #f5f7fa;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: monospace;
}

.action-row {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
}

.action-row :deep(.el-button) {
  padding-left: 0;
  padding-right: 0;
}

.model-cell {
  display: flex;
  align-items: center;
  gap: 4px;
  min-height: 24px;
  overflow: hidden;
  user-select: text;
}

.base-url-cell {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  user-select: text;
}

.model-tag :deep(.el-tag__content) {
  user-select: text;
}

:deep(.base-url-tooltip) {
  max-width: min(720px, calc(100vw - 48px));
}

.base-url-tooltip__content {
  max-width: min(720px, calc(100vw - 48px));
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
  user-select: text;
}

.model-tag {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.more-tag {
  flex-shrink: 0;
}

.proxy-config-wrap {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  width: 100%;
}

.form-extra-collapse {
  border: none;
  margin-bottom: 4px;
}

.form-extra-collapse :deep(.el-collapse-item__header) {
  border: none;
  background: transparent;
  height: 32px;
  line-height: 32px;
  padding: 0 2px;
}

.form-extra-collapse :deep(.el-collapse-item__wrap) {
  border: none;
  background: transparent;
}

.form-extra-collapse :deep(.el-collapse-item__content) {
  padding: 4px 0 0 0;
}
</style>
