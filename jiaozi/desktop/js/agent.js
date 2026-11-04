/* AI 助手（饺子）——人与 AI 共用同一桌面的入口 */
(function () {
  'use strict';
  const JZ = window.JZ;
  const esc = JZ.esc;

  const CHIPS = [
    '看看这台机器的状态',
    '在桌面建一个 todo.md，写三条今天的计划',
    '列一下主目录里有什么',
    '打开系统监视器给我看内存占用',
  ];

  let body, input, sendBtn, statusEl, stepsEl, modelEl, emptyEl;
  let busy = false, abortCtl = null, turn = null, curBubble = null, raf = 0;

  function atBottom() {
    return body.scrollTop + body.clientHeight >= body.scrollHeight - 60;
  }
  function scrollDown(force) {
    if (force || atBottom()) body.scrollTop = body.scrollHeight;
  }

  function hideEmpty() {
    if (emptyEl) { emptyEl.style.display = 'none'; }
  }

  function addUser(text) {
    hideEmpty();
    const el = document.createElement('div');
    el.className = 'msg me';
    el.innerHTML = '<div class="bubble">' + esc(text) + '</div>';
    body.appendChild(el);
    scrollDown(true);
  }

  function newTurn() {
    const el = document.createElement('div');
    el.className = 'msg ai';
    el.innerHTML = '<div class="turn"></div>';
    body.appendChild(el);
    turn = el.querySelector('.turn');
    curBubble = null;
    scrollDown(true);
    return turn;
  }

  function closeBubble() {
    if (curBubble) {
      curBubble.classList.remove('caret');
      curBubble.dataset.closed = '1';
    }
    curBubble = null;
  }

  function ensureBubble() {
    if (curBubble && curBubble.dataset.closed !== '1') return curBubble;
    const b = document.createElement('div');
    b.className = 'bubble caret';
    b.dataset.raw = '';
    turn.appendChild(b);
    curBubble = b;
    scrollDown();
    return b;
  }

  function appendText(delta) {
    const b = ensureBubble();
    b.dataset.raw += delta;
    renderBubble(b);
  }

  function renderBubble(b) {
    if (raf) return;
    raf = requestAnimationFrame(function () {
      raf = 0;
      if (!b.isConnected) return;
      b.innerHTML = JZ.md(b.dataset.raw) || '';
      b.classList.add('caret');
      scrollDown();
    });
  }

  function setBubbleText(text) {
    const b = ensureBubble();
    b.dataset.raw = text;
    b.innerHTML = JZ.md(text);
    b.classList.remove('caret');
    scrollDown();
  }

  /* 从 image_gen 的工具结果里抠出图片路径，好在对话里直接给缩略图。
     让人类"看见"AI 画了什么，而不是读一段 JSON。 */
  function toolImages(ev) {
    if (ev.name !== 'image_gen' || ev.status !== 'ok' || !ev.result) return [];
    try {
      const j = JSON.parse(ev.result);
      if (j && Array.isArray(j.files)) return j.files.filter(Boolean).slice(0, 6);
    } catch (e) {}
    return [];
  }

  function renderToolImages(box, paths) {
    const one = paths.length === 1;
    box.innerHTML = '<div class="sc-imgs' + (one ? ' one' : '') + '">' + paths.map(function (p) {
      return '<button class="sc-img" title="' + esc(p) + '">' +
        '<img loading="lazy" src="' + esc(JZ.api.raw('/api/fs/raw', { path: p })) + '" alt="">' +
        '</button>';
    }).join('') + '</div>';
    box.querySelectorAll('.sc-img').forEach(function (b) {
      b.onclick = function () { JZ.WM.open('viewer', { path: b.title }); };
    });
  }

  function toolCard(ev) {
    closeBubble();
    const id = 'tc-' + (ev.id || Math.random().toString(36).slice(2));
    let card = turn.querySelector('[data-tc="' + id + '"]');
    if (!card) {
      card = document.createElement('div');
      card.className = 'step-card running';
      card.dataset.tc = id;
      card.innerHTML =
        '<div class="sc-head"><span class="sc-ico">' + JZ.icon('zap', 11) + '</span>' +
        '<span class="sc-title"></span><span class="sc-st">进行中</span></div>' +
        '<div class="sc-body"></div>';
      turn.appendChild(card);
      card.querySelector('.sc-head').onclick = function () { card.classList.toggle('open'); };
    }
    card.querySelector('.sc-title').textContent = ev.summary || ev.name || '执行中';
    if (ev.status === 'ok') {
      card.className = 'step-card ok';
      card.querySelector('.sc-st').textContent = '完成';
      const imgs = toolImages(ev);
      if (imgs.length) {
        card.classList.add('open', 'has-img');
        renderToolImages(card.querySelector('.sc-body'), imgs);
      } else {
        card.querySelector('.sc-body').textContent = (ev.result || '(无输出)').slice(0, 4000);
      }
    } else if (ev.status === 'denied') {
      card.className = 'step-card denied';
      card.querySelector('.sc-st').textContent = '已拒绝';
    } else if (ev.status === 'error') {
      card.className = 'step-card error';
      card.querySelector('.sc-st').textContent = '失败';
      card.querySelector('.sc-body').textContent = ev.result || '';
    }
    scrollDown();
  }

  function approvalCard(ev) {
    closeBubble();
    const card = document.createElement('div');
    card.className = 'approve-card';
    const args = ev.args || {};
    const detail = ev.name === 'shell_run' ? (args.cmd || '') : JSON.stringify(args, null, 2);
    card.innerHTML =
      '<h4>' + JZ.icon('alert-triangle', 14) + '需要你确认</h4>' +
      '<p>' + esc(ev.summary || ev.name) + '</p>' +
      (detail ? '<pre>' + esc(String(detail).slice(0, 600)) + '</pre>' : '') +
      '<div class="ac-btns"><button class="btn sm primary" data-a="yes">允许</button>' +
      '<button class="btn sm" data-a="no">拒绝</button></div>';
    turn.appendChild(card);
    scrollDown(true);
    card.querySelector('[data-a="yes"]').onclick = function () { answer(card, true); };
    card.querySelector('[data-a="no"]').onclick = function () { answer(card, false); };
  }

  function answer(card, ok) {
    card.classList.add('answered');
    card.querySelector('p').textContent = (ok ? '已允许：' : '已拒绝：') + card.querySelector('p').textContent;
    JZ.api.post('/api/agent/approve', { id: card.dataset.aid, ok: ok }).catch(function () {});
  }

  function note(text, cls) {
    const el = document.createElement('div');
    el.className = 'hint';
    el.style.margin = '4px 0 10px';
    el.style.color = cls === 'err' ? 'var(--err)' : cls === 'warn' ? 'var(--warn)' : 'var(--text-3)';
    el.textContent = text;
    turn.appendChild(el);
    scrollDown();
  }

  function setBusy(v) {
    busy = v;
    input.disabled = v;
    document.querySelector('.ai-hint').classList.toggle('busy', v);
    if (v) {
      sendBtn.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14"><rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/></svg>';
      sendBtn.title = '停止';
      statusEl.textContent = '思考中';
    } else {
      sendBtn.innerHTML = JZ.icon('send', 15);
      sendBtn.title = '发送';
      statusEl.textContent = '就绪';
      stepsEl.textContent = '';
      input.disabled = false;
      input.focus();
    }
  }

  async function send(text) {
    text = (text || input.value).trim();
    if (!text || busy) return;
    input.value = '';
    input.style.height = 'auto';
    addUser(text);
    newTurn();
    setBusy(true);
    abortCtl = new AbortController();
    let done = false;

    try {
      const res = await fetch('/api/agent/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: text, sid: 'main' }),
        signal: abortCtl.signal,
      });
      if (!res.ok || !res.body) {
        let msg = 'HTTP ' + res.status;
        try { const j = await res.json(); msg = j.error || msg; } catch (e) {}
        throw new Error(msg);
      }
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      while (true) {
        const r = await reader.read();
        if (r.done) break;
        buf += dec.decode(r.value, { stream: true });
        let idx;
        while ((idx = buf.indexOf('\n\n')) >= 0) {
          const chunk = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          const line = chunk.split('\n').find(l => l.startsWith('data:'));
          if (!line) continue;
          let ev;
          try { ev = JSON.parse(line.slice(5).trim()); } catch (e) { continue; }
          handle(ev);
          if (ev.t === 'done') done = true;
        }
      }
    } catch (e) {
      if (e.name === 'AbortError') {
        if (turn) note('已从界面中断。模型可能仍在后台收尾，稍后可以再问我。', 'warn');
      } else {
        if (turn) {
          const el = document.createElement('div');
          el.className = 'msg err';
          el.innerHTML = '<div class="bubble">' + esc(e.message || String(e)) + '</div>';
          turn.appendChild(el);
        }
      }
    } finally {
      closeBubble();
      if (!done && turn && !turn.querySelector('.bubble')) {
        note('本轮没有返回内容。检查模型服务是否在线。', 'err');
      }
      setBusy(false);
      abortCtl = null;
    }
  }

  function handle(ev) {
    switch (ev.t) {
      case 'start':
        statusEl.textContent = '思考中';
        break;
      case 'step':
        stepsEl.textContent = '第 ' + ev.i + ' / ' + ev.max + ' 步';
        break;
      case 'delta':
        appendText(ev.d || '');
        break;
      case 'final_replace':
        setBubbleText(ev.d || '');
        break;
      case 'tool':
        toolCard(ev);
        break;
      case 'approval': {
        approvalCard(ev);
        const card = turn.lastElementChild;
        card.dataset.aid = ev.id;
        statusEl.textContent = '等待确认';
        break;
      }
      case 'warn':
        note(ev.d, 'warn');
        break;
      case 'error':
        note(ev.d, 'err');
        statusEl.textContent = '出错了';
        break;
      case 'done':
        closeBubble();
        if (ev.content && (!turn.querySelector('.bubble') || !turn.querySelector('.bubble').dataset.raw)) {
          setBubbleText(ev.content);
        }
        statusEl.textContent = '就绪';
        break;
      default:
        break;
    }
  }

  async function loadHistory() {
    try {
      const d = await JZ.api.get('/api/agent/history', { sid: 'main' });
      const msgs = (d.messages || []).slice(-30);
      if (!msgs.length) return;
      hideEmpty();
      msgs.forEach(function (m) {
        if (m.role === 'user') addUser(m.content);
        else {
          newTurn();
          setBubbleText(m.content);
          closeBubble();
        }
      });
      scrollDown(true);
    } catch (e) { /* ignore */ }
  }

  async function reset() {
    if (busy) return;
    try { await JZ.api.post('/api/agent/reset', { sid: 'main' }); } catch (e) {}
    body.querySelectorAll('.msg').forEach(el => el.remove());
    emptyEl.style.display = '';
    JZ.toast('新对话', '上下文已清空', 'ok', 1500);
  }

  function toggle(force) {
    const open = force === undefined ? !document.body.classList.contains('ai-open') : force;
    document.body.classList.toggle('ai-open', open);
    JZ.pref.set('aiOpen', open);
    if (JZ.layoutChanged) JZ.layoutChanged();
    if (open) setTimeout(function () { input.focus(); }, 320);
  }

  function init() {
    body = document.getElementById('aiBody');
    input = document.getElementById('aiInput');
    sendBtn = document.getElementById('aiSend');
    statusEl = document.getElementById('aiStatus');
    stepsEl = document.getElementById('aiSteps');
    modelEl = document.getElementById('aiModel');
    emptyEl = document.getElementById('aiEmpty');

    JZ.agent = { send: send, reset: reset, toggle: toggle };

    document.getElementById('aiChips').innerHTML = CHIPS.map(function (c) {
      return '<button class="chip">' + esc(c) + '</button>';
    }).join('');
    document.getElementById('aiChips').querySelectorAll('.chip').forEach(function (b) {
      b.onclick = function () { send(b.textContent); };
    });

    sendBtn.onclick = function () {
      if (busy) { if (abortCtl) abortCtl.abort(); return; }
      send();
    };
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        send();
      }
    });
    input.addEventListener('input', function () {
      input.style.height = 'auto';
      input.style.height = Math.min(132, input.scrollHeight) + 'px';
    });
    document.getElementById('aiNew').onclick = reset;
    document.getElementById('aiClose').onclick = function () { toggle(false); };
    document.getElementById('aiCfg').onclick = function () { JZ.WM.open('settings'); };
    document.getElementById('trayAi').onclick = function () { toggle(); };

    const cfg = JZ.state.config;
    if (cfg && cfg.llm) {
      modelEl.textContent = cfg.llm.model || '未设置模型';
      modelEl.title = cfg.llm.base_url || '';
    }
    loadHistory();

    // 手机上（窄屏）AI 面板是全屏的，默认展开会把桌面整个盖住，
    // 第一眼就变成「一个聊天框」。所以窄屏默认进桌面，想看 AI 点左下角按钮。
    const wide = window.innerWidth >= 900;
    if (wide) {
      if (JZ.pref.get('aiOpen', true)) document.body.classList.add('ai-open');
    } else {
      const closeBtn = document.getElementById('aiClose');
      if (closeBtn) closeBtn.title = '返回桌面';
    }
    // 触屏没有 Enter / Shift，键盘提示对手机用户没有意义
    if (window.matchMedia && window.matchMedia('(pointer: coarse)').matches) {
      input.placeholder = '让饺子做点什么…（点右侧按钮发送）';
    }
  }

  JZ.onConfig = function (cfg) {
    if (modelEl && cfg.llm) {
      modelEl.textContent = cfg.llm.model || '未设置模型';
      modelEl.title = cfg.llm.base_url || '';
    }
  };

  // 其它模块可以调起对话
  JZ.ask = function (text) {
    toggle(true);
    setTimeout(function () { send(text); }, 60);
  };

  JZ.initAgent = init;
})();
