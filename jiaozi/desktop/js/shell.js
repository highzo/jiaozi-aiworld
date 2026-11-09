/* 桌面外壳：启动流程、图标、任务栏、开始菜单、通知 */
(function () {
  'use strict';
  const JZ = window.JZ;
  const esc = JZ.esc;

  const PINNED = ['files', 'terminal', 'editor', 'monitor', 'devices', 'settings'];
  const DESK_ICONS = [
    { app: 'files', label: '文件' },
    { app: 'terminal', label: '终端' },
    { app: 'editor', label: '编辑器' },
    { app: 'monitor', label: '监视器' },
    { app: 'devices', label: '设备' },
    { app: 'settings', label: '设置' },
    { app: '__ai', label: '饺子 AI' },
  ];
  const QUICK = [
    { icon: 'activity', text: '看看这台机器的状态' },
    { icon: 'file-text', text: '在桌面建一个 todo.md，写三条今天的计划' },
    { icon: 'folder-open', text: '列一下主目录里有什么，挑大的告诉我' },
    { icon: 'terminal', text: '用命令查一下磁盘剩余空间' },
  ];

  const notifications = [];
  let bootStep = 0;

  function bootTip(t) {
    const el = document.getElementById('bootTip');
    if (el && t) el.textContent = t;
  }

  /* ---------------- 启动 ---------------- */
  async function boot() {
    try {
      // 先把语言定下来，再让任何界面文字出现。init 只查本地配置和请求头，
      // 不碰网络（IP 定位在 refineByIP 里，首屏之后异步补），所以这里不会卡。
      await JZ.i18n.init();
      JZ.i18n.apply(document);
      bootTip(JZ.t('读取配置…'));
      const cfg = await JZ.api.get('/api/config');
      JZ.state.config = cfg;

      // 确认鉴权已通（cookie 已种）后再把 token 从地址栏抹掉：
      // 别留在浏览历史里，也让「添加到主屏幕」的 start_url 是干净的 "/"。
      // 反过来先抹会让 token 写错的人只看到一堆 401，无从下手。
      try {
        const u = new URL(location.href);
        if (u.searchParams.has('token')) {
          u.searchParams.delete('token');
          history.replaceState(null, '', u.pathname + (u.search || '') + u.hash);
        }
      } catch (e) {}

      bootTip(JZ.t('挂载桌面…'));
      const ds = await JZ.api.get('/api/desktop/state');
      JZ.state.home = ds.home;
      JZ.state.roots = ds.roots;
      JZ.state.host = ds.host;

      applyAppearance(ds.ui || cfg.ui || {});

      bootTip(JZ.t('连接内核…'));
      try { JZ.state.sys = await JZ.api.get('/api/sys/info'); } catch (e) {}

      renderIcons();
      renderTaskbar();
      renderStart();
      bindChrome();
      tickClock();
      setInterval(tickClock, 1000);
      renderTrayCpu();
      setInterval(renderTrayCpu, 4000);

      JZ.connect();
      bindServerEvents();
      if (JZ.initAgent) JZ.initAgent();
      // 语音按钮：服务端说没有识别后端就藏起来，不给一个按了没反应的按钮
      if (JZ.voice) JZ.voice.init();

      bootTip(JZ.t('就绪'));
      setTimeout(function () {
        document.body.classList.remove('booting');
        setTimeout(welcome, 900);
        openDeepLink();
        // 首屏之后再按 IP 判一次：浏览器语言不匹配时才需要，多语言的"最后一公里"
        JZ.i18n.refineByIP();
      }, 420);
    } catch (e) {
      bootTip(JZ.t('启动失败：') + e.message);
      console.error(e);
      JZ.toast(JZ.t('启动异常'), e.message, 'err', 8000);
      setTimeout(function () { document.body.classList.remove('booting'); }, 1200);
    }
  }

  function welcome() {
    if (!JZ.pref.get('welcomed', false)) {
      JZ.pref.set('welcomed', true);
      JZ.toast(JZ.t('饺子AIWorld 已就绪'), JZ.t('我是饺子，住在这台机器里。左边是我的对话窗，直接吩咐就行。'), 'ok', 7000);
      pushNotif(JZ.t('欢迎'), JZ.t('桌面和 AI 共用同一份文件。你改的、我改的，都是同一个。'));
    }
  }

  // 深链：/?app=files&path=/home/pi  或 /?app=terminal 可直接打开某个应用
  function openDeepLink() {
    const p = new URLSearchParams(location.search);
    const app = p.get('app');
    if (!app || !JZ.apps[app]) return;
    const args = {};
    const path = p.get('path');
    if (path) args[app === 'terminal' ? 'cwd' : 'path'] = path;
    setTimeout(function () {
      JZ.WM.open(app, args);
      JZ.layoutChanged();
    }, 420);
  }

  function applyAppearance(ui) {
    const theme = JZ.pref.get('theme', ui.theme || 'light');
    document.documentElement.dataset.theme = theme;
    const wp = JZ.pref.get('wallpaper', ui.wallpaper || 'aurora');
    document.getElementById('wallpaper').className = 'wp-' + wp;
    if (ui.accent) document.documentElement.style.setProperty('--accent', ui.accent);
  }

  /* ---------------- 桌面图标 ---------------- */
  function renderIcons() {
    const host = document.getElementById('icons');
    host.innerHTML = DESK_ICONS.map(function (d) {
      const app = d.app === '__ai' ? { icon: 'bot', color: '#5b8cff', name: '饺子 AI' } : JZ.apps[d.app];
      if (!app) return '';
      return '<div class="dicon" data-app="' + d.app + '">' +
        '<div class="glyph" style="background:linear-gradient(140deg,' + (app.color || '#4d8cf5') + ',' +
        shade(app.color || '#4d8cf5') + ')">' + JZ.icon(app.icon, 24) + '</div>' +
        '<div class="lbl">' + esc(JZ.t(d.label)) + '</div></div>';
    }).join('');
    host.querySelectorAll('.dicon').forEach(function (el) {
      el.onclick = function (e) {
        e.stopPropagation();
        host.querySelectorAll('.dicon').forEach(x => x.classList.remove('sel'));
        el.classList.add('sel');
      };
      el.ondblclick = function () { launch(el.dataset.app); };
      el.oncontextmenu = function (e) {
        e.preventDefault(); e.stopPropagation();
        host.querySelectorAll('.dicon').forEach(x => x.classList.remove('sel'));
        el.classList.add('sel');
        JZ.menu(e.clientX, e.clientY, [
          { label: JZ.t('打开'), icon: 'external-link', action: () => launch(el.dataset.app) },
          { label: JZ.t('应用信息'), icon: 'info', action: () => JZ.toast(JZ.t('应用'), el.dataset.app, 'info') },
        ]);
      };
    });
  }

  function shade(hex) {
    try {
      const n = parseInt(hex.slice(1), 16);
      const r = Math.min(255, ((n >> 16) & 255) + 40);
      const g = Math.min(255, ((n >> 8) & 255) + 30);
      const b = Math.min(255, (n & 255) + 60);
      return 'rgb(' + r + ',' + g + ',' + b + ')';
    } catch (e) { return hex; }
  }

  function launch(appId) {
    if (appId === '__ai') { JZ.agent && JZ.agent.toggle(true); return; }
    JZ.WM.open(appId);
  }

  /* ---------------- 任务栏 ---------------- */
  function renderTaskbar() {
    const host = document.getElementById('tbApps');
    const seen = new Set();
    const items = [];
    PINNED.forEach(function (id) { if (JZ.apps[id]) { items.push(id); seen.add(id); } });
    JZ.WM.wins.forEach(function (w) {
      if (!seen.has(w.appId)) { items.push(w.appId); seen.add(w.appId); }
    });

    host.innerHTML = items.map(function (id) {
      const app = JZ.apps[id];
      const wins = JZ.WM.byApp(id);
      const active = JZ.WM.active && JZ.WM.active.appId === id && !JZ.WM.active.min;
      return '<button class="tb-app' + (wins.length ? ' running' : '') + (active ? ' active' : '') +
        '" data-app="' + id + '" title="' + esc(JZ.t(app.name)) + '">' +
        '<span class="g" style="background:linear-gradient(140deg,' + (app.color || '#4d8cf5') + ',' + shade(app.color || '#4d8cf5') + ')">' +
        JZ.icon(app.icon, 15) + '</span></button>';
    }).join('');

    host.querySelectorAll('.tb-app').forEach(function (b) {
      b.onclick = function () {
        const id = b.dataset.app;
        const wins = JZ.WM.byApp(id);
        if (!wins.length) { JZ.WM.open(id); return; }
        const top = wins.sort((a, c) => (+a.el.style.zIndex || 0) - (+c.el.style.zIndex || 0)).pop();
        if (JZ.WM.active === top && !top.min) JZ.WM.minimize(top);
        else JZ.WM.focus(top);
      };
      b.oncontextmenu = function (e) {
        e.preventDefault();
        const wins = JZ.WM.byApp(b.dataset.app);
        const items = [{ label: JZ.t('新建窗口'), icon: 'plus', action: () => JZ.WM.open(b.dataset.app) }];
        if (wins.length) {
          items.push({ sep: true });
          items.push({ label: JZ.t('关闭全部窗口'), icon: 'x', danger: true, action: () => wins.forEach(w => JZ.WM.close(w)) });
        }
        JZ.menu(e.clientX, e.clientY, items);
      };
    });
  }
  JZ.on('windows:change', renderTaskbar);

  /* ---------------- 开始菜单 ---------------- */
  function renderStart() {
    const grid = document.getElementById('smApps');
    const list = Object.keys(JZ.apps).map(id => JZ.apps[id]);
    list.push({ id: '__ai', name: '饺子 AI', icon: 'bot', color: '#5b8cff' });
    grid.innerHTML = list.map(function (app) {
      return '<button class="sm-app" data-app="' + app.id + '">' +
        '<span class="g" style="background:linear-gradient(140deg,' + (app.color || '#4d8cf5') + ',' + shade(app.color || '#4d8cf5') + ')">' +
        JZ.icon(app.icon, 19) + '</span><span>' + esc(JZ.t(app.name)) + '</span></button>';
    }).join('');
    grid.querySelectorAll('.sm-app').forEach(function (b) {
      b.onclick = function () { closeStart(); launch(b.dataset.app); };
    });

    document.getElementById('smQuick').innerHTML = QUICK.map(function (q) {
      return '<button class="sm-q">' + JZ.icon(q.icon, 15) + '<span>' + esc(JZ.t(q.text)) + '</span></button>';
    }).join('');
    document.getElementById('smQuick').querySelectorAll('.sm-q').forEach(function (b) {
      b.onclick = function () {
        closeStart();
        JZ.ask(b.textContent.trim());
      };
    });

    document.getElementById('smHost').textContent = JZ.state.host || JZ.t('本机');
    document.getElementById('smAvatar').textContent = (JZ.state.host || 'J').slice(0, 1).toUpperCase();

    const search = document.getElementById('smSearch');
    search.oninput = function () {
      const q = search.value.trim().toLowerCase();
      grid.querySelectorAll('.sm-app').forEach(function (b) {
        const name = (JZ.apps[b.dataset.app] || { name: '饺子 AI' }).name.toLowerCase();
        const lname = JZ.t(name).toLowerCase();
        b.style.display = !q || name.indexOf(q) >= 0 || lname.indexOf(q) >= 0 ? '' : 'none';
      });
    };
    search.onkeydown = function (e) {
      if (e.key === 'Enter') {
        const q = search.value.trim();
        if (!q) return;
        closeStart();
        JZ.ask(q);
      }
      if (e.key === 'Escape') closeStart();
    };

    document.getElementById('smSettings').onclick = function () { closeStart(); JZ.WM.open('settings'); };
    document.getElementById('smPower').onclick = function () {
      closeStart();
      JZ.modal({
        title: JZ.t('关闭这个桌面窗口？'),
        body: JZ.t('只是关掉浏览器页面。服务端还在运行，重新打开地址即可回来。'),
        okText: JZ.t('关闭'),
      }).then(function (ok) { if (ok) window.close(); });
    };
  }

  function toggleStart() {
    const m = document.getElementById('startMenu');
    const on = m.classList.toggle('on');
    document.getElementById('startBtn').classList.toggle('on', on);
    if (on) {
      setTimeout(function () { document.getElementById('smSearch').focus(); }, 60);
    }
  }
  function closeStart() {
    document.getElementById('startMenu').classList.remove('on');
    document.getElementById('startBtn').classList.remove('on');
  }

  /* ---------------- 时钟 / 托盘 ---------------- */
  function tickClock() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    document.getElementById('clock').innerHTML =
      '<b>' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + '</b>' +
      '<small>' + (d.getMonth() + 1) + '/' + d.getDate() + '</small>';
  }
  async function renderTrayCpu() {
    if (JZ.state.sys) {
      try {
        const info = await JZ.api.get('/api/sys/info');
        JZ.state.sys = info;
        document.getElementById('trayCpu').textContent = info.cpu_percent.toFixed(0) + '%';
      } catch (e) {}
    }
  }

  /* ---------------- 通知 ---------------- */
  function pushNotif(title, body, level) {
    notifications.unshift({ title: title, body: body, level: level, ts: Date.now() });
    if (notifications.length > 40) notifications.pop();
    renderNotif();
  }
  function renderNotif() {
    const l = document.getElementById('npList');
    if (!notifications.length) {
      l.innerHTML = '<div class="np-empty">' + esc(JZ.t('还没有通知')) + '</div>';
      return;
    }
    l.innerHTML = notifications.map(function (n) {
      const d = new Date(n.ts);
      return '<div class="np-item"><b>' + esc(n.title) + '</b><span>' + esc(n.body || '') + '</span>' +
        '<small>' + d.toLocaleTimeString(JZ.i18n.locale, { hour: '2-digit', minute: '2-digit' }) + '</small></div>';
    }).join('');
  }

  /* ---------------- 服务端事件 ---------------- */
  function bindServerEvents() {
    JZ.on('ev:notify', function (ev) {
      const d = ev.d || {};
      JZ.toast(d.title || JZ.t('通知'), d.body, d.level || 'info', 5000);
      pushNotif(d.title || JZ.t('通知'), d.body, d.level);
    });
    JZ.on('ev:toast', function (ev) {
      const d = ev.d || {};
      JZ.toast(d.text || '', '', d.level || 'info', 2600);
    });
    JZ.on('ev:ui', function (ev) {
      const d = ev.d || {};
      if (d.action === 'open' && d.app) {
        const map = { terminal: 'cwd', files: 'path', editor: 'path', viewer: 'path' };
        const args = {};
        if (d.path && map[d.app]) args[map[d.app]] = d.path;
        JZ.WM.open(d.app, args);
      } else if (d.action === 'notify') {
        JZ.toast(d.title || 'AI', d.body, 'info', 5000);
      } else if (d.action === 'wallpaper' && d.value) {
        document.getElementById('wallpaper').className = 'wp-' + d.value;
        JZ.pref.set('wallpaper', d.value);
      }
    });
    JZ.on('ev:ai_shell', function (ev) {
      const d = ev.d || {};
      pushNotif(JZ.t('AI 执行命令'), '$ ' + (d.cmd || '').slice(0, 120) + '\n' + JZ.t('退出码') + ' ' + d.exit_code);
    });
    JZ.on('ev:config', function (ev) {
      JZ.api.get('/api/config').then(function (c) { JZ.state.config = c; if (JZ.onConfig) JZ.onConfig(c); }).catch(function () {});
    });
    JZ.on('ev:sse', function (d) {
      if (!d.online) {
        document.getElementById('aiStatus').textContent = JZ.t('连接断开');
      }
    });
    JZ.on('ev:fs_change', function () { /* 文件管理器自行订阅 */ });
  }

  /* ---------------- 交互绑定 ---------------- */
  function bindChrome() {
    document.getElementById('startBtn').onclick = function (e) { e.stopPropagation(); toggleStart(); };
    document.getElementById('trayBell').onclick = function (e) {
      e.stopPropagation();
      document.getElementById('notifPanel').classList.toggle('on');
    };
    document.getElementById('traySys').onclick = function () { JZ.WM.open('monitor'); };

    // 任务栏搜索
    const tbs = document.getElementById('tbSearchInput');
    tbs.onkeydown = function (e) {
      if (e.key === 'Enter') {
        const q = tbs.value.trim();
        if (!q) return;
        const hit = Object.keys(JZ.apps).find(function (id) {
          return JZ.apps[id].name.toLowerCase().indexOf(q.toLowerCase()) >= 0;
        });
        tbs.value = '';
        if (hit) JZ.WM.open(hit);
        else JZ.ask(q);
      }
    };

    // 桌面空白：取消选择 / 右键菜单 / 关闭菜单
    const desk = document.getElementById('desk');
    desk.addEventListener('pointerdown', function (e) {
      if (e.target.closest('.win') || e.target.closest('.dicon')) return;
      document.querySelectorAll('.dicon').forEach(x => x.classList.remove('sel'));
      closeStart();
      document.getElementById('notifPanel').classList.remove('on');
    });
    desk.addEventListener('contextmenu', function (e) {
      if (e.target.closest('.win') || e.target.closest('.dicon')) return;
      e.preventDefault();
      JZ.menu(e.clientX, e.clientY, [
        { label: JZ.t('新建文件夹'), icon: 'plus', action: newDesktopFolder },
        { label: JZ.t('打开终端'), icon: 'terminal', action: () => JZ.WM.open('terminal') },
        { label: JZ.t('刷新'), icon: 'refresh', action: () => window.location.reload() },
        { sep: true },
        { label: JZ.t('换一张壁纸'), icon: 'image', action: cycleWallpaper },
        { label: JZ.t('显示设置'), icon: 'settings', action: () => JZ.WM.open('settings') },
        { sep: true },
        { label: JZ.t('问饺子'), icon: 'sparkles', action: () => JZ.agent && JZ.agent.toggle(true) },
      ]);
    });

    // 快捷键
    document.addEventListener('keydown', function (e) {
      const meta = e.ctrlKey || e.metaKey;
      if (meta && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        toggleStart();
      }
      if (meta && e.shiftKey && e.key.toLowerCase() === 'a') {
        e.preventDefault();
        JZ.agent && JZ.agent.toggle();
      }
      if (e.key === 'Escape') {
        closeStart();
        JZ.closeMenu();
        document.getElementById('notifPanel').classList.remove('on');
      }
      if (meta && e.key.toLowerCase() === 'w' && JZ.WM.active) {
        e.preventDefault();
        JZ.WM.close(JZ.WM.active);
      }
    });

    window.addEventListener('beforeunload', function () {});
  }

  async function newDesktopFolder() {
    const home = JZ.state.home || '';
    const sep = home.indexOf('\\') >= 0 ? '\\' : '/';
    const name = await JZ.prompt(JZ.t('新建文件夹'), JZ.t('新建文件夹'), JZ.t('将创建在') + ' ' + home + sep + 'Desktop');
    if (!name) return;
    try {
      await JZ.api.post('/api/fs/mkdir', { path: home.replace(/[\\/]$/, '') + sep + 'Desktop' + sep + name });
      JZ.toast(JZ.t('已创建'), name, 'ok');
      const f = JZ.WM.open('files');
    } catch (e) {
      JZ.toast(JZ.t('创建失败'), e.message + JZ.t('（可能没有 Desktop 目录，试试在文件管理器里新建）'), 'err', 6000);
    }
  }

  function cycleWallpaper() {
    const all = ['aurora', 'dawn', 'ocean', 'forest', 'graphite'];
    const cur = document.getElementById('wallpaper').className.replace('wp-', '');
    const next = all[(all.indexOf(cur) + 1) % all.length];
    document.getElementById('wallpaper').className = 'wp-' + next;
    JZ.pref.set('wallpaper', next);
    JZ.toast(JZ.t('壁纸已切换'), next, 'ok', 1400);
  }

  document.addEventListener('DOMContentLoaded', boot);
})();
