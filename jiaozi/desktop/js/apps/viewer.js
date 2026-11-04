/* 图片查看器：支持单张图片，也支持直接打开一个目录当相册看 */
(function () {
  'use strict';
  const JZ = window.JZ;
  const esc = JZ.esc;

  const IMG_EXT = /\.(png|jpe?g|gif|webp|bmp|svg|avif)$/i;

  JZ.registerApp({
    id: 'viewer', name: '图片', icon: 'image', color: '#22a06b',
    size: [760, 560], multi: true,
    mount: function (root, win, args) {
      const startPath = args.path || '';
      let list = [];        // 要展示的图片路径
      let idx = 0;
      let zoom = 1;

      root.innerHTML =
        '<div class="app">' +
          '<div class="app-bar"><span class="vw-name" style="font-size:12.5px;color:var(--text-2);max-width:42%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></span>' +
            '<div style="flex:1"></div>' +
            '<button class="btn sm" data-z="prev" title="上一张">‹</button>' +
            '<button class="btn sm" data-z="next" title="下一张">›</button>' +
            '<button class="btn sm" data-z="out">缩小</button>' +
            '<button class="btn sm" data-z="fit">适应</button>' +
            '<button class="btn sm" data-z="in">放大</button>' +
            '<button class="btn sm" data-z="open">外部打开</button>' +
          '</div>' +
          '<div class="viewer"><img alt=""></div>' +
          '<div class="vw-strip" hidden></div>' +
          '<div class="app-status"><span data-role="sz"></span></div>' +
        '</div>';

      const img = root.querySelector('img');
      const strip = root.querySelector('.vw-strip');
      const viewer = root.querySelector('.viewer');
      const nameEl = root.querySelector('.vw-name');

      function applyZoom() {
        img.style.maxWidth = zoom === 1 ? '100%' : 'none';
        img.style.maxHeight = zoom === 1 ? '100%' : 'none';
        img.style.transform = 'scale(' + zoom + ')';
      }

      function show(i) {
        if (!list.length) return;
        idx = (i + list.length) % list.length;
        const p = list[idx];
        const name = p.split(/[\\/]/).pop() || '图片';
        zoom = 1;
        applyZoom();
        img.src = JZ.api.raw('/api/fs/raw', { path: p });
        nameEl.textContent = name;
        win.setTitle(name + ' — 图片');
        root.querySelectorAll('.vw-thumb').forEach(function (b, k) {
          b.classList.toggle('on', k === idx);
        });
        const cur = strip.querySelector('.vw-thumb.on');
        if (cur && cur.scrollIntoView) {
          try { cur.scrollIntoView({ block: 'nearest', inline: 'nearest' }); } catch (e) {}
        }
      }

      img.onload = function () {
        const box = root.querySelector('[data-role="sz"]');
        const dim = img.naturalWidth + ' × ' + img.naturalHeight + ' px';
        box.textContent = list.length > 1
          ? (idx + 1) + ' / ' + list.length + '   ' + dim
          : dim;
      };
      img.onerror = function () {
        viewer.innerHTML = '<div class="empty">' + JZ.icon('alert-triangle', 36) +
          '<div>无法显示这张图片</div></div>';
      };

      root.querySelector('[data-z="in"]').onclick = function () { zoom = Math.min(6, zoom * 1.25); applyZoom(); };
      root.querySelector('[data-z="out"]').onclick = function () { zoom = Math.max(0.1, zoom / 1.25); applyZoom(); };
      root.querySelector('[data-z="fit"]').onclick = function () { zoom = 1; applyZoom(); };
      root.querySelector('[data-z="prev"]').onclick = function () { show(idx - 1); };
      root.querySelector('[data-z="next"]').onclick = function () { show(idx + 1); };
      root.querySelector('[data-z="open"]').onclick = function () {
        window.open(JZ.api.raw('/api/fs/raw', { path: list[idx] || startPath }), '_blank');
      };

      // 键盘：只在「这个窗口是当前活动窗口」时才响应左右翻页（窗口关掉就自摘监听）
      function onKey(e) {
        if (!JZ.WM.wins.has(win.id)) { document.removeEventListener('keydown', onKey); return; }
        if (JZ.WM.active !== win) return;
        if (e.target && /INPUT|TEXTAREA/.test(e.target.tagName)) return;
        if (e.key === 'ArrowLeft') { show(idx - 1); e.preventDefault(); }
        if (e.key === 'ArrowRight') { show(idx + 1); e.preventDefault(); }
      }
      document.addEventListener('keydown', onKey);

      function renderStrip() {
        if (list.length < 2) { strip.hidden = true; return; }
        strip.hidden = false;
        strip.innerHTML = list.map(function (p, i) {
          return '<button class="vw-thumb" data-i="' + i + '">' +
            '<img src="' + esc(JZ.api.raw('/api/fs/raw', { path: p })) + '" alt="">' +
            '</button>';
        }).join('');
        strip.querySelectorAll('.vw-thumb').forEach(function (b) {
          b.onclick = function () { show(parseInt(b.dataset.i, 10) || 0); };
        });
      }

      /* 起步：先判断给的是文件还是目录。
         AI 常常把「存图的文件夹」直接甩过来，这时当相册看才是对的。 */
      (async function () {
        try {
          const st = await JZ.api.get('/api/fs/stat', { path: startPath });
          if (st && st.is_dir) {
            const d = await JZ.api.get('/api/fs/list', { path: st.path });
            list = (d.items || [])
              .filter(function (it) { return !it.is_dir && IMG_EXT.test(it.name); })
              .sort(function (a, b) { return (b.mtime || 0) - (a.mtime || 0); })
              .map(function (it) { return it.path; });
            if (!list.length) {
              viewer.innerHTML = '<div class="empty">' + JZ.icon('image', 36) +
                '<div>这个文件夹里没有图片</div></div>';
              nameEl.textContent = st.name;
              win.setTitle(st.name + ' — 图片');
              return;
            }
            win.setTitle(st.name + ' — 图片');
            renderStrip();
            show(0);
            return;
          }
          list = [st ? st.path : startPath];
          nameEl.textContent = (st && st.name) || '图片';
          win.setTitle(((st && st.name) || '图片') + ' — 图片');
          show(0);
        } catch (e) {
          nameEl.textContent = '图片';
          viewer.innerHTML = '<div class="empty">' + JZ.icon('alert-triangle', 36) +
            '<div>打不开：' + esc(e.message || '路径无效') + '</div></div>';
        }
      })();
    },
  });
})();
