# HTTP API

所有接口返回 JSON：`{"ok": true, "data": ...}` 或 `{"ok": false, "error": "..."}`。
鉴权：本机回环默认放行；其他来源需 `X-Jiaozi-Token` 头、`?token=` 参数，或 `jz_token` Cookie。

端口默认 `8787`，下文省略。

## 鉴权怎么走（手机连电脑时最常踩）

```
浏览器访问 http://<电脑IP>:8787/?token=<token>
      ↓  服务端确认 token 正确
Set-Cookie: jz_token=<token>; Path=/; Max-Age=2592000; SameSite=Lax
      ↓  之后同源的 fetch 与 EventSource 自动带 cookie
全部 /api/* 请求通过
```

几点说明：

- 页面把鉴权确认后才把地址栏里的 `?token=` 抹掉（`history.replaceState`），
  既不留在浏览历史里，也让"添加到主屏幕"的启动地址是干净的 `/`。
- Cookie 有 `Max-Age`（30 天）。会话级 cookie 在 PWA 关掉重开后会被清掉，
  整个界面就 401 了，所以必须持久化。
- `?token=` 只在**首页**触发种 cookie；直接请求 `/api/*?token=` 也能过鉴权，但不种 cookie。
- 关掉 `server.allow_localhost` 后，本机也要带凭据——这是给别人演示鉴权行为时用的开关。

## 静态与 PWA

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 桌面页（HTML） |
| GET | `/manifest.webmanifest` | PWA 清单：`display: standalone`，图标用 SVG |
| GET | `/icon.svg` | 应用图标（桌面、任务栏、主屏幕共用） |
| GET | `/favicon.ico` | 204（兼容老浏览器的自动请求） |

清单里**不写 token**——它是公开资源，写进去等于把门钥匙挂在门上。

---

## 系统

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 存活检查、版本、客户端数 |
| GET | `/api/ping` | 极简探活 |
| GET | `/api/sys/info` | OS/CPU/内存/磁盘/运行时长/沙箱根目录 |
| GET | `/api/sys/proc?limit=40` | 进程列表（按内存排序） |
| POST | `/api/sys/kill` | `{"pid":123,"force":true}` |
| GET | `/api/config` | 配置（token 与 api_key 已脱敏） |
| POST | `/api/config` | 局部更新，见下 |
| GET | `/api/desktop/state` | `home` / `roots` / `ui` / 主机名 |
| GET | `/api/tools` | 工具 JSON Schema 列表 |

```bash
curl localhost:8787/api/sys/info
```

```json
{"ok":true,"data":{"os":"Linux 6.6.31","machine":"aarch64","cpu_count":4,
 "cpu_percent":12.5,"load":[0.42,0.31,0.28],
 "memory":{"total":8000000000,"used":3100000000,"percent":38.8},
 "disk":{"total":128000000000,"used":48000000000,"percent":37.5},
 "uptime":9123.4,"root":"/home/pi","roots":[{"name":"pi","path":"/home/pi"}]}}
```

### 更新配置

只传要改的字段，其余保持不变：

```bash
curl -X POST localhost:8787/api/config -H 'Content-Type: application/json' -d '{
  "llm": {"base_url":"http://127.0.0.1:11434/v1","model":"qwen2.5:1.5b-instruct"},
  "agent": {"approval":"auto","max_steps":10},
  "ui": {"theme":"dark","wallpaper":"ocean"}
}'
```

`llm.api_key` 传 `"********"` 表示"不修改"。

---

## 文件

| 方法 | 路径 | 参数 |
|---|---|---|
| GET | `/api/fs/list?path=~` | 列目录 |
| GET | `/api/fs/read?path=...` | 读文本（大文件截断） |
| GET | `/api/fs/stat?path=...` | 单个路径信息 |
| GET | `/api/fs/raw?path=...` | 原始字节（图片/下载） |
| GET | `/api/fs/search?q=xxx&path=...&limit=200` | 按文件名递归搜索 |
| GET | `/api/fs/roots` | 沙箱根目录列表 |
| POST | `/api/fs/write` | `{"path":"...","content":"..."}` |
| POST | `/api/fs/mkdir` | `{"path":"..."}` |
| POST | `/api/fs/rename` | `{"path":"...","to":"..."}` |
| POST | `/api/fs/copy` | `{"path":"...","to":"目录或新路径"}` |
| POST | `/api/fs/delete` | `{"path":"...","hard":false}` → 进回收站 |
| POST | `/api/fs/upload` | `{"dir":"...","name":"a.png","data":"base64..."}` |

越界（不在沙箱根目录内）一律 `403`。

---

## 终端

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/term/open` | `{"cols":100,"rows":30,"shell":"/bin/bash"}` → `{id,tty,shell}` |
| POST | `/api/term/input` | `{"id":"...","data":"ls\r"}` |
| POST | `/api/term/resize` | `{"id":"...","cols":120,"rows":40}` |
| POST | `/api/term/close` | `{"id":"..."}` |
| GET | `/api/term/list` | 所有会话 |
| GET | `/api/term/buffer?id=...` | 最近 96KB 原始输出（断线重连补齐用） |

输出通过 `/api/events` 推送：`{"t":"term","id":"ab12","d":"..."}`。
`tty:false` 表示该平台没有 PTY（Windows），此时客户端不做本地回显。

---

## 事件流

```
GET /api/events            无限流
GET /api/events?ms=1500    1.5 秒后自动结束（调试/截图）
```

事件类型：

| t | 含义 |
|---|---|
| `hello` | 连接建立，带 `cid` |
| `term` | 终端输出 `{id,d}` |
| `term_open` / `term_close` | 会话生命周期 |
| `fs_change` | 文件变动 `{path,action}` |
| `notify` | 桌面通知 `{title,body,level}` |
| `toast` | 轻提示 `{text,level}` |
| `ui` | 让前端做事 `{action:"open",app,path}` |
| `ai_shell` | AI 执行了命令（含 cmd/输出） |
| `approval` / `approval_result` | 审批请求与结果 |
| `agent_event` | Agent 内部事件（多端旁观用） |
| `config` | 配置变更 |

Python 订阅示例：

```python
import json, requests
with requests.get("http://127.0.0.1:8787/api/events", stream=True) as r:
    for line in r.iter_lines():
        if line and line.startswith(b"data:"):
            ev = json.loads(line[5:])
            if ev["t"] == "notify":
                print(ev["d"]["title"])
```

---

## AI

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/agent/chat` | `{"text":"...","sid":"main"}`，返回 **SSE 流** |
| POST | `/api/agent/approve` | `{"id":"...","ok":true}` |
| POST | `/api/agent/reset` | `{"sid":"main"}` |
| GET | `/api/agent/history?sid=main` | 历史消息 |
| GET | `/api/llm/models` | 模型列表（透传上游） |
| POST | `/api/llm/test` | 推送配置做连通性 + 推理测试 |
| POST | `/api/image/generate` | `{"prompt":"...","n":1,"size":"1024x1024"}` → 生成并落盘 |
| POST | `/api/image/test` | 用 512×512 小图做一次真实连通性验证 |

`/api/agent/chat` 的事件序列：

```
{"t":"start","native":true}
{"t":"step","i":1,"max":12}
{"t":"delta","d":"我先看一下。"}                 ← 可能多次
{"t":"tool","status":"running","name":"fs_list","summary":"浏览 ~"}
{"t":"tool","status":"ok","name":"fs_list","result":"{...}"}
{"t":"delta","d":"目录里..."}
{"t":"done","content":"...","tools":[...]}
{"t":"eof"}
```

遇到危险操作会插入 `{"t":"approval","id":"ab12","name":"shell_run","summary":"执行命令 ...","args":{...}}`，
此时**流会挂住等你批准**（默认 300 秒超时视为拒绝）：

```bash
curl -X POST localhost:8787/api/agent/approve \
  -H 'Content-Type: application/json' -d '{"id":"ab12","ok":true}'
```

---

## 图像生成

```bash
curl -X POST localhost:8787/api/image/generate \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"一位穿旗袍的女子站在江南园林里，真实摄影","n":2}'
```

```json
{"ok": true, "data": {
  "files": ["/home/pi/Pictures/JiaoziAI/20261104-144823-一位穿旗袍的女子.png",
            "/home/pi/Pictures/JiaoziAI/20261104-144823-一位穿旗袍的女子-2.png"],
  "model": "agnes-image-2.5-flash", "size": "1024x1024",
  "prompt": "...", "elapsed": 73.4
}}
```

要点：

- **返回的是磁盘路径，不是临时 URL。** 图片真的写进了 `image.save_dir`，
  可以直接用 `/api/fs/raw?path=...` 读、用 `ui_open` 打开、或者被别的程序拿去用。
- 一次调用只描述**一个画面**。要不同场景就调多次——在一条 prompt 里写
  "第一张…第二张…"，模型会把它们挤进同一张画布里（实测踩过）。
- `n` 是**同一画面的变体数**，实现上是循环调用上游（兼容性最好），所以耗时按倍数增加。
- 上游返回 `b64_json` 或 `url` 都能吃；`url` 会被下载下来（上限 24MB）。
- `image.enabled=false` 时接口直接 400，不会偷偷发请求——这一点有测试守着。
- `base_url` / `api_key` 留空则回落到 `llm` 的配置。

---

## 设备 / 机器人

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/device/health` | `{brain:"online", model, tools, platform}` |
| POST | `/api/device/task` | 同步执行一句话任务，返回最终结果 |

```bash
curl -X POST localhost:8787/api/device/task \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"看看磁盘还剩多少，低于 20% 就告诉我","device":"bot-1"}'
```

```json
{"ok": true, "result": "磁盘剩余 62.4 GB（48%），暂时不需要处理。",
 "steps": 2, "elapsed": 4.12, "error": null}
```

- `device` 相同的请求共用一个会话（有上下文），不同设备互相隔离。
- 同一设备并发调用会返回 `409 设备正忙`。
- 关闭入口：设置 → 智能体 → 设备接口。

---

## 局域网互认（peer）

同一个局域网里的多个饺子互相发现、配对、调用。设计说明见 `jiaozi/peer.py` 顶部。

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/api/peer/state` | 需要 | 本机身份 + 附近设备 + 已配对表 |
| GET | `/api/peer/hello` | **公开** | 探活：名字、端口、能力，**不含 token** |
| POST | `/api/peer/code` | 需要 | 生成一次性 6 位配对码（5 分钟） |
| POST | `/api/peer/claim` | **公开** | 拿配对码换取本机 token（对方此时还没有 token） |
| POST | `/api/peer/pair` | 需要 | 主动配对：`{host, port, code}` |
| POST | `/api/peer/probe` | 需要 | 手动探测某个地址是不是饺子 |
| POST | `/api/peer/exec` | 需要 | 远程执行一个工具：`{tool, args}` |
| POST | `/api/peer/forget` | 需要 | 删除配对关系 `{id}` |
| POST | `/api/peer/announce` | 需要 | 立刻广播一次（不等 5 秒轮询） |

只有 `/api/peer/hello` 和 `/api/peer/claim` 走公开白名单，理由见代码里的 `PUBLIC_API` 注释：
配对发生的时刻，双方还没有共享凭据，这一步必须能在无 token 下完成；
安全性靠一次性码 + 5 分钟过期 + 试错上限（6 次）来保证。

**一次完整配对**

```bash
# 1) A 机器上生成码（界面上点「生成配对码」也是同一个接口）
curl -X POST localhost:8787/api/peer/code -H "X-Jiaozi-Token: $TOKEN_A"
# {"ok":true,"data":{"code":"752330","expires":...,"ttl":300,"name":"客厅电脑"}}

# 2) B 机器上输入 A 的地址和这个码
curl -X POST localhost:8787/api/peer/pair \
  -H "X-Jiaozi-Token: $TOKEN_B" -H 'Content-Type: application/json' \
  -d '{"host":"192.168.1.20","port":8787,"code":"752330"}'

# 3) 之后 B 就能在 A 上执行工具
curl -X POST localhost:8787/api/peer/exec \
  -H "X-Jiaozi-Token: $TOKEN_B" -H 'Content-Type: application/json' \
  -d '{"tool":"fs_list","args":{"path":"~/Desktop"}}'
```

`/api/peer/state` 的返回里，已配对的设备会带 `token`（对方的访问凭据）。
这是刻意留的：前端要拿它拼「打开对方桌面」的地址，能读这个接口的调用方本来就已经通过本机鉴权。

**发现的实现**

UDP 组播到 `239.255.77.87:8788`，每 5 秒一条 JSON。每张网卡各发一遍——
多网卡机器（WSL / Hyper-V / VMware 虚拟网卡）只发默认网卡会漏。
组播被禁时发现栏会一直空着，但不影响手动填 IP 配对。

**不能做的事**

- `/api/peer/exec` 拒绝执行 `peer_call` / `peer_list`，否则 A→B→A 会无限套娃。
- 跨设备调用用的是目标机自己的 token，没有"万能钥匙"这种东西。

---

## 多语言

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/i18n` | 当前语言、判定来源、支持列表。**不会主动去查 IP** |
| POST | `/api/i18n` | 改语言：`{"lang":"de"}` 或 `{"lang":"auto"}` |
| GET | `/api/geo` | IP 归属地：`?ip=` 指定地址，`?refresh=1` 绕过 6 小时缓存 |
| GET | `/i18n/<code>.json` | 词典本体（静态文件，缺失就是 404） |

`GET /api/i18n` 的返回：

```json
{"ok": true, "data": {
  "lang": "de", "source": "browser", "country": "",
  "default": "en",
  "langs": [{"code": "de", "native": "Deutsch", "en": "German"}, ...]
}}
```

`source` 有四种，前端就是靠它告诉用户"这次是为什么变成这个语言的"：

| source | 含义 |
|---|---|
| `user` | 用户自己选的 |
| `browser` | 按 `Accept-Language`（取 q 值最高且我们支持的那个） |
| `ip` | 按 IP 归属地推的 |
| `default` | 以上都不成立，回落英文 |

`GET /api/geo` 的返回：

```json
{"ok": true, "data": {
  "ok": true, "ip": "1.2.3.4", "country_code": "CN",
  "country": "China", "city": "Yiwu", "source": "ip.sb",
  "suggest": "zh-CN", "cached": false, "ts": 1793925825
}}
```

- 对端是回环/内网地址时（手机通过局域网连进来就是 `192.168.x.x`），
  查的是**服务器自己的出口 IP**——内网地址推不出国家；
- 三家 provider 依次回退（`api.ip.sb` → `ipwho.is` → `ipinfo.io`），单次超时 3 秒，
  整次请求总预算 4.5 秒，**永远不抛异常**，最坏情况返回 `{"ok": false}`；
- 结果在磁盘上缓存 6 小时（`~/.jiaozi/geo.json`），失败也会缓存，避免每秒钟重试。

---

## 桌面操作（给外部程序用）

```bash
# 让桌面打开文件管理器到某个目录（所有连着的客户端都会弹）
curl -X POST localhost:8787/api/desktop/event \
  -H 'Content-Type: application/json' \
  -d '{"action":"open","app":"files","path":"/home/pi/Pictures"}'
```

等价于 AI 的 `ui_open` 工具。

---

## 错误码

| 状态 | 含义 |
|---|---|
| 400 | 参数缺失或格式错 |
| 401 | 缺 token / token 不对 |
| 403 | 越界访问沙箱、或功能被关闭 |
| 404 | 路径/会话/接口不存在 |
| 409 | Agent 或设备正忙 |
| 413 | 上传过大 |
| 502 | 模型服务不可达（会带上上游原文） |
| 500 | 未预期异常（服务端有 traceback） |
