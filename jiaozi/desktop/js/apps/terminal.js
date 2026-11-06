/* 终端应用：基于 JZ.VT 的自绘屏幕，不依赖 xterm.js（离线可用、单文件可跑） */
(function () {
  'use strict';
  const JZ = window.JZ;
  const esc = JZ.esc;
  const VT = JZ.VT;

  JZ.registerApp({
    id: 'terminal', name: '终端', icon: 'terminal', color: '#1f2937',
    size: [860, 520], multi: true,
    mount: function (root, win, args) {
      root.innerHTML =
        '<div class="app" style="background:#0c1119">' +
          '<div class="term-tabbar"><span class="dot"></span><span class="tt-title">' + esc(JZ.t('本地终端')) + '</span>' +
            '<span class="sp"></span><span class="tt-size">—</span>' +
            '<button data-t="clear">' + esc(JZ.t('清屏')) + '</button><button data-t="restart">' + esc(JZ.t('重启')) + '</button>' +
          '</div>' +
          '<div class="term-wrap">' +
            '<div class="term-screen"><div class="term-content">' +
              '<div class="term-hist"></div><div class="term-live"></div>' +
              '<div class="term-cursor" style="display:none"></div>' +
            '</div></div>' +
            '<textarea class="term-input" autocapitalize="off" autocomplete="off" spellcheck="false"></textarea>' +
          '</div>' +
        '</div>';

      const wrap = root.querySelector('.term-wrap');
      const scroller = root.querySelector('.term-screen');
      const histEl = root.querySelector('.term-hist');
      const liveEl = root.querySelector('.term-live');
      const cursorEl = root.querySelector('.term-cursor');
      const inputEl = root.querySelector('.term-input');
      const sizeEl = root.querySelector('.tt-size');

      let sid = null, screen = null, parser = null;
      let cw = 7.8, lh = 17.2;
      let raf = 0, dirty = true, histCount = 0;
      let atBottom = true;

      function measure() {
        const probe = document.createElement('span');
        probe.style.cssText = 'position:absolute;visibility:hidden;white-space:pre;font-family:var(--mono);font-size:12.6px';
        probe.textContent = 'M'.repeat(40);
        scroller.appendChild(probe);
        cw = probe.getBoundingClientRect().width / 40;
        probe.textContent = 'M';
        lh = probe.getBoundingClientRect().height * 1.36;
        probe.remove();
        if (!cw || cw < 3) cw = 7.8;
        if (!lh || lh < 8) lh = 17.2;
      }

      function calcSize() {
        const rect = scroller.getBoundingClientRect();
        return {
          cols: Math.max(20, Math.floor((rect.width - 20) / cw)),
          rows: Math.max(6, Math.floor((rect.height - 14) / lh)),
        };
      }

      function pushHistory(row) {
        const html = VT.renderRow(row);
        const div = document.createElement('div');
        div.className = 'term-line';
        div.innerHTML = html || ' ';
        histEl.appendChild(div);
        histCount++;
        if (histCount > 600) {
          histCount--;
          if (histEl.firstChild) histEl.removeChild(histEl.firstChild);
        }
      }

      function paint() {
        if (!screen) return;
        if (dirty) {
          liveEl.innerHTML = screen.grid.map(function (row) {
            return '<div class="term-line">' + (VT.renderRow(row) || ' ') + '</div>';
          }).join('');
          cursorEl.style.left = (10 + screen.x * cw) + 'px';
          cursorEl.style.top = (histCount * lh + screen.y * lh + 7) + 'px';
          cursorEl.style.width = Math.max(4, cw - 1) + 'px';
          cursorEl.style.height = (lh - 2) + 'px';
          cursorEl.style.display = '';
          dirty = false;
        }
        if (atBottom) scroller.scrollTop = scroller.scrollHeight;
      }

      let timer = 0;
      function schedule() {
        dirty = true;
        if (!raf) raf = requestAnimationFrame(function () { raf = 0; paint(); });
        // 兜底：后台标签页 / 无合成的环境里 rAF 可能不触发
        clearTimeout(timer);
        timer = setTimeout(function () {
          if (!dirty) return;
          if (raf) { cancelAnimationFrame(raf); raf = 0; }
          paint();
        }, 150);
      }

      function createScreen(cols, rows) {
        const s = new VT.Screen(cols, rows);
        s.onScrollOut = pushHistory;
        return s;
      }

      function fit(force) {
        measure();
        const sz = calcSize();
        if (!screen) {
          screen = createScreen(sz.cols, sz.rows);
          parser = new VT.Parser(screen);
        } else if (force || sz.cols !== screen.cols || sz.rows !== screen.rows) {
          screen.resize(sz.cols, sz.rows);
        }
        sizeEl.textContent = sz.cols + '×' + sz.rows;
        if (sid) JZ.api.post('/api/term/resize', { id: sid, cols: sz.cols, rows: sz.rows }).catch(function () {});
        schedule();
      }

      // 与服务端缓冲对齐：首次打开时很可能错过了 shell 启动的前几行；
      // 断线重连后也需要补齐。缓冲是权威的，整体重建一次即可（幂等）。
      async function sync(tries, force) {
        if (!sid) return;
        let b;
        try {
          b = await JZ.api.get('/api/term/buffer', { id: sid });
        } catch (e) { return; }
        if (b.text) {
          if (!force) {
            const has = !screen.grid.every(row => row.every(function (c) { return c.c === ' '; }));
            if (has) return;   // 实时流已经填好了
          }
          histEl.innerHTML = '';
          histCount = 0;
          screen = createScreen(screen.cols, screen.rows);
          parser = new VT.Parser(screen);
          parser.feed(b.text);
          schedule();
          return;
        }
        if (tries > 0) setTimeout(function () { sync(tries - 1, force); }, 300);
      }

      /* 内部函数：启动会话 */
      async function start(shellSel) {
        try {
          measure();
          const sz = calcSize();
          histEl.innerHTML = '';
          liveEl.innerHTML = '';
          histCount = 0;
          screen = createScreen(sz.cols, sz.rows);
          parser = new VT.Parser(screen);
          const r = await JZ.api.post('/api/term/open', {
            cols: sz.cols, rows: sz.rows, shell: shellSel || undefined,
          });
          sid = r.id;
          outQueue = '';        // 新会话：丢掉旧会话残留的按键
          outBusy = false;
          screen.__tty = r.tty;
          sizeEl.textContent = sz.cols + '×' + sz.rows;
          win.setTitle(JZ.t('终端') + ' — ' + String(r.shell || '').split(/[\\/]/).pop());
          if (args.cwd) {
            setTimeout(function () {
              send('cd "' + String(args.cwd).replace(/"/g, '\\"') + '"' + (r.tty ? '\n' : '\r'));
            }, 260);
          }
          atBottom = true;
          scroller.scrollTop = scroller.scrollHeight;
          inputEl.focus();
        } catch (e) {
          histEl.innerHTML = '<div class="term-line"><span style="color:#ff6b6b">' + esc(JZ.t('启动终端失败：')) + '' +
            esc(e.message) + '</span></div>';
          histCount = 1;
        }
      }

      // 输入必须严格保序：浏览器会并行发起多个 fetch，落到不同 TCP 连接上
      // 时到达顺序无法保证（实测 echo 会变成 ecoh）。所以这里用「单通道队列」：
      // 同一时刻只允许一个请求在途，期间的按键全部合并进下一批一起发。
      let outQueue = '';
      let outBusy = false;

      function flushInput() {
        if (outBusy || !sid || !outQueue) return;
        const data = outQueue;
        const useId = sid;
        outQueue = '';
        outBusy = true;
        JZ.api.post('/api/term/input', { id: useId, data: data }).catch(function () {
          // 会话已关闭时后面还会有按键，忽略即可；真失败也不重放，避免重复输入
        }).then(function () {
          outBusy = false;
          flushInput();
        });
      }

      function send(data) {
        if (!sid || !data) return;
        outQueue += data;
        flushInput();
      }

      const offTerm = JZ.on('ev:term', function (ev) {
        if (!sid || (ev.id && ev.id !== sid)) return;
        parser.feed(ev.d || '');
        schedule();
      });
      const offClose = JZ.on('ev:term_close', function (ev) {
        if (sid && ev.id === sid) {
          histEl.insertAdjacentHTML('beforeend',
            '<div class="term-line"><span style="color:#6f8199">— ' + esc(JZ.t('会话已结束')) + ' —</span></div>');
          histCount++;
          sid = null;
          cursorEl.style.display = 'none';
        }
      });
      const offSse = JZ.on('ev:sse', function (d) {
        if (!d.online || !sid) return;
        setTimeout(function () { sync(2, true); }, 500);
      });
      win.onClose = function () {
        offTerm(); offClose(); offSse();
        if (sid) JZ.api.post('/api/term/close', { id: sid }).catch(function () {});
        sid = null;
      };

      // ---------------- 键盘 ----------------
      const KEYS = {
        Enter: '\r', Backspace: '\x7f', Tab: '\t', Escape: '\x1b',
        ArrowUp: '\x1b[A', ArrowDown: '\x1b[B', ArrowRight: '\x1b[C', ArrowLeft: '\x1b[D',
        Home: '\x1b[H', End: '\x1b[F', Delete: '\x1b[3~', Insert: '\x1b[2~',
        PageUp: '\x1b[5~', PageDown: '\x1b[6~',
      };
      const CTRL = { c: '\x03', d: '\x04', z: '\x1a', l: '\x0c', a: '\x01', e: '\x05',
        u: '\x15', w: '\x17', r: '\x12', k: '\x0b', p: '\x10', n: '\x0e' };

      inputEl.addEventListener('keydown', function (e) {
        const key = e.key;
        if (e.ctrlKey && !e.altKey && CTRL[key.toLowerCase()]) {
          e.preventDefault(); send(CTRL[key.toLowerCase()]); return;
        }
        if (e.ctrlKey && (key === 'v' || key === 'V')) return;
        if (e.ctrlKey || e.metaKey) return;
        if (KEYS[key]) { e.preventDefault(); send(KEYS[key]); return; }
        if (e.altKey && key.length === 1) { e.preventDefault(); send('\x1b' + key); return; }
        if (key.length === 1) { e.preventDefault(); send(key); }
      });
      inputEl.addEventListener('paste', function (e) {
        e.preventDefault();
        const t = (e.clipboardData || window.clipboardData).getData('text');
        if (t) { send(t); }
      });

      wrap.addEventListener('pointerdown', function () { inputEl.focus(); });
      scroller.addEventListener('scroll', function () {
        atBottom = scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 24;
      });
      wrap.addEventListener('wheel', function (e) {
        if (e.ctrlKey) { e.preventDefault(); scroller.scrollTop += e.deltaY; }
      }, { passive: false });

      root.querySelector('[data-t="clear"]').onclick = function () {
        histEl.innerHTML = ''; histCount = 0;
        if (screen) { screen.eraseScreen(2); screen.x = 0; screen.y = 0; }
        schedule();
      };
      root.querySelector('[data-t="restart"]').onclick = function () {
        if (sid) JZ.api.post('/api/term/close', { id: sid }).catch(function () {});
        sid = null;
        start();
      };

      let rto = null;
      const refit = function () { clearTimeout(rto); rto = setTimeout(function () { fit(true); }, 130); };
      window.addEventListener('resize', refit);
      if (window.ResizeObserver) new ResizeObserver(refit).observe(scroller);

      start(args.shell).then(function () { setTimeout(function () { sync(9); }, 260); });
      setTimeout(function () { fit(true); }, 160);
    },
  });
})();
