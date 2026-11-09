/* 家电：ESP32 开关 / 插座 / 灯 —— 电脑和手机上都点得到同一批开关 */
(function () {
  'use strict';
  const JZ = window.JZ;
  const esc = JZ.esc;

  function ago(ts) {
    if (!ts) return '—';
    const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
    if (s < 15) return JZ.t('刚刚');
    if (s < 90) return JZ.t('{n} 秒前', { n: s });
    if (s < 5400) return JZ.t('{n} 分钟前', { n: Math.round(s / 60) });
    return JZ.t('{n} 小时前', { n: Math.round(s / 3600) });
  }

  // 传感器名的翻译表。值写成函数是为了让 JZ.t 的字面量出现在源码里——
  // 翻译检查器只能看见 t('…') 这种写法，写成 {temp:'温度'} 就会被判成孤儿。
  // 认不出来的键原样显示，设备以后加了别的东西（土壤湿度、光照）也不会空白。
  const SENSORS = {
    temp: function () { return JZ.t('温度'); },
    temperature: function () { return JZ.t('温度'); },
    humi: function () { return JZ.t('湿度'); },
    humidity: function () { return JZ.t('湿度'); },
    light: function () { return JZ.t('光照'); },
    lux: function () { return JZ.t('光照'); },
    pressure: function () { return JZ.t('气压'); },
    co2: function () { return JZ.t('二氧化碳'); },
  };

  function sensorText(st) {
    const sen = (st && st.sensors) || {};
    const out = [];
    Object.keys(sen).forEach(function (k) {
      const v = sen[k];
      if (typeof v !== 'number') return;
      const label = SENSORS[k] ? SENSORS[k]() : k;
      const unit = /temp|温度/i.test(k) ? ' °C'
        : /humi|湿/i.test(k) ? ' %'
        : /lux|光照|light/i.test(k) ? ' lx' : '';
      out.push(label + ' ' + v + unit);
    });
    return out.join(' · ');
  }

  JZ.registerApp({
    id: 'home', name: '家电', icon: 'zap', color: '#d97706',
    size: [840, 660], singleton: true,
    mount: function (root, win) {
      root.innerHTML =
        '<div class="app">' +
          '<div class="app-bar">' +
            '<b style="font-size:12.5px">' + esc(JZ.t('家电')) + '</b>' +
            '<div style="flex:1"></div>' +
            '<span class="tag" data-role="dot">' + esc(JZ.t('连接中…')) + '</span>' +
            '<button class="btn sm" data-act="scan">' + JZ.icon('search', 13) + esc(JZ.t('搜索设备')) + '</button>' +
            '<button class="btn sm" data-act="add-toggle">' + JZ.icon('plus', 13) + esc(JZ.t('手动添加')) + '</button>' +
          '</div>' +
          '<div class="hm">' +
            '<div class="hm-add" data-role="add" hidden>' +
              '<input class="input hm-ip" data-role="host" placeholder="' + esc(JZ.t('设备 IP，例如 192.168.1.66')) + '">' +
              '<input class="input hm-port" data-role="port" value="80" inputmode="numeric">' +
              '<input class="input hm-key" data-role="key" placeholder="' + esc(JZ.t('密钥（没设就留空）')) + '">' +
              '<button class="btn sm primary" data-act="add">' + esc(JZ.t('添加')) + '</button>' +
            '</div>' +
            '<div class="hm-hint" data-role="hint"></div>' +
            '<div class="hm-list" data-role="list"></div>' +
          '</div>' +
        '</div>';

      const $ = (s) => root.querySelector('[data-role="' + s + '"]');
      let devices = [];
      let states = {};
      let busy = {};
      let timer = 0;
      let tick = 0;

      function hint(msg, kind) {
        const el = $('hint');
        el.textContent = msg || '';
        el.className = 'hm-hint' + (kind ? ' ' + kind : '');
      }

      /* ---------------- 渲染 ---------------- */

      function renderChan(d, c) {
        const st = (states[d.id] || {}).channels || {};
        const cur = st[c.id] || {};
        const on = !!cur.on;
        const name = cur.name || c.name || c.id;
        const key = d.id + '/' + c.id;
        const pending = busy[key];
        // 三目里直接嵌 JZ.t(...) 会让翻译检查器抓不到字面量，所以分开写
        const tip = on ? JZ.t('点一下关掉') : JZ.t('点一下打开');
        const label = on ? JZ.t('开') : JZ.t('关');
        return '<div class="hm-ch">' +
            '<div class="hm-ch-main"><b>' + esc(JZ.t(name)) + '</b>' +
              '<small>' + esc(c.id) + (c.type && c.type !== 'relay' ? ' · ' + esc(c.type) : '') + '</small></div>' +
            '<button class="hm-sw' + (on ? ' on' : '') + (pending ? ' wait' : '') + '"' +
              ' data-act="toggle" data-id="' + esc(d.id) + '" data-ch="' + esc(c.id) + '"' +
              ' aria-pressed="' + (on ? 'true' : 'false') + '"' +
              ' title="' + esc(tip) + '">' +
              '<i></i><span>' + esc(label) + '</span></button>' +
          '</div>';
      }

      function renderCard(d) {
        const st = states[d.id] || {};
        const chans = d.channels || [];
        const online = !!d.online;
        const sen = sensorText(st);
        return '<div class="hm-card' + (online ? '' : ' off') + '" data-id="' + esc(d.id) + '">' +
            '<div class="hm-head">' +
              '<span class="hm-ico">' + JZ.icon('zap', 17) + '</span>' +
              '<div class="hm-title"><b>' + esc(JZ.t(d.name)) + '</b>' +
                '<small>' + esc(d.host) + ':' + esc(d.port) +
                  ' · ' + (online ? esc(JZ.t('在线')) + ' · ' + esc(ago(d.last_seen))
                                  : esc(JZ.t('离线'))) + '</small></div>' +
              '<button class="btn sm ghost" data-act="more" data-id="' + esc(d.id) + '"' +
                ' title="' + esc(JZ.t('更多')) + '">' + JZ.icon('sliders', 13) + '</button>' +
            '</div>' +
            '<div class="hm-chs">' +
              (chans.length ? chans.map(function (c) { return renderChan(d, c); }).join('')
                            : '<div class="hm-none">' + esc(JZ.t('这台设备没有开关通道')) + '</div>') +
            '</div>' +
            '<div class="hm-foot">' +
              '<span>' + esc(sen || JZ.t('无传感器')) + '</span>' +
              (typeof st.rssi === 'number'
                ? '<span>' + esc(JZ.t('信号 {dbm} dBm', { dbm: st.rssi })) + '</span>' : '') +
              (st.uptime ? '<span>' + esc(JZ.t('已运行 {t}', { t: JZ.fmt.dur(st.uptime) })) + '</span>' : '') +
            '</div>' +
          '</div>';
      }

      function render() {
        const on = devices.filter(function (d) { return d.online; }).length;
        $('dot').textContent = devices.length
          ? JZ.t('{on}/{n} 台在线', { on: on, n: devices.length })
          : JZ.t('还没有设备');
        $('dot').className = 'tag' + (on ? ' ok' : '');

        $('list').innerHTML = devices.length
          ? devices.map(renderCard).join('')
          : '<div class="empty"><b>' + esc(JZ.t('还没有接入家电')) + '</b>' +
            '<small>' + esc(JZ.t('ESP32 通电并连上同一个 WiFi，就会自动出现在这里。')) + '</small>' +
            '<small class="hm-dim">' + esc(JZ.t('搜不到就点「手动添加」，填设备的 IP。')) + '</small></div>';
      }

      /* ---------------- 数据 ---------------- */

      async function loadDevices(ping) {
        try {
          const r = await JZ.api.get('/api/esp/devices' + (ping ? '' : '?ping=0'));
          const day = r.data || r;
          devices = day.devices || [];
          render();
          return true;
        } catch (e) {
          hint(JZ.t('读取设备失败：{msg}', { msg: e.message || e }), 'err');
          return false;
        }
      }

      async function loadStates() {
        const ons = devices.filter(function (d) { return d.online; });
        for (let i = 0; i < ons.length; i++) {
          const d = ons[i];
          try {
            const r = await JZ.api.get('/api/esp/state?id=' + encodeURIComponent(d.id));
            states[d.id] = r.data || r;
          } catch (e) {
            states[d.id] = states[d.id] || {};
          }
        }
        render();
      }

      async function refresh(ping) {
        await loadDevices(ping !== false);
        await loadStates();
      }

      async function toggle(id, ch) {
        const key = id + '/' + ch;
        if (busy[key]) return;
        const cur = ((states[id] || {}).channels || {})[ch] || {};
        const next = !cur.on;
        busy[key] = true;
        // 先乐观改，让人立刻看到反应；失败再翻回来
        states[id] = states[id] || {};
        states[id].channels = states[id].channels || {};
        states[id].channels[ch] = Object.assign({}, cur, { on: next });
        render();
        try {
          const r = await JZ.api.post('/api/esp/control', { id: id, channel: ch, on: next });
          const data = r.data || r;
          if (data && data.channels) {
            Object.keys(data.channels).forEach(function (k) {
              states[id].channels[k] = Object.assign({}, states[id].channels[k] || {},
                                                     { on: !!data.channels[k] });
            });
          }
          hint('');
        } catch (e) {
          states[id].channels[ch] = Object.assign({}, cur, { on: !next });
          hint(JZ.t('操作失败：{msg}', { msg: e.message || e }), 'err');
        } finally {
          delete busy[key];
          render();
        }
      }

      /* ---------------- 动作 ---------------- */

      root.addEventListener('click', async function (ev) {
        const b = ev.target.closest('[data-act]');
        if (!b) return;
        const act = b.dataset.act;
        if (act === 'toggle') {
          toggle(b.dataset.id, b.dataset.ch);
        } else if (act === 'scan') {
          b.disabled = true;
          hint(JZ.t('正在搜索…'));
          try {
            const r = await JZ.api.post('/api/esp/scan', {});
            const d = r.data || r;
            hint(d.new ? JZ.t('新发现 {n} 台', { n: d.new }) : JZ.t('搜索完成，没有新设备'),
                 d.new ? 'ok' : '');
          } catch (e) {
            hint(JZ.t('搜索失败：{msg}', { msg: e.message || e }), 'err');
          }
          b.disabled = false;
          refresh();
        } else if (act === 'add-toggle') {
          $('add').hidden = !$('add').hidden;
          if (!$('add').hidden) $('host').focus();
        } else if (act === 'add') {
          const host = $('host').value.trim();
          if (!host) { hint(JZ.t('先填设备 IP'), 'err'); return; }
          try {
            await JZ.api.post('/api/esp/add', {
              host: host, port: Number($('port').value) || 80, key: $('key').value.trim(),
            });
            $('host').value = ''; $('key').value = '';
            hint(JZ.t('已添加'), 'ok');
            refresh();
          } catch (e) {
            hint(JZ.t('添加失败：{msg}', { msg: e.message || e }), 'err');
          }
        } else if (act === 'more') {
          openMore(b.dataset.id, b);
        }
      });

      root.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter' && ev.target.dataset.role === 'host') {
          const btn = root.querySelector('[data-act="add"]');
          if (btn) btn.click();
        }
      });

      function openMore(id, anchor) {
        const d = devices.filter(function (x) { return x.id === id; })[0];
        if (!d) return;
        const r = anchor.getBoundingClientRect();
        JZ.menu(r.left - 120, r.bottom + 4, [
          { label: JZ.t('改名'), icon: 'edit', action: async function () {
              const name = await JZ.prompt(JZ.t('给这台设备起个名字'), d.name);
              if (!name) return;
              try {
                await JZ.api.post('/api/esp/rename', { id: id, name: name });
                refresh();
              } catch (e) { hint(String(e.message || e), 'err'); }
            } },
          { label: JZ.t('复制地址'), icon: 'copy', action: function () {
              try {
                navigator.clipboard.writeText(d.host + ':' + d.port);
              } catch (e) { /* 非 https 下没有剪贴板，忽略 */ }
              hint(JZ.t('地址已复制') + ' ' + d.host + ':' + d.port, 'ok');
            } },
          { label: JZ.t('忘记这台'), icon: 'trash', danger: true, action: async function () {
              try {
                await JZ.api.post('/api/esp/forget', { id: id });
                delete states[id];
                refresh();
              } catch (e) { hint(String(e.message || e), 'err'); }
            } },
        ]);
      }

      /* ---------------- 定时 ---------------- */
      refresh().then(function () {
        timer = setInterval(async function () {
          if (win && win.min) return;  // 最小化时不打设备，省电省心
          tick++;
          // 每 3 轮才 ping 一次（判断在线要打设备，别太勤）
          await loadDevices(tick % 3 === 0);
          await loadStates();
        }, 4000);
      });

      win.onClose = function () { clearInterval(timer); };
    },
  });
})();
