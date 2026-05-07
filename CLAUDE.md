# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## 项目概述

CPA（Central Proxy for APIs）是一个本地 API Key 中转系统：

- 后端统一管理多组上游 API Key
- 对外暴露兼容 OpenAI / Claude 的代理接口
- 前端提供号池管理、统计面板、配置页面
- 默认使用单一 Master Key 管理后台和代理访问

当前仓库既包含源码，也包含可直接交付的制品目录。

---

## 一、目录结构总览

### 1. 源码目录

#### `backend/`
FastAPI 后端源码。

关键内容：
- `main.py`：应用入口，注册路由、健康检查、前端静态托管
- `config.py`：配置读取，包含 `host`、`port`、`master_key`、超时等
- `database.py`：SQLAlchemy Async engine / session 初始化
- `routers/`
  - `admin.py`：Key、模型、配置等后台管理接口
  - `proxy.py`：OpenAI / Claude 兼容代理接口
  - `stats.py`：统计接口
- `services/`
  - `pool_manager.py`：号池轮询与模型匹配
  - `proxy_service.py`：上游请求转发
  - `usage_tracker.py`：请求用量记录
  - `usage_rollup_service.py`：统计汇总维护
- `models/`：数据库模型
- `data/`：SQLite 数据、`master_key.txt` 等运行数据
- `requirements.txt`：Python 依赖

#### `frontend/`
Vue 3 前端源码。

关键内容：
- `src/main.js`：前端入口
- `src/router.js`：页面路由
- `src/api/index.js`：统一 axios 访问层
- `src/views/`
  - `Dashboard.vue`：总览统计
  - `KeyManage.vue`：Key 管理
  - `UsageStats.vue`：调用统计与日志
  - `Settings.vue`：Master Key 与调用示例
- `dist/`：前端构建产物
- `package.json`：前端脚本定义

### 2. 根目录脚本

仓库根目录还保留了一套“源码开发 / 本机运行”脚本：

- `start.bat`
- `stop.bat`
- `restart.bat`
- `config.bat`

这套脚本的定位是：
- 后端从源码目录启动
- 前端默认使用 Vite dev server
- 支持分别配置前后端端口
- 适合本机开发联调，不是最终发布制品的唯一入口

当前根目录 `config.bat` 默认：
- `BACKEND_PORT=8000`
- `FRONTEND_PORT=3000`
- `BACKEND_HOST=0.0.0.0`

### 3. 制品目录

#### `artifact/`
发布制品目录。

当前可见内容：
- `artifact/release-cpa-20260410/`：发布包目录
- `artifact/release-cpa-20260411.zip`：发布压缩包

`release-cpa-20260410/` 内包含：
- `backend/`
- `frontend/`
- `python/`
- `runtime/`
- `config.bat`
- `start.bat`
- `stop.bat`
- `restart.bat`
- `README-发布包说明.txt`

定位：
- 面向交付的发布包
- 默认由后端直接托管前端页面
- 支持本机 Python 与包内 Python 的运行方式

#### `portable-green/`
全绿色迁移包目录。

包含：
- `backend/`
- `frontend/`
- `python/`
- `config.bat`
- `start.bat`
- `start-debug.bat`
- `stop.bat`
- `restart.bat`
- `README-绿色包说明.txt`

定位：
- 面向无需额外安装 Python / Node 的绿色运行目录
- 依赖自带 `python/` 运行时
- 适合整目录拷贝后直接运行

---

## 二、源码运行方式

### 1. 后端单独运行

```bash
cd backend && pip install -r requirements.txt
cd backend && uvicorn main:app --reload --port 8000
```

或：

```bash
cd backend && python main.py
```

说明：
- 默认端口 `8000`
- 首次启动会自动创建数据库和 `data/master_key.txt`
- 运行目录应在 `backend/`，否则相对路径数据文件可能读错位置

### 2. 前端单独运行

```bash
cd frontend && npm install
cd frontend && npm run dev
cd frontend && npm run build
cd frontend && npm run preview
```

说明：
- Vite 开发环境通过 `/api` 代理到后端
- 源码开发时，前端与后端通常分别运行在不同端口

### 3. 根目录一键启动

```bash
start.bat
```

用途：
- 用于本地开发环境快速同时拉起后端和 Vite 前端
- 默认前端 `3000`、后端 `8000`
- 会优先尝试使用绿色 Python，其次使用系统 Python

---

## 三、制品运行方式

### 1. artifact 发布包

使用目录：`artifact/release-cpa-20260410/`

启动方式：
- 双击 `start.bat`
- 修改端口时编辑 `config.bat`
- 停止用 `stop.bat`
- 重启用 `restart.bat`

特点：
- 发布目录中已经包含前端构建产物
- 后端会直接托管 `frontend/dist`
- `python/` 与 `runtime/` 用于便携运行支持

### 2. portable-green 绿色包

使用目录：`portable-green/`

启动方式：
- 双击 `start.bat`
- 如需看详细报错可双击 `start-debug.bat`
- 修改端口时编辑 `config.bat`
- 停止用 `stop.bat`
- 重启用 `restart.bat`

特点：
- 自带 Python 运行时
- 目标机器无需单独安装 Python 或 Node
- 适合整个目录直接迁移到其他机器后运行

---

## 四、当前架构重点

### 1. 后端也负责托管前端页面

当前后端实现中：
- `backend/main.py` 会从 `backend` 的上级目录查找 `frontend/dist`
- `/` 返回前端首页
- 非 API 路径会走 SPA fallback

这意味着：
- 在发布制品形态下，通常“访问页面的端口”就是后端端口
- 如果后续要实现前后端独立端口，需要额外增加静态入口或网关能力，不能只改 `config.bat`

### 2. 前端接口走同源 `/api`

`frontend/src/api/index.js` 里统一使用：
- `baseURL: '/api'`

这意味着：
- 前端默认假设页面与管理接口同源
- 如果页面和后端分离运行，需要靠代理或网关转发 `/api`
- 不建议轻易改成写死绝对地址

### 3. 代理核心链路

代理主链路：

- `routers/proxy.py`
- `services/pool_manager.py`
- `services/proxy_service.py`
- `services/usage_tracker.py`

行为要点：
- 按 provider 维度轮询可用 key
- 一个请求只会命中一个上游 key
- 普通请求可记录 usage
- 流式请求主要记录状态与耗时

### 4. Master Key 机制

- 管理接口使用 `Authorization: Bearer <master_key>`
- 代理接口支持 `Authorization` 或 `x-api-key`
- 如果未显式配置 `master_key`，系统会读取或生成 `backend/data/master_key.txt`

---

## 五、开发时优先关注的文件

### 后端
- `backend/main.py`
- `backend/config.py`
- `backend/database.py`
- `backend/routers/admin.py`
- `backend/routers/proxy.py`
- `backend/routers/stats.py`
- `backend/services/pool_manager.py`
- `backend/services/proxy_service.py`

### 前端
- `frontend/src/api/index.js`
- `frontend/src/router.js`
- `frontend/src/views/KeyManage.vue`
- `frontend/src/views/Dashboard.vue`
- `frontend/src/views/UsageStats.vue`
- `frontend/src/views/Settings.vue`

### 制品与脚本
- `config.bat`
- `start.bat`
- `stop.bat`
- `restart.bat`
- `artifact/release-cpa-20260410/config.bat`
- `artifact/release-cpa-20260410/start.bat`
- `artifact/release-cpa-20260410/stop.bat`
- `portable-green/config.bat`
- `portable-green/start.bat`
- `portable-green/stop.bat`

---

## 六、已知实现约束

### 1. 制品中的 bat 脚本不能写死绝对路径

这是当前交付约束，必须遵守：
- 制品包内脚本必须优先使用相对路径
- 如果必须使用绝对路径，只能基于脚本所在目录动态计算
- 推荐统一用 `%~dp0`、`PACKAGE_DIR`、派生目录变量处理路径

适用范围：
- `artifact` 发布包
- `portable-green` 绿色包
- 相关 README 说明

### 2. 前端能力高度依赖本地保存的 Master Key

- 前端没有登录态
- 主要依赖浏览器 `localStorage.masterKey`
- `/api/admin/master-key` 可以返回当前 Master Key，适合初始化或开发场景

### 3. 数据与统计注意点

- `ApiKey.weight` 已入库，但当前轮询没有真正使用权重
- `UsageStats.vue` 的日志分页总数是前端估算值，不是后端返回真实 total
- 如果改日志分页，通常需要前后端一起改

---

## 七、制品同步与交付时的建议

当源码有改动，需要更新制品时，优先按以下思路处理：

### 1. 需要同步的核心内容
- `backend/` 最新后端源码
- `frontend/dist/` 最新前端构建产物
- 制品目录内对应的 `backend/`、`frontend/dist/`
- 如脚本行为变更，还需要同步 `config.bat`、`start.bat`、`stop.bat`、`restart.bat`

### 2. 需要重点校验的事项
- 制品脚本中不能出现写死盘符路径
- 从非当前目录执行脚本也能正常找到 `backend`、`frontend`、`python`、`runtime`
- `artifact` 与 `portable-green` 行为尽量保持一致
- 如 `artifact` 目录内容变化，记得重新生成 zip

### 3. 数据库同步安全规则

当需要将源码包代码同步到绿色包或制品包时，必须遵守以下规则：

**同步代码时禁止覆盖运行数据：**
- 同步 `backend/` 源码到 `portable-green/backend` 或 `artifact/.../backend` 时，必须排除 `backend/data/` 目录
- `backend/data/` 包含 `cpa.db`、`master_key.txt`、图片输出等运行数据，覆盖会导致用户历史数据丢失
- 推荐使用 `robocopy` 并加 `/XD data __pycache__` 参数排除

**双向数据库同步优先级：**
- 如果当前正在运行的是绿色包程序（`portable-green/`），在同步源码到绿色包之前，必须先将绿色包的 `backend/data/cpa.db` 同步回源码包的 `backend/data/cpa.db`
- 这样可以避免绿色包运行期间产生的业务数据（图片任务、调用日志等）被源码包的旧数据库覆盖
- 同步顺序：绿色包 DB → 源码包 DB → 再同步代码到绿色包（此时 DB 已一致，代码同步排除 data/ 即可）
- 如果源码包是运行中的程序，则反向操作：源码包 DB → 绿色包 DB

**操作步骤：**
1. 确认哪个目录是当前正在运行的程序
2. 将运行中程序的 DB 备份并复制到另一侧
3. 再执行代码同步（排除 `backend/data/`）
4. 验证两侧 DB 内容一致

### 4. 最小验证建议
- 前端：`cd frontend && npm run build`
- 后端：在正确工作目录下启动 `uvicorn main:app`
- 制品：执行 `start.bat`
- 健康检查：访问 `/health`
- 管理界面：确认首页可打开、管理接口可访问

---

## 八、后续开发建议

1. 涉及代理逻辑时，优先从 `routers/proxy.py` 和 `services/proxy_service.py` 入手
2. 涉及号池选择、模型支持判断时，优先看 `services/pool_manager.py`
3. 涉及 Key 管理、批量操作、管理后台功能时，优先看 `routers/admin.py` 与 `frontend/src/views/KeyManage.vue`
4. 涉及制品启动失败、端口、迁移问题时，优先看各目录下 bat 脚本与 `backend/config.py`
5. 涉及“前端端口 / 后端端口”分离时，先确认当前是源码模式还是发布制品模式，因为两者运行形态不同

---

## 九、当前开发进度

### 1. 前端样式与页面收口

已完成以下页面的浅色科技风统一与间距收口：
- `frontend/src/styles/theme.css`
- `frontend/src/views/Dashboard.vue`
- `frontend/src/views/UsageStats.vue`
- `frontend/src/views/ModelMarket.vue`
- `frontend/src/views/Settings.vue`
- `frontend/src/views/KeyManage.vue`

当前页面风格基线：
- 全站模块间距统一按 `12px` 收口
- 主按钮文字显示问题已修复
- `Settings.vue` 中输入框 append 区按钮拥挤问题已修复
- `Settings.vue` 中主按钮文字颜色已修复为白色
- Key 管理页已调整为更紧凑的后台布局，减少空白并提升单屏信息密度

### 2. Key 管理页功能增强

围绕 `frontend/src/views/KeyManage.vue` 与后台管理接口，已完成以下改动：
- 顶部按钮“批量请求调整信息”已改为“keys调整”
- “导出全部”“一键检测”“keys调整”按钮已统一较稳定的宽度
- 已新增“一键检测”按钮，用于检测 Key 请求地址可用性
- 批量操作范围继续复用现有 `filtered / selected` 模式
- 批量弹窗默认范围与校验逻辑已统一复用筛选条件判断状态

### 3. 前后端一键检测实现状态

已完成接口与服务主链路升级：
- `frontend/src/api/index.js`
  - 已保留 `adminApi.batchCheckKeyEndpoints`
  - 已新增 `adminApi.checkKey`
- `backend/routers/admin.py`
  - `/keys/batch/check` 已升级为“地址 + 指定模型”检测请求结构
  - 已新增 `/keys/{key_id}/check` 单项检测接口
  - 已继续支持 `filtered / selected` 两种范围参数结构
- `backend/services/proxy_service.py`
  - 已保留 Key 地址探测能力
  - 已新增指定模型最小化真实调用检测能力
  - 已新增失败分类归并能力
  - 已支持输出地址检测结果、模型检测结果、失败分类、失败详情、总耗时等信息
- `frontend/src/views/KeyManage.vue`
  - “一键检测”已改为先弹出“检测配置”对话框
  - 主表“备注”列已改为“检测结果”列
  - 已新增失败详情对话框
  - 已改为前端受控并发逐项调用单项检测接口，并在主表实时回写结果

当前检测能力说明：
- 点击“一键检测”后，先输入待检测模型，再开始检测
- 每个 Key 会先做地址探测，再做目标模型调用检测
- 主表会逐项实时显示检测状态，而不是等待全部完成后再统一弹窗汇总
- 成功项显示绿色耗时
- 失败项显示红色失败分类链接
- 点击失败分类链接可查看具体失败原因
- 当前 `filtered` 模式按“当前页已加载结果”逐项检测，未扩展到“命中筛选条件的全部分页数据”

### 4. 已完成验证

已完成的验证：
- 前端构建通过：`cd frontend && npm run build`
- 后端语法校验通过：`cd backend && python -m py_compile routers/admin.py services/proxy_service.py`
- 源码后端健康检查通过：访问 `/health` 返回正常
- Vite 前端页面可访问：`/keys` 页面已通过浏览器截图方式确认可打开

当前联调结论：
- 代码层主链路已完成并通过静态校验
- 页面入口可正常打开
- 浏览器自动化完整联调尚未完全走通，当前阻塞点在本机 Playwright 运行环境，而不是业务接口本身

### 5. 当前剩余事项

以下内容仍建议继续验证：
- 在真实浏览器交互中完整走通“一键检测”流程
- 验证输入模型后是否按预期逐项实时刷新主表结果
- 验证成功项是否稳定显示绿色耗时
- 验证失败项是否稳定显示红色失败分类链接，并可正常弹出详情框
- 验证 `selected` 范围检测是否正常
- 验证 `filtered` 范围检测是否符合当前页范围预期
- 验证未输入模型、未勾选项、无筛选条件等边界提示是否正确
- 验证超时、401/403、404、429、502、503、5xx、请求错误、未知错误等失败分类展示是否清晰
- 如需继续做浏览器自动化联调，需先补齐本机 Playwright 可执行脚本/测试环境
- 如源码改动需要同步到交付包，还需同步更新制品目录中的前端构建产物与后端源码

### 6. 最近新增改动与交付同步状态

已完成的新增改动：
- `frontend/src/views/KeyManage.vue`
  - 已新增“一键删除”按钮，位置在 `keys调整` 后
  - “一键删除”按钮样式已调整为与 `keys调整` 保持一致，不再使用危险按钮风格
  - 一键检测默认范围已改为：优先使用当前勾选项；未勾选时才按当前筛选条件检测
  - 检测弹窗内按回车已改为只触发“开始检测”，不再触发当前页面筛选查询
  - 一键检测失败详情已补充更具体的错误信息，汇总展示总体错误、地址探测错误、模型检测错误
  - 一键检测当前已采用“前端并发逐项调用单项检测接口”的方式，避免批量接口单次请求过长导致整体超时
- `frontend/src/api/index.js`
  - 已新增 `adminApi.batchDeleteKeys`
- `backend/routers/admin.py`
  - 已新增 `/keys/batch/delete` 批量删除接口

交付同步状态：
- 已同步最新后端到：`portable-green/backend`、`artifact/release-cpa-20260410/backend`
- 已同步最新前端构建产物到：`portable-green/frontend/dist`、`artifact/release-cpa-20260410/frontend/dist`
- 已重新生成压缩包：`artifact/release-cpa-20260419.zip`

当前关于交付包的结论：
- 用户已明确：`green` 包和制品包当前阶段先不要做“去源码化”处理
- 原因是现有交付目录仍依赖 `backend/*.py` 直接运行，若直接移除源码会导致包无法启动
- 如后续要做真正“无源码交付”，需要单独设计后端可执行化打包方案，而不是直接删除 Python 文件

### 7. 当前可回滚备份

已创建当前项目备份，便于后续功能改动失败时还原：
- 备份文件：`D:/AI/cpa-backup-20260419_004800.zip`
- 备份说明：该备份排除了常见缓存与依赖目录，例如 `node_modules`、`__pycache__`、`.vite`、`dist`

### 8. 当前进行中的独立出口代理改造

当前正在推进“单个 Key 可配置是否启用独立出口代理”能力，并继续扩展“单个 Key 可配置是否启用独立伪装 IP 头”能力，当前已完成：
- `backend/models/api_key.py`
  - 已保留 `enable_proxy`、`proxy_url`、`proxy_username`、`proxy_password` 字段
  - 已新增 `enable_fake_ip`、`fake_ip` 字段
- `backend/database.py`
  - 已按现有 SQLite 增量迁移方式补充独立代理字段自动建列逻辑
  - 已新增 `enable_fake_ip`、`fake_ip` 的自动建列逻辑
- `backend/routers/admin.py`
  - `ApiKeyCreate`、`ApiKeyUpdate`、`ApiKeyResponse`、`ApiKeyBatchImportItem` 已接入独立代理字段
  - 已继续接入 `enable_fake_ip`、`fake_ip` 字段透传
  - 已增加伪装 IP 最小校验：启用时必须填写合法 IPv4 / IPv6；关闭时自动清空
  - Key 新增、编辑、导入、导出、复制配置链路已接入 fake IP 字段
  - 已新增 `/keys/batch/fake-ip` 批量接口，仅接收 `key_ids`
  - 已支持为勾选 Key 批量开启独立 fake IP，并自动分配 `198.51.100.x` 保留测试网段地址
  - 已支持为勾选 Key 批量关闭 fake IP，并清空 `fake_ip`
- `backend/services/proxy_service.py`
  - 已保留按 Key 构造 `httpx.AsyncClient` 代理参数的逻辑
  - fake IP 写头已收敛为仅写 `X-Forwarded-For` 与 `X-Real-IP`
- `frontend/src/views/KeyManage.vue`
  - Key 新增/编辑表单已新增“伪装 IP”开关
  - 开启后显示 IP 输入项，关闭后提交时清空 `fake_ip`
  - 已补充前端合法 IP 校验
  - 已补充复制配置、复制记录、导入模板、一键导入的数据字段支持
  - 已在 `keys调整` 弹窗中新增“独立 fake IP”模式：`不修改 / 开启并分配 / 关闭并清空`
  - fake IP 批量操作当前仅允许“当前勾选项”，不支持 `filtered` 范围
  - 已支持同一次弹窗内顺序提交“地址/模型/权重调整”与“fake IP 批量开关”
- `frontend/src/api/index.js`
  - 已新增 `adminApi.batchSetKeysFakeIp`
- `frontend/tests/key-proxy-verify.spec.js`
  - 已扩展 Playwright CLI 验收脚本，同时覆盖独立代理与 fake IP 字段保存/回显断言
  - 已新增批量 fake IP 开启/关闭场景断言

当前已确认的问题与结论：
- 之前看到的“`PUT /api/admin/keys/{id}` 返回 200 但页面回显仍缺少 proxy 字段”问题，根因不在前端提交逻辑；当前源码里的 `admin.py` 保存链路本地直连数据库已可写入 proxy 字段
- 当前正在运行的 `8000` 服务仍未加载最新代码，因此接口回显还未体现 `enable_proxy / proxy_url / proxy_username / proxy_password / enable_fake_ip / fake_ip`
- 还需要使用最新源码重新启动后端，并让旧数据库自动补齐新列后再做最终接口与页面验收
- 用户已确认 green 包和制品包同步更新已验证

当前仍待完成：
- 用最新源码重新启动后端，确认 `api_keys` 表自动补齐 `enable_fake_ip`、`fake_ip`
- 继续验证 `GET /api/admin/keys/{id}` 与 `PUT /api/admin/keys/{id}` 对 proxy/fake IP 字段的保存与回显
- 继续做 Playwright CLI 真实浏览器验收
- 继续验证 `keys调整` 中批量开启/关闭独立 fake IP 的页面交互与接口回显
- 如需最终验收，继续验证启用/未启用独立代理、启用/未启用 fake IP 的普通请求、流式请求、一键检测请求是否按预期生效

本轮已完成验证：
- 后端语法校验通过：`cd backend && python -m py_compile routers/admin.py services/proxy_service.py database.py models/api_key.py`
- 前端构建通过：`cd frontend && npm run build`
- 本地直接使用 SQLAlchemy 会话写入 `api_keys` 表时，`enable_proxy / proxy_url / proxy_username / proxy_password` 已确认可落库
- Playwright CLI 已重新运行，但当前断言仍命中旧后端进程，尚不能作为最新代码验收结论
- 本轮新增代码的最小静态校验已通过：`python -m py_compile backend/routers/admin.py`、`npm run build`

本轮交付同步结果：
- 已同步 `backend/` 最新源码到：`portable-green/backend`、`artifact/release-cpa-20260410/backend`
- 已同步 `frontend/dist/` 最新构建产物到：`portable-green/frontend/dist`、`artifact/release-cpa-20260410/frontend/dist`

当前实现约束：
- `enable_proxy / proxy_url ...` 控制的是按 Key 走指定代理出口，可能影响真实出口 IP
- `enable_fake_ip / fake_ip` 控制的是按 Key 覆盖显示/透传类 IP 请求头，不改变真实网络层来源地址
- 不同上游是否采信这些 IP 头仍取决于上游自身规则；当前实现只保证 CPA 发出的头部会按 Key 覆盖写出
- 批量 fake IP 当前只对 `selected` 勾选项生效，避免在 `filtered` 范围下误改大量 Key

### 10. 当前新增的 Key ID 批量筛选能力

围绕 `frontend/src/views/KeyManage.vue` 与 `backend/routers/admin.py`，已新增 Key ID 作为列表筛选条件，当前实现包括：
- Key 管理筛选区已新增 Key ID 输入框
- 支持一次输入多个 Key ID
- 支持英文逗号 `,` 与中文逗号 `，` 混合分隔
- 前端输入示例 `1,2,3，4` 会解析为多个独立 Key ID 条件
- 前端已对非法输入做拦截，仅允许正整数 Key ID
- `/api/admin/keys` 已新增 `key_ids` 查询参数支持
- 后端列表查询已支持按 `ApiKey.id.in_(...)` 过滤
- 现有 `filtered` 范围批量操作已兼容 Key ID 筛选条件透传

当前待验证：
- 后端语法校验
- 前端构建
- 页面实际输入 `1,2,3，4` 后的列表回显

### 11. 当前图片广场能力

围绕“图片广场 / 图片中转站”能力，当前已完成以下主链路：
- `backend/models/image_generation_task.py`
  - 已新增 `ImageGenerationTask` 与 `ImageGenerationTaskResult`
  - 图片生成按“任务 + 单图结果”沉淀历史
  - 任务记录模型、提示词、请求参数、命中 Key、状态、成功/失败统计、错误摘要等信息
  - 结果记录单图 URL / base64、状态、错误详情、来源 Key、生成时间等信息
- `backend/models/__init__.py`
  - 已导出图片任务与结果模型，确保 SQLAlchemy metadata 可自动建表
- `backend/database.py`
  - 已接入图片历史表初始化
- `backend/services/proxy_service.py`
  - 已新增图片生成专用转发能力，不改动文本代理主链路
  - 已支持 OpenAI Images 兼容格式 `/v1/images/generations`
  - 已支持 Chat 兼容格式 `/v1/chat/completions`
  - 已对 URL / base64 图片结果做统一归一，便于前端展示
  - 已复用现有 Key 独立代理与 fake IP 头处理逻辑
- `backend/routers/admin.py`
  - 已新增图片模型白名单：`gpt-image-2`、`gpt-image-1-vip`、`gpt-image-1`、`nano-banana-pro`、`nano-banana-pro-4k`
  - 已新增图片模型列表接口，按“启用且支持目标模型”的 Key 数返回可用模型
  - 已新增图片生成接口，复用现有 Key 轮询机制选择可用 Key
  - 已新增图片任务历史、任务详情、任务结果、Key 成功率相关接口
  - 已接入图片生成失败策略：连续失败 3 次降低权重，连续失败 5 次禁用 Key
- `frontend/src/api/index.js`
  - 已新增图片模型、图片生成、图片任务列表、任务详情、任务结果、Key 成功率接口封装
- `frontend/src/router.js`
  - 已新增 `/images` 路由
- `frontend/src/App.vue`
  - 已新增“图片广场”菜单，并放在“模型广场”下方
- `frontend/src/views/ImageSquare.vue`
  - 已完成图片广场主页面
  - 页面保持 CPA 当前蓝系科技风，不使用偏粉色风格
  - 包含图片生成、模型选择、提示词、尺寸、质量、数量、请求格式、生成结果、历史记录、Key 统计弹框、提示词样例弹框
  - “提示词”已作为页面文案使用，不再使用 Prompt 作为主标签
  - 生成结果与历史记录为同宽折叠区域
  - 可用模型列表展示每个模型满足条件的 Key 数，点击 Key 数可查看对应 Key 的成功率和生成次数
  - 图片尺寸下拉已扩展手机、平板、社媒、桌面等常用尺寸
  - 提示词示例已合并为一个示例集合，不再按多组分类铺开
  - `主体`、`场景`、`镜头构图`、`风格`、`光线` 已作为描述中的内联超链接，可点击查看具体提示词样例
  - 已去掉提示词区域多余的“示例”标题
  - 已去掉“图片生成”和“可用模型”两个卡片标题下方的文字描述
  - 提示词示例区已改为折叠面板，并默认折叠
  - 连续生成 5 次后会提示用户确认是否继续

当前图片广场验证状态：
- 前端构建已通过：`cd frontend && npm run build`
- Key 315 已作为真实图片 Key 用于后端生成链路验证，`gpt-image-2` 任务可成功返回并写入历史
- 最新前端构建产物已同步到：`portable-green/frontend/dist`、`artifact/release-cpa-20260410/frontend/dist`
- 本轮最后一次调整仅涉及前端图片广场 UI，未改动后端源码

当前图片广场仍待完成 / 建议继续验证：
- 使用 Playwright CLI + 系统 Chrome 真实打开 `/images` 页面，验证最新布局是否符合截图要求
- 验证提示词示例区默认折叠、展开后链接与样例弹框可正常使用
- 验证 `主体`、`场景`、`镜头构图`、`风格`、`光线` 内联链接的样例查看、复制、插入提示词能力
- 验证 `gpt-image-2` 在页面端完整生成、展示图片、复制 URL、下载图片、写入历史
- 验证 `nano-banana-pro` 与 `nano-banana-pro-4k` 的 Images / Chat 兼容格式生成链路
- 验证无可用 Key、Key 不支持模型、上游返回错误、超时、429、5xx 等失败场景的页面提示与历史记录
- 验证连续失败 3 次降权、连续失败 5 次禁用 Key 的策略是否按预期生效
- 验证连续生成 5 次后的继续确认提示是否稳定触发
- 如需最终交付压缩包，还需要基于最新 `artifact/release-cpa-20260410` 重新生成 zip
