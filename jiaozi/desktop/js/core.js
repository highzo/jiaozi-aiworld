/* ============================================================
   饺子AIWorld · 内核（无框架，无构建）
   ============================================================ */
(function () {
  'use strict';

  const JZ = window.JZ = {
    version: '0.1.0',
    apps: {},
    state: { config: null, sys: null, roots: [], home: '', host: '' },
    handlers: {},
  };

  /* ---------------- 图标 ---------------- */
  const P = {
    folder: '<path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h4l2 2.5h7A1.5 1.5 0 0 1 19 10v7a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 3 17z"/>',
    'folder-open': '<path d="M3 8V6.5A1.5 1.5 0 0 1 4.5 5h3.7l2 2.5h6.3A1.5 1.5 0 0 1 18 9v1"/><path d="M3 9h17l-2 8.2a1.5 1.5 0 0 1-1.46 1.1H4.6a1.5 1.5 0 0 1-1.46-1.1z"/>',
    file: '<path d="M14 3H7a1.6 1.6 0 0 0-1.6 1.6v14.8A1.6 1.6 0 0 0 7 21h10a1.6 1.6 0 0 0 1.6-1.6V7.5z"/><path d="M14 3v4.5h4.6"/>',
    'file-text': '<path d="M14 3H7a1.6 1.6 0 0 0-1.6 1.6v14.8A1.6 1.6 0 0 0 7 21h10a1.6 1.6 0 0 0 1.6-1.6V7.5z"/><path d="M14 3v4.5h4.6"/><path d="M8.5 12.5h7M8.5 16h5"/>',
    image: '<rect x="3" y="4.5" width="18" height="15" rx="2"/><circle cx="8.6" cy="9.6" r="1.5"/><path d="M20 15.5l-4.4-4.2L6.5 19.5"/>',
    terminal: '<rect x="2.8" y="4.2" width="18.4" height="15.6" rx="2.2"/><path d="M7 9.5l2.6 2.4L7 14.4M12.4 14.8h4.2"/>',
    activity: '<path d="M3 12.5h3.6l2.2-6 3.4 11 2.4-5h6.4"/>',
    settings: '<circle cx="12" cy="12" r="3.1"/><path d="M19.4 14.4a1.5 1.5 0 0 0 .3 1.65l.05.05a1.8 1.8 0 1 1-2.55 2.55l-.05-.05a1.5 1.5 0 0 0-1.65-.3 1.5 1.5 0 0 0-.9 1.37V20a1.8 1.8 0 1 1-3.6 0v-.1a1.5 1.5 0 0 0-.98-1.37 1.5 1.5 0 0 0-1.65.3l-.05.05a1.8 1.8 0 1 1-2.55-2.55l.05-.05a1.5 1.5 0 0 0 .3-1.65 1.5 1.5 0 0 0-1.37-.9H4a1.8 1.8 0 1 1 0-3.6h.1a1.5 1.5 0 0 0 1.37-.98 1.5 1.5 0 0 0-.3-1.65l-.05-.05A1.8 1.8 0 1 1 7.67 4.9l.05.05a1.5 1.5 0 0 0 1.65.3H9.5a1.5 1.5 0 0 0 .9-1.37V4a1.8 1.8 0 1 1 3.6 0v.1a1.5 1.5 0 0 0 .9 1.37 1.5 1.5 0 0 0 1.65-.3l.05-.05a1.8 1.8 0 1 1 2.55 2.55l-.05.05a1.5 1.5 0 0 0-.3 1.65v.08a1.5 1.5 0 0 0 1.37.9H20a1.8 1.8 0 1 1 0 3.6h-.1a1.5 1.5 0 0 0-1.37.9z"/>',
    sliders: '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
    search: '<circle cx="10.8" cy="10.8" r="6.3"/><path d="M15.5 15.5l4.3 4.3"/>',
    bell: '<path d="M18 8.5a6 6 0 1 0-12 0c0 5-2 6.5-2 6.5h16s-2-1.5-2-6.5"/><path d="M10.3 19a2 2 0 0 0 3.4 0"/>',
    cpu: '<rect x="6.5" y="6.5" width="11" height="11" rx="1.8"/><path d="M10 3v3.5M14 3v3.5M10 17.5V21M14 17.5V21M3 10h3.5M3 14h3.5M17.5 10H21M17.5 14H21"/>',
    plus: '<path d="M12 5.5v13M5.5 12h13"/>',
    minus: '<path d="M5.5 12h13"/>',
    x: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    'chevron-right': '<path d="M9.5 5.5l6.5 6.5-6.5 6.5"/>',
    'chevron-left': '<path d="M14.5 5.5L8 12l6.5 6.5"/>',
    'chevron-down': '<path d="M5.5 9.5L12 16l6.5-6.5"/>',
    'chevrons-right': '<path d="M6.5 6l6 6-6 6M13 6l6 6-6 6"/>',
    'chevrons-left': '<path d="M17.5 6l-6 6 6 6M11 6l-6 6 6 6"/>',
    send: '<path d="M21 3L10.5 13.5"/><path d="M21 3l-6.8 18-3.7-7.5L3 9.8z"/>',
    square: '<rect x="6" y="6" width="12" height="12" rx="1.6"/>',
    power: '<path d="M12 3.5v8"/><path d="M7.2 6.4a7.2 7.2 0 1 0 9.6 0"/>',
    home: '<path d="M4 11.2l8-6.7 8 6.7V19a1.4 1.4 0 0 1-1.4 1.4H5.4A1.4 1.4 0 0 1 4 19z"/><path d="M9.6 20.4v-6.2h4.8v6.2"/>',
    desktop: '<rect x="3" y="4.5" width="18" height="12" rx="1.8"/><path d="M9 20.5h6M12 16.5v4"/>',
    download: '<path d="M12 4v10.5M8 11l4 3.5 4-3.5"/><path d="M4.5 17.5v1.5a1.5 1.5 0 0 0 1.5 1.5h12a1.5 1.5 0 0 0 1.5-1.5v-1.5"/>',
    upload: '<path d="M12 15.5V5M8 8.5L12 5l4 3.5"/><path d="M4.5 17.5v1.5a1.5 1.5 0 0 0 1.5 1.5h12a1.5 1.5 0 0 0 1.5-1.5v-1.5"/>',
    refresh: '<path d="M20 11.5a8 8 0 1 0-.7 4.6"/><path d="M20 4.5v6h-6"/>',
    trash: '<path d="M4.5 7h15M9.5 7V4.8h5V7M6.5 7l.9 12.2a1.6 1.6 0 0 0 1.6 1.5h6a1.6 1.6 0 0 0 1.6-1.5L17.5 7"/>',
    edit: '<path d="M4.5 19.5h4l10-10a2.1 2.1 0 0 0-3-3l-10 10z"/><path d="M14 7l3 3"/>',
    copy: '<rect x="8.5" y="8.5" width="11" height="11" rx="1.8"/><path d="M15.5 5.5h-9A1.5 1.5 0 0 0 5 7v9"/>',
    save: '<path d="M5 4.5h11L19.5 8v10.5A1.5 1.5 0 0 1 18 20H6a1.5 1.5 0 0 1-1.5-1.5V6A1.5 1.5 0 0 1 6 4.5z"/><path d="M8 4.5v5h7v-5M8 20v-6h8v6"/>',
    'alert-triangle': '<path d="M12 4.5l8.5 15h-17z"/><path d="M12 9.5v4.5M12 17h.01"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    sparkles: '<path d="M12 3.5l1.9 4.9 4.9 1.9-4.9 1.9L12 17.1l-1.9-4.9L5.2 10.3l4.9-1.9z"/><path d="M18.5 16.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
    bot: '<rect x="4.5" y="7" width="15" height="11" rx="3"/><circle cx="9.5" cy="12.5" r="1.2"/><circle cx="14.5" cy="12.5" r="1.2"/><path d="M12 4.5V7M9 18v2M15 18v2"/>',
    info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5M12 7.8h.01"/>',
    'hard-drive': '<rect x="3.5" y="5" width="17" height="14" rx="2.2"/><path d="M3.5 13.5h17"/><circle cx="7.5" cy="16.5" r=".9"/><circle cx="10.5" cy="16.5" r=".9"/>',
    zap: '<path d="M13.5 3L5 13.5h5.5L10 21l8.5-10.5H13z"/>',
    'external-link': '<path d="M14 4.5h5.5V10"/><path d="M19 5l-8 8"/><path d="M18 14.5v4a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6h4"/>',
    'arrow-left': '<path d="M19 12H5M11 5.5L4.5 12 11 18.5"/>',
    'arrow-up': '<path d="M12 19V5M5.5 11.5L12 5l6.5 6.5"/>',
    'arrow-right': '<path d="M5 12h14M13 5.5L19.5 12 13 18.5"/>',
    code: '<path d="M8.5 8L4.5 12l4 4M15.5 8l4 4-4 4"/>',
    grid: '<rect x="4" y="4" width="7" height="7" rx="1.6"/><rect x="13" y="4" width="7" height="7" rx="1.6"/><rect x="4" y="13" width="7" height="7" rx="1.6"/><rect x="13" y="13" width="7" height="7" rx="1.6"/>',
    list: '<path d="M8 6.5h12M8 12h12M8 17.5h12M4.2 6.5h.01M4.2 12h.01M4.2 17.5h.01"/>',
    wifi: '<path d="M4 9.5a12 12 0 0 1 16 0M7 13a7.6 7.6 0 0 1 10 0M10 16.4a3.4 3.4 0 0 1 4 0"/><circle cx="12" cy="19.6" r=".8"/>',
    eye: '<path d="M2.5 12S6 6.5 12 6.5 21.5 12 21.5 12 18 17.5 12 17.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>',
    lock: '<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>',
    mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3"/>',
    globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17"/><path d="M12 3.5c2.6 2.4 3.9 5.3 3.9 8.5s-1.3 6.1-3.9 8.5c-2.6-2.4-3.9-5.3-3.9-8.5S9.4 5.9 12 3.5z"/>',
  };

  JZ.icon = function (name, size) {
    const s = size || 16;
    const body = P[name] || P.file;
    return '<svg viewBox="0 0 24 24" width="' + s + '" height="' + s +
      '" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' +
      body + '</svg>';
  };
  JZ.paintIcons = function (root) {
    (root || document).querySelectorAll('[data-icon]').forEach(function (el) {
      if (el.dataset.iconDone === '1') return;
      el.insertAdjacentHTML('afterbegin', JZ.icon(el.dataset.icon, el.dataset.iconSize || 16));
      el.dataset.iconDone = '1';
    });
  };

  /* ---------------- 工具函数 ---------------- */
  const esc = JZ.esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };

  JZ.fmt = {
    bytes(n) {
      n = Number(n) || 0;
      if (n < 1024) return n + ' B';
      const u = ['KB', 'MB', 'GB', 'TB'];
      let i = -1;
      do { n /= 1024; i++; } while (n >= 1024 && i < u.length - 1);
      return n.toFixed(n < 10 ? 1 : 0) + ' ' + u[i];
    },
    time(t) {
      if (!t) return '—';
      const d = new Date(t * 1000);
      const now = new Date();
      const pad = (x) => String(x).padStart(2, '0');
      const hm = pad(d.getHours()) + ':' + pad(d.getMinutes());
      if (d.toDateString() === now.toDateString()) return hm;
      return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + hm;
    },
    dur(s) {
      s = Math.floor(s || 0);
      const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
      if (d) return JZ.t('{d} 天 {h} 小时', { d: d, h: h });
      if (h) return JZ.t('{h} 小时 {m} 分', { h: h, m: m });
      return JZ.t('{m} 分钟', { m: m });
    },
    num(n) { return (Number(n) || 0).toLocaleString(JZ.i18n ? JZ.i18n.locale : 'en-US'); },
  };

  /* ---------------- API ---------------- */
  function qs(params) {
    if (!params) return '';
    const u = new URLSearchParams();
    Object.keys(params).forEach(function (k) {
      if (params[k] !== undefined && params[k] !== null) u.set(k, params[k]);
    });
    const s = u.toString();
    return s ? '?' + s : '';
  }

  async function req(method, path, opts) {
    opts = opts || {};
    const res = await fetch(path + qs(opts.params), {
      method: method,
      headers: Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {}),
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
    let data = null;
    const text = await res.text();
    try { data = text ? JSON.parse(text) : {}; } catch (e) { data = { ok: false, error: text.slice(0, 300) }; }
    if (!res.ok || data.ok === false) {
      const err = new Error((data && data.error) || ('HTTP ' + res.status));
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data.data !== undefined ? data.data : data;
  }

  JZ.api = {
    get: (p, params) => req('GET', p, { params: params }),
    post: (p, body) => req('POST', p, { body: body || {} }),
    raw: (p, params) => p + qs(params),
  };

  /* ---------------- 事件总线（本地 + 服务端） ---------------- */
  JZ.on = function (type, fn) {
    (JZ.handlers[type] = JZ.handlers[type] || []).push(fn);
    return () => {
      JZ.handlers[type] = JZ.handlers[type].filter((f) => f !== fn);
    };
  };
  JZ.emit = function (type, data) {
    (JZ.handlers[type] || []).forEach(function (f) {
      try { f(data); } catch (e) { console.error('[handler]', type, e); }
    });
  };

  let es = null, esReady = false;
  JZ.connect = function () {
    // ?nosse=1 用于静态截图/自动化预览：不建立长连接，页面才能"加载完成"
    if (/[?&]nosse=1/.test(location.search)) { JZ.emit('sse', { online: false }); return; }
    if (es) try { es.close(); } catch (e) {}
    // ?ms=1500 时事件流会在 1.5 秒后自行结束（方便截图/调试）
    const ms = new URLSearchParams(location.search).get('ms');
    es = new EventSource('/api/events' + (ms ? '?ms=' + encodeURIComponent(ms) : ''));
    let gotHello = false;
    es.onopen = function () { esReady = true; JZ.emit('sse', { online: true }); };
    es.onerror = function () {
      esReady = false;
      JZ.emit('sse', { online: false });
      if (ms && gotHello) { try { es.close(); } catch (e) {} }  // 有界流不重连
    };
    es.onmessage = function (ev) {
      let obj;
      try { obj = JSON.parse(ev.data); } catch (e) { return; }
      if (obj.t === 'hello') { JZ.state.cid = obj.cid; gotHello = true; return; }
      JZ.emit('ev:' + obj.t, obj);
      JZ.emit('ev', obj);
    };
  };
  JZ.sseOnline = () => esReady;

  /* ---------------- Toast ---------------- */
  const toastHost = () => document.getElementById('toasts');
  JZ.toast = function (title, body, level, timeout) {
    const el = document.createElement('div');
    el.className = 'toast ' + (level || '');
    const ico = { ok: 'check', warn: 'alert-triangle', err: 'alert-triangle' }[level] || 'info';
    el.innerHTML = '<div class="tico">' + JZ.icon(ico, 13) + '</div><div class="tbody"><b>' +
      esc(title) + '</b>' + (body ? '<span>' + esc(body) + '</span>' : '') + '</div>';
    toastHost().appendChild(el);
    const kill = () => { el.classList.add('out'); setTimeout(() => el.remove(), 260); };
    setTimeout(kill, timeout || 3600);
    el.onclick = kill;
  };

  /* ---------------- 模态 ---------------- */
  const mh = () => document.getElementById('modalHost');
  JZ.modal = function (opts) {
    return new Promise(function (resolve) {
      const host = mh();
      const el = document.createElement('div');
      el.className = 'modal';
      let inputHtml = '';
      if (opts.input) {
        inputHtml = '<input class="input" id="mInput" value="' + esc(opts.value || '') + '" placeholder="' +
          esc(opts.placeholder || '') + '">';
      }
      el.innerHTML = '<h3>' + esc(opts.title || '') + '</h3>' +
        (opts.body ? '<p>' + esc(opts.body) + '</p>' : '') + inputHtml +
        '<div class="modal-foot">' +
        (opts.cancel === false ? '' : '<button class="btn" data-act="cancel">' + esc(opts.cancelText || JZ.t('取消')) + '</button>') +
        '<button class="btn ' + (opts.danger ? 'primary' : 'primary') + '" data-act="ok" style="' +
        (opts.danger ? 'background:var(--err)' : '') + '">' + esc(opts.okText || JZ.t('确定')) + '</button>' +
        '</div>';
      host.innerHTML = '';
      const mask = document.createElement('div');
      mask.className = 'modal-mask';
      host.appendChild(mask);
      host.appendChild(el);
      host.classList.add('on');
      JZ.paintIcons(el);
      const inp = el.querySelector('#mInput');
      if (inp) { inp.focus(); inp.select(); }
      else { const b = el.querySelector('[data-act="ok"]'); if (b) b.focus(); }

      function done(v) { host.classList.remove('on'); host.innerHTML = ''; resolve(v); }
      el.querySelector('[data-act="ok"]').onclick = () => done(opts.input ? (inp.value || '') : true);
      const c = el.querySelector('[data-act="cancel"]');
      if (c) c.onclick = () => done(opts.input ? null : false);
      mask.onclick = () => done(opts.input ? null : false);
      el.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); el.querySelector('[data-act="ok"]').click(); }
        if (e.key === 'Escape') { done(opts.input ? null : false); }
      });
    });
  };
  JZ.confirm = (title, body, danger) => JZ.modal({ title: title, body: body, danger: danger, okText: danger ? JZ.t('确认') : JZ.t('确定') });
  JZ.prompt = (title, value, body) => JZ.modal({ title: title, body: body, input: true, value: value, okText: JZ.t('确定') });

  /* ---------------- 右键菜单 ---------------- */
  const ctx = () => document.getElementById('ctxMenu');
  JZ.menu = function (x, y, items) {
    const m = ctx();
    m.innerHTML = items.map(function (it, i) {
      if (it.sep) return '<div class="ctx-sep"></div>';
      return '<div class="ctx-item ' + (it.danger ? 'danger ' : '') + (it.disabled ? 'disabled' : '') +
        '" data-i="' + i + '">' + (it.icon ? JZ.icon(it.icon, 14) : '') +
        '<span>' + esc(it.label) + '</span>' + (it.key ? '<span class="ctx-k">' + esc(it.key) + '</span>' : '') + '</div>';
    }).join('');
    m.classList.add('on');
    const w = m.offsetWidth, h = m.offsetHeight;
    m.style.left = Math.min(x, window.innerWidth - w - 8) + 'px';
    m.style.top = Math.min(y, window.innerHeight - h - 8) + 'px';
    m.querySelectorAll('.ctx-item').forEach(function (el) {
      el.onclick = function () {
        const it = items[+el.dataset.i];
        JZ.closeMenu();
        if (it && it.action) it.action();
      };
    });
    setTimeout(() => document.addEventListener('pointerdown', JZ.closeMenu, { once: true }), 0);
  };
  JZ.closeMenu = function () { ctx().classList.remove('on'); };

  /* ---------------- 轻量 Markdown ---------------- */
  JZ.md = function (src) {
    if (!src) return '';
    const blocks = [];
    let text = String(src).replace(/```(\w*)\n?([\s\S]*?)```/g, function (_, lang, code) {
      blocks.push('<pre><code>' + esc(code.replace(/\n$/, '')) + '</code></pre>');
      return '\u0000' + (blocks.length - 1) + '\u0000';
    });
    text = esc(text);
    text = text.replace(/`([^`\n]+)`/g, '<code>$1</code>');
    text = text.replace(/^### (.+)$/gm, '<h3>$1</h3>')
      .replace(/^## (.+)$/gm, '<h2>$1</h2>')
      .replace(/^# (.+)$/gm, '<h1>$1</h1>');
    text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    text = text.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    text = text.replace(/^\s*[-*] (.+)$/gm, '<li>$1</li>');
    text = text.replace(/(<li>[\s\S]*?<\/li>)(?!\s*<li>)/g, '<ul>$1</ul>');
    text = text.replace(/^\s*\d+\. (.+)$/gm, '<li>$1</li>');
    const parts = text.split(/\n{2,}/).map(function (p) {
      p = p.trim();
      if (!p) return '';
      if (/^<(h\d|ul|ol|pre|li)/.test(p)) return p;
      return '<p>' + p.replace(/\n/g, '<br>') + '</p>';
    });
    text = parts.join('');
    text = text.replace(/\u0000(\d+)\u0000/g, (_, i) => blocks[+i]);
    return text;
  };

  /* ---------------- 偏好 ---------------- */
  JZ.pref = {
    get(k, d) {
      try { const v = localStorage.getItem('jz:' + k); return v === null ? d : JSON.parse(v); }
      catch (e) { return d; }
    },
    set(k, v) {
      try { localStorage.setItem('jz:' + k, JSON.stringify(v)); } catch (e) {}
    },
  };

  document.addEventListener('DOMContentLoaded', function () { JZ.paintIcons(); });
})();
