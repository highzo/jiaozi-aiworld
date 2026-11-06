/* 系统监视器 */
(function () {
  'use strict';
  const JZ = window.JZ;
  const esc = JZ.esc;

  function spark(canvas, data, color) {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth || 240, h = canvas.clientHeight || 58;
    canvas.width = w * dpr; canvas.height = h * dpr;
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    if (!data.length) return;
    const max = Math.max(60, Math.max.apply(null, data));
    const step = w / Math.max(1, data.length - 1);
    ctx.beginPath();
    data.forEach(function (v, i) {
      const x = i * step, y = h - (v / max) * (h - 4) - 2;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    const lg = ctx.createLinearGradient(0, 0, w, 0);
    lg.addColorStop(0, color); lg.addColorStop(1, '#a78bfa');
    ctx.strokeStyle = lg; ctx.lineWidth = 1.8; ctx.lineJoin = 'round'; ctx.stroke();
    ctx.lineTo(w, h); ctx.lineTo(0, h); ctx.closePath();
    const fill = ctx.createLinearGradient(0, 0, 0, h);
    fill.addColorStop(0, color + '33'); fill.addColorStop(1, color + '00');
    ctx.fillStyle = fill; ctx.fill();
  }

  JZ.registerApp({
    id: 'monitor', name: '监视器', icon: 'activity', color: '#14a06a',
    size: [780, 600], singleton: true,
    mount: function (root, win) {
      root.innerHTML =
        '<div class="app">' +
          '<div class="app-bar"><b style="font-size:12.5px">' + esc(JZ.t('实时状态')) + '</b>' +
            '<div style="flex:1"></div>' +
            '<span class="tag" data-role="os">—</span>' +
            '<button class="btn sm" data-role="refresh">' + JZ.icon('refresh', 13) + esc(JZ.t('刷新')) + '</button>' +
          '</div>' +
          '<div class="mon">' +
            '<div class="mon-cards">' +
              '<div class="mon-card"><div class="mc-top"><span class="mc-label">CPU</span>' +
                '<span class="mc-val" data-role="cpu">–</span></div>' +
                '<div class="mc-sub" data-role="cpuc">—</div>' +
                '<canvas class="mon-spark" data-role="cpuSpark"></canvas></div>' +
              '<div class="mon-card"><div class="mc-top"><span class="mc-label">' + esc(JZ.t('内存')) + '</span>' +
                '<span class="mc-val" data-role="mem">–</span></div>' +
                '<div class="mc-sub" data-role="memc">—</div>' +
                '<div class="mon-bar" data-role="membar"><i style="width:0"></i></div></div>' +
              '<div class="mon-card"><div class="mc-top"><span class="mc-label">' + esc(JZ.t('磁盘')) + '</span>' +
                '<span class="mc-val" data-role="disk">–</span></div>' +
                '<div class="mc-sub" data-role="diskc">—</div>' +
                '<div class="mon-bar" data-role="diskbar"><i style="width:0"></i></div></div>' +
              '<div class="mon-card"><div class="mc-top"><span class="mc-label">' + esc(JZ.t('运行时间')) + '</span>' +
                '<span class="mc-val" data-role="up" style="font-size:17px">–</span></div>' +
                '<div class="mc-sub" data-role="root">—</div></div>' +
            '</div>' +
            '<div class="mon-sec-title">' + esc(JZ.t('占用内存最高的进程')) + '</div>' +
            '<table class="mon-table"><thead><tr><th style="width:74px">PID</th><th>' + esc(JZ.t('进程')) + '</th>' +
              '<th style="width:88px">' + esc(JZ.t('内存')) + '</th><th style="width:70px">' + esc(JZ.t('占比')) + '</th><th style="width:64px"></th></tr></thead>' +
            '<tbody data-role="procs"><tr><td colspan="5" style="color:var(--text-3);padding:14px">' + esc(JZ.t('读取中…')) + '</td></tr></tbody></table>' +
          '</div>' +
        '</div>';

      const q = (r) => root.querySelector('[data-role="' + r + '"]');
      const cpuData = [];
      let timer = null, procs = [];

      async function tick() {
        try {
          const info = await JZ.api.get('/api/sys/info');
          JZ.state.sys = info;
          const cpu = info.cpu_percent;
          cpuData.push(cpu);
          if (cpuData.length > 60) cpuData.shift();
          q('cpu').textContent = cpu.toFixed(0) + '%';
          q('cpuc').textContent = info.cpu_count + ' ' + JZ.t('核') + ' · ' + JZ.t('负载') + ' ' + info.load.map(function (v) { return v.toFixed(2); }).join(' / ');
          spark(q('cpuSpark'), cpuData, '#4d8cf5');

          const m = info.memory;
          q('mem').textContent = m.percent.toFixed(0) + '%';
          q('memc').textContent = JZ.fmt.bytes(m.used) + ' / ' + JZ.fmt.bytes(m.total);
          const mb = q('membar');
          mb.firstElementChild.style.width = Math.min(100, m.percent) + '%';
          mb.classList.toggle('warn', m.percent > 85);

          q('disk').textContent = info.disk.percent.toFixed(0) + '%';
          q('diskc').textContent = JZ.t('可用') + ' ' + JZ.fmt.bytes(info.disk.free);
          const db = q('diskbar');
          db.firstElementChild.style.width = Math.min(100, info.disk.percent) + '%';
          db.classList.toggle('warn', info.disk.percent > 90);

          q('up').textContent = JZ.fmt.dur(info.uptime);
          q('root').textContent = info.root;
          q('os').textContent = info.os + ' · ' + info.machine;
        } catch (e) { /* ignore */ }
        try {
          procs = await JZ.api.get('/api/sys/proc', { limit: 22 });
          renderProcs();
        } catch (e) {}
      }

      function renderProcs() {
        const tb = q('procs');
        if (!procs.length) {
          tb.innerHTML = '<tr><td colspan="5" style="color:var(--text-3);padding:14px">' + esc(JZ.t('无数据')) + '</td></tr>';
          return;
        }
        tb.innerHTML = procs.map(function (p) {
          return '<tr><td>' + p.pid + '</td>' +
            '<td class="pname" title="' + esc(p.name) + '">' + esc(p.name) + '</td>' +
            '<td>' + JZ.fmt.bytes(p.rss) + '</td>' +
            '<td>' + (p.mem_percent || 0).toFixed(1) + '%</td>' +
            '<td><button class="mon-kill" data-pid="' + p.pid + '">' + esc(JZ.t('结束')) + '</button></td></tr>';
        }).join('');
        tb.querySelectorAll('.mon-kill').forEach(function (b) {
          b.onclick = async function () {
            const pid = b.dataset.pid;
            const ok = await JZ.confirm(JZ.t('结束进程 {pid}？', { pid: pid }), JZ.t('强制结束可能丢失未保存的数据。'), true);
            if (!ok) return;
            try {
              await JZ.api.post('/api/sys/kill', { pid: pid, force: true });
              JZ.toast(JZ.t('已结束进程'), pid, 'ok');
              tick();
            } catch (e) { JZ.toast(JZ.t('操作失败'), e.message, 'err'); }
          };
        });
      }

      q('refresh').onclick = tick;
      tick();
      timer = setInterval(tick, 2000);
      win.onClose = function () { clearInterval(timer); };
    },
  });
})();
