<template>
  <div class="image-square page-shell">
    <div class="page-header">
      <div class="page-header-main">
        <div class="page-kicker">Images</div>
        <h2 class="page-title"><a href="https://photofan.heabl.top/" target="_blank" rel="noopener noreferrer" class="title-hidden-link">光影世界</a></h2>
      </div>
      <div class="header-actions">
        <el-button :loading="loadingModels" @click="loadAll">刷新</el-button>
      </div>
    </div>

    <div class="workspace-grid">
      <el-card class="generate-card" shadow="never">
        <template #header>
          <div class="card-header-simple">
            <div>
              <div class="panel-title">图片生成</div>
            </div>
          </div>
        </template>

        <el-form label-position="top" class="generate-form">
          <div class="model-mode-row">
            <el-form-item label="模型" class="model-field">
              <el-select v-model="form.model" filterable placeholder="选择图片模型" @change="handleModelChange">
                <el-option
                  v-for="item in imageModels"
                  :key="item.model"
                  :label="`${item.display_name}（可用 Key：${item.available_key_count}，${formatRemainingImageCount(item.total_remaining_image_count)}）`"
                  :value="item.model"
                >
                  <div class="model-option">
                    <span>{{ item.display_name }}</span>
                    <div class="model-option-meta">
                      <el-tag :type="item.available_key_count > 0 ? 'success' : 'info'" size="small">
                        {{ item.available_key_count }} 个可用 Key
                      </el-tag>
                      <el-tag type="info" size="small">
                        {{ formatRemainingImageCount(item.total_remaining_image_count) }}
                      </el-tag>
                    </div>
                  </div>
                </el-option>
              </el-select>
            </el-form-item>

            <el-form-item label="生成模式" class="mode-field">
              <el-radio-group v-model="form.mode" class="mode-switch">
                <el-radio-button
                  v-for="item in imageModeOptions"
                  :key="item.value"
                  :label="item.value"
                >
                  {{ item.label }}
                </el-radio-button>
              </el-radio-group>
            </el-form-item>
          </div>

          <div v-if="selectedModel" class="model-meta">
            <el-tag type="primary" size="small">{{ selectedModel.provider }}</el-tag>
            <el-tag size="small">最多 {{ selectedModel.max_count }} 张</el-tag>
            <el-tag v-for="item in selectedModel.request_formats" :key="item" type="info" size="small">{{ formatLabel(item) }}</el-tag>
          </div>

          <el-form-item label="提示词">
            <el-input
              v-model="form.prompt"
              type="textarea"
              :rows="5"
              maxlength="4000"
              show-word-limit
              placeholder="输入图片生成提示词，描述主体、风格、构图和细节"
            />
          </el-form-item>

          <el-collapse v-model="promptTipPanels" class="prompt-helper">
            <el-collapse-item name="examples">
              <template #title>
                <span class="prompt-helper-collapse-title">提示词示例</span>
              </template>
              <div class="prompt-helper-desc">
                <span>建议按</span>
                <el-button
                  v-for="item in promptStructureLinks"
                  :key="item.title"
                  link
                  type="primary"
                  size="small"
                  class="inline-prompt-link"
                  @click="openPromptExample(item, item.type)"
                >
                  {{ item.title }}
                </el-button>
                <span>和限制项组织提示词，示例可点击查看完整提示词。</span>
              </div>
              <div class="prompt-tip-groups">
                <div v-for="group in promptTipGroups" :key="group.type" class="prompt-tip-group">
                  <div class="prompt-tip-group-title">{{ group.type }}</div>
                  <div class="prompt-tip-list">
                    <el-button
                      v-for="item in group.examples"
                      :key="item.title"
                      link
                      type="primary"
                      size="small"
                      @click="openPromptExample(item, group.type)"
                    >
                      {{ item.title }}
                    </el-button>
                  </div>
                </div>
              </div>
              <div class="prompt-external-links">
                <span>更多提示词参考：</span>
                <el-button link type="primary" size="small" tag="a" href="https://youmind.com/zh-CN/gpt-image-2-prompts" target="_blank">YouMind 提示词库</el-button>
                <el-button link type="primary" size="small" tag="a" href="https://evolink.ai/zh/gpt-image-2-prompts" target="_blank">Evolink 提示词库</el-button>
              </div>
            </el-collapse-item>
          </el-collapse>

          <el-form-item v-if="form.mode === 'image_to_image'" label="参考图">
            <div class="input-image-uploader">
              <input
                ref="inputImageFileRef"
                class="input-image-file"
                type="file"
                accept="image/png,image/jpeg,image/webp"
                multiple
                @change="handleInputImageChange"
              />
              <div class="input-image-actions">
                <el-button :disabled="form.input_images.length >= maxInputImageCount" @click="selectInputImages">
                  上传参考图
                </el-button>
                <span>支持 PNG、JPEG、WebP，最多 {{ maxInputImageCount }} 张</span>
              </div>
              <div v-if="form.input_images.length" class="input-image-list">
                <div v-for="(item, index) in form.input_images" :key="item.id" class="input-image-item">
                  <el-image
                    class="input-image-preview"
                    :src="item.data_url || item.image_url"
                    fit="cover"
                    :preview-src-list="inputImagePreviewList"
                    :preview-teleported="true"
                    :initial-index="index"
                    :zoom-rate="1.2"
                    :min-scale="0.2"
                    :max-scale="7"
                  />
                  <div class="input-image-info">
                    <div class="input-image-name" :title="item.name">{{ item.name }}</div>
                    <div>{{ item.mime_type }} · {{ formatFileSize(item.size_bytes) }}</div>
                  </div>
                  <el-button link type="danger" @click="removeInputImage(index)">移除</el-button>
                </div>
              </div>
            </div>
          </el-form-item>

          <div class="param-grid">
            <el-form-item label="尺寸">
              <el-select v-model="form.size" filterable allow-create default-first-option placeholder="选择或输入尺寸">
                <el-option-group
                  v-for="group in sizeOptionGroups"
                  :key="group.label"
                  :label="group.label"
                >
                  <el-option
                    v-for="item in group.options"
                    :key="item.value"
                    :value="item.value"
                    :label="item.label"
                  >
                    <div class="size-option">
                      <span>{{ item.label }}</span>
                      <span>{{ item.scene }}</span>
                    </div>
                  </el-option>
                </el-option-group>
              </el-select>
            </el-form-item>
            <el-form-item label="质量">
              <el-select v-model="form.quality" placeholder="质量">
                <el-option value="auto" label="auto" />
                <el-option value="low" label="low" />
                <el-option value="medium" label="medium" />
                <el-option value="high" label="high" />
              </el-select>
            </el-form-item>
            <el-form-item label="数量">
              <el-input-number v-model="form.count" :min="1" :max="maxCount" controls-position="right" />
            </el-form-item>
            <el-form-item label="请求格式">
              <el-select v-model="form.request_format" placeholder="请求格式">
                <el-option
                  v-for="item in requestFormatOptions"
                  :key="item"
                  :value="item"
                  :label="formatLabel(item)"
                />
              </el-select>
            </el-form-item>
          </div>

          <div class="generate-actions">
            <div class="form-tip">
              默认走 images；备用入口验证通过后再开放选择。
            </div>
            <el-button type="primary" :loading="generating" @click="submitGeneration">
              <el-icon><Picture /></el-icon>
              开始生成
            </el-button>
          </div>
        </el-form>
      </el-card>

      <div class="side-stack">
        <el-card class="model-card" shadow="never">
          <template #header>
            <div class="card-header-simple compact-header">
              <div>
                <div class="panel-title">可用模型</div>
              </div>
            </div>
          </template>
          <div class="model-list" v-loading="loadingModels">
            <div v-for="item in imageModels" :key="item.model" class="model-list-item" :class="{ 'is-active': form.model === item.model }" @click="selectModel(item.model)">
              <div>
                <div class="model-name">{{ item.display_name }}</div>
                <div class="model-id">{{ item.model }}</div>
              </div>
              <div class="model-capacity">
                <el-button link type="primary" @click.stop="openModelKeys(item)">
                  {{ item.available_key_count }} Key
                </el-button>
                <span>{{ formatRemainingImageCount(item.total_remaining_image_count) }}</span>
              </div>
            </div>
          </div>
        </el-card>
      </div>
    </div>

    <el-collapse v-model="activePanels" class="content-collapse">
      <el-collapse-item v-if="currentTask" name="result">
        <template #title>
          <div class="collapse-title">
            <div>
              <div class="panel-title">生成结果</div>
              <div class="panel-subtitle">任务 #{{ currentTask.id }} · {{ currentTask.api_key_name || '未命名 Key' }} · {{ formatTime(currentTask.created_at) }}</div>
            </div>
            <div class="collapse-title-right">
              <el-tag :type="statusType(currentTask.status)">{{ statusText(currentTask.status) }}</el-tag>
              <span class="task-duration">{{ formatDuration(currentTask.duration_ms) }}</span>
            </div>
          </div>
        </template>

        <el-alert
          v-if="currentTask.status === 'running'"
          title="上游仍在生成，可稍后用 ID取图回填结果。"
          type="info"
          show-icon
          :closable="false"
        >
          <template #default>
            <div class="error-actions">
              <el-button link type="primary" @click="openTaskUpstreamRefresh(currentTask)">ID取图</el-button>
            </div>
          </template>
        </el-alert>

        <el-alert
          v-if="currentTask.status === 'error'"
          :title="currentTask.error_summary || '图片生成失败'"
          type="error"
          show-icon
          :closable="false"
        >
          <template #default>
            <div class="error-actions">
              <el-button link type="primary" @click="openTaskUpstreamRefresh(currentTask)">ID取图</el-button>
            </div>
          </template>
        </el-alert>

        <div v-if="successResults.length" class="image-grid">
          <div v-for="item in successResults" :key="item.id" class="image-card">
            <div v-if="isImageToImageTask(currentTask) && getFirstInputImageUrl(currentTask)" class="image-pair">
              <el-image
                class="image-pair-input"
                :src="getFirstInputImageUrl(currentTask)"
                fit="cover"
                :preview-src-list="[getFirstInputImageUrl(currentTask)]"
                :preview-teleported="true"
              />
              <span class="image-pair-arrow">-&gt;</span>
              <el-image
                class="image-pair-output"
                :src="imageSrc(item)"
                fit="cover"
                :preview-src-list="previewImages"
                :preview-teleported="true"
                :zoom-rate="1.2"
                :min-scale="0.2"
                :max-scale="7"
              />
            </div>
            <el-image
              v-else
              class="image-preview"
              :src="imageSrc(item)"
              fit="cover"
              :preview-src-list="previewImages"
              :preview-teleported="true"
              :zoom-rate="1.2"
              :min-scale="0.2"
              :max-scale="7"
            />
            <div class="image-card-footer">
              <div class="image-card-info">
                <span>#{{ item.image_index }}</span>
                <span class="image-card-meta">{{ imageSizeText(item) }}</span>
              </div>
              <div class="image-actions">
                <el-button v-if="item.image_url" link type="primary" @click="copyToClipboard(item.image_url)">复制 URL</el-button>
                <el-button
                  link
                  type="primary"
                  :loading="isSavingResult(item.id)"
                  @click="downloadImage(item)"
                >下载</el-button>
                <el-button v-if="imageEnhancementEnabled" link type="primary" :loading="isSavingResult(item.id)" @click="downloadPsd(item)">PSD</el-button>
              </div>
            </div>
          </div>
        </div>
      </el-collapse-item>

      <el-collapse-item name="history">
        <template #title>
          <div class="collapse-title">
            <div class="panel-title">历史记录</div>
            <div class="history-actions" @click.stop>
              <el-select
                v-if="showUserFilter"
                v-model="userIdFilter"
                placeholder="筛选用户"
                clearable
                filterable
                size="small"
                style="width: 140px; margin-right: 8px"
                @change="() => { taskPage = 1; loadTasks() }"
              >
                <el-option
                  v-for="item in userOptions"
                  :key="item.id"
                  :label="item.username"
                  :value="item.id"
                />
              </el-select>
              <el-button
                :disabled="!selectedHistoryTasks.length"
                :loading="deletingHistoryTasks"
                @click.stop="confirmBatchDeleteTasks"
              >
                批量删除
              </el-button>
              <el-button @click.stop="openStorageDialog">存储位置</el-button>
              <el-badge :value="pendingRefreshTaskIds.size" :hidden="!pendingRefreshTaskIds.size" class="polling-badge">
                <el-button :disabled="!pendingRefreshTaskIds.size" @click.stop="openPollingDialog">轮询信息</el-button>
              </el-badge>
              <el-button :loading="loadingTasks" @click.stop="loadTasks">刷新历史</el-button>
            </div>
          </div>
        </template>

        <el-table
          :data="tasks"
          stripe
          size="small"
          v-loading="loadingTasks"
          height="400"
          @selection-change="handleHistorySelectionChange"
        >
          <el-table-column type="selection" width="38" />
          <el-table-column prop="id" label="任务" width="58">
            <template #default="{ row }">#{{ row.id }}</template>
          </el-table-column>
          <el-table-column prop="model" label="模型" width="110" show-overflow-tooltip />
          <el-table-column label="模式" width="78">
            <template #default="{ row }">
              <div class="mode-cell">
                <el-tag :type="taskMode(row) === 'image_to_image' ? 'warning' : 'info'" size="small">
                  {{ taskModeLabel(row) }}
                </el-tag>
                <span v-if="taskInputImageCount(row)">参考图 {{ taskInputImageCount(row) }} 张</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="prompt" label="提示词" min-width="360" show-overflow-tooltip />
          <el-table-column label="Key" width="112" show-overflow-tooltip>
            <template #default="{ row }">
              <el-button
                v-if="row.api_key_id"
                link
                type="primary"
                class="key-name-link"
                @click="openImageKeyDetail(row.api_key_id)"
              >
                {{ row.api_key_name || `Key #${row.api_key_id}` }}
              </el-button>
              <span v-else>{{ row.api_key_name || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="64" align="center">
            <template #default="{ row }">
              <el-tag :type="statusType(row.status)" size="small">{{ statusText(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="用时" width="72" align="center">
            <template #default="{ row }">{{ formatDuration(row.duration_ms) }}</template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" width="142">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="150" fixed="right">
            <template #default="{ row }">
              <div class="history-row-actions">
                <el-button link type="primary" @click="openTask(row.id)">查看</el-button>
                <el-button v-if="row.status === 'success'" link type="primary" @click="editTaskImage(row)">调整</el-button>
                <el-button v-if="row.status === 'error' || row.status === 'running'" link type="primary" @click="openTaskUpstreamRefresh(row)">ID取图</el-button>
                <el-button link type="primary" @click="reuseTaskPrompt(row)">引用</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>

        <div class="pagination image-history-pagination">
          <el-pagination
            v-model:current-page="taskPage"
            v-model:page-size="taskPageSize"
            :page-sizes="[10, 20, 50]"
            :total="taskTotal"
            small
            layout="total, sizes, prev, pager, next"
            @current-change="loadTasks"
            @size-change="handleTaskSizeChange"
          />
        </div>
      </el-collapse-item>
    </el-collapse>

    <el-dialog v-model="modelKeyDialogVisible" :title="`${selectedKeyModel?.display_name || '模型'} 满足条件的 Key`" width="1360px" class="model-key-dialog">
      <el-alert
        v-if="selectedKeyModel && !canValidateImageModel(selectedKeyModel.model)"
        title="当前模型暂未开放生图验证，支持 GPT Image 2、GPT Image 1、Nano Banana Pro、Nano Banana Pro 4K。"
        type="info"
        show-icon
        :closable="false"
        class="model-key-validate-tip"
      />
      <div class="model-key-toolbar">
        <el-input
          v-model="modelKeyFilters.names"
          clearable
          placeholder="按 Key name 查询，多个用逗号分隔"
        />
        <el-input
          v-model="modelKeyFilters.weights"
          clearable
          placeholder="按权重查询，多个用逗号分隔"
        />
        <el-date-picker
          v-model="modelKeyFilters.generatedDates"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="最近生图开始日期"
          end-placeholder="最近生图结束日期"
          range-separator="至"
          clearable
        />
        <el-button class="model-key-reset-button" @click="resetModelKeyFilters">重置</el-button>
      </div>
      <el-table :data="filteredModelKeyRows" size="small" stripe v-loading="loadingModelKeys" max-height="480">
        <el-table-column prop="api_key_id" label="ID" width="58" align="center" header-align="center" sortable />
        <el-table-column prop="api_key_name" label="Key" width="156" align="center" header-align="center" sortable show-overflow-tooltip />
        <el-table-column prop="provider" label="提供商" width="84" align="center" header-align="center" sortable show-overflow-tooltip />
        <el-table-column prop="weight" label="权重值" width="78" align="center" header-align="center" sortable>
          <template #default="{ row }">{{ row.weight ?? '-' }}</template>
        </el-table-column>
        <el-table-column prop="remaining_amount" label="剩余金额" width="92" align="center" header-align="center" sortable>
          <template #default="{ row }">{{ Number.isFinite(row.remaining_amount) ? row.remaining_amount.toFixed(3) : '-' }}</template>
        </el-table-column>
        <el-table-column prop="remaining_image_count" label="可生成" width="80" align="center" header-align="center" sortable>
          <template #default="{ row }">{{ Number.isInteger(row.remaining_image_count) ? row.remaining_image_count : '-' }}</template>
        </el-table-column>
        <el-table-column prop="success_rate" label="成功率" width="82" align="center" header-align="center" sortable>
          <template #default="{ row }">{{ row.success_rate }}%</template>
        </el-table-column>
        <el-table-column prop="total_count" label="次数" width="66" align="center" header-align="center" sortable />
        <el-table-column prop="success_count" label="成功" width="66" align="center" header-align="center" sortable />
        <el-table-column prop="error_count" label="失败" width="66" align="center" header-align="center" sortable />
        <el-table-column prop="last_generated_at" label="最近生图时间" width="158" align="center" header-align="center" sortable>
          <template #default="{ row }">{{ formatTime(row.last_generated_at) }}</template>
        </el-table-column>
        <el-table-column label="验证结果" width="190" align="center" header-align="center" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="validate-result-cell">
              <el-tag v-if="row.validating" type="warning" size="small">验证中</el-tag>
              <template v-else-if="row.validate_result">
                <el-tag :type="statusType(row.validate_result.status)" size="small">
                  {{ statusText(row.validate_result.status) }}
                </el-tag>
                <span class="validate-result-text">{{ imageValidateSummary(row.validate_result) }}</span>
                <el-button
                  v-if="row.validate_result.status === 'error'"
                  link
                  type="danger"
                  size="small"
                  @click="showImageValidateDetail(row)"
                >详情</el-button>
              </template>
              <span v-else class="validate-result-empty">未验证</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="104" align="center" header-align="center" fixed="right">
          <template #default="{ row }">
            <el-button
              link
              type="primary"
              :loading="row.validating"
              :disabled="!selectedKeyModel || !canValidateImageModel(selectedKeyModel.model)"
              @click="validateImageKey(row)"
            >生图验证</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="imageValidateDetailVisible" title="生图验证详情" width="720px">
      <div v-if="selectedImageValidateResult" class="validate-detail">
        <div class="detail-summary validate-detail-summary">
          <div><span>Key：</span>{{ selectedImageValidateResult.api_key_name || '-' }}</div>
          <div><span>模型：</span>{{ selectedImageValidateResult.model || '-' }}</div>
          <div><span>状态：</span>{{ statusText(selectedImageValidateResult.status) }}</div>
          <div><span>耗时：</span>{{ selectedImageValidateResult.response_time_ms || 0 }}ms</div>
          <div><span>格式：</span>{{ formatLabel(selectedImageValidateResult.request_format) }}</div>
          <div><span>路径：</span>{{ selectedImageValidateResult.path || '-' }}</div>
          <div><span>状态码：</span>{{ selectedImageValidateResult.status_code || '-' }}</div>
          <div><span>图片数：</span>{{ selectedImageValidateResult.image_count || 0 }}</div>
        </div>
        <el-alert
          v-if="selectedImageValidateResult.status === 'error'"
          :title="selectedImageValidateResult.failure_category || '验证失败'"
          :description="selectedImageValidateResult.error_message || '未返回具体错误信息'"
          type="error"
          show-icon
          :closable="false"
        />
        <div v-if="imageSrc(selectedImageValidateResult)" class="validate-preview">
          <el-image
              class="validate-preview-image"
              :src="imageSrc(selectedImageValidateResult)"
              fit="cover"
              :preview-src-list="[imageSrc(selectedImageValidateResult)]"
              :preview-teleported="true"
              :zoom-rate="1.2"
              :min-scale="0.2"
              :max-scale="7"
            />
          <div>{{ imageSizeText(selectedImageValidateResult) }}</div>
        </div>
      </div>
    </el-dialog>

    <el-dialog v-model="promptExampleVisible" :title="selectedPromptExample?.title || '提示词样例'" width="680px">
      <div v-if="selectedPromptExample" class="prompt-example-dialog">
        <div class="prompt-example-meta">
          <el-tag type="primary" size="small">{{ selectedPromptExample.type }}</el-tag>
          <el-tag v-if="selectedPromptExample.mode === 'image_to_image'" type="warning" size="small">图生图</el-tag>
          <span>{{ selectedPromptExample.desc }}</span>
        </div>
        <div v-if="selectedPromptExample.mode === 'image_to_image'" class="prompt-example-i2i-hint">
          此示例需要上传参考图，插入后将自动切换到图生图模式。
        </div>
        <div class="prompt-example-content">{{ selectedPromptExample.prompt }}</div>
        <div class="prompt-example-actions">
          <el-button @click="copyToClipboard(selectedPromptExample.prompt)">复制样例</el-button>
          <el-button type="primary" @click="insertPromptExample">插入到提示词</el-button>
        </div>
      </div>
    </el-dialog>

    <el-dialog v-model="storageDialogVisible" title="图片存储位置" width="680px">
      <div class="storage-dialog">
        <el-alert title="存储位置只影响后续新生成图片，不会迁移历史图片文件。" type="info" show-icon :closable="false" />
        <el-form label-position="top">
          <el-form-item label="当前存储目录">
            <el-input v-model="storageForm.storage_dir" placeholder="请输入图片存储目录" />
          </el-form-item>
          <div class="storage-default-path">默认目录：{{ storageForm.default_storage_dir || '-' }}</div>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="storageDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingStorage" @click="saveStorageConfig">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="imageKeyDetailDialogVisible"
      title="Key 详情"
      width="1040px"
      @closed="handleImageKeyDetailDialogClosed"
    >
      <div v-loading="imageKeyDetailLoading" class="key-detail-dialog">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="Key ID">{{ imageKeyDetail.id || '-' }}</el-descriptions-item>
          <el-descriptions-item label="名称">
            <span>{{ imageKeyDetail.name || '-' }}</span>
            <el-button
              v-if="imageKeyDetail.password"
              link
              size="small"
              style="margin-left: 6px; padding: 0"
              title="复制登录密码"
              @click="copyKeyPassword(imageKeyDetail.password)"
            ><el-icon><View /></el-icon></el-button>
          </el-descriptions-item>
          <el-descriptions-item label="提供商">{{ imageKeyDetail.provider || '-' }}</el-descriptions-item>
          <el-descriptions-item label="启用状态">
            <el-button
              :type="imageKeyDetail.is_active ? 'success' : 'danger'"
              size="small"
              :loading="imageKeyDetailToggling"
              @click="toggleImageKeyDetailActive"
            >
              {{ imageKeyDetail.is_active ? '已启用' : '已关闭' }}
            </el-button>
          </el-descriptions-item>
          <el-descriptions-item label="API Key">{{ imageKeyDetail.api_key_masked || '-' }}</el-descriptions-item>
          <el-descriptions-item label="请求地址">
            <a v-if="imageKeyDetail.base_url" :href="imageKeyDetail.base_url" target="_blank" rel="noopener noreferrer" style="color:var(--el-color-primary);word-break:break-all;">{{ imageKeyDetail.base_url }}</a>
            <span v-else>-</span>
          </el-descriptions-item>
          <el-descriptions-item label="独立 fake IP">
            <el-tag :type="imageKeyDetail.enable_fake_ip ? 'success' : 'info'" size="small">
              {{ imageKeyDetail.enable_fake_ip ? '已启用' : '未启用' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="fake IP">{{ imageKeyDetail.fake_ip || '-' }}</el-descriptions-item>
          <el-descriptions-item label="生图总次数">{{ formatNumber(imageKeyDetailImageStats.total_count || 0) }}</el-descriptions-item>
          <el-descriptions-item label="生图成功率">{{ imageKeySuccessRate }}%</el-descriptions-item>
          <el-descriptions-item label="成功次数">{{ formatNumber(imageKeyDetailImageStats.success_count || 0) }}</el-descriptions-item>
          <el-descriptions-item label="失败次数">{{ formatNumber(imageKeyDetailImageStats.error_count || 0) }}</el-descriptions-item>
          <el-descriptions-item label="当前余额">
            <span v-if="imageKeyDetailBalanceLoading" style="color: #909399; font-size: 13px">查询中...</span>
            <span v-else-if="imageKeyDetailBalance">
              <span style="color: #10b981; font-weight: 600">${{ imageKeyDetailBalance.balance_usd.toFixed(4) }}</span>
              <span style="color: #909399; font-size: 12px; margin-left: 8px">已用 ${{ imageKeyDetailBalance.used_usd.toFixed(4) }}</span>
            </span>
            <span v-else style="color: #909399; font-size: 13px">-</span>
          </el-descriptions-item>
          <el-descriptions-item label="生图记录数">{{ formatNumber(imageKeyDetailTasksTotal) }}</el-descriptions-item>
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

          <el-table :data="imageKeyDetailTasks" stripe border size="small" v-loading="imageKeyDetailTasksLoading" max-height="360">
            <el-table-column prop="id" label="任务" width="72">
              <template #default="{ row }">#{{ row.id }}</template>
            </el-table-column>
            <el-table-column prop="model" label="模型" min-width="210" show-overflow-tooltip />
            <el-table-column label="模式" width="110">
              <template #default="{ row }">
                <div class="mode-cell">
                  <el-tag :type="taskMode(row) === 'image_to_image' ? 'warning' : 'info'" size="small">
                    {{ taskModeLabel(row) }}
                  </el-tag>
                  <span v-if="taskInputImageCount(row)">参考图 {{ taskInputImageCount(row) }} 张</span>
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
            <el-table-column label="操作" width="76" fixed="right" align="center">
              <template #default="{ row }">
                <el-button link type="primary" @click="openTask(row.id)">查看</el-button>
              </template>
            </el-table-column>
          </el-table>

          <div class="pagination key-detail-pagination">
            <el-pagination
              v-model:current-page="imageKeyDetailTasksPage"
              v-model:page-size="imageKeyDetailTasksPageSize"
              :page-sizes="[10, 20, 50]"
              :total="imageKeyDetailTasksTotal"
              layout="total, sizes, prev, pager, next"
              @current-change="handleImageKeyDetailTasksPageChange"
              @size-change="handleImageKeyDetailTasksPageSizeChange"
            />
          </div>
        </el-card>
      </div>
      <template #footer>
        <el-button @click="imageKeyDetailDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailVisible" title="图片任务详情" width="860px">
      <div v-if="detailTask" class="detail-body">
        <div class="detail-summary">
          <div><span>任务：</span>#{{ detailTask.id }}</div>
          <div><span>模型：</span>{{ detailTask.model }}</div>
          <div><span>Key：</span>{{ detailTask.api_key_name || '-' }}</div>
          <div><span>状态：</span>{{ statusText(detailTask.status) }}</div>
          <div><span>用时：</span>{{ formatDuration(detailTask.duration_ms) }}</div>
          <div><span>创建：</span>{{ formatTime(detailTask.created_at) }}</div>
          <div><span>模式：</span>{{ taskModeLabel(detailTask) }}</div>
          <div><span>参考图：</span>{{ taskInputImageCount(detailTask) }} 张</div>
        </div>
        <div class="detail-prompt">{{ detailTask.prompt }}</div>
        <el-alert
          v-if="detailTask.status === 'running' && detailTask.pending_refresh"
          title="任务已进入后台自动回填，页面会自动刷新结果。"
          type="info"
          show-icon
          :closable="false"
        >
          <template #default>
            <div class="error-actions">
              <el-button link type="primary" @click="openTaskUpstreamRefresh(detailTask)">ID取图</el-button>
            </div>
          </template>
        </el-alert>
        <el-alert
          v-if="detailTask.status === 'running' && !detailTask.pending_refresh"
          title="上游仍在生成，可稍后用 ID取图回填结果。"
          type="info"
          show-icon
          :closable="false"
        >
          <template #default>
            <div class="error-actions">
              <el-button link type="primary" @click="openTaskUpstreamRefresh(detailTask)">ID取图</el-button>
            </div>
          </template>
        </el-alert>
        <el-alert
          v-if="detailTask.error_summary"
          :title="detailTask.error_summary"
          type="error"
          show-icon
          :closable="false"
        >
          <template #default>
            <div class="error-actions">
              <el-button link type="primary" @click="openTaskUpstreamRefresh(detailTask)">ID取图</el-button>
            </div>
          </template>
        </el-alert>
        <div class="image-grid detail-images">
          <div v-for="item in detailTask.results" :key="item.id" class="image-card">
            <div v-if="imageSrc(item) && isImageToImageTask(detailTask) && getFirstInputImageUrl(detailTask)" class="image-pair">
              <el-image
                class="image-pair-input"
                :src="getFirstInputImageUrl(detailTask)"
                fit="cover"
                :preview-src-list="[getFirstInputImageUrl(detailTask)]"
                :preview-teleported="true"
              />
              <span class="image-pair-arrow">-&gt;</span>
              <el-image
                class="image-pair-output"
                :src="imageSrc(item)"
                fit="cover"
                :preview-src-list="detailPreviewImages"
                :preview-teleported="true"
                :zoom-rate="1.2"
                :min-scale="0.2"
                :max-scale="7"
              />
            </div>
            <el-image
                v-else-if="imageSrc(item)"
                class="image-preview"
                :src="imageSrc(item)"
                fit="cover"
                :preview-src-list="detailPreviewImages"
                :preview-teleported="true"
                :zoom-rate="1.2"
                :min-scale="0.2"
                :max-scale="7"
              />
            <div v-else class="error-box">{{ item.error_detail || '无图片结果' }}</div>
            <div class="detail-image-info">
              <div class="image-card-footer">
                <div class="image-card-info">
                  <span>#{{ item.image_index }}</span>
                  <el-tag :type="statusType(item.status)" size="small">{{ statusText(item.status) }}</el-tag>
                </div>
                <div class="image-actions" v-if="item.status === 'success'">
                  <el-button size="small" link type="primary" :loading="isSavingResult(item.id)" @click="downloadImage(item)">下载</el-button>
                  <el-button v-if="imageEnhancementEnabled" size="small" link type="primary" :loading="isSavingResult(item.id)" @click="downloadPsd(item)">PSD</el-button>
                </div>
              </div>
              <div class="file-meta-list">
                <div><span>尺寸：</span>{{ imageSizeText(item) }}</div>
                <div><span>大小：</span>{{ item.file_size_bytes ? formatFileSize(item.file_size_bytes) : '-' }}</div>
                <div><span>用时：</span>{{ formatDuration(item.duration_ms) }}</div>
                <div class="local-path" :title="item.local_path || ''"><span>本地：</span>{{ item.local_path || '未保存到本地' }}</div>
              </div>
              <div v-if="item.local_path" class="local-file-actions">
                <el-button size="small" @click="openResultFolder(item)">打开文件夹</el-button>
                <el-button size="small" type="primary" @click="revealResultFile(item)">定位文件</el-button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </el-dialog>
    <el-dialog v-model="upstreamRefreshVisible" title="ID取图" width="520px">
      <div class="upstream-refresh-body">
        <el-alert
          title="只查询上游已有任务结果，不会重新发起生图，也不会再次扣费。"
          type="info"
          show-icon
          :closable="false"
        />
        <el-form label-width="96px" class="upstream-refresh-form">
          <el-form-item label="CPA任务">
            <span>#{{ upstreamRefreshForm.taskId || '-' }}</span>
          </el-form-item>
          <el-form-item label="上游任务ID">
            <el-input
              v-model="upstreamRefreshForm.upstreamTaskId"
              placeholder="留空则按提示词和时间自动匹配"
              clearable
              @keyup.enter="submitUpstreamRefresh"
            />
            <div class="form-tip">填写后按任务 ID 精确查询；留空则自动按提示词和时间近似匹配。</div>
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="upstreamRefreshVisible = false">取消</el-button>
        <el-button type="primary" :loading="upstreamRefreshing" @click="submitUpstreamRefresh">查询并回填</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="pollingDialogVisible" title="轮询信息" width="680px" class="polling-dialog">
      <div class="polling-dialog-body">
        <el-alert
          :title="`正在轮询 ${pendingRefreshTaskIds.size} 个任务，每 ${autoRefreshIntervalSec} 秒检查一次回填状态`"
          type="info"
          show-icon
          :closable="false"
          style="margin-bottom: 12px"
        />
        <el-table :data="pollingTaskRows" size="small" stripe max-height="360">
          <el-table-column prop="id" label="任务" width="72">
            <template #default="{ row }">#{{ row.id }}</template>
          </el-table-column>
          <el-table-column prop="prompt" label="提示词" min-width="200" show-overflow-tooltip />
          <el-table-column prop="attempts" label="已轮询" width="80" align="center">
            <template #default="{ row }">{{ row.attempts }} 次</template>
          </el-table-column>
          <el-table-column label="已耗时" width="90" align="center">
            <template #default="{ row }">{{ formatElapsed(row.elapsed) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="90" align="center">
            <template #default="{ row }">
              <el-button type="danger" link size="small" @click="stopSinglePendingRefresh(row.id)">停止</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <template #footer>
        <el-button @click="pollingDialogVisible = false">关闭</el-button>
        <el-button type="danger" :disabled="!pendingRefreshTaskIds.size" @click="stopAllPendingRefresh">全部停止</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { View } from '@element-plus/icons-vue'
import { adminApi, authApi, copyText } from '../api'

const imageModels = ref([])
const keyStats = ref([])
const modelKeyRows = ref([])
const modelKeyFilters = reactive({
  names: '',
  weights: '',
  generatedDates: [],
})
const tasks = ref([])
const currentTask = ref(null)
const detailTask = ref(null)
const detailVisible = ref(false)
const storageDialogVisible = ref(false)
const savingStorage = ref(false)
const storageForm = reactive({
  storage_dir: '',
  default_storage_dir: '',
})
const modelKeyDialogVisible = ref(false)
const selectedKeyModel = ref(null)
const imageValidateDetailVisible = ref(false)
const selectedImageValidateResult = ref(null)
const promptExampleVisible = ref(false)
const selectedPromptExample = ref(null)
const imageKeyDetailDialogVisible = ref(false)
const imageKeyDetailLoading = ref(false)
const imageKeyDetail = ref({})
const imageKeyDetailImageStats = ref({})
const imageKeyDetailTasks = ref([])
const imageKeyDetailTasksLoading = ref(false)
const imageKeyDetailTasksPage = ref(1)
const imageKeyDetailTasksPageSize = ref(10)
const imageKeyDetailTasksTotal = ref(0)
const imageKeyDetailBalance = ref(null)
const imageKeyDetailBalanceLoading = ref(false)
const imageKeyDetailToggling = ref(false)
const loadingModels = ref(false)
const loadingStats = ref(false)
const loadingModelKeys = ref(false)
const loadingTasks = ref(false)
const deletingHistoryTasks = ref(false)
const selectedHistoryTasks = ref([])
const generating = ref(false)
const taskPage = ref(1)
const taskPageSize = ref(20)
const taskTotal = ref(0)
const userIdFilter = ref(null)
const userOptions = ref([])
const showUserFilter = computed(() => authApi.isAdmin() && authApi.isLoggedIn())
const generationCount = ref(0)
const historyRefreshTimer = ref(null)
const taskPollingTimer = ref(null)
const pendingRefreshCheckTimer = ref(null)
const autoRefreshIntervalMs = ref(30000)
const historyRefreshIntervalMs = ref(5000)
const autoRefreshIntervalSec = computed(() => Math.round(autoRefreshIntervalMs.value / 1000))
const pendingRefreshTaskIds = ref(new Set())
const pollingMeta = ref(new Map())
const pollingDialogVisible = ref(false)
const savingResultIds = ref(new Set())
const refreshingTaskIds = ref(new Set())
const upstreamRefreshVisible = ref(false)
const upstreamRefreshing = ref(false)
const upstreamRefreshForm = reactive({
  taskId: null,
  upstreamTaskId: '',
})
const activePanels = ref(['history'])
const promptTipPanels = ref([])
const inputImageFileRef = ref(null)
const isEditMode = ref(false)
const inputImageAllowedTypes = ['image/png', 'image/jpeg', 'image/webp']
const imageValidateModels = new Set(['gpt-image-2', 'gpt-image-2-pro', 'gpt-image-1', 'nano-banana-pro', 'nano-banana-pro-4k'])
const maxInputImageCount = 4
const imageEnhancementEnabled = ref(false)

const parseCommaValues = (value) => String(value || '')
  .split(/[，,]/)
  .map((item) => item.trim())
  .filter(Boolean)

const toDateOnlyTime = (value, endOfDay = false) => {
  if (!value) return null
  const normalizedValue = typeof value === 'string' ? value.replace(/-/g, '/') : value
  const date = new Date(normalizedValue)
  if (Number.isNaN(date.getTime())) return null
  date.setHours(endOfDay ? 23 : 0, endOfDay ? 59 : 0, endOfDay ? 59 : 0, endOfDay ? 999 : 0)
  return date.getTime()
}

const filteredModelKeyRows = computed(() => {
  const names = parseCommaValues(modelKeyFilters.names).map((item) => item.toLowerCase())
  const weights = parseCommaValues(modelKeyFilters.weights)
    .map((item) => Number(item))
    .filter((item) => Number.isFinite(item))
  const [startDate, endDate] = Array.isArray(modelKeyFilters.generatedDates) ? modelKeyFilters.generatedDates : []
  const startTime = toDateOnlyTime(startDate)
  const endTime = toDateOnlyTime(endDate, true)

  return modelKeyRows.value.filter((row) => {
    if (names.length) {
      const keyName = String(row.api_key_name || '').toLowerCase()
      if (!names.some((name) => keyName.includes(name))) return false
    }

    if (weights.length) {
      const weight = Number(row.weight)
      if (!weights.includes(weight)) return false
    }

    if (startTime !== null && endTime !== null) {
      const generatedTime = new Date(String(row.last_generated_at || '').replace(/-/g, '/')).getTime()
      if (!Number.isFinite(generatedTime) || generatedTime < startTime || generatedTime > endTime) return false
    }

    return true
  })
})

const resetModelKeyFilters = () => {
  modelKeyFilters.names = ''
  modelKeyFilters.weights = ''
  modelKeyFilters.generatedDates = []
}

const imageModeOptions = [
  { value: 'text_to_image', label: '文生图' },
  { value: 'image_to_image', label: '图生图' },
]

const form = reactive({
  model: '',
  prompt: '',
  size: 'auto',
  quality: 'high',
  count: 1,
  request_format: 'images',
  mode: 'text_to_image',
  input_images: [],
})

const sizeOptionGroups = [
  {
    label: '基础兼容',
    options: [
      { value: 'auto', label: 'auto · 自动', scene: '自动匹配' },
      { value: '1024x1024', label: '1024x1024 · 方图', scene: '通用方图' },
      { value: '1024x1536', label: '1024x1536 · 竖图', scene: '海报竖版' },
      { value: '1536x1024', label: '1536x1024 · 横图', scene: '横版封面' },
    ],
  },
  {
    label: '手机常用',
    options: [
      { value: '1080x1920', label: '1080x1920 · 手机竖屏', scene: '壁纸 / 海报' },
      { value: '1170x2532', label: '1170x2532 · iPhone 竖屏', scene: '高清壁纸' },
      { value: '1290x2796', label: '1290x2796 · 大屏手机', scene: '超清壁纸' },
      { value: '1920x1080', label: '1920x1080 · 手机横屏', scene: '横屏封面' },
    ],
  },
  {
    label: '平板常用',
    options: [
      { value: '1536x2048', label: '1536x2048 · 平板竖屏', scene: '阅读 / 插画' },
      { value: '1668x2388', label: '1668x2388 · 平板竖屏高清', scene: '展示图' },
      { value: '2048x1536', label: '2048x1536 · 平板横屏', scene: '横版展示' },
      { value: '2388x1668', label: '2388x1668 · 平板横屏高清', scene: '宽屏背景' },
    ],
  },
  {
    label: '社媒与桌面',
    options: [
      { value: '1080x1080', label: '1080x1080 · 社媒方图', scene: '头像 / 封面' },
      { value: '1080x1350', label: '1080x1350 · 竖版信息流', scene: '小红书 / 电商' },
      { value: '1200x628', label: '1200x628 · 横版分享图', scene: '链接卡片' },
    ],
  },
  {
    label: '桌面高清',
    options: [
      { value: '2560x1440', label: '2560x1440 · 2K横屏', scene: '2K桌面壁纸' },
      { value: '1440x2560', label: '1440x2560 · 2K竖屏', scene: '2K竖版壁纸' },
      { value: '3840x2160', label: '3840x2160 · 4K横屏', scene: '4K桌面壁纸' },
      { value: '2160x3840', label: '2160x3840 · 4K竖屏', scene: '4K竖版壁纸' },
    ],
  },
]

const promptStructureLinks = [
  {
    title: '主体',
    type: '提示词结构',
    desc: '适合补全画面主体的材质、颜色、姿态和关键特征，让模型更稳定地理解画面中心。',
    prompt: '主体清晰，补充主体的材质、颜色、姿态和关键特征，保持画面中心明确，背景不喧宾夺主',
  },
  {
    title: '场景',
    type: '提示词结构',
    desc: '适合确定画面发生的环境、时间、天气、空间关系和整体氛围。',
    prompt: '说明场景、时间、天气、环境氛围和主体与背景的关系，让画面自然统一',
  },
  {
    title: '镜头构图',
    type: '提示词结构',
    desc: '适合控制景别、视角、构图、镜头语言和画面组织方式。',
    prompt: '指定构图、镜头、景别和视角，让主体位置、画面层次和视觉重点更清晰',
  },
  {
    title: '风格',
    type: '提示词结构',
    desc: '适合指定摄影、插画、3D、极简、科技感等整体视觉风格。',
    prompt: '明确画面风格，例如真实摄影、3D 渲染、扁平插画、蓝色科技风或极简高级感',
  },
  {
    title: '光线',
    type: '提示词结构',
    desc: '适合控制自然光、棚拍光、轮廓光、氛围光和明暗关系。',
    prompt: '指定光线类型、方向、强弱和明暗层次，例如柔和棚拍光、自然晨光、蓝色轮廓光',
  },
]

const promptTipGroups = [
  {
    type: '示例',
    examples: [
      {
        title: '直播UI样机',
        desc: '适合直播平台界面原型、带货直播场景，突出主播、弹幕、礼物、商品卡片等完整UI元素。',
        prompt: '直播UI样机截图，画面中央Elon Musk微笑肖像，黑色技术图T恤。左侧背景屏幕"SPACEX"，右侧红色Tesla T标志和深色汽车。顶部状态栏：头像"Elon Musk"、"55.6万本场点赞"、红色关注按钮、金币"全站第1名"、观众"68.7万"。中部左侧两条礼物通知："科技爱好者 送小心心 x1314"、"星辰大海 送火箭 x666"。左下聊天区7条中文弹幕讨论SpaceX和AI。右下商品卡片：橙色"热卖x1888"标签、特斯拉Cybertruck图片、"¥1,618,000"、红色"抢"按钮。底部输入栏"说点什么..."。移动端APP界面，中文，高清晰度',
      },
      {
        title: '智能手表海报',
        desc: '适合科技产品主图，强调蓝系科技背景、棚拍质感和干净构图。',
        prompt: '一只哑光黑色智能手表，悬浮在浅蓝科技背景中，柔和棚拍光，产品海报构图，无文字无水印',
      },
      {
        title: '香水高级静物',
        desc: '适合美妆、香氛类商品，突出玻璃、反射和高级极简氛围。',
        prompt: '透明玻璃香水瓶放在水面反射上，清晨自然光，极简高级感，浅景深，干净背景',
      },
      {
        title: '科技感女性头像',
        desc: '适合个人主页、宣传图头像，突出真实摄影与蓝色科技背景。',
        prompt: '年轻女性半身肖像，蓝色科技感背景，柔和轮廓光，真实摄影风格，85mm 镜头，表情自然',
      },
      {
        title: '商务男性头像',
        desc: '适合职业头像，强调正面视角、干净轮廓光和真实质感。',
        prompt: '商务男性头像，深蓝渐变背景，正面视角，干净轮廓光，真实质感，适合个人主页',
      },
      {
        title: '竖屏星云壁纸',
        desc: '适合手机竖屏壁纸，强调中心留白、高对比和蓝色宇宙氛围。',
        prompt: '竖版手机壁纸，深蓝渐变宇宙星云，中心留白，细腻粒子光效，高对比，无文字',
      },
      {
        title: '玻璃拟态壁纸',
        desc: '适合极简科技壁纸，突出蓝色玻璃曲线和底部留白。',
        prompt: '竖屏极简科技壁纸，蓝色玻璃拟态曲线，柔和光晕，底部留白，高清细节',
      },
      {
        title: '未来城市横幅',
        desc: '适合平板横屏、发布会背景和科技展示封面。',
        prompt: '横版平板展示图，未来城市天际线，蓝色霓虹光，宽屏构图，干净留白，科技发布会背景',
      },
      {
        title: '雪山湖面壁纸',
        desc: '适合平板横屏壁纸，强调宁静、低饱和和高级自然感。',
        prompt: '平板横屏壁纸，湖面与雪山晨光，低饱和蓝灰色调，广角构图，宁静高级感',
      },
      {
        title: '现代办公大厅',
        desc: '适合建筑摄影和办公空间展示，强调玻璃、灯带和反射。',
        prompt: '现代办公大厅，玻璃幕墙与蓝色灯带，超现实建筑摄影，广角镜头，干净地面反射',
      },
      {
        title: '未来科技展厅',
        desc: '适合展厅、展会、空间背景，突出曲面墙体和蓝色交互屏。',
        prompt: '未来科技展厅，白色曲面墙体，蓝色交互屏，柔和环境光，无人场景，空间纵深明显',
      },
      {
        title: 'API 网关 3D 图标',
        desc: '适合系统功能入口、产品能力图标，保持蓝色科技风。',
        prompt: '蓝色科技风 3D 图标，一个云端 API 网关，透明玻璃材质，等距视角，干净背景',
      },
      {
        title: '机器人连接 API',
        desc: '适合说明 AI 助手与 API 节点连接的扁平插画。',
        prompt: '扁平矢量插画，机器人助手正在连接多个 API 节点，蓝白配色，线条清晰，无文字',
      },
      {
        title: 'Apple风格工程设计草图',
        desc: '适合产品设计手稿、技术方案展示，类似苹果/特斯拉产品设计手稿的现代感。',
        prompt: '简洁专业的现代工程产品设计草图，纯白色背景大量留白，工程图纸线条风格细腻精确，手写体标题深灰色，工程标注方式展示步骤，淡蓝色、淡绿色、淡橙色水彩点缀高透明度，类似苹果特斯拉产品设计手稿的现代感，简洁图标配合步骤说明，清爽专业科技感',
      },
      {
        title: '恐龙解剖剖面科普海报',
        desc: '适合科学出版、教育百科，复古自然历史风格的解剖剖面图，含编号标注和侧边知识卡片。',
        prompt: '出版级教育科学百科剖面海报，简体中文标签与说明。主标题"霸王龙剖面图解"，副标题"地球上最强大的掠食者之一"。霸王龙大型咆哮侧面姿态从左向右行走，张开大嘴尾巴伸展保持平衡。高度精细半写实科学插画，复古自然历史百科全书风格，水彩水粉质感清晰墨线勾勒，温暖羊皮纸背景。左半部展示外部鳞片皮肤和头骨，右侧解剖处理露出骨骼红色肌肉肋骨肺部心脏肠道胃部肌腱及横截面腿部肌肉层。橄榄棕色赭石色鳞片带深色条纹，象牙色骨骼，深红粉色肌肉，蓝紫色肺部，亮红色心脏，橙棕色消化器官。纵向海报布局恐龙居中，编号标注箭头围绕辐射，圆角奶油色卡片内嵌小型图解。背景中生代森林针叶树蕨类植物岩石溪流朦胧山脉远方火山小型翼龙温暖阳光。左上角探险家儿童对话气泡"一起来探索霸王龙的身体秘密吧!"。右上角档案小知识卡片含名称生活年代白垩纪晚期约6800万年前发现地北美洲体长12-13米体重6-8吨。10个编号解剖标注：头骨牙齿颈部肌肉肺部含气囊心脏胃部肋骨胸腔肠道骨盆后肢肌肉。5张侧边信息卡：咬合力对比6-8吨、短小前肢功能、体型对比人类与霸王龙、尾巴平衡作用、趣味知识带羽毛幼年恐龙。顶部加粗深海军蓝中文标题红色丝带副标题，彩色编号圆圈纤细彩色引导线圆角奶油色注释卡片。解剖结构清晰分层准确，高分辨率可打印海报，无照片级写实无3D渲染无现代UI元素',
      },
      {
        title: '便利店收银员抓拍',
        desc: '适合写实人像、生活场景，模拟顾客视角的隐蔽抓拍风格。',
        prompt: '写实风格便利店收银员抓拍，一位美丽的年轻印尼女性，20出头，身穿典型7-Eleven制服（带绿红橙色装饰的白衬衫，名牌写着FELISHA，头发整齐扎在脑后）。她站在收银台后，面带友好自然的表情为顾客服务。柜台上放着POS机、条形码扫描仪以及糖果饮料等小商品。照片由顾客视角使用智能手机隐蔽拍摄，前景略有模糊，构图不完美，具有未经摆拍的自发感。光线来自明亮均匀的便利店霓虹灯。现代便利店内部，收银台后货架商品摆放整齐，干净明亮氛围。写实摄影、抓拍、浅景深、自然肤色、高细节、轻微运动模糊增加真实感、4K画质。略微倾斜角度，智能手机摄像头噪点效果，玻璃展示柜反光，收银员温柔微笑递出收据',
      },
      {
        title: '8格动作片分镜脚本',
        desc: '适合打斗场面规划、动作电影分镜，严格的8格分镜，好莱坞动作电影质感，画面中无文字。',
        prompt: '高质量4K电影级动作片分镜脚本，严格8个画面，展示女性主角在写实打斗场景中获胜。戏剧性光影高对比度阴影，写实废弃仓库环境，粗粝电影色调，画面无文字。8个场景：1暗色调高强度环境全景建立镜头，雨或灰尘低光氛围，两名格斗者面对面站立。2女性主角专注表情特写，呼吸平稳紧张感积聚。3对手率先发起攻击，动作具有侵略性拳击或踢腿。4她惊险躲避，动态动作快速反应摄像机追踪。5近身格斗交换，格挡反击带电影级慢动作冲击瞬间。6转折点，她看穿对手打出干净利落强力反击。7决定性击倒，对手重重倒地产生戏剧冲击效果，环境反应灰尘水花飞溅。8最终画面，她站姿稳健冷静虽有轻伤但占据主导地位，戏剧性光影下看向前方明确获胜。多样摄像机角度全景特写肩后镜头低角度，写实格斗编排运动模糊物理冲击细节。好莱坞动作电影基调，侧重紧张感写实感角色力量，非风格化非社交媒体审美',
      },
      {
        title: '三联画运动时尚拼贴',
        desc: '适合高端运动品牌广告、时尚杂志，三联画布局统一灯光和品牌元素。',
        prompt: '电影感运动时尚拼贴画，三联画布局。顶部面板大型主视觉图，女性网球运动员自信坐在巨大倾斜网球拍上，深绿色奢华球场背景，反光亮面地板，背景大号字体"PRECISION"，戏剧性编辑风格灯光，超简洁构图，高级运动时尚美学。左下面板运动员特写肖像，皮肤光泽极简妆容柔光，文字"FOCUS"和"FUEL"巧妙点缀。右下面板全身蹲姿持拍姿态有力，文字"DISCIPLINE DRIVES DOMINANCE"，基于网格布局线条，高端运动品牌质感。深绿色和白色色调统一，细节锐利，电影感阴影，奢华广告大片风格，1:1纵横比',
      },
      {
        title: '电影感忧伤特写肖像',
        desc: '适合情绪人像、艺术摄影，突出光影质感和神秘忧伤氛围的特写肖像。',
        prompt: '32K超高清夜景，长发飘逸部分遮住美丽忧伤面庞，微醺感，细腻自然表情，深色调背景，柔和发丝轮廓光，清晰面部细节，流畅优雅线条，特写肖像，杰作，高级审美，神秘氛围，脸颊泪痕，晶莹泪眼',
      },
      {
        title: '日式街头匿名抓拍',
        desc: '适合写实街头摄影、匿名风格人像，超真实手机拍摄质感的日本城市街拍。',
        prompt: '写实风格竖版手机街头抓拍，一位留着齐肩深棕色波浪卷发的成年女性，在阳光明媚的日本城市人行道上蹲伏在广角镜头前。低蹲姿势身体前倾，一手肘抵在膝盖上另一手向镜头伸出，手部和修长淡粉色光泽美甲在前景中格外突出。脸部被居中不透明棕粉色模糊方块完全遮盖呈现匿名效果。身穿紧身低胸白色短袖上衣、浅色水洗蓝牛仔裤、米色透明带方头凉鞋。正午强烈阳光，沥青路面上浓重阴影，逼真皮肤高光，随风飘动发丝，类似狗仔队抓拍构图，略微倾斜视角，超真实手机拍摄质感，浅景深透视畸变，高细节。背景日本城市街角，贴有瓷砖建筑立面、绿色遮阳棚、带有贴纸和手写日文标记垂直电线杆、蓝色行人路标、写有"かめや"餐厅招牌，更多细小日文标志和街头杂物增强真实感。近地面极低角度拍摄，紧凑裁剪，9:16竖屏比例，写实纪录片风格，拒绝插画或动漫感',
      },
      {
        title: '小红书微醺夜拍手写心情',
        desc: '适合治愈系、微醺感、深夜生活方式帖文，带手写中文心情标注的路边摊人像，文案感极强。',
        prompt: '一张具有小红书风格治愈系项目美学的温馨深夜路边摊照片。画面中是一位坐着的年轻女性，面部经过模糊处理，留着中长直黑发，身穿暖米色的深V领罗纹针织上衣和高腰蓝色牛仔裤。她侧身坐在红色塑料凳上，一只手拿着一小杯淡色啤酒靠近嘴边，神态放松且略带微醺，呈现出一种随性的夜生活抓拍感。场景是一个休闲的路边摊，灯光昏暗温暖：左下角的黄色桌面上摆放着2瓶绿色标签的啤酒、1个带有啤酒泡沫的塑料杯、1包彩色香烟和几张零碎的餐巾纸；她身后放置着1台旧式电风扇，放在1个白色家电包装箱上，身后挂着半透明的塑料帘，背景中可见2把红色塑料凳。右侧是一个小型摊位柜台，上面有货架、杯子和红色易拉罐，还有一个部分可见的照明招牌。在人物和物体周围添加手绘的白色涂鸦轮廓，并配以箭头、闪光、爱心、漩涡以及遍布画面的手写中文标注，如同情绪化的配文。包含10条中文标注："老式风扇呼呼转着～有种怀旧感♡"、"塑胶布帘隔开的小空间 反而更有安全感～"、"路边小摊 人间烟火气 最抚慰人心～"、"冰凉的啤酒 苦中带甘～ 越喝越放松！"、"小口慢慢喝～ 让自己 稍微放空一下♡"、"杯子里的泡泡 像小小的快乐 慢慢消失～"、"今晚有点微醺… 心情刚刚好 什么烦恼都 先放一边吧♡"、"舒服的穿搭 自在又放松～ 做自己最重要♡"、"高腰牛仔裤 修饰比例 也很有安全感！"，以及左下角附近一个云朵形状的大号文案，写着"生活偶尔需要 一点微醺的小确幸～ 今天也要好好爱自己♡"。采用写实的手机摄影质感，具有电影般的对比度，皮肤和头发上有光泽感，构图略显紧凑，营造出亲密的街头夜晚氛围，并呈现出柔和而清晰的编辑级画质。保持手写笔记为明亮的白色且清晰易读，自然地融入照片中',
      },
      {
        title: '学生制服抓拍肖像',
        desc: '适合日常生活、社交媒体风格摄影，穿着朴素学生制服的年轻女性写实抓拍肖像，隐私模糊处理。',
        prompt: '一张由智能手机拍摄的抓拍照片，主角是一位外表朴素、学生打扮的年轻日本女性，正坐在明媚春日或夏日的现代城市广场户外。画面采用略微俯视的竖构图近中景，上半身占据画面主体。她留着深棕色至黑色的直发，中分并扎成两个低马尾，脸颊和颈部周围有几缕散落的发丝。她的面部中心被一个简单的矩形隐私模糊块遮挡，但仍可见一只耳朵、下颌线、颈部和部分脸颊。她身穿一件挺括的白色短袖衬衫，领口系着整洁的深蓝色蝴蝶结，下身穿着深色百褶裙。佩戴1条带有微小吊坠的细银项链。左肩背着1个深蓝色或黑色皮革单肩包，包带较宽且带有明显的金属扣，包身垂在身侧。她的右手抬起靠近脸部，仿佛正在整理头发，左前臂随意地放在膝盖上。整体氛围自然、朴素，更偏向日常感而非华丽感。背景展示了一个整洁的城市办公区或购物中心，可见2盆绿色灌木、玻璃建筑外墙、浅色石材路面以及柔和的阳光阴影。采用写实摄影风格，光线柔和，对比度适中，肤色自然，具有浅景深效果，呈现出一种安静的社交媒体抓拍美感。服装配色应为白色衬衫、海军蓝蝴蝶结、海军蓝短裙、深色包袋，场景应呈现为玻璃建筑前的现代户外广场，摄影风格应为带有柔和自然光的休闲iPhone风格人像照片',
      },
      {
        title: '前后端与SaaS概念信息图',
        desc: '适合技术科普、编程入门教学，通过清晰的图解拆解前端、后端、数据库和SaaS概念，信息层次分明易懂。',
        prompt: '一张清晰易懂的技术概念信息图，风格为扁平化矢量插画，配色明快，适合编程入门教学。画面分为上下两层结构，上层为横向排列的4个核心模块，下层为总结区域。上层从左到右依次：模块01"前端"标注"用户看到的部分"，配一个浏览器窗口和手机屏幕的图标，下方小字说明"前端就是界面，是用户能看见、能点、能操作的部分"，列出用到的技术"HTML（结构）、CSS（样式）、JavaScript（交互）"，应用场景"网页、小程序、App的界面"。模块02"后端"标注"背后处理的部分"，配一个服务器机柜图标，下方小字说明"后端就是幕后大脑，负责逻辑和运算"，列出作用"处理登录注册、计算价格推荐商品、接收前端请求返回数据"，常用语言"Java、Python、Go、Node.js"。模块03"数据库"标注"记忆的部分"，配一个圆柱形数据库图标，下方小字说明"数据库就是用来存储和管理数据的"，列出存储内容"账号、密码、订单、库存"，常见类型"MySQL、PostgreSQL（关系型）、MongoDB（文档型）"。模块04"SaaS"标注"软件即服务"，配一个云朵和齿轮图标，下方小字说明"SaaS=Software as a Service"，核心特点"打开就能用、按月按年订阅、网站/App/小程序都可以是SaaS"。用箭头从左到右依次连接四个模块表示数据流。下层总结区域用一条流程线串联："前端展示→后端处理→数据库存储→SaaS是交付方式"，每一步配对应的小图标。整体画面干净、层次分明、文字清晰可读、色彩协调，适合初学者理解',
      },
      {
        title: '人物传记信息图',
        desc: '适合人物介绍、品牌故事、名人传记，将写实肖像与时间轴、图表、名言、注释相结合的深度传记信息图。',
        prompt: '请帮我制作一张关于{{人物姓名}}的信息图，视觉效果要非常丰富且有深度。不仅是罗列信息：需要深入挖掘他的生平、主要成就、职场关键节点、哲学思想，以及他对科技和设计的独特影响。不要用那种死板的一块一块的布局，要用图解、注释和引线标注把这些信息有机地结合在一起。画面风格：走那种大胆有力、图形感很强的插画路线。具体看起来是这样的：中心焦点是一张细节极其逼真、像照片一样的人物肖像。以此为核心，周围环绕着像时间轴、分析图表、经典产品、名言警句和短小精悍的文字。构图技巧：背景保持干净。运用分层构图，把逼真的人物肖像和强烈的图形元素（比如各种形状、图标、大色块）完美混搭在一起。整个画面要显得内容满满、有质感，看起来非常专业',
      },
      {
        title: '手绘城市美食旅行地图',
        desc: '适合城市旅行攻略、美食地图，手绘水彩风格的旅行地图信息图，含地标建筑、编号美食与图例，可替换城市名与内容复用。',
        prompt: '一张手绘水彩风格的旅行地图信息图。整体画风为复古羊皮纸上的水彩墨水手绘插画。顶部中央为主标题"{{城市名}} {{地图副标题，如：吃货暴走地图}}"，标题旁有一个吉祥物——{{吉祥物描述，如：戴着墨镜并竖起大拇指的卡通红辣椒}}。四周边框用{{边框装饰，如：绿叶与红辣椒藤蔓}}环绕装饰。背景为带有黄色道路、蓝色河流和绿色公园区域的纹理米色羊皮纸。画面分为三个区域：左侧为"地标建筑"区域，包含6幅手绘插画与标注——{{地标1插画}}标注{{地标1名称}}、{{地标2插画}}标注{{地标2名称}}、{{地标3插画}}标注{{地标3名称}}、{{地标4插画}}标注{{地标4名称}}、{{地标5插画}}标注{{地标5名称}}、{{地标6插画}}标注{{地标6名称}}。中部为"美食地点"区域，包含12幅编号的手绘美食插画与地点标注——1 {{美食1}}对应{{地点1}}、2 {{美食2}}对应{{地点2}}、3 {{美食3}}对应{{地点3}}、4 {{美食4}}对应{{地点4}}、5 {{美食5}}对应{{地点5}}、6 {{美食6}}对应{{地点6}}、7 {{美食7}}对应{{地点7}}、8 {{美食8}}对应{{地点8}}、9 {{美食9}}对应{{地点9}}、10 {{美食10}}对应{{地点10}}、11 {{美食11}}对应{{地点11}}、12 {{美食12}}对应{{地点12}}。右下角为"图例"区域，包含5个图例符号——红点代表美食地点、绿色建筑代表地标景点、绿树代表公园绿地、蓝线代表河流湖泊、黄色双线代表主要道路。画面正中央有一个{{中心吉祥物，如：坐着吃竹子的大熊猫}}。右下角附带一个带有东南西北方向的复古罗盘，以及一行免责声明小字"{{温馨提示文案，如：温馨提示：吃辣需谨慎，肠胃要保护~}}"。整体风格温馨可爱、信息丰富、色彩饱满，适合打印或社交媒体分享',
      },
      {
        title: '北京旅行水彩地图海报',
        desc: '适合旅行艺术品、城市指南、纪念品印刷，手绘水彩风格的北京地图海报，含地标、美食与文化街区，竖版3:4。',
        prompt: '创作一张详细的北京水彩插画海报，采用手工中国旅行写生风格，绘制在有纹理的奶油色纸张上。左上方使用大型黑色书法书写主标题"北京"，并配有一个刻有"京味儿"的小红印章。以简化的鸟瞰城市地图为背景，绘有淡色的道路、运河、公园和街区。在地图内外安排17个带标签的插图：10个地标或区域场景、5个美食插图和2个现代或生活方式街区。将故宫置于中心作为视觉焦点，天安门位于其下方。包含以下中文标签场景和菜肴：八达岭长城、北京烤鸭、颐和园、奥林匹克公园、老北京胡同、故宫、炸酱面、天坛、驴打滚、北京大学、豆汁儿、天安门广场、老北京涮羊肉、什刹海、国贸CBD、王府井大街。在每个标签旁添加简短的手写中文描述。展示青山上的长城、水边的颐和园、带鸟巢的奥林匹克公园、带自行车和黄包车的胡同四合院、天坛、北京大学校门、国贸天际线、王府井牌楼以及带小船的什刹海。美食插图展示烤鸭、炸酱面、驴打滚、豆汁儿套装和铜锅涮羊肉。画面保持轻盈迷人，运用柔和的水彩晕染、随性的墨线、柔和的绿蓝色调、宫廷红与赭石色，营造出怀旧的文化旅游海报感。左侧添加一段手写中文介绍"一座古都，三千多年建城史，八百多年建都史。胡同里听京腔，四合院品茶香，感受独属于北京的烟火气与文化底蕴。"，右下角添加一张撕边纸条，写有结束语"北京，传统与现代交融，历史与生活共存，欢迎你来，发现更多美好！"。竖版3:4比例',
      },
      {
        title: '建筑平面图转3D效果图',
        mode: 'image_to_image',
        desc: '适合房产销售手册，将2D黑白平面图转换为逼真3D等轴测效果图，需上传参考平面图。',
        prompt: '使用提供的平面图参考图像，将2D黑白建筑平面图转换为清晰逼真的3D等轴测房地产平面效果图，保留原始布局、房间尺寸和标签。添加逼真的墙壁厚度、浅色木地板、柔和中性墙面色彩、具有深度的门窗，以及与各房间功能相符的精美室内陈设。保留所有可见的房间标签。1F布局：厨房、4人餐桌椅、带沙发和咖啡桌的起居区、卫生间、带浴缸的浴室、洗面区及少量绿植。2F布局：3间卧室或工作间（单人床卧室、书桌椅房间、双人床主卧）、2个储物空间、带货架的步入式衣帽间。采用明亮的目录式呈现风格，背景简洁，略微抬高的斜顶视图，适合房产销售手册',
      },
      {
        title: '商品灵感女装设计',
        mode: 'image_to_image',
        desc: '适合电商服装设计，以参考商品为灵感生成配套女装造型，需上传商品参考图。',
        prompt: '以这件商品为灵感，设计一套清凉风格女装，整体搭配协调，突出商品特点，模特姿态自然，背景简洁干净，适合电商展示',
      },
      {
        title: 'Q版健身涂鸦头像',
        mode: 'image_to_image',
        desc: '适合社交媒体头像、健身打卡，以人物照片为基础生成Q版迷你形象涂鸦风格，需上传人物参考图。',
        prompt: '在保持原图完全不变的前提下进行编辑，包括人物、面部、身体、姿势、光影以及健身房背景。在画面周围添加多个可爱的小型Q版迷你形象，每个迷你角色拥有大头特征、生动面部表情，与原图发型和服装保持一致。描绘每个迷你形象进行不同的健身活动：一个举起双臂欢呼、一个穿着跑鞋跑步、一个用摇摇杯喝水、一个戴运动跑步眼镜、一个在她腿边攀爬。使用白色和粉色手绘涂鸦及手写笔记增强画面感，营造剪贴簿风格，包含箭头、星星、爱心、闪光和草图线条。添加可爱手写风格健身励志短语："lift strong"、"stronger every rep"、"no pain no gain"、"sweat now shine later"、"progress over perfection"、"train hard stay soft"。整体氛围充满趣味、活力和女性魅力',
      },
      {
        title: '照片涂鸦手绘叠加',
        mode: 'image_to_image',
        desc: '适合社交媒体分享，在照片上叠加趣味涂鸦和手写文字，需上传人物或场景参考图。',
        prompt: '分析上传的图像，保留原始主体、构图和光影，不改变主体身份或结构。添加趣味十足的手绘涂鸦，使其与图像中的主体产生直接互动。涂鸦应模仿、跟随或夸大图像中呈现的形状、姿势或动作，例如勾勒姿势、延伸肢体、添加运动线条，或创作出与主体互动的创意元素。确保涂鸦自然融入场景，仿佛是有意在照片上绘制的。采用草图式、不完美的手绘风格，线条有机、笔触略显不均匀，带有随性的插画感。在图像周围加入灵动的手写文字元素，文字与场景氛围相符，语气活泼自然。避免固定短语，根据每张独特图像生成具有情境感、创意且幽默的文字。保持构图平衡，涂鸦增强图像表现力但不喧宾夺主。整体美学风格趣味性、表现力强，适合社交媒体分享。高分辨率、清晰叠加效果，鲜活自然的色彩协调',
      },
      {
        title: '便利店35mm胶片人像',
        mode: 'image_to_image',
        desc: '适合写实人像、胶片风格，以人物照片生成便利店场景的Kodak Portra 800胶片质感肖像，需上传人物参考图。',
        prompt: '顶级胶片摄影大师以35mm Kodak Portra 800胶片拍摄的极致电影感肖像，配合强烈便利店荧光灯与户外色彩霓虹灯，真实胶片颗粒感，高对比度，微微色彩偏移，街头电影式剪辑风格。使用上传的参考图作为主要拍摄对象，面部特征、骨骼结构和自然肤质需100%匹配，不得改变种族或性别特征。细腻肌肤质地和微毛孔，自然水润妆容，脸颊柔和泛红，光泽自然粉色唇微微张开，深棕色长发散发散落在脸颊和脖子周围。身穿收腰紧身白色短袖衬衫，搭配黑色百褶裙，脚穿黑色亮面尖头细跟高跟鞋，深夜靠在24小时便利店玻璃门上，一手拿冰饮料另一手放身后，目光调皮又略带脆弱直视观众，柔和眼中充满静谧温柔微笑。店内明亮冷荧光灯与外面招牌粉蓝色霓虹灯交织，强烈灯光和霓虹点缀，玻璃门真实倒影，模糊便利店内部背景有货架和零食。Kodak Portra 800特有温暖肤色与冷光对比，自然高光溢出与柔美过渡，35mm胶片轻微晕光颗粒与电影级质感，电影感构图，超高细节，8K极致真实质感。柔和皮肤渲染，自然发丝，真实布料褶皱垂坠感，无塑料皮肤，无数字过度锐化，无油腻皮肤，地道深夜便利店氛围',
      },
      {
        title: '剪贴簿Q版涂鸦构图',
        mode: 'image_to_image',
        desc: '适合社交媒体、纪念照片，将参考照片转换为温暖剪贴簿风格，添加Q版角色微缩形象和手绘涂鸦，需上传人物参考图。',
        prompt: '以8K电影级画质将参考图像转换为温馨剪贴簿风格构图，严格保留主体、身份、姿势、光影和背景。添加多个相同的Q版玩偶角色微缩版本，匹配面部发型服装，自然放置在画面中并进行各种活动。叠加手绘涂鸦，包含爱心、箭头、星星、标题。使用柔和粉彩色调。保持画面丰富且整洁、温暖、梦幻，呈现Instagram风格。最终成品必须在同一图像基础上进行增强，而非重新创作',
      },
      {
        title: '篮球场35mm直闪偶像',
        mode: 'image_to_image',
        desc: '适合偶像人像、运动时尚，以人物照片生成35mm胶片直闪美学的篮球场黄昏写真，需上传人物参考图。',
        prompt: '35mm彩色胶片摄影，强烈直射闪光灯，皮肤和服装高光，眼睛强烈捕捉光，高对比闪光灯光，真实胶片颗粒和色移，时尚纯真篮球场剪辑风格，第一人称低角度视角镜头。五官长相完全参考上传参考图角色，百分百匹配，20出头中国女偶像，超写实细腻中国五官，杏仁形狐狸眼配自然双眼皮，高鼻梁，小巧锐利V字形下颌线，完美逼真瓷白肌肤，细腻肌肤质地毛孔微细节，闪光灯下自然水润光泽，清新自然运动妆容配柔和水润光泽，脸颊淡淡自然红晕，微微张开自然粉唇，鼻子脸颊上细腻自然雀斑，深棕色长发与参考图发型一致。天色黄昏时分，身体侧向自然拱起背部，一条腿自然向镜头前伸另一条腿微弯，双手轻轻搭在肩高篮球杆上，直视观众，眼神柔和脆弱而渴望，微笑中带着温柔，闪光灯刺眼制造锐利镜面高光和强烈光线。背景模糊篮球场和篮筐，黄昏天空下，高对比度胶片调色，自然闪光效果，皮肤极为锐利且柔和，真实35mm直闪美学，自然发丝',
      },
      {
        title: '秋季城市街景插画',
        mode: 'image_to_image',
        desc: '适合场景转换、动漫背景，将城市人行道参考图重绘为精致秋季动漫风格街景，保留视角与布局，需上传街景参考图。',
        prompt: '使用提供的城市人行道参考图，将场景转换为精致的秋季城市街景插画。保持原有的视角、街道布局、树木位置、人行道透视、右侧道路以及左侧建筑群的结构，但将夏季的绿色植被替换为红、橙、金黄色的绚丽秋叶。将阴天效果改为明亮清澈的日间天空，并加入温暖的阳光和柔和的定向阴影。去除街景截图中的伪影，将整个场景重绘为精致且写实的动漫风格背景插画。保留繁华商业街的氛围，但将行人重绘为时尚的现代都市人，并使店面和车辆看起来更加优雅且协调',
      },
      {
        title: '纽约旅行九宫格',
        mode: 'image_to_image',
        desc: '适合旅行博主、朋友圈分享，基于正脸照片生成3x3纽约旅行日记九宫格，含地标建筑与手机抓拍随性风格，需上传清晰正脸照。',
        prompt: '请基于我上传的清晰正脸照片，生成一张"纽约旅行博主随手拍九宫格照片"。请严格保留照片中人物的真实身份特征，包括脸型、五官比例、眼睛、鼻子、嘴唇、下颌线、肤色、年龄感、发际线和整体气质。不要把人物变成欧美脸，不要过度美颜，不要改变成另一个人。最终九张图里的人物必须看起来是同一个人，只是在纽约旅行时被朋友或手机随手拍下。画面形式：生成一张3x3九宫格拼贴图，一共9张旅行照片。整体像朋友圈、小红书、Instagram旅行相册，不是精修大片。每一格都是不同场景、不同表情、不同姿势的手机照片。人物设定：一位来自中国一线城市的年轻旅行博主，气质自然、漂亮、松弛、爱笑，有生活方式博主和旅行博主的感觉。穿搭是适合纽约旅行的时尚休闲风，可以有白色背心、牛仔裤、针织衫、短外套、墨镜、斜挎包、球鞋等元素。整体审美偏中日韩流行风，不要过度性感，不要影楼感，不要网红脸。整体摄影风格：低清晰度iPhone随手拍感，轻微模糊，偶尔过曝，光线不完全稳定，有些照片构图随意，角度略歪，像朋友边走边拍、自拍、抓拍、旅行途中随手记录。不要太完美，不要像商业广告大片。照片要真实、有生活感、有旅行记忆感。九宫格内容如下：第一格左上：自由女神像附近的自拍照，人物拿手机自拍，背景能看到自由女神像和海面，开心微笑，头发被风轻轻吹起，画面略微过曝。第二格上中：夜晚时代广场，背景是霓虹灯、广告屏、人群和街道，人物在路上回头看向镜头边走边笑，画面有轻微运动模糊。第三格右上：中央公园，人物坐在长椅上或草地边，一只手托腮或扶头发，表情轻松自然，背景是树木和阳光。第四格左中：纽约街头披萨店或热狗摊，人物拿着一块纽约披萨或街头小吃，正在笑着准备吃，表情生动开心有感染力。第五格中间：纽约艺术博物馆展厅，人物站在一幅大型现代艺术画作旁边侧身回头看镜头，姿势自然，有艺术展厅和名画氛围。第六格右中：自然历史博物馆或大型展馆，人物站在恐龙骨架展品附近，笑着抬头看展品或看向朋友，姿态有好奇感和旅行兴奋感。第七格左下：布鲁克林大桥，人物在桥上边走边回头笑，头发被风吹起，画面有一点抓拍糊感。第八格下中：帝国大厦观景台或纽约高楼观景台，背景是纽约城市天际线，人物可以比剪刀手、嘟嘴、开心笑或自然看向远处。第九格右下：SoHo、DUMBO或纽约街区街拍，人物在街边行走，穿搭时尚休闲，戴墨镜或背包，侧身回头笑，背景有红砖建筑、街道、咖啡店或城市路牌。表情和姿势要求：九张照片里不要全部看镜头，也不要全部微笑，需要有丰富变化：自拍笑、回头笑、侧脸笑、吃东西大笑、看风景、看展品、走路抓拍、坐着放松、比手势。整体感觉是一个真实的人在纽约旅行，不是摆拍模特图。画面限制：保持真实手机旅行照片质感，画幅比例1:1',
      },
      {
        title: '大师画作服装设计拆解',
        mode: 'image_to_image',
        desc: '适合时装设计、风格分析，解析画作或照片中人物的穿搭，生成含多视角和材质细节的专业服装设计图，需上传参考图。',
        prompt: '拆解图中核心人物的穿搭，生成服装设计图。包含服装结构、配色、材质、配饰、道具、正面、侧面、背面、细节特写和真人穿搭效果，3:2',
      },
      {
        title: '个人发型适配分析图卡',
        mode: 'image_to_image',
        desc: '适合发型推荐、形象设计，基于上传人像生成发型对比分析图卡，区分最适合、普通与不建议发型，需上传清晰正面人像照。',
        prompt: '请根据我上传的人像照片，制作一张高质感个人发型分析图卡。保留主角原本五官、脸型与真实特征，透过左右或并排对比方式，展示不同发型套用在主角身上的效果，清楚区分"最适合"、"普通"与"不建议"发型，让人一眼看出哪些发型最修饰脸型、提升气质与整体颜值',
      },
      {
        title: '奇异联动',
        desc: '适合古风角色维秘联动宣传图，突出古典美人姿态与蕾丝吊带丝袜造型，替换角色名和背景即可复用。',
        prompt: '{{角色名}}角色的维秘联动活动宣传图，人物占画面80%以上，{{角色名}}在{{场景背景}}上，优雅侧身回眸姿态，突出古典美人身姿曲线，穿着维秘联动款：融合古风元素的蕾丝吊带裙，搭配精致吊带丝袜（黑色或淡青色，带有轻微古风刺绣），丝袜包裹修长双腿，整体造型唯美古典。高品质真人级 3D古风游戏截图风格，电影级光影，{{角色名}}清丽绝俗、长发微散，眼神柔美回眸，轻纱飘逸。背景为{{背景描述}}，青砖城垛、灯笼照明、月光洒落，古建筑灯火点点，氛围梦幻唯美。高细节，8K品质，精致渲染，真实丝袜质感，电影级构图，光影细腻，古典武侠风',
      },
      {
        title: '现代舞台',
        desc: '适合现代时尚维秘风格宣传图，突出超模气场与蕾丝内衣丝袜造型，替换角色名和背景即可复用。',
        prompt: '{{角色名}}角色的维秘时尚活动宣传图，人物占画面80%以上，{{角色名}}在{{场景背景}}上，自信走秀姿态，突出模特般修长身材曲线，穿着维秘经典款：精致蕾丝内衣套装，搭配丝袜（黑色网纱或裸色薄丝，带有闪钻装饰），丝袜包裹修长双腿，整体造型性感高级。高品质真人级时尚摄影风格，影棚级光影，{{角色名}}妆容精致、发型时尚，眼神自信坚定，翅膀配饰闪耀。背景为{{背景描述}}，T台灯光、镜面地板、闪光灯此起彼伏，氛围璀璨华丽。高细节，8K品质，精致渲染，真实肌肤质感，杂志级构图，光影细腻，国际超模风',
      },
    ],
  },
]

const selectedModel = computed(() => imageModels.value.find((item) => item.model === form.model))
const requestFormatOptions = computed(() => selectedModel.value?.request_formats?.length ? selectedModel.value.request_formats : ['images', 'chat'])
const maxCount = computed(() => Math.max(1, Number(selectedModel.value?.max_count || 1)))
const successResults = computed(() => (currentTask.value?.results || []).filter((item) => item.status === 'success' && imageSrc(item)))
const previewImages = computed(() => successResults.value.map((item) => imageSrc(item)).filter(Boolean))
const detailPreviewImages = computed(() => (detailTask.value?.results || []).map((item) => imageSrc(item)).filter(Boolean))
const inputImagePreviewList = computed(() => form.input_images.map((item) => item.data_url || item.image_url).filter(Boolean))

const formatLabel = (value) => {
  if (value === 'chat') return 'Chat 兼容'
  if (value === 'images') return 'Dalle / Images'
  return value
}

const formatRemainingImageCount = (value) => {
  if (value === null || value === undefined) return '可生成 - 张'
  return `可生成 ${Number(value || 0)} 张`
}

const isSavingResult = (id) => savingResultIds.value.has(id)

const setResultSaving = (id, saving) => {
  if (!id) return
  const next = new Set(savingResultIds.value)
  if (saving) {
    next.add(id)
  } else {
    next.delete(id)
  }
  savingResultIds.value = next
}

const replaceResultInTask = (task, result) => {
  if (!task?.results?.length || !result?.id) return
  task.results = task.results.map((item) => (item.id === result.id ? { ...item, ...result } : item))
}

const updateResultState = (result) => {
  replaceResultInTask(currentTask.value, result)
  replaceResultInTask(detailTask.value, result)
}

const imageSrc = (item) => {
  if (!item) return ''
  if (item.local_url) return item.local_url
  if (item.local_path && item.id) return adminApi.getImageResultFileUrl(item.id)
  if (item.image_url) return item.image_url
  if (item.image_base64) {
    const mimeType = item.mime_type || 'image/png'
    if (item.image_base64.startsWith('data:')) return item.image_base64
    return `data:${mimeType};base64,${item.image_base64}`
  }
  return ''
}

const taskMode = (task) => task?.request_params?.mode || 'text_to_image'

const isImageToImageTask = (task) => taskMode(task) === 'image_to_image'

const taskModeLabel = (task) => isImageToImageTask(task) ? '图生图' : '文生图'

const taskInputImageCount = (task) => Number(task?.request_params?.input_images_count || 0)

const getFirstInputImageUrl = (task) => {
  const urls = task?.request_params?.input_image_urls
  if (!Array.isArray(urls) || !urls.length) return ''
  return urls[0] || ''
}

const formatFileSize = (value) => {
  const size = Number(value || 0)
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)}MB`
  if (size >= 1024) return `${(size / 1024).toFixed(1)}KB`
  return `${size}B`
}

const readFileAsDataUrl = (file) => new Promise((resolve, reject) => {
  const reader = new FileReader()
  reader.onload = () => resolve(reader.result)
  reader.onerror = () => reject(new Error('读取参考图失败'))
  reader.readAsDataURL(file)
})

const selectInputImages = () => {
  inputImageFileRef.value?.click()
}

const handleInputImageChange = async (event) => {
  const files = Array.from(event.target.files || [])
  event.target.value = ''
  if (!files.length) return

  const availableCount = maxInputImageCount - form.input_images.length
  if (availableCount <= 0) {
    ElMessage.warning(`参考图最多支持 ${maxInputImageCount} 张`)
    return
  }
  if (files.length > availableCount) {
    ElMessage.warning(`本次最多还可上传 ${availableCount} 张参考图`)
  }

  for (const file of files.slice(0, availableCount)) {
    if (!inputImageAllowedTypes.includes(file.type)) {
      ElMessage.warning(`${file.name} 类型不支持`)
      continue
    }
    try {
      const dataUrl = await readFileAsDataUrl(file)
      form.input_images.push({
        id: `${Date.now()}-${Math.random()}`,
        data_url: dataUrl,
        name: file.name,
        mime_type: file.type,
        size_bytes: file.size,
      })
    } catch (error) {
      ElMessage.error(error.message || '读取参考图失败')
    }
  }
}

const removeInputImage = (index) => {
  form.input_images.splice(index, 1)
}

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

const stopImageViewerPageScroll = (event) => {
  if (!event.target?.closest?.('.el-image-viewer__wrapper')) return
  event.preventDefault()
}

const hasTimezone = (value) => /(?:z|[+-]\d{2}:?\d{2})$/i.test(value)

const parseBackendTime = (value) => {
  if (!value) return null
  if (value instanceof Date) return value
  let text = String(value).trim()
  if (!text) return null
  // SQLite 返回的微秒精度（6位小数）截断为毫秒（3位），否则 new Date 返回 NaN
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

const imageKeySuccessRate = computed(() => {
  const total = Number(imageKeyDetailImageStats.value?.total_count || 0)
  if (!total) return '0.00'
  return ((Number(imageKeyDetailImageStats.value?.success_count || 0) / total) * 100).toFixed(2)
})

const selectModel = (model) => {
  form.model = model
  handleModelChange()
}

const handleModelChange = () => {
  const opts = requestFormatOptions.value
  if (!opts.includes(form.request_format)) {
    // 当前格式不在新模型支持列表里，重新选，优先 images
    form.request_format = opts.includes('images') ? 'images' : (opts[0] || 'images')
  } else if (opts.includes('images')) {
    // 新模型支持 images，始终切换为 images（每次切换模型都优先 images）
    form.request_format = 'images'
  }
  if (form.count > maxCount.value) {
    form.count = maxCount.value
  }
  loadKeyStats()
}

const insertPromptTip = (tip) => {
  const current = form.prompt.trim()
  form.prompt = current ? `${current}\n${tip}` : tip
}

const openPromptExample = (example, type) => {
  selectedPromptExample.value = {
    type,
    ...example,
  }
  promptExampleVisible.value = true
}

const insertPromptExample = () => {
  if (!selectedPromptExample.value?.prompt) return
  if (selectedPromptExample.value.mode === 'image_to_image') {
    form.mode = 'image_to_image'
  }
  insertPromptTip(selectedPromptExample.value.prompt)
  promptExampleVisible.value = false
}

const canValidateImageModel = (model) => imageValidateModels.has(String(model || '').trim().toLowerCase())

const imageValidateSummary = (result) => {
  if (!result) return ''
  if (result.status === 'success') {
    return `${result.response_time_ms || 0}ms · ${result.image_count || 0} 张`
  }
  return result.failure_category || result.error_message || '验证失败'
}

const showImageValidateDetail = (row) => {
  if (!row?.validate_result) return
  selectedImageValidateResult.value = row.validate_result
  imageValidateDetailVisible.value = true
}

const refreshModelKeyRows = async () => {
  if (!selectedKeyModel.value?.model) return
  const res = await adminApi.getImageKeyStats({ model: selectedKeyModel.value.model })
  const validateResultMap = new Map(
    modelKeyRows.value.map((item) => [item.api_key_id, item.validate_result]).filter(([, result]) => result)
  )
  modelKeyRows.value = (res.items || []).map((item) => ({
    ...item,
    validate_result: validateResultMap.get(item.api_key_id),
  }))
}

const validateImageKey = async (row) => {
  if (!selectedKeyModel.value || !canValidateImageModel(selectedKeyModel.value.model)) return
  row.validating = true
  try {
    const requestFormat = selectedKeyModel.value.request_formats?.[0] || 'images'
    const result = await adminApi.validateImageGeneration({
      api_key_id: row.api_key_id,
      model: selectedKeyModel.value.model,
      quality: 'high',
      request_format: requestFormat,
    })
    row.validate_result = result
    if (result.status === 'success') {
      await refreshModelKeyRows()
      ElMessage.success('生图验证成功')
    } else {
      ElMessage.error(result.error_message || '生图验证失败')
    }
  } catch (error) {
    row.validate_result = {
      api_key_id: row.api_key_id,
      api_key_name: row.api_key_name,
      model: selectedKeyModel.value?.model,
      status: 'error',
      response_time_ms: 0,
      request_format: selectedKeyModel.value?.request_formats?.[0] || 'images',
      image_count: 0,
      failure_category: 'request_error',
      error_message: error.message || '生图验证失败',
    }
    ElMessage.error(error.message || '生图验证失败')
  } finally {
    row.validating = false
  }
}

const openModelKeys = async (model) => {
  selectedKeyModel.value = model
  modelKeyRows.value = []
  resetModelKeyFilters()
  modelKeyDialogVisible.value = true
  loadingModelKeys.value = true
  try {
    await refreshModelKeyRows()
  } catch (error) {
    ElMessage.error(error.message || '加载 Key 成功率失败')
  } finally {
    loadingModelKeys.value = false
  }
}

const loadModels = async () => {
  loadingModels.value = true
  try {
    const res = await adminApi.getImageModels()
    imageModels.value = res.items || []
    if (!form.model && imageModels.value.length) {
      const available = imageModels.value.find((item) => item.available_key_count > 0) || imageModels.value[0]
      form.model = available.model
      handleModelChange()
    }
  } finally {
    loadingModels.value = false
  }
}

const loadImageCapabilities = async () => {
  try {
    const res = await adminApi.getImageCapabilities()
    imageEnhancementEnabled.value = Boolean(res?.psd_enabled)
  } catch (_) {
    imageEnhancementEnabled.value = false
  }
}

const loadKeyStats = async () => {
  loadingStats.value = true
  try {
    const res = await adminApi.getImageKeyStats({ model: form.model || undefined })
    keyStats.value = res.items || []
  } finally {
    loadingStats.value = false
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

const loadTasks = async () => {
  loadingTasks.value = true
  try {
    const params = { page: taskPage.value, limit: taskPageSize.value }
    if (userIdFilter.value) params.user_id = userIdFilter.value
    const res = await adminApi.listImageTasks(params)
    tasks.value = res.items || []
    taskTotal.value = res.total || 0
    if (currentTask.value?.id) {
      const matchedTask = tasks.value.find((item) => Number(item.id) === Number(currentTask.value.id))
      if (matchedTask) {
        currentTask.value = {
          ...currentTask.value,
          ...matchedTask,
          results: currentTask.value.results?.length ? currentTask.value.results : matchedTask.results,
        }
      }
    }
  } finally {
    loadingTasks.value = false
  }
}

const refreshCurrentTaskOnce = async (taskId = currentTask.value?.id) => {
  if (!taskId) return
  const latestTask = await adminApi.getImageTask(taskId)
  currentTask.value = latestTask
  if (detailTask.value?.id === latestTask.id) {
    detailTask.value = latestTask
  }
}

const loadAutoRefreshConfig = async () => {
  try {
    const config = await adminApi.getImageAutoRefreshConfig()
    autoRefreshIntervalMs.value = Math.max((config.image_auto_refresh_interval_seconds || 30) * 1000, 5000)
  } catch (_) {}
  try {
    const config = await adminApi.getStaleTaskCleanupConfig()
    historyRefreshIntervalMs.value = Math.max((config.image_history_refresh_interval_seconds || 5) * 1000, 1000)
  } catch (_) {}
}

const loadAll = async () => {
  // 历史记录独立加载，不被 loadModels 等慢请求阻塞
  loadTasks()
  await Promise.all([loadModels(), loadKeyStats(), loadImageCapabilities(), loadAutoRefreshConfig(), loadUserOptions()])
}

const handleTaskSizeChange = () => {
  taskPage.value = 1
  loadTasks()
}

const scheduleHistoryRefresh = () => {
  if (historyRefreshTimer.value) {
    clearTimeout(historyRefreshTimer.value)
  }
  historyRefreshTimer.value = setTimeout(async () => {
    historyRefreshTimer.value = null
    taskPage.value = 1
    await loadTasks()
  }, historyRefreshIntervalMs.value)
}

const validateForm = () => {
  if (!form.model) {
    ElMessage.warning('请选择图片模型')
    return false
  }
  if (!form.prompt.trim()) {
    ElMessage.warning('请输入提示词')
    return false
  }
  if (form.mode === 'image_to_image' && !form.input_images.length) {
    ElMessage.warning('图生图模式下请至少上传 1 张参考图')
    return false
  }
  const model = selectedModel.value
  if (model && model.available_key_count <= 0) {
    ElMessage.warning('当前模型没有启用且支持的 Key')
    return false
  }
  return true
}

const confirmContinueIfNeeded = async () => {
  if (generationCount.value < 5) return true
  try {
    await ElMessageBox.confirm('已连续生成 5 次，是否继续生成？', '继续确认', {
      confirmButtonText: '继续生成',
      cancelButtonText: '先暂停',
      type: 'warning',
    })
    generationCount.value = 0
    return true
  } catch (_) {
    return false
  }
}

const stopTaskPolling = () => {
  if (taskPollingTimer.value) {
    clearTimeout(taskPollingTimer.value)
    taskPollingTimer.value = null
  }
}

const stopPendingRefreshCheck = () => {
  if (pendingRefreshCheckTimer.value) {
    clearTimeout(pendingRefreshCheckTimer.value)
    pendingRefreshCheckTimer.value = null
  }
  pollingMeta.value = new Map()
}

const stopSinglePendingRefresh = (taskId) => {
  pendingRefreshTaskIds.value = new Set([...pendingRefreshTaskIds.value].filter((id) => id !== taskId))
  const next = new Map(pollingMeta.value)
  next.delete(taskId)
  pollingMeta.value = next
  if (!pendingRefreshTaskIds.value.size) {
    stopPendingRefreshCheck()
  }
}

const pollingTaskRows = computed(() => {
  const rows = []
  for (const [taskId, meta] of pollingMeta.value.entries()) {
    const task = tasks.value.find((t) => t.id === taskId)
    rows.push({
      id: taskId,
      prompt: task?.prompt || '',
      attempts: meta.attempts,
      startTime: meta.startTime,
      elapsed: Date.now() - meta.startTime,
    })
  }
  return rows
})

const formatElapsed = (ms) => {
  const sec = Math.floor(ms / 1000)
  if (sec < 60) return `${sec}秒`
  const min = Math.floor(sec / 60)
  return `${min}分${sec % 60}秒`
}

const pollingMetaTimer = ref(null)

const startPollingMetaRefresh = () => {
  if (pollingMetaTimer.value) return
  pollingMetaTimer.value = setInterval(() => {
    pollingMeta.value = new Map(pollingMeta.value)
  }, 1000)
}

const stopPollingMetaRefresh = () => {
  if (pollingMetaTimer.value) {
    clearInterval(pollingMetaTimer.value)
    pollingMetaTimer.value = null
  }
}

const startPendingRefreshCheck = (taskId) => {
  pendingRefreshTaskIds.value = new Set([...pendingRefreshTaskIds.value, taskId])
  const next = new Map(pollingMeta.value)
  next.set(taskId, { startTime: Date.now(), attempts: 0 })
  pollingMeta.value = next
  startPollingMetaRefresh()
  if (pendingRefreshCheckTimer.value) return
  const checkOnce = async () => {
    pendingRefreshCheckTimer.value = null
    if (!pendingRefreshTaskIds.value.size) return
    // 递增所有正在轮询任务的尝试次数
    const updated = new Map(pollingMeta.value)
    for (const id of pendingRefreshTaskIds.value) {
      const m = updated.get(id)
      if (m) m.attempts += 1
    }
    pollingMeta.value = updated
    try {
      const idsToCheck = [...pendingRefreshTaskIds.value]
      const results = await Promise.all(idsToCheck.map((id) => adminApi.getImageTask(id).catch(() => null)))
      let hasCompleted = false
      for (const task of results) {
        if (!task) continue
        if (task.status !== 'running' || !task.pending_refresh) {
          pendingRefreshTaskIds.value = new Set([...pendingRefreshTaskIds.value].filter((id) => id !== task.id))
          const metaNext = new Map(pollingMeta.value)
          metaNext.delete(task.id)
          pollingMeta.value = metaNext
          hasCompleted = true
          if (task.status === 'success') {
            ElMessage.success(`任务 #${task.id} 回填成功，图片已就绪`)
          } else if (task.status === 'error') {
            ElMessage.error(`任务 #${task.id} 回填失败：${task.error_summary || '未找到图片结果'}`)
          }
        }
      }
      if (hasCompleted) {
        taskPage.value = 1
        await loadTasks()
        await loadKeyStats()
        if (currentTask.value?.id && idsToCheck.includes(currentTask.value.id)) {
          refreshCurrentTaskOnce(currentTask.value.id)
        }
        if (detailTask.value?.id && idsToCheck.includes(detailTask.value.id)) {
          refreshCurrentTaskOnce(detailTask.value.id)
        }
      }
    } catch (_) {}
    if (!pendingRefreshTaskIds.value.size) {
      stopPollingMetaRefresh()
      return
    }
    if (pendingRefreshTaskIds.value.size) {
      pendingRefreshCheckTimer.value = setTimeout(checkOnce, autoRefreshIntervalMs.value)
    }
  }
  pendingRefreshCheckTimer.value = setTimeout(checkOnce, autoRefreshIntervalMs.value)
}

const openPollingDialog = () => {
  if (!pendingRefreshTaskIds.value.size) return
  pollingDialogVisible.value = true
}

const stopAllPendingRefresh = () => {
  stopPendingRefreshCheck()
  pendingRefreshTaskIds.value = new Set()
  pollingDialogVisible.value = false
  ElMessage.info('已停止全部轮询')
}

const pollImageTaskUntilFinished = (taskId, attempt = 0) => {
  stopTaskPolling()
  taskPollingTimer.value = setTimeout(async () => {
    taskPollingTimer.value = null
    try {
      const latestTask = await adminApi.getImageTask(taskId)
      currentTask.value = latestTask
      if (detailTask.value?.id === latestTask.id) {
        detailTask.value = latestTask
      }
      taskPage.value = 1
      await loadTasks()
      if (latestTask.pending_refresh) {
        generating.value = false
        startPendingRefreshCheck(taskId)
        ElMessage.info('任务已进入后台回填，可继续生成新图片')
        return
      }
      if (latestTask.status === 'running') {
        if (attempt >= 180) {
          generating.value = false
          ElMessage.info('图片仍在生成中，可稍后在历史记录查看结果')
          return
        }
        pollImageTaskUntilFinished(taskId, attempt + 1)
        return
      }

      generating.value = false
      await Promise.all([loadKeyStats(), loadModels()])
      if (latestTask.status === 'success') {
        ElMessage.success('图片生成完成')
      } else {
        ElMessage.error(latestTask.error_summary || '图片生成失败')
      }
    } catch (error) {
      generating.value = false
      ElMessage.error(error.message || '刷新图片任务失败')
    }
  }, historyRefreshIntervalMs.value)
}

const submitGeneration = async () => {
  if (!validateForm()) return
  const canContinue = await confirmContinueIfNeeded()
  if (!canContinue) return

  stopTaskPolling()
  generating.value = true
  const payload = {
    model: form.model,
    prompt: form.prompt.trim(),
    size: form.size === 'auto' ? undefined : form.size,
    quality: form.quality,
    count: form.count,
    request_format: form.request_format,
    mode: form.mode,
    input_images: form.mode === 'image_to_image'
      ? form.input_images.map((item) => ({
          data_url: item.data_url || '',
          image_url: item.image_url || '',
          name: item.name,
          mime_type: item.mime_type,
          size_bytes: item.size_bytes,
        }))
      : [],
  }
  try {
    const task = await adminApi.generateImage(payload)
    currentTask.value = task
    if (!activePanels.value.includes('result')) {
      activePanels.value = ['result', ...activePanels.value]
    }
    generationCount.value += 1
    taskPage.value = 1
    await loadTasks()
    if (task.status === 'running') {
      ElMessage.info('图片任务已创建，正在后台生成')
      pollImageTaskUntilFinished(task.id)
      return
    }

    generating.value = false
    await Promise.all([refreshCurrentTaskOnce(task.id), loadKeyStats(), loadModels()])
    if (task.status === 'success') {
      ElMessage.success('图片生成完成')
    } else {
      ElMessage.error(task.error_summary || '图片生成失败')
    }
  } catch (error) {
    generating.value = false
    ElMessage.error(error.message || '图片生成失败')
  }
}

const isRefreshingTask = (id) => refreshingTaskIds.value.has(id)

const canRefreshTask = (task) => {
  if (!task) return false
  if (task.status === 'running') return true
  const summary = task.error_summary || ''
  return task.status === 'error' && /stale_running_timeout|长时间|CPA 图片结果处理失败/.test(summary)
}

const refreshImageTask = async (task) => {
  if (!task?.id) return
  try {
    await ElMessageBox.confirm('将尝试从上游重新抓取该任务结果，不会重新发起生图请求。是否继续？', '重新抓取', {
      confirmButtonText: '重新抓取',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch (_) {
    return
  }

  refreshingTaskIds.value = new Set([...refreshingTaskIds.value, task.id])
  try {
    const latestTask = await adminApi.refreshImageTask(task.id)
    currentTask.value = latestTask
    if (detailTask.value?.id === latestTask.id) {
      detailTask.value = latestTask
    }
    await Promise.all([loadTasks(), loadKeyStats(), loadModels()])
    ElMessage.success('重新抓取成功')
  } catch (error) {
    ElMessage.error(error.message || '重新抓取失败')
  } finally {
    const nextIds = new Set(refreshingTaskIds.value)
    nextIds.delete(task.id)
    refreshingTaskIds.value = nextIds
  }
}

const openTaskUpstreamRefresh = (task) => {
  if (!task?.id) return
  upstreamRefreshForm.taskId = task.id
  upstreamRefreshForm.upstreamTaskId = ''
  upstreamRefreshVisible.value = true
}

const submitUpstreamRefresh = async () => {
  const taskId = upstreamRefreshForm.taskId
  const upstreamTaskId = upstreamRefreshForm.upstreamTaskId.trim()
  if (!taskId) {
    ElMessage.warning('缺少 CPA 任务 ID')
    return
  }

  upstreamRefreshing.value = true
  refreshingTaskIds.value = new Set([...refreshingTaskIds.value, taskId])
  try {
    let latestTask
    if (upstreamTaskId) {
      latestTask = await adminApi.refreshImageTaskByUpstreamId(taskId, upstreamTaskId)
    } else {
      latestTask = await adminApi.refreshImageTask(taskId)
    }
    currentTask.value = latestTask
    if (detailTask.value?.id === latestTask.id) {
      detailTask.value = latestTask
    }
    await Promise.all([loadTasks(), loadKeyStats(), loadModels()])
    upstreamRefreshVisible.value = false
    ElMessage.success(upstreamTaskId ? '图片已按上游任务 ID 回填' : '图片已按提示词和时间自动匹配回填')
  } catch (error) {
    ElMessage.error(error.message || '查询回填失败')
  } finally {
    upstreamRefreshing.value = false
    const nextIds = new Set(refreshingTaskIds.value)
    nextIds.delete(taskId)
    refreshingTaskIds.value = nextIds
  }
}

const openTask = async (id) => {
  const task = await adminApi.getImageTask(id)
  detailTask.value = task
  detailVisible.value = true
  if (task.status === 'running' && task.pending_refresh) {
    startPendingRefreshCheck(task.id)
  }
}

const loadImageKeyDetailTasks = async (apiKeyId = imageKeyDetail.value?.id) => {
  if (!apiKeyId) return
  imageKeyDetailTasksLoading.value = true
  try {
    const res = await adminApi.listImageTasks({
      api_key_id: apiKeyId,
      page: imageKeyDetailTasksPage.value,
      limit: imageKeyDetailTasksPageSize.value,
    })
    imageKeyDetailTasks.value = res.items || []
    imageKeyDetailTasksTotal.value = res.total || 0
  } catch (error) {
    ElMessage.error(error.message || '加载 Key 生图历史失败')
  } finally {
    imageKeyDetailTasksLoading.value = false
  }
}

const loadImageKeyStats = async (apiKeyId) => {
  if (!apiKeyId) return
  const res = await adminApi.getImageKeyStats()
  imageKeyDetailImageStats.value = (res.items || []).find((item) => Number(item.api_key_id) === Number(apiKeyId)) || {}
}

const openImageKeyDetail = async (apiKeyId) => {
  if (!apiKeyId) return
  imageKeyDetailDialogVisible.value = true
  imageKeyDetailLoading.value = true
  imageKeyDetailBalance.value = null
  try {
    const keyData = await adminApi.getKey(apiKeyId)
    imageKeyDetail.value = keyData || {}
    imageKeyDetailTasksPage.value = 1
    await Promise.all([
      loadImageKeyStats(apiKeyId),
      loadImageKeyDetailTasks(apiKeyId),
    ])
    // 异步加载余额，不阻塞弹窗
    loadImageKeyDetailBalance(apiKeyId)
  } catch (error) {
    ElMessage.error(error.message || '加载 Key 详情失败')
  } finally {
    imageKeyDetailLoading.value = false
  }
}

const loadImageKeyDetailBalance = async (keyId) => {
  imageKeyDetailBalanceLoading.value = true
  try {
    const data = await adminApi.getProviderBalance(keyId)
    imageKeyDetailBalance.value = data
  } catch {
    imageKeyDetailBalance.value = null
  } finally {
    imageKeyDetailBalanceLoading.value = false
  }
}

const toggleImageKeyDetailActive = async () => {
  const keyId = imageKeyDetail.value?.id
  if (!keyId || imageKeyDetailToggling.value) return
  imageKeyDetailToggling.value = true
  try {
    const updated = await adminApi.toggleKey(keyId)
    imageKeyDetail.value = { ...imageKeyDetail.value, is_active: updated.is_active }
    ElMessage.success(updated.is_active ? 'Key 已启用' : 'Key 已关闭')
  } catch (e) {
    ElMessage.error(e.message || '操作失败')
  } finally {
    imageKeyDetailToggling.value = false
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

const handleImageKeyDetailTasksPageChange = (page) => {
  imageKeyDetailTasksPage.value = page
  loadImageKeyDetailTasks()
}

const handleImageKeyDetailTasksPageSizeChange = (size) => {
  imageKeyDetailTasksPageSize.value = size
  imageKeyDetailTasksPage.value = 1
  loadImageKeyDetailTasks()
}

const handleImageKeyDetailDialogClosed = () => {
  imageKeyDetail.value = {}
  imageKeyDetailImageStats.value = {}
  imageKeyDetailTasks.value = []
  imageKeyDetailTasksTotal.value = 0
  imageKeyDetailTasksPage.value = 1
  imageKeyDetailTasksPageSize.value = 10
  imageKeyDetailBalance.value = null
}

const imageSizeText = (item) => {
  const width = Number(item?.width || 0)
  const height = Number(item?.height || 0)
  if (width > 0 && height > 0) return `${width}×${height}`
  return '尺寸未知'
}

const reuseTaskPrompt = (task) => {
  const prompt = String(task?.prompt || '').trim()
  if (!prompt) {
    ElMessage.warning('该历史记录没有可引用的提示词')
    return
  }
  insertPromptTip(prompt)
  ElMessage.success('已引用历史提示词')
}

const ensureDataUrl = async (src, mimeType = 'image/png') => {
  if (!src) return ''
  if (src.startsWith('data:')) return src
  try {
    const response = await fetch(src)
    if (!response.ok) throw new Error(`获取图片失败：${response.status}`)
    const blob = await response.blob()
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(reader.result)
      reader.onerror = () => reject(new Error('读取图片数据失败'))
      reader.readAsDataURL(blob)
    })
  } catch (error) {
    ElMessage.error(error.message || '获取图片数据失败')
    return ''
  }
}

const editTaskImage = async (task) => {
  // 获取任务详情和结果图片
  let fullTask = task
  try {
    fullTask = await adminApi.getImageTask(task.id)
  } catch (error) {
    ElMessage.warning('获取任务详情失败')
    return
  }

  const successResult = (fullTask.results || []).find((r) => r.status === 'success')
  if (!successResult) {
    ElMessage.warning('没有可编辑的成功图片')
    return
  }

  // 获取图片数据：优先使用在线 URL
  const imgSrc = imageSrc(successResult)
  if (!imgSrc) {
    ElMessage.warning('无法获取图片数据')
    return
  }

  // 优先尝试从本地 URL 转为 data URL（避免依赖外部存储服务）
  // 同时保留在线 URL 作为 chat 格式的后备
  const hasOnlineUrl = successResult.image_url && successResult.image_url.startsWith('http')
  const localUrl = successResult.local_url || ''
  let dataUrl = ''
  // 优先从 CPA 本地端点获取（稳定可靠），其次从在线 URL 获取
  if (localUrl) {
    dataUrl = await ensureDataUrl(localUrl, successResult.mime_type)
  }
  if (!dataUrl && hasOnlineUrl) {
    dataUrl = await ensureDataUrl(successResult.image_url, successResult.mime_type)
  }
  if (!dataUrl && !hasOnlineUrl) {
    ElMessage.warning('无法获取图片数据')
    return
  }

  // 设置表单：同时提供 data_url 和 image_url
  // images 格式用 data_url（避免下载失败），chat 格式用 image_url（传递给上游）
  isEditMode.value = true
  form.mode = 'image_to_image'
  form.input_images = [{
    id: `${Date.now()}-${Math.random()}`,
    data_url: dataUrl || '',
    image_url: hasOnlineUrl ? successResult.image_url : '',
    name: `task-${task.id}-result.png`,
    mime_type: successResult.mime_type || 'image/png',
    size_bytes: successResult.file_size_bytes || 0,
  }]
  form.model = task.model || form.model
  form.size = (task.request_params && task.request_params.size) || form.size
  form.quality = (task.request_params && task.request_params.quality) || form.quality

  setTimeout(() => { isEditMode.value = false }, 100)

  // 滚动到页面顶部
  window.scrollTo({ top: 0, behavior: 'smooth' })
  ElMessage.success('已加载图片到图生图引用区，可修改提示词进行调整')
}

const handleHistorySelectionChange = (rows) => {
  selectedHistoryTasks.value = rows || []
}

const removeDeletedTasksFromHistory = (deletedIds) => {
  const deletedIdSet = new Set(deletedIds)
  tasks.value = tasks.value.filter((item) => !deletedIdSet.has(item.id))
  selectedHistoryTasks.value = selectedHistoryTasks.value.filter((item) => !deletedIdSet.has(item.id))
  taskTotal.value = Math.max(0, taskTotal.value - deletedIdSet.size)
}

const confirmDeleteTask = async (task) => {
  try {
    await ElMessageBox.confirm(
      `确认删除图片任务 #${task.id}？请选择删除范围。`,
      '删除图片历史',
      {
        confirmButtonText: '删除记录和图片',
        cancelButtonText: '仅删除记录',
        distinguishCancelAndClose: true,
        type: 'warning',
      }
    )
    await deleteTask(task, true)
  } catch (action) {
    if (action === 'cancel') {
      await deleteTask(task, false)
    }
  }
}

const deleteTask = async (task, deleteFiles) => {
  try {
    const res = await adminApi.deleteImageTask(task.id, { delete_files: deleteFiles })
    if (detailTask.value?.id === task.id) {
      detailVisible.value = false
      detailTask.value = null
    }
    if (currentTask.value?.id === task.id) {
      currentTask.value = null
      activePanels.value = activePanels.value.filter((item) => item !== 'result')
    }
    ElMessage.success(deleteFiles ? `已删除记录和 ${res.deleted_files || 0} 个图片文件` : '已删除历史记录')
  } catch (_) {
    // 接口报错不影响列表移除（任务可能已被删除）
  }
  removeDeletedTasksFromHistory([task.id])
}

const batchDeleteTasks = async (deleteFiles) => {
  const selectedTasks = [...selectedHistoryTasks.value]
  if (!selectedTasks.length) return

  deletingHistoryTasks.value = true
  try {
    let deletedFiles = 0
    const results = await Promise.allSettled(
      selectedTasks.map((task) => adminApi.deleteImageTask(task.id, { delete_files: deleteFiles }))
    )
    results.forEach((result) => {
      if (result.status === 'fulfilled') {
        deletedFiles += Number(result.value?.deleted_files || 0)
      }
    })

    const selectedIds = new Set(selectedTasks.map((item) => item.id))
    if (detailTask.value && selectedIds.has(detailTask.value.id)) {
      detailVisible.value = false
      detailTask.value = null
    }
    if (currentTask.value && selectedIds.has(currentTask.value.id)) {
      currentTask.value = null
      activePanels.value = activePanels.value.filter((item) => item !== 'result')
    }

    selectedHistoryTasks.value = []
    removeDeletedTasksFromHistory([...selectedIds])
    ElMessage.success(deleteFiles ? `已删除 ${selectedTasks.length} 条记录和 ${deletedFiles} 个图片文件` : `已删除 ${selectedTasks.length} 条历史记录`)
  } catch (error) {
    ElMessage.error(error.message || '批量删除图片历史失败')
  } finally {
    deletingHistoryTasks.value = false
  }
}

const confirmBatchDeleteTasks = async () => {
  if (!selectedHistoryTasks.value.length) {
    ElMessage.warning('请先选择要删除的历史记录')
    return
  }

  try {
    await ElMessageBox.confirm(
      `确认删除选中的 ${selectedHistoryTasks.value.length} 条图片历史？请选择删除范围。`,
      '批量删除图片历史',
      {
        confirmButtonText: '删除记录和图片',
        cancelButtonText: '仅删除记录',
        distinguishCancelAndClose: true,
        type: 'warning',
      }
    )
    await batchDeleteTasks(true)
  } catch (action) {
    if (action === 'cancel') {
      await batchDeleteTasks(false)
    }
  }
}

const openStorageDialog = async () => {
  storageDialogVisible.value = true
  try {
    const res = await adminApi.getImageStorageConfig()
    storageForm.storage_dir = res.storage_dir || ''
    storageForm.default_storage_dir = res.default_storage_dir || ''
  } catch (error) {
    ElMessage.error(error.message || '加载图片存储配置失败')
  }
}

const saveStorageConfig = async () => {
  if (!storageForm.storage_dir.trim()) {
    ElMessage.warning('请输入图片存储目录')
    return
  }
  savingStorage.value = true
  try {
    const res = await adminApi.updateImageStorageConfig({ storage_dir: storageForm.storage_dir.trim() })
    storageForm.storage_dir = res.storage_dir || storageForm.storage_dir
    storageForm.default_storage_dir = res.default_storage_dir || storageForm.default_storage_dir
    storageDialogVisible.value = false
    ElMessage.success('图片存储位置已更新，后续新生成图片会写入新目录')
  } catch (error) {
    ElMessage.error(error.message || '保存图片存储配置失败')
  } finally {
    savingStorage.value = false
  }
}

const openResultFolder = async (item) => {
  try {
    await adminApi.openImageResultFolder(item.id)
    ElMessage.success('已打开图片所在文件夹')
  } catch (error) {
    ElMessage.error(error.message || '打开文件夹失败')
  }
}

const revealResultFile = async (item) => {
  try {
    await adminApi.revealImageResultFile(item.id)
    ElMessage.success('已定位图片文件')
  } catch (error) {
    ElMessage.error(error.message || '定位图片文件失败')
  }
}

const copyToClipboard = async (value) => {
  await copyText(value)
  ElMessage.success('已复制')
}

const downloadImage = async (item) => {
  if (!item?.id) return
  let target = item
  if (!target.local_path) {
    setResultSaving(target.id, true)
    try {
      target = await adminApi.saveImageResultLocal(target.id)
      updateResultState(target)
      ElMessage.success('图片已保存到本地')
    } catch (error) {
      ElMessage.error(error.message || '保存图片到本地失败')
      return
    } finally {
      setResultSaving(item.id, false)
    }
  }

  const src = imageSrc(target)
  if (!src) return
  const link = document.createElement('a')
  link.href = src
  link.download = `image-task-${target.task_id}-${target.image_index}.png`
  link.target = '_blank'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}

const downloadPsd = async (item) => {
  if (!item?.id) return
  // PSD 接口需要后台鉴权，先用 axios 带 Authorization 获取文件再触发下载。
  let target = item
  if (!target.local_path) {
    setResultSaving(target.id, true)
    try {
      target = await adminApi.saveImageResultLocal(target.id)
      updateResultState(target)
    } catch (error) {
      ElMessage.error(error.message || '保存图片到本地失败，无法导出 PSD')
      return
    } finally {
      setResultSaving(item.id, false)
    }
  }

  setResultSaving(target.id, true)
  try {
    const response = await adminApi.downloadImageResultPsd(target.id)
    const blob = response instanceof Blob ? response : new Blob([response], { type: 'image/vnd.adobe.photoshop' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `image-result-${target.id}.psd`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  } catch (error) {
    ElMessage.error(error.message || 'PSD 下载失败')
  } finally {
    setResultSaving(target.id, false)
  }
}

watch(() => form.mode, (value) => {
  if (value === 'text_to_image' && !isEditMode.value) {
    form.input_images = []
  }
})

watch(requestFormatOptions, () => {
  if (!requestFormatOptions.value.includes(form.request_format)) {
    form.request_format = requestFormatOptions.value.includes('images')
      ? 'images'
      : (requestFormatOptions.value[0] || 'images')
  } else if (requestFormatOptions.value.includes('images')) {
    // 模型切换后，只要新模型支持 images，始终优先切换为 images
    form.request_format = 'images'
  }
})

onMounted(() => {
  loadAll()
  document.addEventListener('wheel', stopImageViewerPageScroll, { passive: false })
})

onUnmounted(() => {
  stopTaskPolling()
  stopPendingRefreshCheck()
  if (historyRefreshTimer.value) {
    clearTimeout(historyRefreshTimer.value)
  }
  document.removeEventListener('wheel', stopImageViewerPageScroll)
})
</script>

<style scoped>
.image-square {
  color: var(--cpa-text);
}

.workspace-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(300px, 0.75fr);
  gap: 12px;
  align-items: start;
}

.generate-card,
.result-card,
.model-card {
  min-width: 0;
}

.generate-card,
.model-card {
  min-height: 100%;
}

.panel-subtitle {
  margin-top: 6px;
  font-size: 13px;
  color: var(--cpa-text-secondary);
}

.compact-header {
  min-height: 24px;
  justify-content: space-between;
}

.content-collapse {
  width: 100%;
  margin-top: 12px;
  border: 1px solid var(--cpa-border);
  border-radius: 18px;
  background: var(--cpa-surface-strong);
  overflow: hidden;
}

.content-collapse :deep(.el-collapse-item__header) {
  min-height: 64px;
  height: auto;
  padding: 12px 16px;
  border-bottom-color: var(--cpa-border);
  background: linear-gradient(180deg, rgba(248, 251, 255, 0.96), rgba(255, 255, 255, 0.9));
}

.content-collapse :deep(.el-collapse-item__content) {
  padding: 14px 16px 10px;
  background: var(--cpa-surface-strong);
}

.content-collapse :deep(.el-collapse-item:last-child) {
  margin-bottom: 0;
}

.collapse-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  min-width: 0;
}

.collapse-title > div:first-child {
  min-width: 0;
}

.collapse-title .panel-subtitle {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.collapse-title-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.task-duration {
  font-size: 12px;
  color: var(--cpa-text-tertiary);
}

.history-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
}

.polling-badge :deep(.el-badge__content) {
  background-color: var(--cpa-primary);
}

.polling-dialog-body {
  max-height: 440px;
  overflow-y: auto;
}

.history-row-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  white-space: nowrap;
}

.history-row-actions :deep(.el-button) {
  margin-left: 0;
  padding: 0;
}

.key-name-link {
  max-width: 100%;
  padding: 0;
  vertical-align: baseline;
}

.key-name-link :deep(span) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.key-detail-dialog {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.key-detail-history-card {
  border-color: var(--cpa-border);
}

.key-detail-history-card :deep(.el-card__header) {
  padding: 12px 14px;
  background: linear-gradient(180deg, rgba(248, 251, 255, 0.96), rgba(255, 255, 255, 0.9));
}

.key-detail-pagination {
  margin-top: 12px;
}

.image-card-meta {
  min-width: 0;
  color: var(--cpa-text-tertiary);
  text-align: right;
  white-space: nowrap;
}

.generate-form :deep(.el-select),
.generate-form :deep(.el-input-number) {
  width: 100%;
}

.model-mode-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: end;
}

.model-mode-row :deep(.el-form-item) {
  margin-bottom: 0;
}

.mode-field {
  min-width: 220px;
}

.mode-switch :deep(.el-radio-button__inner) {
  min-width: 88px;
}

.mode-switch :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  border-color: var(--cpa-primary);
  background: var(--cpa-primary);
  box-shadow: -1px 0 0 0 var(--cpa-primary);
  color: #fff;
}

.mode-switch :deep(.el-radio-button__inner:hover) {
  color: var(--cpa-primary);
}

.model-meta :deep(.el-tag),
.model-option :deep(.el-tag) {
  border-color: var(--cpa-border-strong);
  background: var(--cpa-chip-bg);
  color: var(--cpa-chip-text);
}

.model-meta :deep(.el-tag--info),
.model-option :deep(.el-tag--info) {
  border-color: var(--cpa-border);
  background: var(--cpa-surface-muted);
  color: var(--cpa-text-secondary);
}

.model-meta :deep(.el-tag--success),
.model-option :deep(.el-tag--success) {
  border-color: rgba(16, 185, 129, 0.24);
  background: rgba(16, 185, 129, 0.10);
  color: var(--cpa-success);
}

@media (max-width: 768px) {
  .model-mode-row {
    grid-template-columns: 1fr;
    align-items: stretch;
  }

  .mode-field {
    min-width: 0;
  }
}

.input-image-uploader {
  width: 100%;
  padding: 12px;
  border: 1px dashed var(--cpa-border-strong);
  border-radius: 14px;
  background: var(--cpa-chip-bg);
}

.input-image-file {
  display: none;
}

.input-image-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--cpa-text-secondary);
  font-size: 13px;
}

.input-image-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 10px;
  margin-top: 12px;
}

.input-image-item {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 8px;
  border: 1px solid var(--cpa-border);
  border-radius: 12px;
  background: var(--cpa-surface-strong);
}

.input-image-preview {
  width: 52px;
  height: 52px;
  flex: 0 0 auto;
  border-radius: 10px;
  overflow: hidden;
}

.input-image-info {
  flex: 1;
  min-width: 0;
  color: var(--cpa-text-tertiary);
  font-size: 12px;
  line-height: 1.5;
}

.input-image-name {
  overflow: hidden;
  color: var(--cpa-text);
  font-size: 13px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.prompt-helper {
  margin: -8px 0 14px;
  border: 1px solid var(--cpa-border);
  border-radius: 14px;
  background: linear-gradient(180deg, rgba(248, 251, 255, 0.96), rgba(241, 247, 255, 0.88));
}

.prompt-helper :deep(.el-collapse-item__header) {
  height: 40px;
  padding: 0 12px;
  border-bottom: 0;
  background: transparent;
}

.prompt-helper :deep(.el-collapse-item__wrap) {
  border-bottom: 0;
  background: transparent;
}

.prompt-helper :deep(.el-collapse-item__content) {
  padding: 0 12px 12px;
}

.prompt-helper-collapse-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--cpa-text);
}

.prompt-helper-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--cpa-text);
}

.prompt-helper-desc {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  margin-top: 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--cpa-text-secondary);
}

.prompt-helper-desc :deep(.inline-prompt-link) {
  min-height: auto;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--cpa-primary);
  text-decoration: underline;
  text-underline-offset: 3px;
}

.prompt-tip-groups {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 10px;
}

.prompt-tip-group {
  padding: 10px;
  border: 1px solid var(--cpa-border);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.62);
}

.prompt-tip-group-title {
  display: none;
}

.prompt-tip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.prompt-tip-list :deep(.el-button) {
  height: auto;
  min-height: 28px;
  margin-left: 0;
  padding: 6px 10px;
  border-color: var(--cpa-border-strong);
  color: var(--cpa-primary);
  background: var(--cpa-chip-bg);
  white-space: normal;
  text-align: left;
  line-height: 1.4;
}

.prompt-tip-list :deep(.el-button.is-link) {
  min-height: 24px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--cpa-primary);
  text-decoration: underline;
  text-underline-offset: 3px;
}

.prompt-external-links {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  font-size: 13px;
  color: var(--cpa-text-secondary);
}

.prompt-external-links :deep(.el-button) {
  margin-left: 0;
}

.prompt-example-dialog {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.prompt-example-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--cpa-text-secondary);
  line-height: 1.5;
}

.prompt-example-i2i-hint {
  margin-top: 8px;
  padding: 8px 12px;
  border-radius: 8px;
  background: var(--cpa-warning-bg, #fff7e6);
  color: var(--cpa-warning-text, #d48806);
  font-size: 13px;
  line-height: 1.5;
}

.prompt-example-content {
  padding: 14px;
  border: 1px solid var(--cpa-border);
  border-radius: 14px;
  background: linear-gradient(180deg, rgba(248, 251, 255, 0.96), rgba(255, 255, 255, 0.9));
  color: var(--cpa-text);
  line-height: 1.7;
  white-space: pre-wrap;
}

.prompt-example-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.size-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.size-option span:first-child {
  color: var(--cpa-text);
}

.size-option span:last-child {
  font-size: 12px;
  color: var(--cpa-text-tertiary);
}

.model-card :deep(.el-card__body) {
  height: calc(100% - 72px);
}

.model-card .model-list {
  height: 100%;
  max-height: 524px;
}

.model-meta,
.generate-actions,
.image-card-footer,
.model-option,
.card-header-simple,
.mode-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.model-option {
  justify-content: space-between;
  width: 100%;
  min-width: 0;
}

.model-option > span {
  overflow: hidden;
  min-width: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.model-option-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
}

.model-meta {
  flex-wrap: wrap;
  margin: 8px 0 14px;
}

.mode-cell {
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  color: var(--cpa-text-tertiary);
  font-size: 12px;
}

.param-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.generate-actions {
  justify-content: space-between;
  margin-top: 4px;
}

.form-tip {
  font-size: 13px;
  color: var(--cpa-text-secondary);
}

.side-stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
  height: 100%;
}

.model-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 248px;
  overflow-y: auto;
  padding-right: 2px;
}

.model-list-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--cpa-border);
  border-radius: 14px;
  background: var(--cpa-surface-muted);
  cursor: pointer;
  transition: all 0.2s ease;
}

.model-list-item:hover,
.model-list-item.is-active {
  border-color: var(--cpa-border-strong);
  background: var(--cpa-chip-bg);
}

.model-list-item :deep(.el-button.is-link),
.model-list-item :deep(.el-button--primary.is-link) {
  color: #1d4ed8;
  font-weight: 700;
}

.model-list-item:hover :deep(.el-button.is-link),
.model-list-item:hover :deep(.el-button--primary.is-link),
.model-list-item :deep(.el-button.is-link:hover),
.model-list-item :deep(.el-button--primary.is-link:hover) {
  color: #0f172a;
}

.model-capacity {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  flex: 0 0 auto;
  color: var(--cpa-text-secondary);
  font-size: 12px;
  line-height: 1.4;
  text-align: right;
}

.model-capacity :deep(.el-button) {
  height: auto;
  min-height: auto;
  margin-left: 0;
  padding: 0;
}

.model-capacity span {
  white-space: nowrap;
}

.model-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--cpa-text);
}

.model-id {
  margin-top: 4px;
  font-size: 12px;
  color: var(--cpa-text-tertiary);
}

.image-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
  margin-top: 12px;
}

.image-card {
  overflow: hidden;
  border: 1px solid var(--cpa-border);
  border-radius: 16px;
  background: var(--cpa-surface-strong);
}

.image-preview,
.error-box {
  width: 100%;
  height: 220px;
  display: block;
}

.error-box {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  color: var(--cpa-danger);
  background: rgba(239, 68, 68, 0.08);
  text-align: center;
}

.image-card-footer {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  padding: 10px 12px;
  font-size: 13px;
  color: var(--cpa-text-secondary);
}

.image-card-info {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.image-flow-label {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 12px 0;
  color: var(--cpa-text-secondary);
  font-size: 13px;
  font-weight: 600;
}

.flow-arrow {
  color: var(--cpa-primary);
}

.image-pair {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.image-pair-input {
  width: 80px;
  height: 80px;
  border-radius: 6px;
  flex-shrink: 0;
  border: 1px solid var(--cpa-border);
}

.image-pair-arrow {
  font-size: 18px;
  font-weight: 700;
  color: var(--cpa-primary);
  flex-shrink: 0;
}

.image-pair-output {
  flex: 1;
  min-width: 0;
  border-radius: 6px;
  aspect-ratio: 1;
}

.image-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
  flex-wrap: wrap;
}

.model-key-dialog :deep(.el-dialog__body) {
  padding-top: 14px;
}

.model-key-toolbar {
  display: grid;
  grid-template-columns: minmax(0, 260px) minmax(0, 220px) minmax(360px, 1fr) 44px;
  gap: 10px;
  align-items: center;
  margin-bottom: 12px;
}

.model-key-toolbar :deep(.el-date-editor) {
  width: 100%;
}

.model-key-reset-button {
  width: 44px;
  padding-right: 0;
  padding-left: 0;
}

.model-key-dialog :deep(.el-table th.el-table__cell),
.model-key-dialog :deep(.el-table td.el-table__cell) {
  text-align: center;
}

.model-key-dialog :deep(.el-table .cell) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  padding-right: 8px;
  padding-left: 8px;
}

.model-key-dialog :deep(.el-table th.el-table__cell .cell) {
  gap: 3px;
}

.model-key-dialog :deep(.caret-wrapper) {
  display: inline-flex;
  flex: 0 0 12px;
  width: 12px;
  height: 18px;
  margin-left: 2px;
  transform: scale(0.82);
  transform-origin: center;
  vertical-align: middle;
}

.model-key-dialog :deep(.sort-caret) {
  left: 2px;
}

.model-key-dialog :deep(.sort-caret.ascending) {
  top: 1px;
}

.model-key-dialog :deep(.sort-caret.descending) {
  bottom: 1px;
}

.model-key-validate-tip {
  margin-bottom: 12px;
}

.validate-result-cell {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-width: 0;
  width: 100%;
}

.validate-result-text,
.validate-result-empty {
  overflow: hidden;
  color: var(--cpa-text-secondary);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.validate-result-empty {
  color: var(--cpa-text-tertiary);
}

.validate-detail {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.validate-detail-summary {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.validate-preview {
  display: flex;
  align-items: center;
  gap: 14px;
  color: var(--cpa-text-secondary);
  font-size: 13px;
}

.validate-preview-image {
  width: 160px;
  height: 160px;
  border: 1px solid var(--cpa-border);
  border-radius: 14px;
}

.pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.image-history-pagination {
  margin-top: 6px;
}

.image-history-pagination :deep(.el-pagination) {
  --el-pagination-button-width: 26px;
  --el-pagination-button-height: 26px;
  --el-pagination-font-size: 13px;
  gap: 4px;
}

.image-history-pagination :deep(.el-pagination__total),
.image-history-pagination :deep(.el-pagination__sizes) {
  margin-right: 6px;
}

.image-history-pagination :deep(.el-select) {
  width: 98px;
}

.image-history-pagination :deep(.el-input__wrapper) {
  min-height: 28px;
  border-radius: 12px;
}

.detail-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.detail-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  padding: 12px;
  border-radius: 14px;
  background: var(--cpa-surface-muted);
  color: var(--cpa-text-secondary);
  font-size: 13px;
}

.detail-summary span {
  color: var(--cpa-text-tertiary);
}

.detail-prompt {
  padding: 12px;
  border: 1px solid var(--cpa-border);
  border-radius: 14px;
  color: var(--cpa-text);
  background: var(--cpa-surface);
  white-space: pre-wrap;
}

.error-actions {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.upstream-refresh-body {
  display: grid;
  gap: 14px;
}

.upstream-refresh-form {
  margin-top: 2px;
}

.detail-images {
  max-height: 520px;
  overflow-y: auto;
  padding-right: 4px;
}

.detail-image-info {
  padding: 10px 12px 12px;
}

.detail-image-info .image-card-footer {
  padding: 0;
}

.detail-image-info .image-actions {
  justify-content: flex-start;
}

.file-meta-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 10px;
  color: var(--cpa-text-secondary);
  font-size: 13px;
  line-height: 1.5;
}

.file-meta-list span {
  color: var(--cpa-text-tertiary);
}

.local-path {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.local-file-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 10px;
}

.storage-dialog {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.storage-default-path {
  color: var(--cpa-text-secondary);
  font-size: 13px;
}

@media (max-width: 1180px) {
  .workspace-grid,
  .param-grid,
  .detail-summary {
    grid-template-columns: 1fr;
  }

  .side-stack {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .generate-actions {
    align-items: stretch;
    flex-direction: column;
  }
}

@media (max-width: 760px) {
  .side-stack {
    grid-template-columns: 1fr;
  }

  .collapse-title {
    align-items: flex-start;
    flex-direction: column;
  }

  .content-collapse :deep(.el-collapse-item__header) {
    padding: 12px;
  }

  .content-collapse :deep(.el-collapse-item__content) {
    padding: 12px;
  }
}

.title-hidden-link {
  color: inherit;
  text-decoration: none;
  cursor: pointer;
}
</style>
