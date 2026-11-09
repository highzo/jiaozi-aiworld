/* 语音输入：麦克风 → 16k 单声道 WAV → 识别 → 直接交给饺子去做
 *
 * 为什么在浏览器里编码 WAV：WebAudio 拿到的就是裸 PCM，拼一个 44 字节的头就行。
 * 服务端因此不需要 ffmpeg、不需要解码库，零依赖的承诺才守得住。
 *
 * 两种用法：
 *   点一下 = 说一句，停下来 1.2 秒自动结束并发送；
 *   右键 → 「一直听」= 常开，只有说到唤醒词（默认「饺子」）才当命令。
 * 麦克风只在真的在录音时打开，随时点一下停掉。
 */
(function () {
  'use strict';
  const JZ = window.JZ;

  const TARGET_RATE = 16000;
  const SILENCE_RMS = 0.012;   // 判断「安静」的阈值
  const SPEECH_RMS = 0.020;    // 判断「在说话」的阈值（滞回，避免抖）
  const SILENCE_MS = 1200;     // 说完多久算说完
  const MIN_MS = 350;          // 短于这个当误触
  const MAX_MS = 30000;        // 单句上限

  let status = null;
  let ctx = null;
  let stream = null;
  let node = null;
  let srcNode = null;
  let chunks = [];
  let frames = 0;
  let startedAt = 0;
  let spoke = false;
  let silentSince = 0;
  let running = false;
  let always = false;
  let lastRate = TARGET_RATE;
  let hintEl = null;
  let polling = 0;

  /* ---------------- WAV ---------------- */

  function encodeWav(samples, rate) {
    const n = samples.length;
    const buf = new ArrayBuffer(44 + n * 2);
    const v = new DataView(buf);
    const str = (off, s) => { for (let i = 0; i < s.length; i++) v.setUint8(off + i, s.charCodeAt(i)); };
    str(0, 'RIFF');
    v.setUint32(4, 36 + n * 2, true);
    str(8, 'WAVE');
    str(12, 'fmt ');
    v.setUint32(16, 16, true);
    v.setUint16(20, 1, true);          // PCM
    v.setUint16(22, 1, true);          // 单声道
    v.setUint32(24, rate, true);
    v.setUint32(28, rate * 2, true);   // 字节率
    v.setUint16(32, 2, true);          // 块对齐
    v.setUint16(34, 16, true);         // 位深
    str(36, 'data');
    v.setUint32(40, n * 2, true);
    let off = 44;
    for (let i = 0; i < n; i++) {
      let s = Math.max(-1, Math.min(1, samples[i]));
      v.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      off += 2;
    }
    return new Uint8Array(buf);
  }

  function toBase64(bytes) {
    let s = '';
    const CH = 0x8000;
    for (let i = 0; i < bytes.length; i += CH) {
      s += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
    }
    return btoa(s);
  }

  function concat(list, total) {
    const out = new Float32Array(total);
    let off = 0;
    list.forEach(function (c) { out.set(c, off); off += c.length; });
    return out;
  }

  function rms(block) {
    let sum = 0;
    for (let i = 0; i < block.length; i++) sum += block[i] * block[i];
    return Math.sqrt(sum / block.length);
  }

  /* ---------------- 采集 ---------------- */

  function setHint(text, kind) {
    if (!hintEl) return;
    hintEl.textContent = text || '';
    hintEl.className = 'ai-voice-hint' + (kind ? ' ' + kind : '');
    hintEl.hidden = !text;
  }

  function paint() {
    const b = document.getElementById('aiMic');
    if (!b) return;
    b.classList.toggle('on', running);
    b.classList.toggle('always', always);
    b.title = running ? JZ.t('点一下停止')
                      : always ? JZ.t('一直听着（右键关闭）') : JZ.t('按住说话');
  }

  async function begin() {
    if (running || !status || !status.ready) return;
    chunks = [];
    frames = 0;
    spoke = false;
    silentSince = 0;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true,
                 autoGainControl: true },
      });
    } catch (e) {
      setHint(JZ.t('打不开麦克风：{msg}', { msg: (e && e.message) || e }), 'err');
      return;
    }
    const AC = window.AudioContext || window.webkitAudioContext;
    ctx = new AC();
    lastRate = ctx.sampleRate || TARGET_RATE;
    if (ctx.state === 'suspended') { try { await ctx.resume(); } catch (e) {} }
    srcNode = ctx.createMediaStreamSource(stream);
    node = ctx.createScriptProcessor(4096, 1, 1);
    startedAt = Date.now();
    running = true;
    paint();
    setHint(JZ.t('在听…'));

    node.onaudioprocess = function (ev) {
      if (!running) return;
      const input = ev.inputBuffer.getChannelData(0);
      const copy = new Float32Array(input.length);
      copy.set(input);
      chunks.push(copy);
      frames += copy.length;
      const level = rms(copy);
      const now = Date.now();
      if (level > SPEECH_RMS) {
        spoke = true;
        silentSince = 0;
      } else if (spoke && level < SILENCE_RMS) {
        if (!silentSince) silentSince = now;
        else if (now - silentSince > SILENCE_MS) { stop(true); return; }
      }
      if (now - startedAt > MAX_MS) stop(true);
    };
    srcNode.connect(node);
    // 必须接到目的地，否则某些浏览器不驱动 onaudioprocess；音量设 0 不出声
    const mute = ctx.createGain();
    mute.gain.value = 0;
    node.connect(mute);
    mute.connect(ctx.destination);
  }

  function release() {
    try { if (node) node.disconnect(); } catch (e) {}
    try { if (srcNode) srcNode.disconnect(); } catch (e) {}
    try { if (stream) stream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) {}
    try { if (ctx && ctx.close) ctx.close(); } catch (e) {}
    node = null; srcNode = null; stream = null; ctx = null;
  }

  function stop(submit) {
    if (!running) return;
    running = false;
    const ms = Date.now() - startedAt;
    release();
    paint();
    const total = chunks.reduce(function (a, c) { return a + c.length; }, 0);
    const all = concat(chunks, total);
    chunks = [];
    if (!submit) { setHint(''); return; }
    if (ms < MIN_MS || total < 1600) { setHint(JZ.t('太短了，再说一次'), 'warn'); return; }
    send(all, total);
  }

  async function send(samples, total) {
    setHint(JZ.t('识别中…'));
    // 采样率不是 16k 的话（Safari 会给 44.1k），先降到 16k——服务端就只认 16k
    const rate = lastRate || TARGET_RATE;
    let pcm = samples;
    if (rate !== TARGET_RATE) {
      const n = Math.max(1, Math.round(total * TARGET_RATE / rate));
      pcm = new Float32Array(n);
      const step = rate / TARGET_RATE;
      for (let i = 0; i < n; i++) {
        const x = i * step, a = Math.floor(x), b = Math.min(a + 1, total - 1);
        pcm[i] = samples[a] * (1 - (x - a)) + samples[b] * (x - a);
      }
    }
    const wav = encodeWav(pcm, TARGET_RATE);
    if (wav.length > 2.2 * 1024 * 1024) { setHint(JZ.t('这句话太长了'), 'err'); return; }
    let text = '';
    try {
      const r = await JZ.api.post('/api/voice/asr', { wav: toBase64(wav) });
      const d = r.data || r;
      text = (d.text || '').trim();
    } catch (e) {
      setHint(JZ.t('识别失败：{msg}', { msg: (e && e.message) || e }), 'err');
      return;
    }
    if (!text) { setHint(JZ.t('没听清'), 'warn'); return; }

    const wake = (status && status.wake) || '饺子';
    let cmd = text;
    const hit = text.indexOf(wake);
    if (hit >= 0) cmd = text.slice(hit + wake.length).replace(/^[，,。、\s]+/, '');
    if (always) {
      // 常开模式：没说到唤醒词就当闲聊，不打扰
      if (hit < 0) { setHint(JZ.t('听到「{t}」（没说唤醒词）', { t: text })); return; }
      if (!cmd) { setHint(JZ.t('在，你说')); return; }
    }
    setHint('');
    if (!cmd) cmd = text;
    if (JZ.agent && JZ.agent.send) JZ.agent.send(cmd);
  }

  /* ---------------- 开关 ---------------- */

  async function init() {
    const btn = document.getElementById('aiMic');
    if (!btn) return;
    hintEl = document.getElementById('aiHintVoice');
    try {
      const r = await JZ.api.get('/api/voice/status');
      status = r.data || r;
    } catch (e) {
      status = { ready: false };
    }
    btn.hidden = !status.ready;
    if (!status.ready) {
      btn.title = (status && status.hint) || JZ.t('没有语音识别后端');
      return;
    }
    btn.title = JZ.t('按住说话');
    btn.onclick = function (ev) {
      ev.preventDefault();
      if (running) stop(true);
      else begin();
    };
    btn.oncontextmenu = function (ev) {
      ev.preventDefault();
      const r = btn.getBoundingClientRect();
      JZ.menu(r.right - 180, r.top - 10, [
        { label: always ? JZ.t('关闭「一直听」') : JZ.t('一直听（说到唤醒词才执行）'),
          icon: always ? 'x' : 'mic',
          action: function () {
            always = !always;
            paint();
            if (always) begin(); else stop(false);
          } },
        { sep: true },
        { label: JZ.t('唤醒词：{w}', { w: (status && status.wake) || '饺子' }), disabled: true },
        { label: JZ.t('识别后端：{b}', { b: (status && status.backend) || '?' }), disabled: true },
        { label: (status && status.hint) || '', disabled: true },
      ]);
    };
    // 设置里改完配置回来，状态可能变了
    polling = setInterval(async function () {
      if (running) return;
      try {
        const r = await JZ.api.get('/api/voice/status');
        const s = r.data || r;
        if ((s.ready !== status.ready) || (s.backend !== status.backend)) {
          status = s;
          btn.hidden = !s.ready;
        }
      } catch (e) { /* 服务断了就别刷提示 */ }
    }, 15000);
  }

  JZ.voice = {
    init: init,
    get status() { return status; },
    start: begin,
    stop: function () { stop(true); },
  };
})();
