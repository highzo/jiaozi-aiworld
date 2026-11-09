"""语音输入：把一句话变成文字，交给 Agent 去执行。

**音频在浏览器里就已经变成 16k 单声道 WAV**（WebAudio 直接拿 PCM，纯 JS 拼头），
所以服务端不需要 ffmpeg、不需要解码器——这是能守住「零第三方依赖」的关键。
麦克风只在你按住按钮、或明确打开「一直听」时才开。

三种后端，按可用性自动挑：

1. ``sherpa`` —— 装了 sherpa-onnx 且配了模型目录就用它，**音频完全不出本机**；
2. ``http``   —— 任何 OpenAI 兼容的转写接口（本地 whisper.cpp 服务器、vLLM、
                 OpenAI、SiliconFlow 都行），走 multipart；
3. ``none``   —— 都没有。界面不显示麦克风，而不是显示一个按了没反应的按钮。

选后端不靠猜：``status()`` 会把当前用的是哪个、为什么是它、缺什么，原样告诉前端。
"""
from __future__ import annotations

import io
import json
import os
import struct
import time
import urllib.error
import urllib.request

from . import config

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_sherpa = None
_sherpa_err = ""


class VoiceError(Exception):
    def __init__(self, msg: str, code: int = 400):
        super().__init__(msg)
        self.msg = msg
        self.code = code


# ------------------------------------------------------------------ WAV

def parse_wav(raw: bytes) -> tuple[list[float], int]:
    """解析 PCM WAV，返回 (浮点样本, 采样率)。

    只接受 16 位 PCM——浏览器端是我们自己编码的，不会有别的格式。
    别的格式明确报错，不要静默返回空数组（那会让人以为麦克风坏了）。
    """
    if len(raw) < 44 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise VoiceError("不是 WAV 数据")
    pos = 12
    fmt = None
    data = None
    while pos + 8 <= len(raw):
        cid = raw[pos:pos + 4]
        size = struct.unpack("<I", raw[pos + 4:pos + 8])[0]
        body = raw[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            fmt = body
        elif cid == b"data":
            data = body
            break
        pos += 8 + size + (size & 1)
    if fmt is None or data is None or len(fmt) < 16:
        raise VoiceError("WAV 缺少 fmt/data 块")
    tag, channels, rate, _bps, _align, bits = struct.unpack("<HHIIHH", fmt[:16])
    if tag != 1:
        raise VoiceError(f"只支持未压缩 PCM（当前格式 {tag}）")
    if bits not in (8, 16, 24, 32):
        raise VoiceError(f"不支持的位深 {bits}")
    mono: list[float] = []
    ch = max(1, channels)
    if bits == 16:
        n = len(data) // 2
        vals = struct.unpack("<%dh" % n, data[:n * 2])
        for i in range(0, n - ch + 1, ch):
            mono.append(sum(vals[i:i + ch]) / (ch * 32768.0))
    elif bits == 8:
        for i in range(0, len(data) - ch + 1, ch):
            mono.append((sum(data[i:i + ch]) / ch - 128) / 128.0)
    elif bits == 32:
        n = len(data) // 4
        vals = struct.unpack("<%di" % n, data[:n * 4])
        for i in range(0, n - ch + 1, ch):
            mono.append(sum(vals[i:i + ch]) / (ch * 2147483648.0))
    else:  # 24 位
        step = 3 * ch
        for i in range(0, len(data) - step + 1, step):
            acc = 0
            for c in range(ch):
                o = i + 3 * c
                v = data[o] | (data[o + 1] << 8) | (data[o + 2] << 16)
                if v & 0x800000:
                    v -= 0x1000000
                acc += v
            mono.append(acc / (ch * 8388608.0))
    return mono, rate


def _resample(samples: list[float], src: int, dst: int = 16000) -> list[float]:
    if src == dst or not samples:
        return samples
    n = max(1, int(len(samples) * dst / src))
    out = []
    step = src / dst
    for i in range(n):
        x = i * step
        a = int(x)
        b = min(a + 1, len(samples) - 1)
        f = x - a
        out.append(samples[a] * (1 - f) + samples[b] * f)
    return out


def dur_of(wav: bytes) -> float:
    try:
        s, r = parse_wav(wav)
        return round(len(s) / max(1, r), 2)
    except VoiceError:
        return 0.0


# ------------------------------------------------------------------ 后端

def _cfg() -> dict:
    v = config.load().get("voice") or {}
    return v if isinstance(v, dict) else {}


def _sherpa_ready() -> tuple[bool, str]:
    global _sherpa, _sherpa_err
    if _sherpa is not None:
        return True, ""
    cfg = _cfg()
    model_dir = str(cfg.get("model_dir") or "").strip()
    if not model_dir:
        return False, "没配 voice.model_dir"
    try:
        import sherpa_onnx  # noqa: F401  可选依赖
    except Exception as e:  # noqa: BLE001
        _sherpa_err = f"没装 sherpa-onnx（{type(e).__name__}）"
        return False, _sherpa_err
    try:
        _sherpa = _load_sherpa(model_dir)
        return True, ""
    except Exception as e:  # noqa: BLE001
        _sherpa_err = f"模型加载失败：{e}"
        return False, _sherpa_err


def _load_sherpa(model_dir: str):
    import sherpa_onnx
    tokens = os.path.join(model_dir, "tokens.txt")
    for name in ("model.int8.onnx", "model.onnx"):
        p = os.path.join(model_dir, name)
        if os.path.exists(p) and os.path.exists(tokens):
            return sherpa_onnx.OfflineRecognizer.from_paraformer(
                paraformer=p, tokens=tokens, num_threads=2, sample_rate=16000,
                feature_dim=80, decoding_method="greedy_search")
    for name in ("encoder.int8.onnx", "encoder.onnx"):
        enc = os.path.join(model_dir, name)
        if os.path.exists(enc) and os.path.exists(tokens):
            dec = os.path.join(model_dir, "decoder.onnx")
            joiner = os.path.join(model_dir, "joiner.onnx")
            if os.path.exists(dec) and os.path.exists(joiner):
                return sherpa_onnx.OfflineRecognizer.from_transducer(
                    encoder=enc, decoder=dec, joiner=joiner, tokens=tokens,
                    num_threads=2, sample_rate=16000, feature_dim=80,
                    decoding_method="greedy_search")
    raise RuntimeError("模型目录里找不到 paraformer/transducer 的 onnx + tokens.txt")


def _http_cfg() -> tuple[str, str, str]:
    cfg = _cfg()
    base = str(cfg.get("base_url") or "").strip().rstrip("/")
    key = str(cfg.get("api_key") or "").strip()
    model = str(cfg.get("model") or "whisper-1").strip()
    return base, key, model


def status() -> dict:
    cfg = _cfg()
    ok, why = _sherpa_ready()
    if ok:
        return {"backend": "sherpa", "ready": True, "local": True,
                "hint": "本地识别，音频不出这台机器"}
    base, _key, model = _http_cfg()
    if base:
        return {"backend": "http", "ready": True, "local": False,
                "hint": f"转写走 {base}", "model": model}
    if os.environ.get("JIAOZI_VOICE_MOCK") == "1":
        return {"backend": "mock", "ready": True, "local": True,
                "hint": "模拟后端（测试用，不做真实识别）"}
    return {"backend": "none", "ready": False, "local": False,
            "hint": why or "没配识别后端", "config": {
                "model_dir": str(cfg.get("model_dir") or ""),
                "base_url": base}}


def transcribe(wav: bytes) -> dict:
    if not wav:
        raise VoiceError("没收到音频")
    t0 = time.time()
    st = status()
    backend = st["backend"]
    if backend == "none":
        raise VoiceError("这台机器还没有语音识别后端：" + str(st.get("hint")), 503)

    samples, rate = parse_wav(wav)
    if not samples:
        raise VoiceError("音频是空的")
    dur = len(samples) / max(1, rate)
    if dur > 120:
        raise VoiceError(f"太长（{dur:.0f} 秒），说短一点")
    if dur < 0.25:
        raise VoiceError("太短了，没听清")

    if backend == "mock":
        text = os.environ.get("JIAOZI_VOICE_MOCK_TEXT") or "打开客厅灯"
        return {"text": text, "backend": "mock", "lang": "", "seconds": round(dur, 2),
                "ms": int((time.time() - t0) * 1000)}

    if backend == "sherpa":
        try:
            stream = _sherpa.create_stream()
            stream.accept_waveform(16000, _resample(samples, rate))
            _sherpa.decode_stream(stream)
            text = str(stream.result.text or "").strip()
        except Exception as e:  # noqa: BLE001
            raise VoiceError(f"本地识别失败：{e}", 502) from None
        return {"text": text, "backend": "sherpa", "lang": str(_cfg().get("lang") or "zh"),
                "seconds": round(dur, 2), "ms": int((time.time() - t0) * 1000)}

    # http：multipart 手拼，不引 requests
    base, key, model = _http_cfg()
    boundary = "----jiaozi" + os.urandom(8).hex()
    body = io.BytesIO()

    def part(name: str, value: str) -> None:
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.write(value.encode() + b"\r\n")

    part("model", model)
    part("response_format", "json")
    lang = str(_cfg().get("lang") or "").strip()
    if lang:
        part("language", lang)
    body.write(f"--{boundary}\r\n".encode())
    body.write(b'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n')
    body.write(b"Content-Type: audio/wav\r\n\r\n")
    body.write(wav)
    body.write(b"\r\n" + f"--{boundary}--\r\n".encode())

    req = urllib.request.Request(base + "/audio/transcriptions", data=body.getvalue(), headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "User-Agent": f"JiaoziAIWorld/{config.VERSION}",
        **({"Authorization": f"Bearer {key}"} if key else {}),
    }, method="POST")
    try:
        with _OPENER.open(req, timeout=60) as r:
            out = json.loads(r.read(1_000_000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read(400).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            pass
        raise VoiceError(f"转写接口返回 {e.code} {detail[:200]}", 502) from None
    except (urllib.error.URLError, OSError) as e:
        raise VoiceError(f"连不上转写接口：{getattr(e, 'reason', e)}", 502) from None
    except ValueError:
        raise VoiceError("转写接口回的不是 JSON", 502) from None
    text = ""
    if isinstance(out, dict):
        text = str(out.get("text") or "").strip()
        if not text and isinstance(out.get("results"), list) and out["results"]:
            text = str((out["results"][0] or {}).get("text") or "").strip()
    return {"text": text, "backend": "http", "lang": lang,
            "seconds": round(dur, 2), "ms": int((time.time() - t0) * 1000)}
