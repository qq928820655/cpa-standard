# 运维侧本地改造清单（与上游源码的差异说明）

本文件记录**本仓库相对上游发布包所做的运维改造**，逐条说明：改了什么、为什么改、
怎么改的、如何验证。目的是让后续接手的人或 AI 能直接定位改动意图，而不用反推代码。

- 基线：上游 Linux 发布包（`cpa-linux`，2026-10-14 版）
- 适用：本机 Firecracker microVM / Debian 12 / 原生 python3 + uvicorn（不用 Docker）
- 改造原则：**只改必要处、保持与上游行为兼容、默认值不变时可随时回退**

---

## 一、修改总览

| # | 文件 | 改动 | 触发原因 | 风险 | 本次上传 |
|---|---|---|---|---|---|
| 1 | `backend/main.py` | 插件路由注册位置提前到 SPA catch-all 之前 | 插件后端接口全部返回 HTML | 低（纯顺序调整） | 是 |
| 2 | `backend/services/proxy_service.py` + `backend/routers/proxy.py` + `backend/config.py` | 传输层失败与上游故障分离 | 一次网络抖动把健康 Key 封 120s | 低（只改错误分类与冷却时长） | 是 |
| 3 | `backend/services/proxy_service.py` | 超时预算不再被 60s 重试预算截断 | 合法长生成在 60s 整被杀 | 中（放宽了读超时） | 是 |
| ~~4~~ | `backend/services/proxy_service.py` | ~~`finish_reason` 初始化~~ | **仓库版本已正确，无需修改**；本地部署缺失（见 §4） | — | 否 |
| ~~5~~ | `backend/services/proxy_service.py` | ~~重复的 upstream 计时行~~ | **仓库版本已正确，无需修改**；本地部署存在（见 §5） | — | 否 |
| 6 | `frontend/src/views/Settings.vue` | 使用说明示例地址改为运行时来源 | 面板显示写死的 `127.0.0.1:8000` | 低（纯展示） | 是 |

---

## 二、逐条说明

### 1. 插件后端路由被 SPA catch-all 遮蔽（P0）

**现象**

调用 `/api/admin/video/*`（video-world 插件）返回 `200 text/html`——内容是前端
`index.html`，而不是插件的 JSON 响应。同一时期 `/api/admin/plugins` 却正常。
带 master key 访问也照样返回 HTML，很容易误判成"权限问题"或"插件没装上"。

**原因**

上游把 `plugin_service.load_backend_plugins(app)` 放在 FastAPI 的 `lifespan()`
里调用，而 `lifespan` 在**应用启动时**才执行；`@app.get("/{full_path:path}")` 这个
SPA catch-all 是在**模块导入时**就注册好的。Starlette 的路由按注册顺序匹配，于是
catch-all 先命中，把插件路由全部吃掉。

**修改**（`backend/main.py`）

- 从 `lifespan()` 中删除 `plugin_service.load_backend_plugins(app)`
- 改到模块级调用，位置在**所有 `include_router(...)` 之后、`@app.get("/")` 与
  `@app.get("/{full_path:path}")` 之前**

```python
app.include_router(grok_admin_router, prefix="/api/admin/grok", tags=["grok-admin"])
app.include_router(grok_proxy_router, prefix="/grok", tags=["grok-proxy"])

# 本地修复：插件后端路由必须在下方 SPA catch-all (/{full_path:path}) 之前注册，
# 否则被 catch-all 遮蔽会全部返回前端 index.html（上游包在 lifespan 内注册导致）。
plugin_service.load_backend_plugins(app)
```

**验证**

```bash
# 1) 路由表顺序：插件路由必须在 catch-all 之前
python3 - <<'EOF'
import sys; sys.path.insert(0,'backend')
import main
paths=[getattr(r,'path','') for r in main.app.routes]
idx=paths.index('/{full_path:path}')
print('catch-all at', idx, 'video routes before:', sum(1 for p in paths[:idx] if '/video' in p))
# 期望：video routes before: 61（安装 video-world 插件后）
EOF

# 2) 真实请求返回 JSON 而不是 HTML
curl -s -o /dev/null -w '%{http_code} %{content_type}\n' \
  -H "Authorization: Bearer $(cat backend/data/master_key.txt)" \
  http://127.0.0.1:8000/api/admin/video/ffmpeg/preflight
# 期望：200 application/json
```

> 注意：`load_plugin_models()` 仍然留在 `lifespan` 里——它负责在 `init_db` 之前
> 注册 ORM 模型，时序要求与路由不同，不要一起挪。

---

### 2. 传输层失败与上游故障分离（P0）

**现象**

某个上游（wk 国际版）的 Key 突然被冷却 120 秒，期间所有客户端请求 503，但查上游
日志发现**它当时根本没收到请求**。重启/等待 2 分钟后自行恢复，过一阵又复发。

**原因**

出站 TLS 握手偶发被丢包（本机 egress 特性，独立脚本可复现）→ `httpx` 在**发送
阶段**就抛异常 → `proxy_service` 把它归成 `500/502/504` → `routers/proxy.py` 看到
`status >= 500` 就按"上游故障"处理：冷却 120s + 计入 provider 熔断。

但这类错误**根本没走到上游**，上游完全健康。用 120 秒的惩罚去应对一次毫秒级的网络
抖动，代价过大。

**修改**

1. `backend/services/proxy_service.py`：20 处发送阶段异常返回点（`forward_request`
   ×4、`forward_stream` ×3、`forward_stream_buffered` ×4、`forward_image_request`
   ×4、`forward_audio_request` ×3、`forward_non_stream` ×2）在返回的 body 上加
   `"cpa_transport_error": True`

2. `backend/routers/proxy.py`：新增判定函数与短冷却常量

```python
TRANSPORT_ERROR_COOLDOWN_SECONDS = 10

def is_transport_stage_error(response_data: Any) -> bool:
    return isinstance(response_data, dict) and bool(response_data.get("cpa_transport_error"))
```

3. 三处冷却点分流：传输层失败只冷却 10s（日志带 `reason=transport_stage`），
   真上游 5xx 维持原冷却时长
4. 两处 `pool_manager.record_provider_failure(...)` 排除传输层失败（不罚熔断）

5. `backend/config.py`：`proxy_stream_connect_timeout_seconds` 15 → 5
   （连接阶段本来就该快速失败；读阶段仍是 180s，不受影响）

**为什么只改冷却时长、不改重试语义**

传输层失败仍然会换 Key 重试（行为不变），只是不再把 Key 打进长时间冷却。这样
"上游真的挂了"和"本机网络抖了一下"有了不同的代价。

**验证**

```bash
# 死端口 = 传输层失败；应只冷却 10s、不计熔断
python3 - <<'EOF'
import asyncio, sys; sys.path.insert(0,'backend')
from services.proxy_service import ProxyService
from database import async_session_maker
import routers.proxy as P

class K:
    id=1; provider='test'; name='test'; base_url='http://127.0.0.1:1'
    api_key='x'; protocol='openai'; extra=None; models=None
    model_mapping=None; weight=1

async def main():
    async with async_session_maker() as db:
        code,h,body = await ProxyService().forward_request(
            db, K(), "POST", "/v1/chat/completions", {},
            {"model":"x","messages":[]}, attempt_timeout_seconds=3)
    print("is_transport:", P.is_transport_stage_error(body))   # True
    print("plain 500 :", P.is_transport_stage_error({"error":{"message":"boom"}}))  # False
asyncio.run(main())
EOF

# 日志确认
grep "reason=transport_stage" runtime/logs/linux-backend.log | tail -5
```

---

### 3. 60s 重试预算被误当读超时，截断合法生成（P1）

**现象**

非流式的大生成在 **60 秒整**稳定失败（`ReadTimeout`，usage_logs 里耗时 60.0–60.8s）；
流式健康长流也会在 60s 被掐；日志出现"缓冲窗口读取失败"。

**原因**

`proxy_retry_total_budget_seconds=60` 是**重试总预算**，但代码把它当成单次请求的
读超时传给了 `httpx.Timeout(remaining)`。于是一次合法的 90 秒生成必然在 60s 被杀。

**修改**（`backend/services/proxy_service.py`）

| 位置 | 原来 | 现在 |
|---|---|---|
| 非流式 `request_timeout` | `httpx.Timeout(remaining)` | 读超时 `proxy_request_timeout_seconds`(180s)，连接/写/池 `min(remaining, connect_timeout)` |
| 缓冲流 `read` | `remaining` | `max(proxy_timeout, 300)` |
| 流式 `read` | `remaining` | `proxy_stream_read_timeout_seconds`(180s) |
| 缓冲流总 deadline | 60s 预算 | `proxy_request_timeout_seconds` |
| 缓冲流首包 | 无保护 | 15s `asyncio.wait_for` 首包保护 |

**首包保护的作用**：缓冲模式要等上游第一个字节才能判断"这个 Key 是否可用"。没有
首包超时的话，一个不响应的上游会一直占着连接，直到总 deadline 才失败——期间其他
Key 完全没机会接手。

**验证**

```bash
# 本地起一个 70s 才返回的慢上游，请求应 200 而不是 60s 超时
# （修复前必死 60s，修复后 200@70s）
```

---

### 4. 【仅本地部署问题】`finish_reason` 未初始化导致 `UnboundLocalError`

> **仓库版本已经是正确的**（`backend/services/proxy_service.py` 在 `try` 之前有
> `finish_reason = None`），本条不需要上传。记录在此是因为**本机部署目录**
> 在历次手工打补丁时把这一行删掉了，需要本地补回。

**现象**

流式请求在上游报错（还没收到任何 `finish_reason` 事件）时，客户端看到的是
`UnboundLocalError: local variable 'finish_reason' referenced before assignment`
而不是真实的上游错误。

**原因**

`forward_stream()` 内层的 `stream_generator()` 里，`finish_reason` 只在两个 `if`
分支中赋值（收到 finish_reason 事件时）。但 `finally` 块会把它传给
`_log_pup_output_diagnostic(...)`。如果流在赋值之前就异常退出，`finally` 读取未绑定
的局部变量 → 抛 `UnboundLocalError`，把原始异常盖掉。

**本地修复**（不是本次上传内容）

```python
last_synced_tokens = (0, 0, 0, 0)
# 必须在 try 之前初始化：finally 里的 _log_pup_output_diagnostic 会读它，
# 若流在收到任何 finish_reason 事件之前就抛异常，读取未绑定局部变量会抛
# UnboundLocalError 并盖掉真正的上游错误。
finish_reason = None
stream_started_at = time.perf_counter()
```

**检查命令**

```bash
python3 - <<'EOF'
import ast
src=open('backend/services/proxy_service.py',encoding='utf-8-sig').read()
for node in ast.walk(ast.parse(src)):
    if isinstance(node,ast.AsyncFunctionDef) and node.name=='stream_generator':
        stores=[n.lineno for s in node.body for n in ast.walk(s)
                if isinstance(n,ast.Name) and n.id=='finish_reason' and isinstance(n.ctx,ast.Store)]
        print('finish_reason stores:', sorted(stores))  # 最小行号必须早于 try 块
EOF
```

---

### 5. 【仅本地部署问题】缓冲流 upstream 计时重复累加

> **仓库版本已经是正确的**（只有一对 `upstream_wait_seconds += ...`），本条不需要
> 上传。记录在此是因为**本机部署目录**在加首包保护时把这两行复制成了四行。

**现象**

`upstream_latency_ms` 约为实际值的两倍，`cpa_overhead_ms` 相应偏小。

**原因**

首包保护改造时，`upstream_wait_seconds += ...` 与 `upstream_wait_start = ...`
两行被复制粘贴了两遍，同一段时间被累加两次。

**本地修复**：删掉重复的一对赋值行。

**检查命令**

```bash
# 在首包保护循环内，这两行应各出现一次（不能连续出现两对）
sed -n '/首包保护/,+12p' backend/services/proxy_service.py
```

---

### 6. 使用说明里的示例地址写死 `127.0.0.1:8000`（展示）

**现象**

系统设置 →「使用说明」里的代理地址、OpenAI/Claude/cURL 示例全部写死
`http://127.0.0.1:8000`。通过预览域名或局域网 IP 打开面板时，用户照着复制会连不上。

**原因**

`frontend/src/views/Settings.vue` 模板里直接写了字面量。

**修改**

- 新增 `const proxyBaseUrl = computed(() => window.location.origin)`
- 模板 4 处改为插值：代理地址 `{{ proxyBaseUrl }}`、OpenAI `base_url="{{ proxyBaseUrl }}/v1"`、
  Claude `base_url="{{ proxyBaseUrl }}"`、cURL `curl {{ proxyBaseUrl }}/v1/chat/completions`

**为什么改源码而不是改构建产物**

上游仓库只有 `frontend/src`（`frontend/dist/` 被 `.gitignore` 排除）。之前是在构建
产物上直接替换字符串，无法进入版本管理，每次升级都要重做。改源码后 `npm run build`
即可复现。

**验证**

```bash
cd frontend && npm ci && npm run build
grep -c "127.0.0.1:8000" dist/assets/Settings-*.js   # 期望 0
grep -c "location.origin" dist/assets/Settings-*.js  # 期望 1
```

CDP 实测（1440 宽，`http://127.0.0.1:8014/settings`）：
- 代理地址渲染为 `http://127.0.0.1:8014`
- OpenAI `base_url="http://127.0.0.1:8014/v1"`
- Claude `base_url="http://127.0.0.1:8014"`
- cURL `curl http://127.0.0.1:8014/v1/chat/completions`
- 页面文本中 0 处 `127.0.0.1:8000`

---

## 三、验证矩阵（本次提交实测）

| 项 | 命令 / 方法 | 结果 |
|---|---|---|
| Python 语法 | `ast.parse()` 四个文件 | 全部 OK |
| 后端单测 | `python3 -m unittest discover -s backend/tests` | 27 通过 |
| video-world 单测 | `python3 -m unittest tests.test_video_world` | 21 通过 |
| 插件路由顺序 | 导入 `main` 查 `app.routes` | 61 条 video 路由在 catch-all 之前 |
| 插件接口 | `GET /api/admin/video/ffmpeg/preflight` | 200 `application/json` |
| 传输层标记 | 死端口 `forward_request` | body 带 `cpa_transport_error=True` |
| 冷却时长 | `TRANSPORT_ERROR_COOLDOWN_SECONDS` | 10 |
| 连接超时默认 | `settings.proxy_stream_connect_timeout_seconds` | 5 |
| 前端构建 | `npm ci && npm run build` | 成功 |
| 前端硬编码 | grep 构建产物 | 0 处 `127.0.0.1:8000` |
| 前端渲染 | CDP 1440 实测（`http://127.0.0.1:8014/settings`） | 4 处均为当前 origin，0 处 8000 |
| 隔离实例启动 | `uvicorn main:app --port 8014` | health 200、面板 200、插件接口 200 JSON |

---

## 四、未纳入本次提交的差异

以下文件与上游**仅行尾不同**（CRLF vs LF），内容逐字节一致，不提交：

- `backend/database.py`
- `backend/routers/admin.py`
- `backend/services/video_style_preset_service.py`

另外，本地部署目录里的以下文件属于**运行产物或旧版**，也不提交：

- `backend/_logs_probe.json`（日志探测缓存）
- `backend/tests/test_video_world.py`（本地这份测的是旧内置 `routers.video`，
  上游已改为测插件 `plugins/video-world/backend/video.py`，**上游版本更新**）
- `plugins/cpa-video-world-plugin-0.1.1.zip`（已安装到 `backend/data/plugins/installed/`）

---

## 五、升级上游时的检查清单

拉取新上游包后，逐条确认这些改造是否仍然需要：

```bash
# 1. 插件路由顺序（上游若自行修复则本改造作废）
grep -n "load_backend_plugins" backend/main.py
grep -n 'full_path:path' backend/main.py
# 要求：load_backend_plugins 的行号 < full_path 的行号

# 2. 传输层隔离（上游若收编则作废）
grep -c "cpa_transport_error" backend/services/proxy_service.py   # 应 >= 20
grep -c "is_transport_stage_error" backend/routers/proxy.py       # 应 >= 5

# 3. 超时预算
grep -n "read=settings.proxy_stream_read_timeout_seconds" backend/services/proxy_service.py
grep -n "首包保护" backend/services/proxy_service.py               # 应 >= 1

# 4. finish_reason 初始化
grep -n "^            finish_reason = None" backend/services/proxy_service.py  # 应 >= 1

# 5. 前端示例地址
grep -c "127.0.0.1:8000" frontend/src/views/Settings.vue          # 应 0
grep -c "proxyBaseUrl" frontend/src/views/Settings.vue            # 应 5
```
