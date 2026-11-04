/* ============================================================
   窗口管理器：拖拽 / 缩放 / 贴边 / 最大化 / 层叠
   ============================================================ */
(function () {
  'use strict';
  const JZ = window.JZ;

  const WM = JZ.WM = {
    wins: new Map(),
    z: 100,
    seq: 0,
    active: null,
  };

  const stage = () => document.getElementById('windows');
  const stageRect = () => {
    const el = document.getElementById('windows');
    return { w: el.clientWidth, h: el.clientHeight };
  };

  JZ.registerApp = function (def) { JZ.apps[def.id] = def; };

  function chrome(win) {
    const app = win.app;
    const el = document.createElement('div');
    el.className = 'win';
    el.style.width = win.w + 'px';
    el.style.height = win.h + 'px';
    el.style.left = win.x + 'px';
    el.style.top = win.y + 'px';
    el.innerHTML =
      '<div class="win-head">' +
        '<div class="win-ico" style="background:' + (app.color || '#2f6bff') + '">' + JZ.icon(app.icon, 13) + '</div>' +
        '<div class="win-title">' + JZ.esc(win.title) + '</div>' +
        '<div class="win-tools">' +
          '<button class="wbtn min" title="最小化"><svg viewBox="0 0 24 24" width="12" height="12"><path d="M5 12h14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg></button>' +
          '<button class="wbtn max" title="最大化"><svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2"><rect x="5" y="5" width="14" height="14" rx="2"/></svg></button>' +
          '<button class="wbtn close" title="关闭"><svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg></button>' +
        '</div>' +
      '</div>' +
      '<div class="win-body"></div>' +
      ['n', 's', 'w', 'e', 'nw', 'ne', 'sw', 'se'].map(d => '<div class="rs rs-' + d + '" data-dir="' + d + '"></div>').join('');
    return el;
  }

  function bindDrag(win) {
    const head = win.el.querySelector('.win-head');
    head.addEventListener('pointerdown', function (e) {
      if (e.target.closest('.wbtn') || e.button !== 0) return;
      WM.focus(win);
      if (win.maxed) {
        // 从最大化拖出：还原并按比例定位
        const ratio = (e.clientX - win.el.getBoundingClientRect().left) / win.w;
        const r = win.saved || { w: 760, h: 520 };
        WM.toggleMax(win, true);
        win.w = r.w; win.h = r.h;
        win.x = Math.max(0, Math.min(e.clientX - r.w * ratio, stageRect().w - r.w));
        win.y = Math.max(0, e.clientY - 18);
        apply(win);
      }
      const sx = e.clientX, sy = e.clientY, ox = win.x, oy = win.y;
      let moved = false, snap = null;
      win.el.classList.add('dragging');
      head.setPointerCapture(e.pointerId);

      function move(ev) {
        const dx = ev.clientX - sx, dy = ev.clientY - sy;
        if (!moved && Math.abs(dx) + Math.abs(dy) < 3) return;
        moved = true;
        win.x = ox + dx; win.y = oy + dy;
        apply(win);
        // 贴边检测
        const s = stageRect();
        snap = null;
        if (ev.clientY <= 6) snap = 'max';
        else if (ev.clientX <= 6) snap = 'left';
        else if (ev.clientX >= s.w - 6) snap = 'right';
        showSnap(snap, s);
      }
      function up() {
        head.removeEventListener('pointermove', move);
        head.removeEventListener('pointerup', up);
        win.el.classList.remove('dragging');
        showSnap(null);
        if (snap) doSnap(win, snap);
        else clamp(win);
      }
      head.addEventListener('pointermove', move);
      head.addEventListener('pointerup', up);
    });

    head.addEventListener('dblclick', function (e) {
      if (e.target.closest('.wbtn')) return;
      WM.toggleMax(win);
    });
  }

  function bindResize(win) {
    win.el.querySelectorAll('.rs').forEach(function (h) {
      h.addEventListener('pointerdown', function (e) {
        if (win.maxed) return;
        e.preventDefault(); e.stopPropagation();
        WM.focus(win);
        const dir = h.dataset.dir;
        const sx = e.clientX, sy = e.clientY;
        const r = { x: win.x, y: win.y, w: win.w, h: win.h };
        h.setPointerCapture(e.pointerId);
        function move(ev) {
          const dx = ev.clientX - sx, dy = ev.clientY - sy;
          if (dir.includes('e')) win.w = Math.max(330, r.w + dx);
          if (dir.includes('s')) win.h = Math.max(200, r.h + dy);
          if (dir.includes('w')) {
            const nw = Math.max(330, r.w - dx);
            win.x = r.x + (r.w - nw); win.w = nw;
          }
          if (dir.includes('n')) {
            const nh = Math.max(200, r.h - dy);
            win.y = r.y + (r.h - nh); win.h = nh;
          }
          apply(win);
        }
        function up() {
          h.removeEventListener('pointermove', move);
          h.removeEventListener('pointerup', up);
          win.el.classList.remove('dragging');
        }
        win.el.classList.add('dragging');
        h.addEventListener('pointermove', move);
        h.addEventListener('pointerup', up);
      });
    });
  }

  const snapEl = () => document.getElementById('snapPreview');
  function showSnap(kind, s) {
    const el = snapEl();
    if (!kind) { el.classList.remove('on'); return; }
    const g = 0;
    const rect = kind === 'max' ? { x: g, y: g, w: s.w - g * 2, h: s.h - g * 2 }
      : kind === 'left' ? { x: g, y: g, w: Math.round(s.w / 2) - g, h: s.h - g * 2 }
        : { x: Math.round(s.w / 2), y: g, w: Math.round(s.w / 2) - g, h: s.h - g * 2 };
    el.style.left = rect.x + 'px'; el.style.top = rect.y + 'px';
    el.style.width = rect.w + 'px'; el.style.height = rect.h + 'px';
    el.classList.add('on');
  }
  function doSnap(win, kind) {
    const s = stageRect();
    if (!win.saved) win.saved = { w: win.w, h: win.h, x: win.x, y: win.y };
    if (kind === 'max') {
      win.maxed = true; win.el.classList.add('maxed');
      win.x = 0; win.y = 0; win.w = s.w; win.h = s.h;
    } else {
      win.maxed = false; win.el.classList.remove('maxed');
      win.w = Math.round(s.w / 2); win.h = s.h;
      win.x = kind === 'left' ? 0 : Math.round(s.w / 2);
      win.y = 0;
    }
    apply(win);
  }

  function apply(win) {
    win.el.style.left = Math.round(win.x) + 'px';
    win.el.style.top = Math.round(win.y) + 'px';
    win.el.style.width = Math.round(win.w) + 'px';
    win.el.style.height = Math.round(win.h) + 'px';
  }

  function clamp(win) {
    const s = stageRect();
    win.y = Math.max(-2, Math.min(win.y, s.h - 40));
    win.x = Math.max(-win.w + 90, Math.min(win.x, s.w - 90));
    apply(win);
  }

  WM.open = function (appId, args) {
    const app = JZ.apps[appId];
    if (!app) { JZ.toast('应用不存在', appId, 'err'); return null; }
    if (app.singleton) {
      for (const w of WM.wins.values()) {
        if (w.appId === appId) {
          if (w.min) WM.restore(w); else WM.focus(w);
          if (app.onArgs && args) app.onArgs(w, args);
          return w;
        }
      }
    }
    if (app.multi === false) {
      for (const w of WM.wins.values()) {
        if (w.appId === appId && JSON.stringify(w.args) === JSON.stringify(args)) {
          WM.focus(w); return w;
        }
      }
    }

    const s = stageRect();
    const size = app.size || [880, 560];
    const n = WM.wins.size;
    let w = Math.min(size[0], Math.max(340, s.w - 40));
    let h = Math.min(size[1], Math.max(220, s.h - 40));
    let x = Math.round((s.w - w) / 2 + (n % 6) * 26 - 60);
    let y = Math.round((s.h - h) / 2 + (n % 6) * 20 - 40);
    x = Math.max(8, Math.min(x, s.w - w - 8));
    y = Math.max(8, Math.min(y, s.h - h - 8));

    const win = {
      id: 'w' + (++WM.seq), appId: appId, app: app, title: app.name,
      args: args || {}, x: x, y: y, w: w, h: h, min: false, maxed: false, saved: null,
      el: null,
    };
    win.el = chrome(win);
    stage().appendChild(win.el);
    bindDrag(win);
    bindResize(win);
    win.el.addEventListener('pointerdown', () => WM.focus(win), true);
    win.el.querySelector('.wbtn.min').onclick = (e) => { e.stopPropagation(); WM.minimize(win); };
    win.el.querySelector('.wbtn.max').onclick = (e) => { e.stopPropagation(); WM.toggleMax(win); };
    win.el.querySelector('.wbtn.close').onclick = (e) => { e.stopPropagation(); WM.close(win); };

    win.setTitle = function (t) {
      win.title = t;
      const el = win.el.querySelector('.win-title');
      if (el) el.textContent = t;
      JZ.emit('windows:change');
    };
    win.close = () => WM.close(win);

    WM.wins.set(win.id, win);
    WM.focus(win);
    try {
      app.mount(win.el.querySelector('.win-body'), win, args || {});
    } catch (e) {
      console.error(e);
      win.el.querySelector('.win-body').innerHTML =
        '<div class="empty">' + JZ.icon('alert-triangle', 36) + '<div>应用启动失败：' + JZ.esc(e.message) + '</div></div>';
    }
    JZ.emit('windows:change');
    JZ.emit('window:open', win);
    return win;
  };

  WM.focus = function (win) {
    if (win.min) WM.restore(win);
    WM.wins.forEach(function (w) { w.el.classList.remove('active'); });
    win.el.classList.add('active');
    win.el.style.zIndex = ++WM.z;
    WM.active = win;
    JZ.emit('windows:change');
  };

  WM.minimize = function (win) {
    win.min = true;
    win.el.style.display = 'none';
    if (WM.active === win) WM.active = null;
    JZ.emit('windows:change');
  };

  WM.restore = function (win) {
    win.min = false;
    win.el.style.display = '';
    win.el.style.zIndex = ++WM.z;
    JZ.emit('windows:change');
  };

  WM.toggleMax = function (win, silent) {
    const s = stageRect();
    if (win.maxed) {
      win.maxed = false;
      win.el.classList.remove('maxed');
      if (win.saved) { win.x = win.saved.x; win.y = win.saved.y; win.w = win.saved.w; win.h = win.saved.h; }
    } else {
      win.saved = { x: win.x, y: win.y, w: win.w, h: win.h };
      win.maxed = true;
      win.el.classList.add('maxed');
      win.x = 0; win.y = 0; win.w = s.w; win.h = s.h;
    }
    apply(win);
    if (!silent) JZ.emit('windows:change');
  };

  WM.close = function (win) {
    win.el.classList.add('closing');
    if (win.onClose) try { win.onClose(); } catch (e) {}
    setTimeout(function () { win.el.remove(); }, 170);
    WM.wins.delete(win.id);
    if (WM.active === win) WM.active = null;
    JZ.emit('windows:change');
  };

  WM.byApp = function (appId) {
    return Array.from(WM.wins.values()).filter(w => w.appId === appId);
  };

  // 舞台尺寸变化：最大化窗口跟随
  let rt = null;
  window.addEventListener('resize', function () {
    clearTimeout(rt);
    rt = setTimeout(function () {
      const s = stageRect();
      WM.wins.forEach(function (w) {
        if (w.maxed) { w.w = s.w; w.h = s.h; apply(w); }
        else if (w.x > s.w - 100) { w.x = Math.max(0, s.w - w.w - 10); apply(w); }
      });
    }, 90);
  });

  // body 布局变化（AI 面板开关）：最大化跟随，普通窗口收进舞台内
  JZ.layoutChanged = function () {
    setTimeout(function () {
      const s = stageRect();
      WM.wins.forEach(function (w) {
        if (w.maxed) { w.w = s.w; w.h = s.h; w.x = 0; w.y = 0; }
        else {
          w.w = Math.min(w.w, Math.max(330, s.w - 16));
          w.h = Math.min(w.h, Math.max(200, s.h - 16));
          if (w.x + w.w > s.w - 8) w.x = Math.max(8, s.w - w.w - 8);
          if (w.y + w.h > s.h - 8) w.y = Math.max(8, s.h - w.h - 8);
          if (w.x < 0) w.x = 8;
        }
        apply(w);
      });
    }, 330);
  };
})();
