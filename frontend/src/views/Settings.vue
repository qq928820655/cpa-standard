<template>
  <div class="settings page-shell">
    <div class="page-header">
      <div class="page-header-main">
        <div class="page-kicker">System</div>
        <h2 class="page-title">系统设置</h2>
        <p class="page-subtitle">集中管理后台认证、代理超时与接入说明，并支持一键导出到 CC Switch 便于本地应用接入。</p>
      </div>
    </div>

    <!-- 认证配置 -->
    <el-card class="setting-card" shadow="never">
      <template #header>
        <div class="setting-card-header" @click="toggleCard('auth')">
          <div class="setting-card-header-text">
            <div class="panel-title">认证配置</div>
            <div class="panel-subtitle">查看 Master Key、本地保存管理凭证，并快速导出到 CC Switch 完成客户端接入</div>
          </div>
          <el-icon class="setting-card-arrow" :class="{ 'is-expanded': expandedCards.auth }"><ArrowDown /></el-icon>
        </div>
      </template>
      <div v-show="expandedCards.auth" class="setting-card-body">
        <el-form label-width="120px">
          <el-form-item label="登录验证">
            <el-switch v-model="loginEnabled" active-text="开启" inactive-text="关闭" @change="handleLoginToggle" />
            <div class="form-tip">开启后访问管理页面需先登录，关闭则直接访问</div>
          </el-form-item>
          <el-form-item label="Master Key">
            <el-input v-model="masterKey" :type="showMasterKey ? 'text' : 'password'" readonly style="max-width: 500px">
              <template #append>
                <el-button class="master-key-append-button" @click="showMasterKey = !showMasterKey">
                  <el-icon><View v-if="!showMasterKey" /><Hide v-else /></el-icon>
                </el-button>
                <el-button class="master-key-append-button" @click="copyMasterKey">
                  <el-icon><CopyDocument /></el-icon>
                </el-button>
              </template>
            </el-input>
            <div class="form-tip">此 Key 用于访问本系统的所有 API，请妥善保管</div>
          </el-form-item>
          <el-form-item label="本地 Key 配置">
            <el-input v-model="localMasterKey" placeholder="输入 Master Key 以启用管理功能" style="max-width: 500px">
              <template #append>
                <el-button type="primary" @click="saveMasterKey">保存</el-button>
              </template>
            </el-input>
            <div class="form-tip">在浏览器本地保存 Master Key，用于调用管理接口</div>
          </el-form-item>
          <el-form-item label="导出到 CC Switch">
            <el-button type="primary" @click="openCcSwitchDialog">导出到 CC Switch</el-button>
            <div class="form-tip">支持 Claude、Codex、Gemini 三种应用导入</div>
          </el-form-item>
          <el-form-item label="显示实际模型">
            <el-switch
              v-model="showActualModel"
              active-text="开启"
              inactive-text="关闭"
              @change="handleShowActualModelChange"
            />
            <div class="form-tip">开启后，管理员在请求记录中可看到模型映射的实际模型（格式：请求模型/映射模型）；关闭则所有人只看到请求模型</div>
          </el-form-item>
        </el-form>
      </div>
    </el-card>

    <!-- 显示设置 -->
    <el-card class="setting-card" shadow="never">
      <template #header>
        <div class="setting-card-header" @click="toggleCard('display')">
          <div class="setting-card-header-text">
            <div class="panel-title">显示设置</div>
            <div class="panel-subtitle">调整数据展示方式，修改后立即在仪表盘和用量统计页生效</div>
          </div>
          <el-icon class="setting-card-arrow" :class="{ 'is-expanded': expandedCards.display }"><ArrowDown /></el-icon>
        </div>
      </template>
      <div v-show="expandedCards.display" class="setting-card-body">
        <el-form label-width="160px">
          <el-form-item label="Token 单位自动切换">
            <el-switch v-model="tokenUnitAutoM" active-text="超过百万显示 M" inactive-text="始终显示原始数值" @change="handleTokenUnitChange" />
            <div class="form-tip">开启后，Token 数超过 1,000,000 时自动切换为 M 单位（如 92,415.68 M）；关闭则始终显示千分符整数</div>
          </el-form-item>
        </el-form>
      </div>
    </el-card>

    <!-- 供应商密码配置 -->
    <el-card class="setting-card" shadow="never">
      <template #header>
        <div class="setting-card-header" @click="toggleCard('providerExt')">
          <div class="setting-card-header-text">
            <div class="panel-title">供应商密码配置</div>
            <div class="panel-subtitle">配置各供应商的登录密码，用于查询 Key 余额（如 bb 供应商）</div>
          </div>
          <el-icon class="setting-card-arrow" :class="{ 'is-expanded': expandedCards.providerExt }"><ArrowDown /></el-icon>
        </div>
      </template>
      <div v-show="expandedCards.providerExt" class="setting-card-body">
        <el-form label-width="120px" v-loading="providerExtLoading">
          <div v-for="(cfg, provider) in providerExtForm" :key="provider" class="provider-ext-row">
            <el-form-item :label="provider">
              <el-input
                v-model="cfg.password"
                type="password"
                show-password
                :placeholder="`${provider} 的登录密码`"
                style="max-width: 400px"
              />
              <el-button
                type="danger"
                link
                style="margin-left: 8px"
                @click="removeProviderExt(provider)"
              >删除</el-button>
            </el-form-item>
          </div>
          <el-form-item label="新增供应商">
            <div style="display: flex; gap: 8px; align-items: center">
              <el-input v-model="newProviderName" placeholder="供应商名称（如 bb）" style="max-width: 160px" clearable />
              <el-input v-model="newProviderPassword" type="password" show-password placeholder="登录密码" style="max-width: 240px" />
              <el-button @click="addProviderExt">添加</el-button>
            </div>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="providerExtSaving" @click="saveProviderExtConfig">保存密码配置</el-button>
          </el-form-item>
        </el-form>
      </div>
    </el-card>

    <!-- 余额降权规则配置 -->
    <el-card class="setting-card" shadow="never">
      <template #header>
        <div class="setting-card-header" @click="toggleCard('balanceDowngrade')">
          <div class="setting-card-header-text">
            <div class="panel-title">余额降权规则</div>
            <div class="panel-subtitle">配置余额不足时的 Key 处理策略：按剩余额度区间决定降权或关闭</div>
          </div>
          <el-icon class="setting-card-arrow" :class="{ 'is-expanded': expandedCards.balanceDowngrade }"><ArrowDown /></el-icon>
        </div>
      </template>
      <div v-show="expandedCards.balanceDowngrade" class="setting-card-body">
        <div v-loading="balanceDowngradeLoading">
          <div class="balance-rule-header">
            <span class="balance-rule-col">最小值（含）</span>
            <span class="balance-rule-col">最大值（不含）</span>
            <span class="balance-rule-col">处理方式</span>
            <span class="balance-rule-col">降权值</span>
            <span style="flex: 1; min-width: 120px">适用提供商（留空=所有）</span>
            <span class="balance-rule-col-action"></span>
          </div>
          <div v-for="(rule, idx) in balanceDowngradeRules" :key="idx" class="balance-rule-row">
            <el-input-number
              v-model="rule.min"
              :precision="4"
              :step="0.01"
              :min="0"
              placeholder="不限"
              class="balance-rule-col"
              size="small"
            />
            <el-input-number
              v-model="rule.max"
              :precision="4"
              :step="0.01"
              :min="0"
              placeholder="不限"
              class="balance-rule-col"
              size="small"
            />
            <el-select v-model="rule.action" class="balance-rule-col" size="small">
              <el-option value="none" label="不处理" />
              <el-option value="weight" label="降权" />
              <el-option value="disable" label="关闭 Key" />
            </el-select>
            <el-input-number
              v-if="rule.action === 'weight'"
              v-model="rule.weight"
              :min="1"
              :max="100"
              :precision="0"
              class="balance-rule-col"
              size="small"
            />
            <span v-else class="balance-rule-col" style="color: #909399; font-size: 13px">-</span>
            <el-input
              v-model="rule.providers_str"
              placeholder="如 bb,bbimg 或留空"
              size="small"
              style="flex: 1; min-width: 120px"
            />
            <el-button type="danger" link size="small" class="balance-rule-col-action" @click="removeBalanceRule(idx)">删除</el-button>
          </div>
          <div style="margin-top: 8px; display: flex; gap: 8px">
            <el-button size="small" @click="addBalanceRule">添加规则</el-button>
            <el-button type="primary" size="small" :loading="balanceDowngradeSaving" @click="saveBalanceDowngradeRules">保存规则</el-button>
          </div>
          <div class="form-tip" style="margin-top: 8px">规则按顺序匹配，第一个满足区间的规则生效。留空表示不限制该端。适用提供商多个用逗号分隔，留空匹配所有提供商。</div>
        </div>
      </div>
    </el-card>

    <!-- 供应商迁移规则 -->
    <el-card class="setting-card" shadow="never">
      <template #header>
        <div class="setting-card-header" @click="toggleCard('providerMigration')">
          <div class="setting-card-header-text">
            <div class="panel-title">供应商迁移规则</div>
            <div class="panel-subtitle">余额不足时自动将 Key 迁移到其他供应商（如 bb → bbimg），并调整支持模型</div>
          </div>
          <el-icon class="setting-card-arrow" :class="{ 'is-expanded': expandedCards.providerMigration }"><ArrowDown /></el-icon>
        </div>
      </template>
      <div v-show="expandedCards.providerMigration" class="setting-card-body">
        <div v-loading="providerMigrationLoading">
          <div class="balance-rule-header">
            <span style="flex: 0 0 80px">源供应商</span>
            <span style="flex: 0 0 80px">目标供应商</span>
            <span style="flex: 0 0 90px">最小余额(⚡)</span>
            <span style="flex: 0 0 90px">最大余额(⚡)</span>
            <span style="flex: 1">迁移后支持模型（逗号分隔）</span>
            <span style="flex: 0 0 40px"></span>
          </div>
          <div v-for="(rule, idx) in providerMigrationRules" :key="idx" class="balance-rule-row">
            <el-input v-model="rule.from_provider" placeholder="如 bb" size="small" style="flex: 0 0 80px" />
            <el-input v-model="rule.to_provider" placeholder="如 bbimg" size="small" style="flex: 0 0 80px" />
            <el-input-number v-model="rule.min_balance" :precision="4" :step="0.01" :min="0" size="small" style="flex: 0 0 90px" controls-position="right" />
            <el-input-number v-model="rule.max_balance" :precision="4" :step="0.01" :min="0" size="small" style="flex: 0 0 90px" controls-position="right" placeholder="不限" />
            <el-input v-model="rule.supported_models_str" placeholder="模型1,模型2,..." size="small" style="flex: 1" />
            <el-button type="danger" link size="small" style="flex: 0 0 40px" @click="removeProviderMigrationRule(idx)">删除</el-button>
          </div>
          <div style="margin-top: 8px; display: flex; gap: 8px">
            <el-button size="small" @click="addProviderMigrationRule">添加规则</el-button>
            <el-button type="primary" size="small" :loading="providerMigrationSaving" @click="saveProviderMigrationRules">保存规则</el-button>
          </div>
          <div class="form-tip" style="margin-top: 8px">余额在 [最小, 最大) 区间时触发迁移；低于最小值时走余额降权规则（可能关闭 Key）</div>
        </div>
      </div>
    </el-card>

    <!-- 流式缓冲规则 -->
    <el-card class="setting-card" shadow="never">
      <template #header>
        <div class="setting-card-header" @click="toggleCard('streamBuffer')">
          <div class="setting-card-header-text">
            <div class="panel-title">流式缓冲规则</div>
            <div class="panel-subtitle">针对特定提供商/模型开启完整缓冲模式，上游截流时自动换 Key 重试，不影响其他请求</div>
          </div>
          <el-icon class="setting-card-arrow" :class="{ 'is-expanded': expandedCards.streamBuffer }"><ArrowDown /></el-icon>
        </div>
      </template>
      <div v-show="expandedCards.streamBuffer" class="setting-card-body">
        <div v-loading="streamBufferLoading">
          <div class="balance-rule-header">
            <span style="flex: 0 0 140px">提供商（支持 * 通配）</span>
            <span style="flex: 1">模型（支持 * 通配，留空匹配所有）</span>
            <span style="flex: 0 0 40px"></span>
          </div>
          <div v-for="(rule, idx) in streamBufferRules" :key="idx" class="balance-rule-row">
            <el-input v-model="rule.provider" placeholder="如 lumora 或 *" size="small" style="flex: 0 0 140px" />
            <el-input v-model="rule.model" placeholder="如 kiro* 或留空匹配所有" size="small" style="flex: 1" />
            <el-button type="danger" link size="small" style="flex: 0 0 40px" @click="removeStreamBufferRule(idx)">删除</el-button>
          </div>
          <div style="margin-top: 8px; display: flex; gap: 8px">
            <el-button size="small" @click="addStreamBufferRule">添加规则</el-button>
            <el-button type="primary" size="small" :loading="streamBufferSaving" @click="saveStreamBufferRules">保存规则</el-button>
          </div>
          <div class="form-tip" style="margin-top: 8px">命中规则的请求会先完整缓冲上游响应再输出，断流时自动换 Key 重试（最多 {{ STREAM_RETRY_LIMIT }} 次）。适用于上游会截流的提供商。</div>
        </div>
      </div>
    </el-card>


    <!-- 代理超时配置 -->
    <el-card class="setting-card" shadow="never">
      <template #header>
        <div class="setting-card-header" @click="toggleCard('proxyTimeout')">
          <div class="setting-card-header-text">
            <div class="panel-title">代理超时配置</div>
            <div class="panel-subtitle">统一设置普通请求与流式请求的超时策略，平衡稳定性与响应体验</div>
          </div>
          <el-icon class="setting-card-arrow" :class="{ 'is-expanded': expandedCards.proxyTimeout }"><ArrowDown /></el-icon>
        </div>
      </template>
      <div v-show="expandedCards.proxyTimeout" class="setting-card-body">
        <el-form label-width="160px" v-loading="proxyTimeoutLoading">
          <el-form-item label="普通请求超时">
            <el-input-number v-model="proxyTimeoutForm.proxy_request_timeout_seconds" :min="1" />
            <div class="form-tip">非流式请求的整体等待时间，单位秒。</div>
          </el-form-item>
          <el-form-item label="流式连接超时">
            <el-input-number v-model="proxyTimeoutForm.proxy_stream_connect_timeout_seconds" :min="1" />
            <div class="form-tip">建立流式连接时的超时时间，单位秒。</div>
          </el-form-item>
          <el-form-item label="流式首包超时">
            <el-input-number v-model="proxyTimeoutForm.proxy_stream_first_byte_timeout_seconds" :min="1" />
            <div class="form-tip">连接建立后等待首个数据块的时间，单位秒。</div>
          </el-form-item>
          <el-form-item label="流式读取超时">
            <el-input-number v-model="proxyTimeoutForm.proxy_stream_read_timeout_seconds" :min="1" />
            <div class="form-tip">流式传输过程中后续数据读取超时，单位秒。</div>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="proxyTimeoutSaving" @click="saveProxyTimeoutConfig">保存超时配置</el-button>
          </el-form-item>
        </el-form>
      </div>
    </el-card>

    <!-- 图片自动回填配置 -->
    <el-card class="setting-card" shadow="never">
      <template #header>
        <div class="setting-card-header" @click="toggleCard('imageAutoRefresh')">
          <div class="setting-card-header-text">
            <div class="panel-title">图片自动回填配置</div>
            <div class="panel-subtitle">配置 Cloudflare 超时后自动查询上游任务日志的等待、间隔与最大次数</div>
          </div>
          <el-icon class="setting-card-arrow" :class="{ 'is-expanded': expandedCards.imageAutoRefresh }"><ArrowDown /></el-icon>
        </div>
      </template>
      <div v-show="expandedCards.imageAutoRefresh" class="setting-card-body">
        <el-form label-width="180px" v-loading="imageAutoRefreshLoading">
          <el-form-item label="初始等待">
            <el-input-number v-model="imageAutoRefreshForm.image_auto_refresh_delay_seconds" :min="0" :max="3600" />
            <div class="form-tip">出现 Cloudflare 类超时后，等待多少秒开始第一次获取。</div>
          </el-form-item>
          <el-form-item label="获取间隔">
            <el-input-number v-model="imageAutoRefreshForm.image_auto_refresh_interval_seconds" :min="1" :max="3600" />
            <div class="form-tip">第一次获取失败后，每隔多少秒再次获取。</div>
          </el-form-item>
          <el-form-item label="最大获取次数">
            <el-input-number v-model="imageAutoRefreshForm.image_auto_refresh_max_attempts" :min="1" :max="100" />
            <div class="form-tip">该次回填最多获取多少次，成功后立即停止。</div>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="imageAutoRefreshSaving" @click="saveImageAutoRefreshConfig">保存自动回填配置</el-button>
          </el-form-item>
        </el-form>
      </div>
    </el-card>

    <!-- OpenAI Plus 配额刷新配置 -->
    <el-card class="setting-card" shadow="never">
      <template #header>
        <div class="setting-card-header" @click="toggleCard('openAIPlusQuotaRefresh')">
          <div class="setting-card-header-text">
            <div class="panel-title">OpenAI Plus 配额刷新配置</div>
            <div class="panel-subtitle">配置官方配额刷新时的账号并发数和单账号超时</div>
          </div>
          <el-icon class="setting-card-arrow" :class="{ 'is-expanded': expandedCards.openAIPlusQuotaRefresh }"><ArrowDown /></el-icon>
        </div>
      </template>
      <div v-show="expandedCards.openAIPlusQuotaRefresh" class="setting-card-body">
        <el-form label-width="180px" v-loading="openAIPlusQuotaRefreshLoading">
          <el-form-item label="同时刷新账号数">
            <el-input-number v-model="openAIPlusQuotaRefreshForm.openai_plus_quota_refresh_concurrency" :min="1" :max="20" />
            <div class="form-tip">刷新官方配额时最多同时请求多少个 Plus 账号。</div>
          </el-form-item>
          <el-form-item label="配额请求超时">
            <el-input-number v-model="openAIPlusQuotaRefreshForm.openai_plus_quota_refresh_timeout_seconds" :min="5" :max="300" />
            <div class="form-tip">单个账号读取官方配额接口的超时时间，单位秒。</div>
          </el-form-item>
          <el-form-item label="Token 刷新超时">
            <el-input-number v-model="openAIPlusQuotaRefreshForm.openai_plus_quota_token_refresh_timeout_seconds" :min="5" :max="300" />
            <div class="form-tip">账号 access token 临近过期时，刷新 token 的超时时间，单位秒。</div>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="openAIPlusQuotaRefreshSaving" @click="saveOpenAIPlusQuotaRefreshConfig">保存配额刷新配置</el-button>
          </el-form-item>
        </el-form>
      </div>
    </el-card>

    <!-- 过期任务回收配置 -->
    <el-card class="setting-card" shadow="never">
      <template #header>
        <div class="setting-card-header" @click="toggleCard('staleTaskCleanup')">
          <div class="setting-card-header-text">
            <div class="panel-title">过期任务回收配置</div>
            <div class="panel-subtitle">配置后台定时检查并关闭超时图片任务的间隔</div>
          </div>
          <el-icon class="setting-card-arrow" :class="{ 'is-expanded': expandedCards.staleTaskCleanup }"><ArrowDown /></el-icon>
        </div>
      </template>
      <div v-show="expandedCards.staleTaskCleanup" class="setting-card-body">
        <div v-loading="staleTaskCleanupLoading">
          <div class="cleanup-two-col">
            <div class="cleanup-col">
              <div class="cleanup-label">回收间隔（秒）</div>
              <el-input-number v-model="staleTaskCleanupForm.image_stale_task_cleanup_interval_seconds" :min="10" :max="3600" style="width: 100%" />
              <div class="form-tip">每隔多少秒检查一次过期图片任务，范围 10 ~ 3600</div>
            </div>
            <div class="cleanup-col">
              <div class="cleanup-label">历史刷新间隔（秒）</div>
              <el-input-number v-model="staleTaskCleanupForm.image_history_refresh_interval_seconds" :min="1" :max="60" style="width: 100%" />
              <div class="form-tip">点击生成后，历史记录列表自动刷新的间隔，范围 1 ~ 60</div>
            </div>
            <div class="cleanup-col">
              <div class="cleanup-label">元数据清理间隔（秒）</div>
              <el-input-number v-model="staleTaskCleanupForm.image_result_meta_cleanup_interval_seconds" :min="60" :max="86400" style="width: 100%" />
              <div class="form-tip">定时清空超过 3 小时未回填的冗余字段，范围 60 ~ 86400</div>
            </div>
          </div>
          <div style="margin-top: 12px">
            <el-button type="primary" :loading="staleTaskCleanupSaving" @click="saveStaleTaskCleanupConfig">保存回收配置</el-button>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 默认检测模型 -->
    <el-card class="setting-card" shadow="never">
      <template #header>
        <div class="setting-card-header" @click="toggleCard('keyCheckDefault')">
          <div class="setting-card-header-text">
            <div class="panel-title">默认检测模型</div>
            <div class="panel-subtitle">统一设置 Key 管理页"一键检测"弹窗默认带出的模型名称，留空表示每次手动输入</div>
          </div>
          <el-icon class="setting-card-arrow" :class="{ 'is-expanded': expandedCards.keyCheckDefault }"><ArrowDown /></el-icon>
        </div>
      </template>
      <div v-show="expandedCards.keyCheckDefault" class="setting-card-body">
        <el-form label-width="160px" v-loading="keyCheckDefaultLoading">
          <el-form-item label="默认检测模型">
            <el-input v-model="keyCheckDefaultForm.default_key_check_model" clearable placeholder="留空表示不预填默认模型" style="max-width: 500px" />
            <div class="form-tip">保存后，Key 管理页点击"一键检测"会优先带出这里的值，仍可在弹窗里手动修改。</div>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="keyCheckDefaultSaving" @click="saveKeyCheckDefaultConfig">保存默认检测模型</el-button>
          </el-form-item>
        </el-form>
      </div>
    </el-card>

    <!-- 快捷检测模型 -->
    <el-card class="setting-card" shadow="never">
      <template #header>
        <div class="setting-card-header" @click="toggleCard('keyCheckShortcut')">
          <div class="setting-card-header-text">
            <div class="panel-title">快捷检测模型</div>
            <div class="panel-subtitle">配置 Key 管理页一键检测弹窗的六个快捷按钮，第一项默认来自上面的检测模型</div>
          </div>
          <el-icon class="setting-card-arrow" :class="{ 'is-expanded': expandedCards.keyCheckShortcut }"><ArrowDown /></el-icon>
        </div>
      </template>
      <div v-show="expandedCards.keyCheckShortcut" class="setting-card-body">
        <el-form label-width="160px" v-loading="keyCheckShortcutLoading">
          <div class="shortcut-model-input-grid">
            <el-form-item label="快捷模型 1">
              <el-input v-model="keyCheckShortcutForm.shortcut_models[0]" clearable placeholder="默认带出检测模型" style="max-width: 500px" />
            </el-form-item>
            <el-form-item label="快捷模型 2">
              <el-input v-model="keyCheckShortcutForm.shortcut_models[1]" clearable placeholder="第二个快捷模型" style="max-width: 500px" />
            </el-form-item>
            <el-form-item label="快捷模型 3">
              <el-input v-model="keyCheckShortcutForm.shortcut_models[2]" clearable placeholder="第三个快捷模型" style="max-width: 500px" />
            </el-form-item>
            <el-form-item label="快捷模型 4">
              <el-input v-model="keyCheckShortcutForm.shortcut_models[3]" clearable placeholder="第四个快捷模型" style="max-width: 500px" />
            </el-form-item>
            <el-form-item label="快捷模型 5">
              <el-input v-model="keyCheckShortcutForm.shortcut_models[4]" clearable placeholder="第五个快捷模型" style="max-width: 500px" />
            </el-form-item>
            <el-form-item label="快捷模型 6">
              <el-input v-model="keyCheckShortcutForm.shortcut_models[5]" clearable placeholder="第六个快捷模型" style="max-width: 500px" />
            </el-form-item>
          </div>
          <el-form-item>
            <el-button type="primary" :loading="keyCheckShortcutSaving" @click="saveKeyCheckShortcutModels">保存快捷模型</el-button>
          </el-form-item>
        </el-form>
      </div>
    </el-card>

    <!-- 错误透传配置 -->
    <el-card class="setting-card" shadow="never">
      <template #header>
        <div class="setting-card-header" @click="toggleCard('passThroughError')">
          <div class="setting-card-header-text">
            <div class="panel-title">错误透传配置</div>
            <div class="panel-subtitle">配置哪些错误码直接返回上游响应，不切换 Key、不冷却、不重试</div>
          </div>
          <el-icon class="setting-card-arrow" :class="{ 'is-expanded': expandedCards.passThroughError }"><ArrowDown /></el-icon>
        </div>
      </template>
      <div v-show="expandedCards.passThroughError" class="setting-card-body">
        <el-form label-width="160px" v-loading="passThroughErrorLoading">
          <el-form-item label="透传错误码">
            <el-select
              v-model="passThroughErrorCodes"
              multiple
              filterable
              allow-create
              default-first-option
              placeholder="输入错误码后回车添加"
              style="max-width: 500px"
            >
              <el-option :value="429" label="429 (Rate Limit)" />
              <el-option :value="502" label="502 (Bad Gateway)" />
              <el-option :value="503" label="503 (Service Unavailable)" />
              <el-option :value="504" label="504 (Gateway Timeout)" />
            </el-select>
            <div class="form-tip">添加后，命中这些错误码时将直接返回上游响应，不切换 Key 重试、不触发冷却。留空表示所有错误码均走默认重试逻辑。</div>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="passThroughErrorSaving" @click="savePassThroughErrorCodes">保存透传配置</el-button>
          </el-form-item>
        </el-form>
      </div>
    </el-card>

    <!-- 错误继续配置 -->
    <el-card class="setting-card" shadow="never">
      <template #header>
        <div class="setting-card-header" @click="toggleCard('providerContinueError')">
          <div class="setting-card-header-text">
            <div class="panel-title">错误继续配置</div>
            <div class="panel-subtitle">命中指定提供商和错误关键词时，不返回前台，复用当前 Key 自动追加提示词继续</div>
          </div>
          <el-icon class="setting-card-arrow" :class="{ 'is-expanded': expandedCards.providerContinueError }"><ArrowDown /></el-icon>
        </div>
      </template>
      <div v-show="expandedCards.providerContinueError" class="setting-card-body">
        <el-form label-width="120px" v-loading="providerContinueErrorLoading">
          <div v-for="(rule, index) in providerContinueErrorRules" :key="index" class="rule-card">
            <div class="rule-card__header">
              <span>规则 {{ index + 1 }}</span>
              <el-button size="small" type="danger" link @click="removeProviderContinueRule(index)">删除</el-button>
            </div>
            <el-form-item label="启用">
              <el-switch v-model="rule.enabled" />
            </el-form-item>
            <el-form-item label="提供商">
              <el-input v-model="rule.provider" placeholder="* 表示全部，或填写 xmapi / yz 等 provider" />
            </el-form-item>
            <el-form-item label="状态码">
              <el-select v-model="rule.status_codes" multiple allow-create filterable default-first-option placeholder="400 / 403">
                <el-option :value="400" label="400" />
                <el-option :value="403" label="403" />
              </el-select>
            </el-form-item>
            <el-form-item label="错误关键词">
              <el-select v-model="rule.keywords" multiple allow-create filterable default-first-option placeholder="命中任一关键词即自动继续">
                <el-option value="不支持生成图片" label="不支持生成图片" />
                <el-option value="请切换分组" label="请切换分组" />
                <el-option value="does not support image generation" label="does not support image generation" />
              </el-select>
            </el-form-item>
            <el-form-item label="继续提示词">
              <el-input v-model="rule.prompt" type="textarea" :rows="3" placeholder="追加给模型的继续提示词" />
            </el-form-item>
          </div>
          <el-form-item>
            <el-button @click="addProviderContinueRule">新增规则</el-button>
            <el-button type="primary" :loading="providerContinueErrorSaving" @click="saveProviderContinueErrorRules">保存错误继续配置</el-button>
          </el-form-item>
        </el-form>
      </div>
    </el-card>

    <!-- 运行日志显示 -->
    <el-card class="setting-card" shadow="never">
      <template #header>
        <div class="setting-card-header" @click="toggleCard('runtimeLog')">
          <div class="setting-card-header-text">
            <div class="panel-title">运行日志显示</div>
            <div class="panel-subtitle">控制管理菜单中的运行日志页面，并使用内存循环缓冲实时展示服务日志</div>
          </div>
          <el-icon class="setting-card-arrow" :class="{ 'is-expanded': expandedCards.runtimeLog }"><ArrowDown /></el-icon>
        </div>
      </template>
      <div v-show="expandedCards.runtimeLog" class="setting-card-body">
        <el-form label-width="160px" v-loading="runtimeLogLoading">
          <el-form-item label="运行日志菜单">
            <el-switch v-model="runtimeLogEnabled" active-text="开启" inactive-text="关闭" />
            <div class="form-tip">开启后显示“运行日志”菜单。日志最多占用 3MB 内存，超过后自动清除最早内容；关闭后清空缓冲。</div>
          </el-form-item>
          <el-form-item label="日志自动换行">
            <el-switch v-model="runtimeLogWrap" active-text="开启" inactive-text="关闭" />
            <div class="form-tip">开启后运行日志按页面宽度自动换行显示；关闭时保持单行、横向滚动查看完整内容。</div>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="runtimeLogSaving" @click="saveRuntimeLogConfig">保存运行日志配置</el-button>
          </el-form-item>
        </el-form>
      </div>
    </el-card>

    <!-- 代理调试追踪 -->
    <el-card class="setting-card" shadow="never">
      <template #header>
        <div class="setting-card-header" @click="toggleCard('proxyTrace')">
          <div class="setting-card-header-text">
            <div class="panel-title">代理调试追踪</div>
            <div class="panel-subtitle">按需记录一次请求的模型解析、Key 选择、上游耗时与重试/透传判断</div>
          </div>
          <el-icon class="setting-card-arrow" :class="{ 'is-expanded': expandedCards.proxyTrace }"><ArrowDown /></el-icon>
        </div>
      </template>
      <div v-show="expandedCards.proxyTrace" class="setting-card-body">
        <el-form label-width="160px" v-loading="proxyTraceLoading">
          <el-form-item label="追踪开关">
            <el-switch
              v-model="proxyTraceForm.proxy_trace_enabled"
              active-text="开启"
              inactive-text="关闭"
            />
            <div class="form-tip">默认关闭。开启后仅记录路由决策摘要，不记录完整请求体、响应体、Authorization 或 API Key 明文。</div>
          </el-form-item>
          <el-form-item label="保留时间">
            <el-input-number
              v-model="proxyTraceForm.proxy_trace_retention_hours"
              :min="1"
              :max="168"
              :step="1"
              controls-position="right"
            />
            <span class="form-inline-unit">小时</span>
            <div class="form-tip">超过保留时间的追踪记录可通过清理接口删除，建议日常保持较短保留期。</div>
          </el-form-item>
          <el-form-item label="采样率">
            <el-input-number
              v-model="proxyTraceForm.proxy_trace_sample_rate"
              :min="0"
              :max="1"
              :step="0.1"
              :precision="2"
              controls-position="right"
            />
            <div class="form-tip">取值 0 到 1，1 表示开启后全部记录，0.1 表示约 10% 请求记录。</div>
          </el-form-item>
          <el-form-item label="仅失败请求">
            <el-switch
              v-model="proxyTraceForm.proxy_trace_only_failures"
              active-text="开启"
              inactive-text="关闭"
            />
            <div class="form-tip">开启后成功请求不会落库，只保留失败或异常请求的追踪记录。</div>
          </el-form-item>
          <el-form-item label="Provider 过滤">
            <el-input
              v-model="proxyTraceForm.proxy_trace_target_provider"
              placeholder="留空表示不过滤，如 skk"
              clearable
              style="max-width: 500px"
            />
          </el-form-item>
          <el-form-item label="模型过滤">
            <el-input
              v-model="proxyTraceForm.proxy_trace_target_model"
              placeholder="留空表示不过滤，如 gpt-5.5"
              clearable
              style="max-width: 500px"
            />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="proxyTraceSaving" @click="saveProxyTraceConfig">保存追踪配置</el-button>
          </el-form-item>
        </el-form>
      </div>
    </el-card>

    <!-- 模型种子配置 -->
    <el-card class="setting-card" shadow="never">
      <template #header>
        <div class="setting-card-header" @click="toggleCard('modelSeed')">
          <div class="setting-card-header-text">
            <div class="panel-title">模型种子配置</div>
            <div class="panel-subtitle">控制模型广场是否自动填充默认模型列表，一键还原后会自动关闭</div>
          </div>
          <el-icon class="setting-card-arrow" :class="{ 'is-expanded': expandedCards.modelSeed }"><ArrowDown /></el-icon>
        </div>
      </template>
      <div v-show="expandedCards.modelSeed" class="setting-card-body">
        <el-form label-width="160px">
          <el-form-item label="默认模型回填">
            <el-switch
              v-model="modelSeedEnabled"
              active-text="开启"
              inactive-text="关闭"
              @change="handleModelSeedChange"
            />
            <div class="form-tip">开启后，模型广场会自动填充系统预设的默认模型；关闭后模型广场仅展示与实际 Key 关联的模型。一键还原后会自动关闭此开关。</div>
          </el-form-item>
        </el-form>
      </div>
    </el-card>

    <!-- DeepSeek 思考模式配置 -->
    <el-card class="setting-card" shadow="never">
      <template #header>
        <div class="setting-card-header" @click="toggleCard('thinkingMode')">
          <div class="setting-card-header-text">
            <div class="panel-title">DeepSeek 思考模式配置</div>
            <div class="panel-subtitle">为 DeepSeek 模型自动注入思考模式参数（thinking / reasoning_effort），客户端显式传入时优先</div>
          </div>
          <el-icon class="setting-card-arrow" :class="{ 'is-expanded': expandedCards.thinkingMode }"><ArrowDown /></el-icon>
        </div>
      </template>
      <div v-show="expandedCards.thinkingMode" class="setting-card-body">
        <div v-for="(rule, idx) in thinkingModeRules" :key="idx" style="margin-bottom: 16px; padding: 12px; border: 1px solid #e4e7ed; border-radius: 6px;">
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
            <span style="font-weight: 600; color: #303133;">规则 #{{ idx + 1 }}</span>
            <el-button type="danger" text size="small" @click="removeThinkingModeRule(idx)">删除</el-button>
          </div>
          <el-form label-width="120px" size="small">
            <el-form-item label="启用">
              <el-switch v-model="rule.enabled" active-text="是" inactive-text="否" />
            </el-form-item>
            <el-form-item label="强制模式">
              <el-switch v-model="rule.force" active-text="是" inactive-text="否" />
              <div class="form-tip">关闭时客户端传入的参数优先，CPA 只补充缺失的；开启时 CPA 配置强制覆盖客户端传入的 thinking / reasoning_effort / effort</div>
            </el-form-item>
            <el-form-item label="供应商过滤">
              <el-input v-model="rule.providersText" placeholder="留空匹配所有，逗号分隔（如 deepseek,bb）" style="max-width: 400px" />
              <div class="form-tip">留空则匹配所有供应商；多个供应商用英文逗号分隔</div>
            </el-form-item>
            <el-form-item label="模型过滤">
              <el-input v-model="rule.modelsText" placeholder="留空匹配所有 DeepSeek 模型，逗号分隔（如 deepseek-v4-pro）" style="max-width: 400px" />
              <div class="form-tip">留空则匹配所有含 deepseek 关键词的模型；支持通配符（如 deepseek-*）</div>
            </el-form-item>
            <el-form-item label="思考模式">
              <el-select v-model="rule.thinking_type" style="width: 180px">
                <el-option label="启用 (enabled)" value="enabled" />
                <el-option label="禁用 (disabled)" value="disabled" />
              </el-select>
              <div class="form-tip">控制 DeepSeek 模型的思考模式开关；默认 enabled</div>
            </el-form-item>
            <el-form-item label="思考强度">
              <el-select v-model="rule.reasoning_effort" style="width: 180px" clearable>
                <el-option label="不设置" value="" />
                <el-option label="high" value="high" />
                <el-option label="max" value="max" />
              </el-select>
              <div class="form-tip">控制思考强度；high 适合普通请求，max 适合复杂 Agent 类请求（如 Claude Code）。留空则不注入此参数。客户端传入 reasoning_effort 或 effort 时，非强制模式下保留客户端值</div>
            </el-form-item>
          </el-form>
        </div>
        <el-button type="primary" text @click="addThinkingModeRule">+ 添加规则</el-button>
        <div style="margin-top: 12px;">
          <el-button type="primary" :loading="thinkingModeSaving" @click="saveThinkingModeConfig">保存思考模式配置</el-button>
        </div>
      </div>
    </el-card>

    <!-- 智能协议路由配置 -->
    <el-card class="setting-card" shadow="never">
      <template #header>
        <div class="setting-card-header" @click="toggleCard('intelligentProtocolRouting')">
          <div class="setting-card-header-text">
            <div class="panel-title">智能协议路由</div>
            <div class="panel-subtitle">按客户端偏好和真实上游能力选择 Responses、Chat 或 Messages；关闭时保持现有路由</div>
          </div>
          <el-icon class="setting-card-arrow" :class="{ 'is-expanded': expandedCards.intelligentProtocolRouting }"><ArrowDown /></el-icon>
        </div>
      </template>
      <div v-show="expandedCards.intelligentProtocolRouting" class="setting-card-body">
        <el-form label-width="170px" v-loading="intelligentProtocolRoutingLoading">
          <el-form-item label="智能路由开关">
            <el-switch v-model="intelligentProtocolRoutingForm.enabled" active-text="开启" inactive-text="关闭" />
            <div class="form-tip">仅影响未显式指定协议的请求，以及既有协议失败后的兼容降级；能力结果只来自真实请求。</div>
          </el-form-item>
          <el-form-item label="能力缓存时间（小时）">
            <el-input-number v-model="intelligentProtocolRoutingForm.capability_ttl_hours" :min="1" :max="8760" controls-position="right" />
          </el-form-item>
          <el-form-item label="客户端规则">
            <el-input v-model="intelligentProtocolRoutingForm.clientRulesText" type="textarea" :rows="3" placeholder="每行：客户端标识|User-Agent 包含文本，例如 deepseek_harness|deepseek-harness" style="max-width: 620px" />
          </el-form-item>
          <el-form-item label="提供商模型覆盖">
            <el-input v-model="intelligentProtocolRoutingForm.overridesText" type="textarea" :rows="3" placeholder="每行：provider|model|protocol1,protocol2" style="max-width: 620px" />
            <div class="form-tip">仅用于异常上游的人工覆盖；协议可填 openai_responses、openai_chat、anthropic_messages。</div>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="intelligentProtocolRoutingSaving" @click="saveIntelligentProtocolRoutingConfig">保存配置</el-button>
            <el-button :loading="protocolCapabilitiesLoading" @click="loadProtocolCapabilities">刷新能力记录</el-button>
            <el-button type="danger" plain :loading="protocolCapabilitiesClearing" @click="clearProtocolCapabilities">清空能力记录</el-button>
          </el-form-item>
        </el-form>
        <el-form inline class="capability-filter-form">
          <el-form-item label="Provider"><el-input v-model="protocolCapabilityFilters.provider" clearable /></el-form-item>
          <el-form-item label="Model"><el-input v-model="protocolCapabilityFilters.model" clearable /></el-form-item>
          <el-form-item label="Protocol"><el-input v-model="protocolCapabilityFilters.protocol" clearable /></el-form-item>
          <el-button @click="loadProtocolCapabilities">查询</el-button>
        </el-form>
        <el-table :data="protocolCapabilities" size="small" border>
          <el-table-column prop="provider" label="Provider" width="130" />
          <el-table-column prop="model_id" label="Model" min-width="180" />
          <el-table-column prop="protocol" label="Protocol" width="160" />
          <el-table-column label="结果" width="80"><template #default="scope"><el-tag :type="scope.row.supported ? 'success' : 'danger'">{{ scope.row.supported ? '支持' : '不支持' }}</el-tag></template></el-table-column>
          <el-table-column prop="source" label="来源" width="90" />
          <el-table-column prop="status_code" label="状态码" width="80" />
          <el-table-column prop="updated_at" label="更新时间" min-width="170" />
        </el-table>
        <div class="form-tip" style="margin-top: 8px">当前记录共 {{ protocolCapabilitiesTotal }} 条。认证、限流、超时和 5xx 等异常不会被误记为协议不支持。</div>
      </div>
    </el-card>

    <!-- 用量保留期配置 -->
    <el-card class="setting-card" shadow="never">
      <template #header>
        <div class="setting-card-header" @click="toggleCard('usageRetention')">
          <div class="setting-card-header-text">
            <div class="panel-title">用量保留期</div>
            <div class="panel-subtitle">设置请求明细与按天汇总的保留天数；Key 和用户累计用量不会随清理删除</div>
          </div>
          <el-icon class="setting-card-arrow" :class="{ 'is-expanded': expandedCards.usageRetention }"><ArrowDown /></el-icon>
        </div>
      </template>
      <div v-show="expandedCards.usageRetention" class="setting-card-body">
        <el-form label-width="160px" v-loading="usageRetentionLoading">
          <el-form-item label="请求明细保留天数">
            <el-input-number v-model="usageRetentionForm.usage_log_retention_days" :min="1" :max="3650" :precision="0" controls-position="right" />
            <div class="form-tip">超过该天数的请求明细会被清理。默认 7 天。</div>
          </el-form-item>
          <el-form-item label="按天汇总保留天数">
            <el-input-number v-model="usageRetentionForm.usage_summary_retention_days" :min="1" :max="3650" :precision="0" controls-position="right" />
            <div class="form-tip">超过该天数的按天汇总会被清理。默认 90 天；不影响 Key 和用户的生命周期累计。</div>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="usageRetentionSaving" @click="saveUsageRetentionConfig">保存</el-button>
          </el-form-item>
        </el-form>
      </div>
    </el-card>

    <!-- 同 Key 重试配置 -->
    <el-card class="setting-card" shadow="never">
      <template #header>
        <div class="setting-card-header" @click="toggleCard('retrySameKey')">
          <div class="setting-card-header-text">
            <div class="panel-title">同 Key 重试配置</div>
            <div class="panel-subtitle">指定提供商且单一 Key 来源时，失败后允许重试同一 Key 而非直接返回错误</div>
          </div>
          <el-icon class="setting-card-arrow" :class="{ 'is-expanded': expandedCards.retrySameKey }"><ArrowDown /></el-icon>
        </div>
      </template>
      <div v-show="expandedCards.retrySameKey" class="setting-card-body">
        <el-form label-width="160px">
          <el-form-item label="启用的提供商">
            <el-input v-model="retrySameKeyProvidersText" placeholder="输入提供商名称，逗号分隔（如 deepseek,bb）" style="max-width: 500px" />
            <div class="form-tip">当请求指定了这些提供商且只有一个可用 Key 时，Key 失败后清空排除列表重试同一 Key，而非直接返回"没有可用的 API Key"。留空则不启用此逻辑</div>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="retrySameKeySaving" @click="saveRetrySameKeyConfig">保存</el-button>
          </el-form-item>
        </el-form>
      </div>
    </el-card>

    <!-- 一键还原 -->
    <el-card class="setting-card" shadow="never">
      <template #header>
        <div class="setting-card-header" @click="toggleCard('factoryReset')">
          <div class="setting-card-header-text">
            <div class="panel-title" style="color: #f56c6c">一键还原</div>
            <div class="panel-subtitle">清除非保留提供商的所有数据，此操作不可逆，请谨慎使用</div>
          </div>
          <el-icon class="setting-card-arrow" :class="{ 'is-expanded': expandedCards.factoryReset }"><ArrowDown /></el-icon>
        </div>
      </template>
      <div v-show="expandedCards.factoryReset" class="setting-card-body">
        <el-form label-width="160px">
          <el-form-item label="保留提供商">
            <el-input
              v-model="factoryResetKeepProviders"
              placeholder="输入保留的提供商名称，逗号分隔（如 bb,bbimg）"
              style="max-width: 500px"
              clearable
            />
            <div class="form-tip">输入需要保留的提供商名称，多个用逗号分隔。这些提供商对应的 Key 及其使用记录将被保留。不输入则清空所有提供商数据。</div>
          </el-form-item>
          <el-form-item>
            <el-button type="danger" :loading="factoryResetLoading" @click="handleFactoryReset">一键还原</el-button>
            <div class="form-tip" style="color: #f56c6c">此操作将永久删除非保留提供商的所有 Key、使用记录、图片任务等数据，且不可恢复。</div>
          </el-form-item>
        </el-form>
      </div>
    </el-card>

    <!-- 使用说明 -->
    <el-card class="setting-card" shadow="never">
      <template #header>
        <div class="setting-card-header" @click="toggleCard('usageGuide')">
          <div class="setting-card-header-text">
            <div class="panel-title">使用说明</div>
            <div class="panel-subtitle">快速获取代理地址、认证方式和接入示例，降低本地应用接入成本</div>
          </div>
          <el-icon class="setting-card-arrow" :class="{ 'is-expanded': expandedCards.usageGuide }"><ArrowDown /></el-icon>
        </div>
      </template>
      <div v-show="expandedCards.usageGuide" class="setting-card-body">
        <div class="usage-guide">
          <h4>1. 配置 API Key</h4>
          <p>在「Key 管理」页面添加您的 OpenAI 或 Claude API Key。</p>
          <h4>2. 使用代理接口</h4>
          <p>将您的应用配置为使用本系统的代理地址：</p>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="代理地址"><code>http://127.0.0.1:8000</code></el-descriptions-item>
            <el-descriptions-item label="认证方式"><code>Authorization: Bearer {{ masterKey || 'YOUR_MASTER_KEY' }}</code></el-descriptions-item>
          </el-descriptions>
          <h4>3. 兼容接口</h4>
          <el-table :data="endpoints" stripe size="small">
            <el-table-column prop="method" label="方法" width="80" />
            <el-table-column prop="path" label="路径" />
            <el-table-column prop="description" label="说明" />
          </el-table>
          <h4>4. 示例代码</h4>
          <el-tabs>
            <el-tab-pane label="Python (OpenAI)">
              <pre class="code-block">from openai import OpenAI

client = OpenAI(
    api_key="{{ masterKey || 'YOUR_MASTER_KEY' }}",
    base_url="http://127.0.0.1:8000/v1"
)

response = client.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "{{ usageGuideDefaultContent }}"}]
)</pre>
            </el-tab-pane>
            <el-tab-pane label="Python (Claude)">
              <pre class="code-block">import anthropic

client = anthropic.Anthropic(
    api_key="{{ masterKey || 'YOUR_MASTER_KEY' }}",
    base_url="http://127.0.0.1:8000"
)

message = client.messages.create(
    model="claude-3-sonnet-20240229",
    max_tokens=1024,
    messages=[{"role": "user", "content": "{{ usageGuideDefaultContent }}"}]
)</pre>
            </el-tab-pane>
            <el-tab-pane label="cURL">
              <pre class="code-block">curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer {{ masterKey || 'YOUR_MASTER_KEY' }}" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "{{ usageGuideDefaultContent }}"}]
  }'</pre>
            </el-tab-pane>
          </el-tabs>
        </div>
      </div>
    </el-card>

    <!-- 修改密码 -->
    <el-card v-if="loginEnabled && authApi.isLoggedIn()" class="setting-card" shadow="never">
      <template #header>
        <div class="setting-card-header" @click="toggleCard('changePassword')">
          <div class="setting-card-header-text">
            <div class="panel-title">修改密码</div>
            <div class="panel-subtitle">修改管理后台的登录密码</div>
          </div>
          <el-icon class="setting-card-arrow" :class="{ 'is-expanded': expandedCards.changePassword }"><ArrowDown /></el-icon>
        </div>
      </template>
      <div v-show="expandedCards.changePassword" class="setting-card-body">
        <el-form ref="passwordFormRef" :model="passwordForm" :rules="passwordRules" label-width="120px">
          <el-form-item label="旧密码" prop="oldPassword">
            <el-input v-model="passwordForm.oldPassword" type="password" show-password placeholder="请输入旧密码" style="max-width: 400px" />
          </el-form-item>
          <el-form-item label="新密码" prop="newPassword">
            <el-input v-model="passwordForm.newPassword" type="password" show-password placeholder="请输入新密码（至少 6 位）" style="max-width: 400px" />
          </el-form-item>
          <el-form-item label="确认新密码" prop="confirmPassword">
            <el-input v-model="passwordForm.confirmPassword" type="password" show-password placeholder="请再次输入新密码" style="max-width: 400px" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="passwordSaving" @click="handleChangePassword">修改密码</el-button>
          </el-form-item>
        </el-form>
      </div>
    </el-card>

    <!-- CC Switch 弹窗 -->
    <el-dialog v-model="ccSwitchDialogVisible" title="填入 CC Switch" width="720px">
      <el-form ref="ccSwitchFormRef" :model="ccSwitchForm" :rules="ccSwitchRules" label-position="top">
        <el-form-item label="应用">
          <el-radio-group v-model="selectedApp" @change="handleAppChange">
            <el-radio-button label="claude">Claude</el-radio-button>
            <el-radio-button label="codex">Codex</el-radio-button>
            <el-radio-button label="gemini">Gemini</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="名称" prop="name">
          <el-input v-model="ccSwitchForm.name" @input="nameTouched = true" />
        </el-form-item>
        <el-form-item label="主模型" prop="model" required>
          <div class="model-field-wrap">
            <el-input v-model="mainModelKeyword" clearable placeholder="搜索模型名称 / ID / 别名" />
            <el-select v-model="ccSwitchForm.model" filterable clearable placeholder="请选择模型">
              <el-option v-for="item in filteredMainModels" :key="item.model_id" :label="`${item.display_name || item.model_id} (${item.model_id})`" :value="item.model_id" />
            </el-select>
          </div>
        </el-form-item>
        <el-form-item>
          <template #label>
            <div class="cc-switch-label-row">
              <span>快捷模型</span>
              <span class="cc-switch-label-tip">支持一键填充，首个按钮来自默认检测模型</span>
            </div>
          </template>
          <div class="shortcut-model-grid">
            <el-button v-for="item in shortcutModelButtons" :key="item.label" :type="ccSwitchForm.model === item.value ? 'primary' : 'default'" plain class="shortcut-model-button" @click="applyShortcutModel(item.value)">
              <span class="shortcut-model-button__label">{{ item.label }}</span>
              <span class="shortcut-model-button__value">{{ item.value || '未配置' }}</span>
            </el-button>
          </div>
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="ccSwitchForm.api_key" />
        </el-form-item>
        <el-form-item label="Base URL">
          <el-input v-model="ccSwitchForm.base_url" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="ccSwitchDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="openingCcSwitch" @click="openCcSwitch">打开 CC Switch</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'
import { adminApi, authApi, copyText } from '../api'
import { useDisplaySettings } from '../stores/displaySettings'

const { state: displayState, setTokenUnitAutoM } = useDisplaySettings()
const tokenUnitAutoM = ref(displayState.tokenUnitAutoM)

const handleTokenUnitChange = (val) => {
  setTokenUnitAutoM(val)
}

// ── 折叠状态管理 ──────────────────────────────────────────
const CARD_STATE_KEY = 'settingsCardExpanded'

const loadCardState = () => {
  try {
    const raw = localStorage.getItem(CARD_STATE_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

const savedCardState = loadCardState()

const expandedCards = reactive({
  auth: savedCardState.auth !== false,           // 默认展开
  display: savedCardState.display !== false,
  providerExt: savedCardState.providerExt ?? false,
  balanceDowngrade: savedCardState.balanceDowngrade ?? false,
  providerMigration: savedCardState.providerMigration ?? false,
  streamBuffer: savedCardState.streamBuffer ?? false,
  proxyTimeout: savedCardState.proxyTimeout !== false,
  imageAutoRefresh: savedCardState.imageAutoRefresh ?? false,   // 默认折叠
  openAIPlusQuotaRefresh: savedCardState.openAIPlusQuotaRefresh ?? false,
  staleTaskCleanup: savedCardState.staleTaskCleanup ?? false,
  keyCheckDefault: savedCardState.keyCheckDefault !== false,
  keyCheckShortcut: savedCardState.keyCheckShortcut ?? false,
  usageGuide: savedCardState.usageGuide ?? false,
  changePassword: savedCardState.changePassword ?? false,
  passThroughError: savedCardState.passThroughError ?? false,
  providerContinueError: savedCardState.providerContinueError ?? false,
  runtimeLog: savedCardState.runtimeLog ?? false,
  proxyTrace: savedCardState.proxyTrace ?? false,
  modelSeed: savedCardState.modelSeed ?? false,
  thinkingMode: savedCardState.thinkingMode ?? false,
  usageRetention: savedCardState.usageRetention ?? false,
  retrySameKey: savedCardState.retrySameKey ?? false,
  intelligentProtocolRouting: savedCardState.intelligentProtocolRouting ?? false,
  factoryReset: savedCardState.factoryReset ?? false,
})

const toggleCard = (key) => {
  expandedCards[key] = !expandedCards[key]
  localStorage.setItem(CARD_STATE_KEY, JSON.stringify({ ...expandedCards }))
}
// ─────────────────────────────────────────────────────────

const masterKey = ref('')
const localMasterKey = ref('')
const showMasterKey = ref(false)
const loginEnabled = ref(false)
const showActualModel = ref(false)
const modelOptions = ref([])
const exportMeta = ref(null)
const usageGuideDefaultContent = computed(() => exportMeta.value?.usage_guide_default_content || 'hello!')
const proxyTimeoutLoading = ref(false)
const proxyTimeoutSaving = ref(false)
const imageAutoRefreshLoading = ref(false)
const imageAutoRefreshSaving = ref(false)
const openAIPlusQuotaRefreshLoading = ref(false)
const openAIPlusQuotaRefreshSaving = ref(false)
const staleTaskCleanupLoading = ref(false)
const staleTaskCleanupSaving = ref(false)
const keyCheckDefaultLoading = ref(false)
const keyCheckDefaultSaving = ref(false)

// 透传错误码
const passThroughErrorLoading = ref(false)
const passThroughErrorSaving = ref(false)
const passThroughErrorCodes = ref([])

// 错误继续规则
const providerContinueErrorLoading = ref(false)
const providerContinueErrorSaving = ref(false)
const providerContinueErrorRules = ref([])

// 运行日志显示
const runtimeLogLoading = ref(false)
const runtimeLogSaving = ref(false)
const runtimeLogEnabled = ref(false)
const runtimeLogWrap = ref(false)

// 代理调试追踪
const proxyTraceLoading = ref(false)
const proxyTraceSaving = ref(false)
const proxyTraceForm = reactive({
  proxy_trace_enabled: false,
  proxy_trace_retention_hours: 24,
  proxy_trace_sample_rate: 1,
  proxy_trace_only_failures: false,
  proxy_trace_target_provider: '',
  proxy_trace_target_model: '',
})

// 模型种子
const modelSeedEnabled = ref(true)

// DeepSeek 思考模式
const thinkingModeRules = ref([])
const thinkingModeSaving = ref(false)

const defaultThinkingModeRule = () => ({
  enabled: true,
  force: false,
  providersText: '',
  modelsText: '',
  thinking_type: 'enabled',
  reasoning_effort: '',
})

const addThinkingModeRule = () => {
  thinkingModeRules.value.push(defaultThinkingModeRule())
}

const removeThinkingModeRule = (index) => {
  thinkingModeRules.value.splice(index, 1)
}

const loadThinkingModeConfig = async () => {
  try {
    const data = await adminApi.getThinkingModeConfig()
    const rules = data?.rules || []
    thinkingModeRules.value = rules.length ? rules.map((r) => ({
      enabled: r.enabled !== false,
      force: !!r.force,
      providersText: (r.providers || []).join(','),
      modelsText: (r.models || []).join(','),
      thinking_type: r.thinking_type || 'enabled',
      reasoning_effort: r.reasoning_effort || '',
    })) : [defaultThinkingModeRule()]
  } catch {
    thinkingModeRules.value = [defaultThinkingModeRule()]
  }
}

const saveThinkingModeConfig = async () => {
  thinkingModeSaving.value = true
  try {
    const rules = thinkingModeRules.value.map((r) => ({
      enabled: !!r.enabled,
      force: !!r.force,
      providers: r.providersText ? r.providersText.split(/[,，]/).map((s) => s.trim()).filter(Boolean) : null,
      models: r.modelsText ? r.modelsText.split(/[,，]/).map((s) => s.trim()).filter(Boolean) : null,
      thinking_type: r.thinking_type || 'enabled',
      reasoning_effort: r.reasoning_effort || '',
    }))
    const data = await adminApi.updateThinkingModeConfig({ rules })
    thinkingModeRules.value = (data?.rules || []).map((r) => ({
      enabled: r.enabled !== false,
      providersText: (r.providers || []).join(','),
      modelsText: (r.models || []).join(','),
      thinking_type: r.thinking_type || 'enabled',
      reasoning_effort: r.reasoning_effort || '',
    }))
    ElMessage.success('思考模式配置已保存')
  } catch (e) { ElMessage.error(e.message || '保存思考模式配置失败') }
  finally { thinkingModeSaving.value = false }
}

// 用量保留期配置
const usageRetentionLoading = ref(false)
const usageRetentionSaving = ref(false)
const usageRetentionForm = reactive({
  usage_log_retention_days: 7,
  usage_summary_retention_days: 90,
})

const loadUsageRetentionConfig = async () => {
  usageRetentionLoading.value = true
  try {
    const data = await adminApi.getUsageRetentionConfig()
    usageRetentionForm.usage_log_retention_days = Number(data?.usage_log_retention_days || 7)
    usageRetentionForm.usage_summary_retention_days = Number(data?.usage_summary_retention_days || 90)
  } catch (e) {
    ElMessage.error(e.message || '加载用量保留期配置失败')
  } finally {
    usageRetentionLoading.value = false
  }
}

const saveUsageRetentionConfig = async () => {
  usageRetentionSaving.value = true
  try {
    const data = await adminApi.updateUsageRetentionConfig({ ...usageRetentionForm })
    usageRetentionForm.usage_log_retention_days = Number(data?.usage_log_retention_days || 7)
    usageRetentionForm.usage_summary_retention_days = Number(data?.usage_summary_retention_days || 90)
    ElMessage.success('用量保留期配置已保存')
  } catch (e) {
    ElMessage.error(e.message || '保存用量保留期配置失败')
  } finally {
    usageRetentionSaving.value = false
  }
}

// 同 Key 重试配置
const retrySameKeyProvidersText = ref('')
const retrySameKeySaving = ref(false)

const intelligentProtocolRoutingLoading = ref(false)
const intelligentProtocolRoutingSaving = ref(false)
const protocolCapabilitiesLoading = ref(false)
const protocolCapabilitiesClearing = ref(false)
const protocolCapabilities = ref([])
const protocolCapabilitiesTotal = ref(0)
const protocolCapabilityFilters = reactive({ provider: '', model: '', protocol: '' })
const intelligentProtocolRoutingForm = reactive({
  enabled: false,
  models_dev_enabled: true,
  models_dev_refresh_hours: 24,
  capability_ttl_hours: 240,
  clientRulesText: '',
  overridesText: '',
})

const loadIntelligentProtocolRoutingConfig = async () => {
  intelligentProtocolRoutingLoading.value = true
  try {
    const data = await adminApi.getIntelligentProtocolRoutingConfig()
    intelligentProtocolRoutingForm.enabled = data?.enabled === true
    intelligentProtocolRoutingForm.models_dev_enabled = data?.models_dev_enabled !== false
    intelligentProtocolRoutingForm.models_dev_refresh_hours = Number(data?.models_dev_refresh_hours || 24)
    intelligentProtocolRoutingForm.capability_ttl_hours = Number(data?.capability_ttl_hours || 240)
    intelligentProtocolRoutingForm.clientRulesText = (data?.client_rules || []).map((r) => `${r.client || ''}|${r.user_agent_contains || ''}`).join('\\n')
    intelligentProtocolRoutingForm.overridesText = (data?.provider_model_overrides || []).map((r) => `${r.provider || ''}|${r.model || r.model_id || ''}|${(r.protocols || r.protocol || []).join(',')}`).join('\\n')
  } catch (e) { ElMessage.error(e.message || '加载智能协议路由配置失败') }
  finally { intelligentProtocolRoutingLoading.value = false }
}

const saveIntelligentProtocolRoutingConfig = async () => {
  intelligentProtocolRoutingSaving.value = true
  try {
    const client_rules = intelligentProtocolRoutingForm.clientRulesText.split(/\\r?\\n/).map((line) => {
      const [client, user_agent_contains] = line.split('|').map((s) => s.trim())
      return client && user_agent_contains ? { client, user_agent_contains } : null
    }).filter(Boolean)
    const provider_model_overrides = intelligentProtocolRoutingForm.overridesText.split(/\\r?\\n/).map((line) => {
      const [provider, model, protocols] = line.split('|').map((s) => s.trim())
      return provider && model && protocols ? { provider, model, protocols: protocols.split(/[,，]/).map((s) => s.trim()).filter(Boolean) } : null
    }).filter(Boolean)
    const data = await adminApi.updateIntelligentProtocolRoutingConfig({
      enabled: !!intelligentProtocolRoutingForm.enabled,
      models_dev_enabled: !!intelligentProtocolRoutingForm.models_dev_enabled,
      models_dev_refresh_hours: intelligentProtocolRoutingForm.models_dev_refresh_hours,
      capability_ttl_hours: intelligentProtocolRoutingForm.capability_ttl_hours,
      client_rules,
      provider_model_overrides,
    })
    intelligentProtocolRoutingForm.enabled = data?.enabled === true
    intelligentProtocolRoutingForm.models_dev_enabled = data?.models_dev_enabled !== false
    intelligentProtocolRoutingForm.models_dev_refresh_hours = Number(data?.models_dev_refresh_hours || 24)
    intelligentProtocolRoutingForm.capability_ttl_hours = Number(data?.capability_ttl_hours || 240)
    intelligentProtocolRoutingForm.clientRulesText = (data?.client_rules || []).map((r) => `${r.client || ''}|${r.user_agent_contains || ''}`).join('\n')
    intelligentProtocolRoutingForm.overridesText = (data?.provider_model_overrides || []).map((r) => `${r.provider || ''}|${r.model || r.model_id || ''}|${(r.protocols || r.protocol || []).join(',')}`).join('\n')
    ElMessage.success('智能协议路由配置已保存')
  } catch (e) { ElMessage.error(e.message || '保存智能协议路由配置失败') }
  finally { intelligentProtocolRoutingSaving.value = false }
}

const loadProtocolCapabilities = async () => {
  protocolCapabilitiesLoading.value = true
  try {
    const data = await adminApi.listProtocolCapabilities(protocolCapabilityFilters)
    protocolCapabilities.value = data?.items || []
    protocolCapabilitiesTotal.value = Number(data?.total || 0)
  } catch (e) { ElMessage.error(e.message || '加载协议能力记录失败') }
  finally { protocolCapabilitiesLoading.value = false }
}

const clearProtocolCapabilities = async () => {
  try {
    await ElMessageBox.confirm('确定清空所有协议能力记录吗？后续请求会重新学习。', '确认清空', { type: 'warning' })
    protocolCapabilitiesClearing.value = true
    await adminApi.clearProtocolCapabilities({ ids: [] })
    await loadProtocolCapabilities()
    ElMessage.success('协议能力记录已清空')
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(e.message || '清空协议能力记录失败')
  } finally { protocolCapabilitiesClearing.value = false }
}

const loadRetrySameKeyConfig = async () => {
  try {
    const data = await adminApi.getRetrySameKeyConfig()
    retrySameKeyProvidersText.value = (data?.providers || []).join(',')
  } catch { retrySameKeyProvidersText.value = '' }
}

const saveRetrySameKeyConfig = async () => {
  retrySameKeySaving.value = true
  try {
    const providers = retrySameKeyProvidersText.value
      ? retrySameKeyProvidersText.value.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
      : []
    const data = await adminApi.updateRetrySameKeyConfig({ providers })
    retrySameKeyProvidersText.value = (data?.providers || []).join(',')
    ElMessage.success('同 Key 重试配置已保存')
  } catch (e) { ElMessage.error(e.message || '保存失败') }
  finally { retrySameKeySaving.value = false }
}

// 一键还原
const factoryResetKeepProviders = ref('')
const factoryResetLoading = ref(false)
const keyCheckShortcutLoading = ref(false)
const keyCheckShortcutSaving = ref(false)

// 供应商密码配置
const providerExtLoading = ref(false)
const providerExtSaving = ref(false)
const providerExtForm = reactive({})
const newProviderName = ref('')
const newProviderPassword = ref('')

const loadProviderExtConfig = async () => {
  providerExtLoading.value = true
  try {
    const data = await adminApi.getProviderExtConfig()
    const providers = data?.providers || {}
    Object.keys(providerExtForm).forEach((k) => delete providerExtForm[k])
    Object.entries(providers).forEach(([k, v]) => {
      providerExtForm[k] = { password: v.password || '' }
    })
  } catch (e) {
    ElMessage.error(e.message || '加载供应商密码配置失败')
  } finally {
    providerExtLoading.value = false
  }
}

const addProviderExt = () => {
  const name = (newProviderName.value || '').trim().toLowerCase()
  if (!name) { ElMessage.warning('请输入供应商名称'); return }
  if (providerExtForm[name]) { ElMessage.warning('该供应商已存在'); return }
  providerExtForm[name] = { password: newProviderPassword.value || '' }
  newProviderName.value = ''
  newProviderPassword.value = ''
}

const removeProviderExt = (provider) => {
  delete providerExtForm[provider]
}

const saveProviderExtConfig = async () => {
  providerExtSaving.value = true
  try {
    const providers = {}
    Object.entries(providerExtForm).forEach(([k, v]) => {
      providers[k] = { password: v.password || '' }
    })
    await adminApi.updateProviderExtConfig({ providers })
    ElMessage.success('供应商密码配置已保存')
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    providerExtSaving.value = false
  }
}

// 余额降权规则
const balanceDowngradeLoading = ref(false)
const balanceDowngradeSaving = ref(false)
const balanceDowngradeRules = ref([])

const loadBalanceDowngradeRules = async () => {
  balanceDowngradeLoading.value = true
  try {
    const data = await adminApi.getBalanceDowngradeRules()
    balanceDowngradeRules.value = (data?.rules || []).map((r) => ({
      min: r.min ?? null,
      max: r.max ?? null,
      action: r.action || 'disable',
      weight: r.weight ?? null,
      providers_str: (r.providers || []).join(','),
    }))
  } catch (e) {
    ElMessage.error(e.message || '加载余额降权规则失败')
  } finally {
    balanceDowngradeLoading.value = false
  }
}

const addBalanceRule = () => {
  balanceDowngradeRules.value.push({ min: null, max: null, action: 'disable', weight: null, providers_str: '' })
}

const removeBalanceRule = (idx) => {
  balanceDowngradeRules.value.splice(idx, 1)
}

const saveBalanceDowngradeRules = async () => {
  balanceDowngradeSaving.value = true
  try {
    const rules = balanceDowngradeRules.value.map((r) => {
      const providers = (r.providers_str || '').split(',').map((s) => s.trim()).filter(Boolean)
      return {
        min: r.min ?? undefined,
        max: r.max ?? undefined,
        action: r.action,
        weight: r.action === 'weight' ? (r.weight ?? 1) : undefined,
        providers: providers.length ? providers : undefined,
      }
    })
    await adminApi.updateBalanceDowngradeRules({ rules })
    ElMessage.success('余额降权规则已保存')
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    balanceDowngradeSaving.value = false
  }
}

// 供应商迁移规则
const providerMigrationLoading = ref(false)
const providerMigrationSaving = ref(false)
const providerMigrationRules = ref([])

const loadProviderMigrationRules = async () => {
  providerMigrationLoading.value = true
  try {
    const data = await adminApi.getProviderMigrationRules()
    providerMigrationRules.value = (data?.rules || []).map((r) => ({
      from_provider: r.from_provider || '',
      to_provider: r.to_provider || '',
      min_balance: r.min_balance ?? 0,
      max_balance: r.max_balance ?? null,
      supported_models_str: (r.supported_models || []).join(','),
    }))
  } catch (e) {
    ElMessage.error(e.message || '加载供应商迁移规则失败')
  } finally {
    providerMigrationLoading.value = false
  }
}

const addProviderMigrationRule = () => {
  providerMigrationRules.value.push({
    from_provider: '',
    to_provider: '',
    min_balance: 0,
    max_balance: null,
    supported_models_str: '',
  })
}

const removeProviderMigrationRule = (idx) => {
  providerMigrationRules.value.splice(idx, 1)
}

const saveProviderMigrationRules = async () => {
  providerMigrationSaving.value = true
  try {
    const rules = providerMigrationRules.value.map((r) => ({
      from_provider: r.from_provider.trim(),
      to_provider: r.to_provider.trim(),
      min_balance: Number(r.min_balance) || 0,
      max_balance: r.max_balance != null && r.max_balance !== '' ? Number(r.max_balance) : undefined,
      supported_models: (r.supported_models_str || '').split(',').map((s) => s.trim()).filter(Boolean),
    }))
    await adminApi.updateProviderMigrationRules({ rules })
    ElMessage.success('供应商迁移规则已保存')
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    providerMigrationSaving.value = false
  }
}

// 流式缓冲规则
const STREAM_RETRY_LIMIT = 3
const streamBufferLoading = ref(false)
const streamBufferSaving = ref(false)
const streamBufferRules = ref([])

const loadStreamBufferRules = async () => {
  streamBufferLoading.value = true
  try {
    const data = await adminApi.getStreamBufferRules()
    streamBufferRules.value = (data?.rules || []).map((r) => ({
      provider: r.provider || '',
      model: r.model || '',
    }))
  } catch (e) {
    ElMessage.error(e.message || '加载流式缓冲规则失败')
  } finally {
    streamBufferLoading.value = false
  }
}

const addStreamBufferRule = () => {
  streamBufferRules.value.push({ provider: '', model: '' })
}

const removeStreamBufferRule = (idx) => {
  streamBufferRules.value.splice(idx, 1)
}

const saveStreamBufferRules = async () => {
  streamBufferSaving.value = true
  try {
    const rules = streamBufferRules.value
      .filter((r) => r.provider || r.model)
      .map((r) => ({ provider: r.provider.trim() || undefined, model: r.model.trim() || undefined }))
    await adminApi.updateStreamBufferRules({ rules })
    ElMessage.success('流式缓冲规则已保存')
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    streamBufferSaving.value = false
  }
}

const ccSwitchDialogVisible = ref(false)
const selectedApp = ref('claude')
const openingCcSwitch = ref(false)
const ccSwitchFormRef = ref(null)
const nameTouched = ref(false)
const mainModelKeyword = ref('')
const haikuModelKeyword = ref('')
const sonnetModelKeyword = ref('')
const opusModelKeyword = ref('')

const passwordFormRef = ref(null)
const passwordSaving = ref(false)
const passwordForm = reactive({ oldPassword: '', newPassword: '', confirmPassword: '' })
const validateConfirmNewPassword = (rule, value, callback) => {
  if (value !== passwordForm.newPassword) callback(new Error('两次输入的密码不一致'))
  else callback()
}
const passwordRules = {
  oldPassword: [{ required: true, message: '请输入旧密码', trigger: 'blur' }],
  newPassword: [{ required: true, message: '请输入新密码', trigger: 'blur' }, { min: 6, message: '新密码至少 6 个字符', trigger: 'blur' }],
  confirmPassword: [{ required: true, message: '请再次输入新密码', trigger: 'blur' }, { validator: validateConfirmNewPassword, trigger: 'blur' }],
}

const ccSwitchForm = reactive({ name: '', model: '', haikuModel: '', sonnetModel: '', opusModel: '' })
const proxyTimeoutForm = reactive({ proxy_request_timeout_seconds: 60, proxy_stream_connect_timeout_seconds: 15, proxy_stream_first_byte_timeout_seconds: 15, proxy_stream_read_timeout_seconds: 45 })
const imageAutoRefreshForm = reactive({ image_auto_refresh_delay_seconds: 60, image_auto_refresh_interval_seconds: 30, image_auto_refresh_max_attempts: 10 })
const openAIPlusQuotaRefreshForm = reactive({
  openai_plus_quota_refresh_concurrency: 5,
  openai_plus_quota_refresh_timeout_seconds: 30,
  openai_plus_quota_token_refresh_timeout_seconds: 60,
})
const staleTaskCleanupForm = reactive({ image_stale_task_cleanup_interval_seconds: 60, image_history_refresh_interval_seconds: 5, image_result_meta_cleanup_interval_seconds: 1800 })
const keyCheckDefaultForm = reactive({ default_key_check_model: '' })
const keyCheckShortcutForm = reactive({ shortcut_models: ['', '', '', '', '', ''] })

const ccSwitchRules = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  model: [{ required: true, message: '请选择主模型', trigger: 'change' }],
}

const endpoints = [
  { method: 'POST', path: '/v1/chat/completions', description: 'OpenAI Chat Completions' },
  { method: 'POST', path: '/v1/completions', description: 'OpenAI Completions' },
  { method: 'POST', path: '/v1/embeddings', description: 'OpenAI Embeddings' },
  { method: 'GET', path: '/v1/models', description: 'OpenAI Models 列表' },
  { method: 'POST', path: '/v1/messages', description: 'Claude Messages' },
]

const defaultNames = computed(() => exportMeta.value?.default_names || { claude: 'local Claude', codex: 'local Codex', gemini: 'local Gemini' })

const filterModels = (items, keyword) => {
  const text = keyword.trim().toLowerCase()
  if (!text) return items
  return items.filter((item) => {
    const label = `${item.display_name || ''} ${item.model_id || ''} ${(item.aliases || []).join(' ')}`.toLowerCase()
    return label.includes(text)
  })
}

const filteredMainModels = computed(() => filterModels(modelOptions.value, mainModelKeyword.value))
const filteredHaikuModels = computed(() => filterModels(modelOptions.value, haikuModelKeyword.value))
const filteredSonnetModels = computed(() => filterModels(modelOptions.value, sonnetModelKeyword.value))
const filteredOpusModels = computed(() => filterModels(modelOptions.value, opusModelKeyword.value))
const shortcutModelButtons = computed(() => {
  const items = keyCheckShortcutForm.shortcut_models.slice(0, 6)
  return [
    { label: '默认检测模型', value: items[0] || keyCheckDefaultForm.default_key_check_model || '' },
    { label: '快捷模型 2', value: items[1] || '' },
    { label: '快捷模型 3', value: items[2] || '' },
    { label: '快捷模型 4', value: items[3] || '' },
    { label: '快捷模型 5', value: items[4] || '' },
    { label: '快捷模型 6', value: items[5] || '' },
  ]
})

const loadMasterKey = async () => {
  localMasterKey.value = localStorage.getItem('masterKey') || ''
  try {
    const data = await adminApi.getMasterKey()
    masterKey.value = data.master_key
    if (data.master_key) { localMasterKey.value = data.master_key; localStorage.setItem('masterKey', data.master_key) }
  } catch (e) { masterKey.value = localMasterKey.value }
}

const loadShowActualModel = async () => {
  try {
    const data = await adminApi.getShowActualModel()
    showActualModel.value = !!data.show_actual_model
  } catch { showActualModel.value = false }
}

const handleShowActualModelChange = async (val) => {
  try {
    await adminApi.updateShowActualModel({ show_actual_model: val })
    ElMessage.success(val ? '已开启显示实际模型' : '已关闭显示实际模型')
  } catch (e) {
    showActualModel.value = !val
    ElMessage.error(e.message || '配置更新失败')
  }
}

const loadModels = async () => {
  try {
    const result = await adminApi.listModels()
    modelOptions.value = Array.isArray(result) ? result : (result.items || [])
  } catch (e) { ElMessage.error(e.message) }
}

const loadExportMeta = async () => {
  try { exportMeta.value = await adminApi.exportConfig() } catch (e) { ElMessage.error(e.message); throw e }
}

const loadProxyTimeoutConfig = async () => {
  proxyTimeoutLoading.value = true
  try { const data = await adminApi.getProxyTimeoutConfig(); Object.assign(proxyTimeoutForm, data) } catch (e) { ElMessage.error(e.message) } finally { proxyTimeoutLoading.value = false }
}

const loadImageAutoRefreshConfig = async () => {
  imageAutoRefreshLoading.value = true
  try { const data = await adminApi.getImageAutoRefreshConfig(); Object.assign(imageAutoRefreshForm, data) } catch (e) { ElMessage.error(e.message) } finally { imageAutoRefreshLoading.value = false }
}

const loadOpenAIPlusQuotaRefreshConfig = async () => {
  openAIPlusQuotaRefreshLoading.value = true
  try { const data = await adminApi.getOpenAIPlusQuotaRefreshConfig(); Object.assign(openAIPlusQuotaRefreshForm, data) } catch (e) { ElMessage.error(e.message) } finally { openAIPlusQuotaRefreshLoading.value = false }
}

const loadStaleTaskCleanupConfig = async () => {
  staleTaskCleanupLoading.value = true
  try { const data = await adminApi.getStaleTaskCleanupConfig(); Object.assign(staleTaskCleanupForm, data) } catch (e) { ElMessage.error(e.message) } finally { staleTaskCleanupLoading.value = false }
}

const loadKeyCheckDefaultConfig = async () => {
  keyCheckDefaultLoading.value = true
  try { const data = await adminApi.getKeyCheckDefaultConfig(); keyCheckDefaultForm.default_key_check_model = data?.default_key_check_model || '' } catch (e) { ElMessage.error(e.message) } finally { keyCheckDefaultLoading.value = false }
}

const loadKeyCheckShortcutModels = async () => {
  keyCheckShortcutLoading.value = true
  try {
    const data = await adminApi.getKeyCheckShortcutModels()
    keyCheckDefaultForm.default_key_check_model = data?.default_key_check_model || keyCheckDefaultForm.default_key_check_model || ''
    keyCheckShortcutForm.shortcut_models = [
      data?.shortcut_models?.[0] || keyCheckDefaultForm.default_key_check_model || '',
      data?.shortcut_models?.[1] || '', data?.shortcut_models?.[2] || '',
      data?.shortcut_models?.[3] || '', data?.shortcut_models?.[4] || '',
      data?.shortcut_models?.[5] || '',
    ]
  } catch (e) { ElMessage.error(e.message) } finally { keyCheckShortcutLoading.value = false }
}

const saveMasterKey = () => { localStorage.setItem('masterKey', localMasterKey.value); ElMessage.success('Master Key 已保存到本地'); location.reload() }

const handleLoginToggle = async (val) => {
  try { await authApi.updateConfig(val); ElMessage.success(val ? '登录验证已开启' : '登录验证已关闭') }
  catch (err) { loginEnabled.value = !val; ElMessage.error(err.message || '配置更新失败') }
}

const handleChangePassword = async () => {
  if (!passwordFormRef.value) return
  try { await passwordFormRef.value.validate() } catch { return }
  passwordSaving.value = true
  try {
    await authApi.changePassword(passwordForm.oldPassword, passwordForm.newPassword)
    ElMessage.success('密码修改成功，请使用新密码重新登录')
    passwordForm.oldPassword = ''; passwordForm.newPassword = ''; passwordForm.confirmPassword = ''
    passwordFormRef.value?.resetFields()
  } catch (err) { ElMessage.error(err.message || '密码修改失败') } finally { passwordSaving.value = false }
}

const saveProxyTimeoutConfig = async () => {
  proxyTimeoutSaving.value = true
  try { const data = await adminApi.updateProxyTimeoutConfig({ ...proxyTimeoutForm }); Object.assign(proxyTimeoutForm, data); ElMessage.success('代理超时配置已保存') }
  catch (e) { ElMessage.error(e.message) } finally { proxyTimeoutSaving.value = false }
}

const saveImageAutoRefreshConfig = async () => {
  imageAutoRefreshSaving.value = true
  try { const data = await adminApi.updateImageAutoRefreshConfig({ ...imageAutoRefreshForm }); Object.assign(imageAutoRefreshForm, data); ElMessage.success('图片自动回填配置已保存') }
  catch (e) { ElMessage.error(e.message) } finally { imageAutoRefreshSaving.value = false }
}

const saveOpenAIPlusQuotaRefreshConfig = async () => {
  openAIPlusQuotaRefreshSaving.value = true
  try { const data = await adminApi.updateOpenAIPlusQuotaRefreshConfig({ ...openAIPlusQuotaRefreshForm }); Object.assign(openAIPlusQuotaRefreshForm, data); ElMessage.success('OpenAI Plus 配额刷新配置已保存') }
  catch (e) { ElMessage.error(e.message) } finally { openAIPlusQuotaRefreshSaving.value = false }
}

const saveStaleTaskCleanupConfig = async () => {
  staleTaskCleanupSaving.value = true
  try { const data = await adminApi.updateStaleTaskCleanupConfig({ ...staleTaskCleanupForm }); Object.assign(staleTaskCleanupForm, data); ElMessage.success('过期任务回收配置已保存') }
  catch (e) { ElMessage.error(e.message) } finally { staleTaskCleanupSaving.value = false }
}

const saveKeyCheckDefaultConfig = async () => {
  keyCheckDefaultSaving.value = true
  try {
    const data = await adminApi.updateKeyCheckDefaultConfig({ default_key_check_model: keyCheckDefaultForm.default_key_check_model })
    keyCheckDefaultForm.default_key_check_model = data?.default_key_check_model || ''
    keyCheckShortcutForm.shortcut_models[0] = keyCheckDefaultForm.default_key_check_model || ''
    await saveKeyCheckShortcutModels()
    ElMessage.success('默认检测模型已保存')
  } catch (e) { ElMessage.error(e.message) } finally { keyCheckDefaultSaving.value = false }
}

const saveKeyCheckShortcutModels = async () => {
  keyCheckShortcutSaving.value = true
  try {
    const data = await adminApi.updateKeyCheckShortcutModels({ default_key_check_model: keyCheckDefaultForm.default_key_check_model, shortcut_models: keyCheckShortcutForm.shortcut_models })
    keyCheckDefaultForm.default_key_check_model = data?.default_key_check_model || ''
    keyCheckShortcutForm.shortcut_models = [
      data?.shortcut_models?.[0] || keyCheckDefaultForm.default_key_check_model || '',
      data?.shortcut_models?.[1] || '', data?.shortcut_models?.[2] || '',
      data?.shortcut_models?.[3] || '', data?.shortcut_models?.[4] || '',
      data?.shortcut_models?.[5] || '',
    ]
    ElMessage.success('已保存快捷模型')
  } catch (e) { ElMessage.error(e.message) } finally { keyCheckShortcutSaving.value = false }
}

const copyMasterKey = async () => { try { await copyText(masterKey.value); ElMessage.success('已复制到剪贴板') } catch { ElMessage.error('复制失败') } }

const setDefaultName = () => { if (nameTouched.value) return; ccSwitchForm.name = defaultNames.value[selectedApp.value] || `local ${selectedApp.value}` }

const pickDefaultModel = () => {
  if (!modelOptions.value.length) { ccSwitchForm.model = ''; return }
  const preferred = exportMeta.value?.default_model
  const matched = modelOptions.value.find((item) => item.model_id === preferred)
  ccSwitchForm.model = matched?.model_id || modelOptions.value[0].model_id
}

const resetClaudeExtraModels = () => {
  ccSwitchForm.haikuModel = ''; ccSwitchForm.sonnetModel = ''; ccSwitchForm.opusModel = ''
  haikuModelKeyword.value = ''; sonnetModelKeyword.value = ''; opusModelKeyword.value = ''
}

const handleAppChange = () => {
  setDefaultName()
  if (!modelOptions.value.some((item) => item.model_id === ccSwitchForm.model)) pickDefaultModel()
  if (selectedApp.value !== 'claude') resetClaudeExtraModels()
}

const openCcSwitchDialog = async () => {
  if (!exportMeta.value) await loadExportMeta()
  selectedApp.value = 'claude'; nameTouched.value = false; mainModelKeyword.value = ''
  resetClaudeExtraModels(); setDefaultName(); pickDefaultModel()
  ccSwitchDialogVisible.value = true
}

const applyShortcutModel = (value) => { if (!value) return; ccSwitchForm.model = value; mainModelKeyword.value = value }

const buildCcSwitchLink = () => {
  const endpointMap = { claude: exportMeta.value?.claude_endpoint, codex: exportMeta.value?.codex_endpoint, gemini: exportMeta.value?.gemini_endpoint }
  const homepage = exportMeta.value?.homepage || 'https://www.wishyouhappy.hahaha'
  const params = new URLSearchParams({ resource: 'provider', app: selectedApp.value, name: ccSwitchForm.name, endpoint: endpointMap[selectedApp.value] || '', apiKey: exportMeta.value?.api_key || masterKey.value, model: ccSwitchForm.model, homepage, enabled: 'true' })
  if (selectedApp.value === 'claude') {
    if (ccSwitchForm.haikuModel) params.set('haikuModel', ccSwitchForm.haikuModel)
    if (ccSwitchForm.sonnetModel) params.set('sonnetModel', ccSwitchForm.sonnetModel)
    if (ccSwitchForm.opusModel) params.set('opusModel', ccSwitchForm.opusModel)
  }
  return `ccswitch://v1/import?${params.toString()}`
}

const openCcSwitch = async () => {
  const valid = await ccSwitchFormRef.value.validate().catch(() => false)
  if (!valid) return
  if (!exportMeta.value) { await loadExportMeta().catch(() => false); if (!exportMeta.value) return }
  openingCcSwitch.value = true
  try { window.location.href = buildCcSwitchLink() }
  catch (e) { ElMessage.error(e.message || '打开 CC Switch 失败，请检查是否已安装并注册协议') }
  finally { openingCcSwitch.value = false }
}

const loadLoginConfig = async () => {
  try { const res = await authApi.getConfig(); loginEnabled.value = !!res.login_enabled } catch { loginEnabled.value = false }
}

// ── 模型种子配置 ──────────────────────────────────────────
const loadModelSeedConfig = async () => {
  try {
    const data = await adminApi.getModelSeedConfig()
    modelSeedEnabled.value = !!data?.model_seed_enabled
  } catch { modelSeedEnabled.value = true }
}

const handleModelSeedChange = async (val) => {
  try {
    const data = await adminApi.updateModelSeedConfig({ model_seed_enabled: val })
    modelSeedEnabled.value = !!data?.model_seed_enabled
    ElMessage.success(val ? '已开启默认模型回填' : '已关闭默认模型回填，模型广场仅展示与 Key 关联的模型')
  } catch (e) {
    modelSeedEnabled.value = !val
    ElMessage.error(e.message || '更新失败')
  }
}

// ── 透传错误码 ──────────────────────────────────────────
const loadPassThroughErrorCodes = async () => {
  passThroughErrorLoading.value = true
  try {
    const data = await adminApi.getPassThroughErrorCodes()
    passThroughErrorCodes.value = data?.pass_through_error_codes || []
  } catch { passThroughErrorCodes.value = [] }
  finally { passThroughErrorLoading.value = false }
}

const savePassThroughErrorCodes = async () => {
  passThroughErrorSaving.value = true
  try {
    const data = await adminApi.updatePassThroughErrorCodes({
      pass_through_error_codes: passThroughErrorCodes.value.map(Number),
    })
    passThroughErrorCodes.value = data?.pass_through_error_codes || []
    ElMessage.success('透传配置已保存')
  } catch (e) { ElMessage.error(e.message || '保存失败') }
  finally { passThroughErrorSaving.value = false }
}

const defaultProviderContinueRule = () => ({
  provider: '*',
  keywords: ['不支持生成图片', '请切换分组'],
  prompt: '继续处理用户原始请求。如果当前分组不支持图片生成，请不要再次调用图片生成能力，改用文本方式完成或说明可执行的替代方案。',
  status_codes: [400, 403],
  enabled: true,
})

const loadProviderContinueErrorRules = async () => {
  providerContinueErrorLoading.value = true
  try {
    const data = await adminApi.getProviderContinueErrorRules()
    providerContinueErrorRules.value = data?.rules?.length ? data.rules : [defaultProviderContinueRule()]
  } catch {
    providerContinueErrorRules.value = [defaultProviderContinueRule()]
  } finally { providerContinueErrorLoading.value = false }
}

const addProviderContinueRule = () => {
  providerContinueErrorRules.value.push(defaultProviderContinueRule())
}

const removeProviderContinueRule = (index) => {
  providerContinueErrorRules.value.splice(index, 1)
}

const saveProviderContinueErrorRules = async () => {
  providerContinueErrorSaving.value = true
  try {
    const data = await adminApi.updateProviderContinueErrorRules({ rules: providerContinueErrorRules.value })
    providerContinueErrorRules.value = data?.rules || []
    ElMessage.success('错误继续配置已保存')
  } catch (e) { ElMessage.error(e.message || '保存错误继续配置失败') }
  finally { providerContinueErrorSaving.value = false }
}

// ── 运行日志显示 ──────────────────────────────────────────
const loadRuntimeLogConfig = async () => {
  runtimeLogLoading.value = true
  try {
    const data = await adminApi.getRuntimeLogConfig()
    runtimeLogEnabled.value = !!data.enabled
    runtimeLogWrap.value = !!data.wrap
  } catch (e) {
    ElMessage.error(e.message || '加载运行日志配置失败')
  } finally {
    runtimeLogLoading.value = false
  }
}

const saveRuntimeLogConfig = async () => {
  runtimeLogSaving.value = true
  try {
    const data = await adminApi.updateRuntimeLogConfig({ enabled: runtimeLogEnabled.value, wrap: runtimeLogWrap.value })
    runtimeLogEnabled.value = !!data.enabled
    runtimeLogWrap.value = !!data.wrap
    window.dispatchEvent(new CustomEvent('runtime-log-config-changed', { detail: { enabled: runtimeLogEnabled.value, wrap: runtimeLogWrap.value } }))
    ElMessage.success('运行日志配置已保存')
  } catch (e) {
    ElMessage.error(e.message || '保存运行日志配置失败')
  } finally {
    runtimeLogSaving.value = false
  }
}

// ── 代理调试追踪 ──────────────────────────────────────────
const loadProxyTraceConfig = async () => {
  proxyTraceLoading.value = true
  try {
    const data = await adminApi.getProxyTraceConfig()
    Object.assign(proxyTraceForm, data || {})
  } catch (e) {
    ElMessage.error(e.message || '加载代理调试追踪配置失败')
  } finally {
    proxyTraceLoading.value = false
  }
}

const saveProxyTraceConfig = async () => {
  proxyTraceSaving.value = true
  try {
    const payload = {
      ...proxyTraceForm,
      proxy_trace_target_provider: (proxyTraceForm.proxy_trace_target_provider || '').trim(),
      proxy_trace_target_model: (proxyTraceForm.proxy_trace_target_model || '').trim(),
    }
    const data = await adminApi.updateProxyTraceConfig(payload)
    Object.assign(proxyTraceForm, data || {})
    ElMessage.success('代理调试追踪配置已保存')
  } catch (e) {
    ElMessage.error(e.message || '保存代理调试追踪配置失败')
  } finally {
    proxyTraceSaving.value = false
  }
}

// ── 一键还原 ──────────────────────────────────────────
const handleFactoryReset = async () => {
  const keepProvidersStr = (factoryResetKeepProviders.value || '').trim()
  const keepProviders = keepProvidersStr
    ? keepProvidersStr.split(/[,，]/).map(s => s.trim()).filter(Boolean)
    : []

  try {
    await ElMessageBox.confirm(
      '此操作将永久删除非保留提供商的所有数据（Key、使用记录、图片任务等），且不可恢复。是否继续？',
      '危险操作确认',
      { confirmButtonText: '我已了解风险，继续', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }

  try {
    const { value } = await ElMessageBox.prompt(
      '请输入"确认还原"以确认执行此操作',
      '最终确认',
      { confirmButtonText: '执行还原', cancelButtonText: '取消', inputPattern: /^确认还原$/, inputErrorMessage: '请输入"确认还原"' },
    )
    if (value !== '确认还原') return
  } catch { return }

  factoryResetLoading.value = true
  try {
    const result = await adminApi.factoryReset({
      keep_providers: keepProviders,
      confirmation: '确认还原',
    })
    ElMessage.success(result.message || '还原完成')
  } catch (e) { ElMessage.error(e.message || '一键还原失败') }
  finally { factoryResetLoading.value = false }
}

onMounted(async () => {
  await Promise.all([
    loadMasterKey(),
    loadLoginConfig(),
    loadModels(),
    loadProxyTimeoutConfig(),
    loadImageAutoRefreshConfig(),
    loadOpenAIPlusQuotaRefreshConfig(),
    loadStaleTaskCleanupConfig(),
    loadKeyCheckDefaultConfig(),
    loadExportMeta().catch(() => false),
    loadKeyCheckShortcutModels(),
    loadProviderExtConfig(),
    loadBalanceDowngradeRules(),
    loadShowActualModel(),
    loadProviderMigrationRules(),
    loadStreamBufferRules(),
    loadPassThroughErrorCodes(),
    loadProviderContinueErrorRules(),
    loadRuntimeLogConfig(),
    loadProxyTraceConfig(),
    loadModelSeedConfig(),
    loadThinkingModeConfig(),
    loadUsageRetentionConfig(),
    loadRetrySameKeyConfig(),
    loadIntelligentProtocolRoutingConfig(),
    loadProtocolCapabilities(),
  ])
})
</script>

<style scoped>
.page-title {
  margin-bottom: 12px;
  color: #303133;
}

.setting-card {
  margin-bottom: 0;
}

/* 折叠 header */
.setting-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  cursor: pointer;
  user-select: none;
}

.setting-card-header:hover .panel-title {
  color: #2563eb;
}

.setting-card-header-text {
  flex: 1;
  min-width: 0;
}

.setting-card-arrow {
  flex: 0 0 auto;
  font-size: 14px;
  color: #909399;
  transition: transform 0.25s ease;
  transform: rotate(-90deg);
}

.setting-card-arrow.is-expanded {
  transform: rotate(0deg);
}

.setting-card-body {
  padding-top: 4px;
}

.form-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 5px;
}

.rule-card {
  margin-bottom: 12px;
  padding: 12px;
  border: 1px solid var(--cpa-panel-border-soft);
  border-radius: 10px;
  background: rgba(37, 99, 235, 0.03);
}

.rule-card__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  color: #1f3b5d;
  font-weight: 700;
}

.cleanup-two-col {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 20px;
  max-width: 780px;
}

.cleanup-col {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.cleanup-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--cpa-text-secondary);
}

.usage-guide h4 {
  margin: 16px 0 8px;
  color: #303133;
}

.usage-guide h4:first-child {
  margin-top: 0;
}

.usage-guide p {
  color: #606266;
  margin-bottom: 8px;
}

code {
  background: #f5f7fa;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: monospace;
}

.code-block {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 15px;
  border-radius: 4px;
  overflow-x: auto;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 13px;
  line-height: 1.5;
}

.model-field-wrap {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}

.master-key-append-button {
  width: 48px;
  min-width: 48px;
  padding: 0;
  color: #6b7280;
}

.cc-switch-label-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}

.cc-switch-label-tip {
  color: #909399;
  font-size: 12px;
}

.shortcut-model-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  width: 100%;
}

.shortcut-model-input-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 24px;
  width: 100%;
}

.shortcut-model-button {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 4px;
  min-height: 54px;
  padding: 10px 12px;
}

.shortcut-model-button__label {
  font-size: 12px;
  color: #6b7280;
}

.shortcut-model-button__value {
  font-size: 13px;
  font-weight: 600;
}

:deep(.el-input-group__append) {
  display: inline-flex;
  align-items: center;
  padding: 0 6px;
}

:deep(.el-input-group__append .el-button) {
  margin: 0;
}

:deep(.el-input-group__append .el-button + .el-button) {
  margin-left: 4px;
}

:deep(.el-input-group__append .el-button--primary) {
  color: #fff;
}

.el-table {
  margin-bottom: 14px;
}

.provider-ext-row {
  margin-bottom: 0;
}

.balance-rule-header,
.balance-rule-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.balance-rule-header {
  font-size: 12px;
  font-weight: 600;
  color: #6b7f99;
  margin-bottom: 8px;
}

.balance-rule-col {
  flex: 1;
  min-width: 0;
}

.balance-rule-col-action {
  flex: 0 0 40px;
}

/* ── 移动端：表单标签改顶部排布，输入框放开固定宽度 ── */
@media (max-width: 768px) {
  /* 各表单 label-width 是 120~180px，390px 宽下输入框只剩一半，
     统一改成标签占一行 */
  :deep(.el-form-item) {
    display: block;
    margin-bottom: 14px;
  }

  :deep(.el-form-item__label) {
    width: auto !important;
    justify-content: flex-start;
    padding: 0 0 4px;
    line-height: 1.4;
    text-align: left;
  }

  :deep(.el-form-item__content) {
    margin-left: 0 !important;
    line-height: 1.5;
  }

  /* 模板里写死的 max-width: 400/500px 在窄屏没有意义，放开占满 */
  :deep(.el-form-item__content .el-input),
  :deep(.el-form-item__content .el-select),
  :deep(.el-form-item__content .el-textarea) {
    max-width: 100% !important;
    width: 100%;
  }

  /* 余额规则那几行是横向 flex，窄屏改纵向 */
  .balance-rule-row {
    align-items: stretch;
    flex-direction: column;
  }

  /* 表头与纵向排布的行对不上，隐藏后由每行自身的占位符表达 */
  .balance-rule-header {
    display: none;
  }

  .balance-rule-col-action {
    flex: 0 0 auto;
  }

  /* 接口清单表格与示例代码块允许横向滚动，不撑破页面 */
  .code-block {
    overflow-x: auto;
    font-size: 11px;
  }
}
</style>
