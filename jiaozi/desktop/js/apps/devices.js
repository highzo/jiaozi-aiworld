/* 设备：局域网互认 —— 发现 / 配对 / 跨设备操作 */
(function () {
  'use strict';
  const JZ = window.JZ;
  const esc = JZ.esc;

  const PLAT = { windows: 'Windows', linux: 'Linux', android: '安卓', posix: 'Linux' };

  function platName(p) { return JZ.t(PLAT[p] || p || '未知'); }

  function ago(ts) {
    if (!ts) return '—';
    const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
    if (s < 12) return JZ.t('刚刚');
    if (s < 90) return JZ.t('{n} 秒前', { n: s });
    return JZ.t('{n} 分钟前', { n: Math.round(s / 60) });
  }

  JZ.registerApp({
    id: 'devices', name: '设备', icon: 'wifi', color: '#12886b',
    size: [760, 640], singleton: true,
    mount: function (root, win) {
      root.innerHTML =
        '<div class="app">' +
          '<div class="app-bar"><b style="font-size:12.5px">' + esc(JZ.t('局域网设备')) + '</b>' +
            '<div style="flex:1"></div>' +
            '<span class="tag" data-role="dot">' + esc(JZ.t('连接中…')) + '</span>' +
            '<button class="btn sm" data-act="refresh">' + JZ.icon('refresh', 13) + esc(JZ.t('刷新')) + '</button>' +
          '</div>' +
          '<div class="dev">' +
            '<div class="dev-me" data-role="me"></div>' +
            '<div class="dev-code" data-role="codepanel" hidden></div>' +
            '<div class="dev-add">' +
              '<input class="input" data-role="host" placeholder="' + esc(JZ.t('对方 IP，例如 192.168.1.20')) + '">' +
              '<input class="input dev-port" data-role="port" value="8787" inputmode="numeric">' +
              '<input class="input dev-code-in" data-role="code" placeholder="' + esc(JZ.t('6 位配对码')) + '" maxlength="6" inputmode="numeric">' +
              '<button class="btn sm primary" data-act="pair">' + esc(JZ.t('配对')) + '</button>' +
            '</div>' +
            '<div class="dev-hint" data-role="hint"></div>' +
            '<div class="dev-list" data-role="list"></div>' +
          '</div>' +
        '</div>';

      const $ = (s) => root.querySelector('[data-role="' + s + '"]');
      let state = null;
      let poll = 0;
      let codeTimer = 0;
      let left = 0;

      function hint(msg, kind) {
        const el = $('hint');
        el.textContent = msg || '';
        el.className = 'dev-hint' + (kind ? ' ' + kind : '');
      }

      function byId(id) {
        return (state && state.peers || []).filter(p => p.id === id)[0];
      }

      /* ---------------- 渲染 ---------------- */

      function renderMe() {
        const me = state.me || {};
        const ips = (me.ips || []).join(' · ') || JZ.t('未联网');
        const n = (state.peers || []).filter(p => p.online).length;
        $('me').innerHTML =
          '<div class="dm-ico">' + JZ.icon('wifi', 19) + '</div>' +
          '<div class="dm-main"><b>' + esc(me.name || JZ.t('本机')) + '</b>' +
            '<small>' + esc(ips) + ' : ' + esc(me.port) + '　' + esc(JZ.t('附近在线 {n} 台', { n: n })) + '</small></div>' +
          '<button class="btn sm primary" data-act="code">' + JZ.icon('lock', 13) + esc(JZ.t('生成配对码')) + '</button>';
      }

      function renderRow(p) {
        const on = !!p.online;
        const tag = p.paired
          ? '<span class="tag ok">' + esc(JZ.t('已配对')) + '</span>'
          : '<span class="tag">' + esc(JZ.t('未配对')) + '</span>';
        const caps = (p.caps || []).slice(0, 4)
          .map(c => '<i class="dev-cap">' + esc(c) + '</i>').join('');
        const addr = (p.ip || p.host || JZ.t('地址未知')) + (p.port ? ':' + p.port : '');
        let acts = '';
        if (p.paired && on) {
          acts += '<button class="btn sm" data-act="open" data-id="' + esc(p.id) + '">' +
            JZ.icon('external-link', 13) + esc(JZ.t('打开桌面')) + '</button>';
          acts += '<button class="btn sm" data-act="ask" data-id="' + esc(p.id) + '">' + esc(JZ.t('让饺子操作')) + '</button>';
        } else if (!p.paired && on) {
          acts += '<button class="btn sm primary" data-act="prefill" data-id="' + esc(p.id) + '">' + esc(JZ.t('配对')) + '</button>';
        }
        if (p.paired) {
          acts += '<button class="btn sm danger" data-act="forget" data-id="' + esc(p.id) + '">' + esc(JZ.t('忘记')) + '</button>';
        }
        return '<div class="dev-item' + (on ? '' : ' off') + '">' +
            '<span class="di-dot' + (on ? ' on' : '') + '"></span>' +
            '<div class="di-main"><b>' + esc(p.name) + ' ' + tag + '</b>' +
              '<small>' + esc(addr) + ' · ' + esc(platName(p.plat)) +
              (on ? ' · ' + ago(p.seen_at) : ' · ' + JZ.t('离线')) + '</small></div>' +
            '<div class="di-caps">' + caps + '</div>' +
            '<div class="di-acts">' + acts + '</div>' +
          '</div>';
      }

      function render() {
        if (!state) return;
        const me = state.me || {};
        $('dot').textContent = me.discovery ? JZ.t('发现已开启') : JZ.t('仅手动配对');
        $('dot').className = 'tag' + (me.discovery ? ' ok' : '');
        renderMe();

        const rows = state.peers || [];
        $('list').innerHTML = rows.length
          ? rows.map(renderRow).join('')
          : '<div class="empty"><b>' + esc(JZ.t('附近还没有设备')) + '</b>' +
            '<small>' + esc(JZ.t('在另一台机器上打开饺子；或者在上面填对方的 IP 和配对码。')) + '</small>' +
            '<small class="dev-dim">' + esc(JZ.t('公共 WiFi 常禁组播，发现不到不代表连不上。')) + '</small></div>';
      }

      /* ---------------- 动作 ---------------- */

      async function load() {
        try {
          state = await JZ.api.get('/api/peer/state');
          render();
        } catch (e) {
          hint(JZ.t('读取失败：') + e.message, 'err');
        }
      }

      async function makeCode() {
        try {
          const c = await JZ.api.post('/api/peer/code');
          const panel = $('codepanel');
          const me = state.me || {};
          const ip = (me.ips || [])[0] || JZ.t('本机 IP');
          left = c.ttl || 300;
          panel.hidden = false;
          const paint = function () {
            panel.innerHTML =
              '<div class="dc-num">' + esc(c.code) + '</div>' +
              '<div class="dc-tip">' + esc(JZ.t('在另一台设备的「设备」里填：')) + '<b>' + esc(ip) + '</b> ' +
              esc(JZ.t('端口')) + ' <b>' + esc(me.port) + '</b>' + esc(JZ.t('，再输入上面这个码')) +
              '<br>' + esc(JZ.t('剩余 {n} 秒', { n: left })) +
              '<button class="btn sm" data-act="closecode" style="margin-left:10px">' + esc(JZ.t('收起')) + '</button></div>';
          };
          paint();
          clearInterval(codeTimer);
          codeTimer = setInterval(function () {
            left -= 1;
            if (left <= 0) {
              clearInterval(codeTimer);
              panel.hidden = true;
              return;
            }
            paint();
          }, 1000);
        } catch (e) {
          hint(JZ.t('生成失败：') + e.message, 'err');
        }
      }

      async function doPair() {
        const host = $('host').value.trim();
        const port = parseInt($('port').value, 10) || 8787;
        const code = $('code').value.trim();
        if (!host) return hint(JZ.t('先填对方的 IP 地址'), 'err');
        if (!/^\d{6}$/.test(code)) return hint(JZ.t('配对码是 6 位数字'), 'err');
        hint(JZ.t('正在配对…'));
        try {
          const d = await JZ.api.post('/api/peer/pair', { host: host, port: port, code: code });
          hint(JZ.t('已和「{name}」配对成功', { name: d.name || host }), 'ok');
          $('code').value = '';
          await load();
        } catch (e) {
          hint(e.message, 'err');
        }
      }

      async function forget(id) {
        const p = byId(id) || {};
        if (!window.confirm(JZ.t('断开与「{name}」的配对？之后要重新输入配对码。', { name: p.name || id }))) return;
        try {
          await JZ.api.post('/api/peer/forget', { id: id });
          hint(JZ.t('已断开'), '');
          await load();
        } catch (e) {
          hint(e.message, 'err');
        }
      }

      function openDesk(id) {
        const p = byId(id);
        if (!p) return;
        const host = p.ip || p.host;
        if (!host) return hint(JZ.t('不知道对方地址，等它在线再试'), 'err');
        const url = 'http://' + host + ':' + p.port + '/?token=' + encodeURIComponent(p.token || '');
        const w = window.open(url, '_blank');
        if (!w) hint(JZ.t('浏览器拦了弹窗，请允许后重试'), 'err');
      }

      function askJiaozi(id) {
        const p = byId(id);
        if (!p) return;
        if (JZ.agent && JZ.agent.toggle) JZ.agent.toggle(true);
        const ta = document.getElementById('aiInput');
        if (ta) {
          ta.value = JZ.t('在「{name}」那台设备上', { name: p.name });
          ta.focus();
          ta.setSelectionRange(ta.value.length, ta.value.length);
        }
        hint(JZ.t('已把句子填进 AI 输入框，补完回车即可'), 'ok');
      }

      root.addEventListener('click', function (ev) {
        const b = ev.target.closest('[data-act]');
        if (!b) return;
        const act = b.dataset.act;
        const id = b.dataset.id || '';
        if (act === 'refresh') load();
        else if (act === 'code') makeCode();
        else if (act === 'closecode') {
          clearInterval(codeTimer);
          $('codepanel').hidden = true;
        } else if (act === 'pair') doPair();
        else if (act === 'forget') forget(id);
        else if (act === 'open') openDesk(id);
        else if (act === 'ask') askJiaozi(id);
        else if (act === 'prefill') {
          const p = byId(id);
          if (!p) return;
          $('host').value = p.ip || p.host || '';
          $('port').value = p.port || 8787;
          $('code').value = '';
          $('code').focus();
          hint(JZ.t('在「{name}」上点「生成配对码」，把 6 位数字填进来', { name: p.name }), '');
        }
      });

      load();
      poll = setInterval(load, 3000);
      win.onClose = function () {
        clearInterval(poll);
        clearInterval(codeTimer);
      };
    },
  });
})();
