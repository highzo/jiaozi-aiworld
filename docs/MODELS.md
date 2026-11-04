# 模型选择

饺子AIWorld 只要求上游是 **OpenAI 兼容的 `/chat/completions`**。
下面按"跑在哪"分类。

## 快速对照

| 设备 | 推荐模型 | 量化 | 速度（tok/s） | 多步任务 |
|---|---|---|---|---|
| 手机 (Termux, 8G) | Qwen2.5-1.5B-Instruct | Q4_K_M | 6~12 | 简单任务可以 |
| 树莓派 4B (4G) | Qwen2.5-0.5B / 1.5B | Q4_K_M | 3~6 | 0.5B 容易跑偏 |
| 树莓派 5 (8G) | Qwen2.5-3B-Instruct | Q4_K_M | 4~7 | 基本可用 |
| RK3588 (8~16G) | Qwen2.5-3B / 7B | Q4_K_M | 8~20 | 推荐 |
| x86 迷你主机 | Qwen2.5-7B-Instruct | Q4_K_M | 15~30 | 好用 |
| 有网 | DeepSeek / GPT-4o-mini / 任意云 API | — | 快 | 最好 |

中文场景优先 Qwen 系列：中文理解、工具调用格式都比同级 Llama 稳。

## 原生函数调用 vs 提示协议

| 模型规模 | `native_tools` | 原因 |
|---|---|---|
| ≥ 7B | 开 | function calling 稳定 |
| 3B | 开，不行就关 | 看具体模型，Qwen2.5-3B 勉强可以 |
| 1.5B 及以下 | **关** | 经常吐出畸形 JSON 或忘记 schema |

关掉之后走提示协议：模型输出

```json
{"tool": "fs_list", "args": {"path": "~"}}
```

服务端解析执行，把结果作为【工具结果】回填。这个格式比 function calling 简单得多，
小模型只要会写 JSON 就行——而且我们做了容错（单引号、裸 JSON、多余解释文字都能捞出来）。

如果开着头一次调用就报 400/404/422，会自动降级重试一次，前端只会看到一条 `warn` 提示。

## Ollama（最省事）

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:1.5b-instruct
ollama serve
```

设置里填 `http://127.0.0.1:11434/v1`，模型名 `qwen2.5:1.5b-instruct`，API Key 留空。

Ollama 默认上下文只有 2048，多步任务会被截断。建议加环境变量：

```bash
export OLLAMA_CONTEXT_LENGTH=8192
```

## llama.cpp（板子上最快）

```bash
git clone https://github.com/ggerganov/llama.cpp && cd llama.cpp
cmake -B build -DGGML_NATIVE=ON && cmake --build build -j$(nproc)

./build/bin/llama-server \
  -m Qwen2.5-1.5B-Instruct-Q4_K_M.gguf \
  --host 127.0.0.1 --port 8080 \
  -c 8192 -t 4 --jinja
```

- `--jinja` 必须加，否则 tools 模板不生效。
- `-c 8192` 是上下文长度；内存紧张就降到 4096。
- `-t` 用物理核心数。

设置里填 `http://127.0.0.1:8080/v1`，模型名随便写。

## 云端 API

```json
{
  "llm": {
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-chat",
    "api_key": "sk-..."
  }
}
```

也可以 `https://api.openai.com/v1` + `gpt-4o-mini`，或任何中转站。
注意：只有**非本机/非局域网**地址才会走系统代理；`127.0.0.1`、`192.168.*`、`10.*`、`172.16-31.*`
和 `*.local` 一律直连——否则本机模型会被代理打成 502。

## 调参建议

| 参数 | 默认 | 说明 |
|---|---|---|
| `temperature` | 0.3 | 工具调用要稳，别超过 0.5；闲聊可以调到 0.8 |
| `max_tokens` | 1024 | 小模型调到 512 能明显降延迟 |
| `max_steps` | 12 | 板子上设 6~8；太大容易在小模型上死循环 |
| `shell_timeout` | 60 | 编译类任务可以调到 300 |

## 提示词已经替你调过了

`jiaozi/agent/prompts.py` 里的 system prompt 做了几件事：

- 告诉模型"工具返回的是真实结果，不要猜"；
- 要求"完成任务后调用 `ui_open` 把结果给人看"——这是人机共用桌面的关键动作；
- 要求"命令失败先读错误，不要重复同一条失败命令"——小模型最容易犯的错；
- 注入当前 OS、沙箱根目录、时间、模型名，避免模型编造路径。

想改直接编辑那个文件，或者在自己的 fork 里换掉整个 prompt。

## 怎么判断模型够不够用

跑这个自测（在桌面 AI 面板里输入）：

```
列出主目录下最大的 3 个文件夹，告诉我它们各占多少空间，然后在桌面打开文件管理器
```

合格标准：
1. 调用 `fs_list` 而不是凭空回答；
2. 根据结果继续调用 `shell_run`（`du -sh`）而不是瞎猜；
3. 最后调用 `ui_open`。

1.5B 通常能做到 1，偶尔到 2；3B 基本能走完；7B 很稳。
如果 1.5B 在第 2 步开始重复同一个工具调用，就把 `max_steps` 降到 6，
它会停下来汇报，而不是一直转圈烧 CPU。
