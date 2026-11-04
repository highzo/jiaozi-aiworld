#!/usr/bin/env bash
# 饺子AIWorld · 本地小模型准备（Ollama / llama.cpp）
#
# 目标：让设备断网也能思考和动手。
#   - 电脑 / RK3588 / 树莓派 5：qwen2.5:1.5b-instruct 或 qwen2.5:3b-instruct
#   - 内存 4G 以下的板子：qwen2.5:0.5b-instruct（够用，但工具调用容易跑偏）
#   - 纯 CPU 想更快：用 llama.cpp + GGUF Q4_K_M
set -euo pipefail

say() { printf '\033[1;36m▸\033[0m %s\n' "$*"; }

MODEL="${1:-qwen2.5:1.5b-instruct}"

if command -v ollama >/dev/null 2>&1; then
  say "检测到 Ollama，拉取 $MODEL"
  ollama pull "$MODEL" || { echo "拉取失败，检查网络或换个模型名"; exit 1; }
  say "启动服务"
  (ollama serve >/dev/null 2>&1 &) || true
  sleep 2
  cat <<EOF

配置已就绪。打开饺子AIWorld → 设置 → AI 模型：
  服务地址: http://127.0.0.1:11434/v1
  模型名:   $MODEL
  原生函数调用: 3B 以上建议开；0.5B 建议关（走提示协议）

自测：
  curl http://127.0.0.1:11434/v1/models

EOF
  exit 0
fi

cat <<'EOF'
没有找到 Ollama。两种选法：

一、装 Ollama（最简单，自带 OpenAI 兼容接口）
    curl -fsSL https://ollama.com/install.sh | sh
    ollama pull qwen2.5:1.5b-instruct
    # 然后重跑本脚本

二、用 llama.cpp（开发板上最快，纯 CPU）
    git clone https://github.com/ggerganov/llama.cpp && cd llama.cpp
    cmake -B build && cmake --build build -j
    # 下载 GGUF 模型（例如 Qwen2.5-1.5B-Instruct-Q4_K_M.gguf）
    ./build/bin/llama-server -m Qwen2.5-1.5B-Instruct-Q4_K_M.gguf \
        --host 127.0.0.1 --port 8080 -c 4096 -t 4 --jinja
    # 在设置里填： http://127.0.0.1:8080/v1

三、用云端 API（有网时效果最好）
    服务地址: https://api.deepseek.com/v1
    模型名:   deepseek-chat
    API Key:  你自己的

选模型的经验：
  0.5B  能跑，适合固定流程，复杂任务容易迷路
  1.5B  开发板甜点，中文不错，简单工具调用可用
  3B    8G 内存以上首选，勉强能干多步任务
  7B+   需要 GPU 或 RK3588 这类带 NPU 的板子
EOF
