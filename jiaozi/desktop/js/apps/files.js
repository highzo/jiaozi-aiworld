/* 文件管理器 */
(function () {
  'use strict';
  const JZ = window.JZ;
  const esc = JZ.esc;

  function sep(p) { return p && p.indexOf('\\') >= 0 ? '\\' : '/'; }
  function join(base, name) {
    const s = sep(base);
    return String(base).replace(/[\\/]+$/, '') + s + name;
  }
  function parts(p) {
    if (!p) return [];
    const isWin = p.indexOf('\\') >= 0 || /^[A-Za-z]:/.test(p);
    const arr = p.split(isWin ? /\\/ : /\//).filter(Boolean);
    const out = [];
    let acc = isWin ? '' : '';
    arr.forEach(function (seg, i) {
      if (isWin) acc = i === 0 ? seg + '\\' : acc.replace(/\\$/, '') + '\\' + seg;
      else acc = acc + '/' + seg;
      out.push({ name: seg, path: acc || '/' });
    });
    return out;
  }

  function iconFor(item) {
    if (item.is_dir) return { cls: 'dir', ico: 'folder' };
    if (item.kind === 'image') return { cls: 'img', ico: 'image' };
    if (item.kind === 'text') return { cls: 'text', ico: 'file-text' };
    return { cls: '', ico: 'file' };
  }

  JZ.registerApp({
    id: 'files', name: '文件', icon: 'folder', color: '#e8a33d',
    size: [960, 600], singleton: true,
    mount: function (root, win, args) {
      root.innerHTML =
        '<div class="app">' +
          '<div class="app-bar">' +
            '<button class="ibtn" data-nav="back" title="后退">' + JZ.icon('arrow-left', 16) + '</button>' +
            '<button class="ibtn" data-nav="up" title="上一级">' + JZ.icon('arrow-up', 16) + '</button>' +
            '<button class="ibtn" data-nav="refresh" title="刷新">' + JZ.icon('refresh', 16) + '</button>' +
            '<div class="sep"></div>' +
            '<button class="btn sm" data-nav="newdir">' + JZ.icon('plus', 14) + '新建</button>' +
            '<button class="btn sm" data-nav="upload">' + JZ.icon('upload', 14) + '上传</button>' +
            '<div style="flex:1"></div>' +
            '<div class="tb-search" style="width:190px;height:29px">' + JZ.icon('search', 14) +
              '<input placeholder="在当前目录搜索" class="fsearch"></div>' +
          '</div>' +
          '<div class="fm">' +
            '<div class="fm-side"></div>' +
            '<div class="fm-main">' +
              '<div class="fm-crumb"></div>' +
              '<div class="fm-head"><span>名称</span><span>大小</span><span>修改时间</span></div>' +
              '<div class="fm-list"></div>' +
            '</div>' +
          '</div>' +
          '<div class="app-status"><span class="st-count">—</span><span class="st-sel"></span>' +
            '<span class="grow"></span><span class="st-disk"></span></div>' +
        '</div>';

      const side = root.querySelector('.fm-side');
      const crumb = root.querySelector('.fm-crumb');
      const list = root.querySelector('.fm-list');
      const stCount = root.querySelector('.st-count');
      const stSel = root.querySelector('.st-sel');
      const stDisk = root.querySelector('.st-disk');
      const searchInput = root.querySelector('.fsearch');
      const input = document.createElement('input');
      input.type = 'file'; input.multiple = true; input.style.display = 'none';
      root.appendChild(input);

      let cwd = args.path || JZ.state.home || '';
      let parentPath = null;
      let items = [];
      let selected = null;
      let history = [];
      let searching = false;

      function renderSide() {
        const home = JZ.state.home || '';
        const s = sep(home);
        const quick = [
          { name: '主目录', path: home, icon: 'home' },
          { name: '桌面', path: join(home, 'Desktop'), icon: 'desktop' },
          { name: '下载', path: join(home, 'Downloads'), icon: 'download' },
          { name: '文档', path: join(home, 'Documents'), icon: 'file-text' },
          { name: '图片', path: join(home, 'Pictures'), icon: 'image' },
        ];
        let html = '<div class="fm-grp">常用</div>';
        quick.forEach(function (q) {
          html += '<button class="fm-nav" data-path="' + esc(q.path) + '">' + JZ.icon(q.icon, 15) + esc(q.name) + '</button>';
        });
        html += '<div class="fm-grp">沙箱根目录</div>';
        (JZ.state.roots || []).forEach(function (r) {
          html += '<button class="fm-nav" data-path="' + esc(r.path) + '" title="' + esc(r.path) + '">' +
            JZ.icon('hard-drive', 15) + esc(r.name) + '</button>';
        });
        side.innerHTML = html;
        side.querySelectorAll('.fm-nav').forEach(function (b) {
          b.onclick = function () { go(b.dataset.path); };
          if (b.dataset.path === cwd) b.classList.add('on');
        });
      }

      function renderCrumb() {
        const ps = parts(cwd);
        let html = '<button data-path="' + esc(cwd) + '">' + JZ.icon('hard-drive', 13) + '</button>';
        ps.forEach(function (p, i) {
          html += '<span class="sl">' + JZ.icon('chevron-right', 11) + '</span>';
          html += '<button data-path="' + esc(p.path) + '">' + esc(p.name) + '</button>';
        });
        crumb.innerHTML = html;
        crumb.querySelectorAll('button').forEach(function (b) {
          b.onclick = function () { go(b.dataset.path); };
        });
        crumb.scrollLeft = 99999;
      }

      function renderList() {
        if (!items.length) {
          list.innerHTML = '<div class="empty" style="height:180px">' + JZ.icon('folder-open', 40) +
            '<div>' + (searching ? '没有匹配的文件' : '这个文件夹是空的') + '</div></div>';
          return;
        }
        list.innerHTML = items.map(function (it, i) {
          const ic = iconFor(it);
          return '<div class="fm-row" data-i="' + i + '" data-path="' + esc(it.path) + '">' +
            '<div class="fm-name"><span class="fm-ico ' + ic.cls + '">' + JZ.icon(ic.ico, 16) + '</span>' +
            '<span title="' + esc(it.name) + '">' + esc(it.name) + '</span></div>' +
            '<div class="fm-meta">' + (it.is_dir ? '—' : JZ.fmt.bytes(it.size)) + '</div>' +
            '<div class="fm-meta">' + JZ.fmt.time(it.mtime) + '</div></div>';
        }).join('');
        list.querySelectorAll('.fm-row').forEach(function (row) {
          const it = items[+row.dataset.i];
          row.onclick = function () { select(it, row); };
          row.ondblclick = function () { open(it); };
          row.oncontextmenu = function (e) {
            e.preventDefault(); e.stopPropagation();
            select(it, row);
            rowMenu(e.clientX, e.clientY, it);
          };
        });
      }

      function select(it, row) {
        selected = it;
        list.querySelectorAll('.fm-row').forEach(r => r.classList.remove('sel'));
        if (row) row.classList.add('sel');
        stSel.textContent = it ? ('已选 1 项 · ' + (it.is_dir ? '文件夹' : JZ.fmt.bytes(it.size))) : '';
      }

      function rowMenu(x, y, it) {
        JZ.menu(x, y, [
          { label: '打开', icon: 'external-link', action: () => open(it) },
          { label: it.is_dir ? '在此打开终端' : '用编辑器打开', icon: it.is_dir ? 'terminal' : 'edit', action: () => {
            if (it.is_dir) JZ.WM.open('terminal', { cwd: it.path });
            else JZ.WM.open('editor', { path: it.path });
          }, disabled: false },
          { sep: true },
          { label: '重命名', icon: 'edit', key: 'F2', action: () => rename(it) },
          { label: '复制副本', icon: 'copy', action: () => copyItem(it) },
          { label: '下载到本机', icon: 'download', action: () => download(it) },
          { sep: true },
          { label: '删除', icon: 'trash', key: 'Del', danger: true, action: () => del(it) },
        ]);
      }

      async function go(path) {
        if (!path) return;
        try {
          const d = await JZ.api.get('/api/fs/list', { path: path });
          history.push(cwd);
          cwd = d.path;
          parentPath = d.parent;
          items = d.items;
          searching = false;
          searchInput.value = '';
          selected = null;
          stSel.textContent = '';
          renderSide(); renderCrumb(); renderList();
          stCount.textContent = d.items.length + ' 个项目';
          win.setTitle('文件 — ' + (cwd.split(/[\\/]/).pop() || cwd));
          refreshDisk();
        } catch (e) {
          JZ.toast('打不开这个目录', e.message, 'err');
        }
      }

      async function refresh() {
        try {
          const d = await JZ.api.get('/api/fs/list', { path: cwd });
          items = d.items; parentPath = d.parent;
          const keep = selected ? selected.path : null;
          selected = null;
          renderList(); renderSide(); renderCrumb();
          stCount.textContent = d.items.length + ' 个项目';
          if (keep) {
            const idx = items.findIndex(i => i.path === keep);
            if (idx >= 0) select(items[idx], list.querySelector('.fm-row[data-i="' + idx + '"]'));
          }
          refreshDisk();
        } catch (e) { /* 静默 */ }
      }

      async function refreshDisk() {
        try {
          const info = await JZ.api.get('/api/sys/info');
          JZ.state.sys = info;
          const free = (info.disk.free / 1024 / 1024 / 1024).toFixed(1);
          stDisk.textContent = '可用 ' + free + ' GB / 共 ' +
            (info.disk.total / 1024 / 1024 / 1024).toFixed(0) + ' GB';
        } catch (e) {}
      }

      function open(it) {
        if (it.is_dir) return go(it.path);
        if (it.kind === 'image') return JZ.WM.open('viewer', { path: it.path });
        if (it.kind === 'text') return JZ.WM.open('editor', { path: it.path });
        download(it);
      }

      function download(it) {
        const a = document.createElement('a');
        a.href = JZ.api.raw('/api/fs/raw', { path: it.path });
        a.download = it.name;
        document.body.appendChild(a); a.click(); a.remove();
      }

      async function rename(it) {
        const n = await JZ.prompt('重命名', it.name, it.path);
        if (!n || n === it.name) return;
        try {
          await JZ.api.post('/api/fs/rename', { path: it.path, to: join(cwd, n) });
          JZ.toast('已重命名', n, 'ok');
          refresh();
        } catch (e) { JZ.toast('重命名失败', e.message, 'err'); }
      }

      async function copyItem(it) {
        try {
          await JZ.api.post('/api/fs/copy', { path: it.path, to: cwd });
          JZ.toast('已复制', it.name, 'ok');
          refresh();
        } catch (e) { JZ.toast('复制失败', e.message, 'err'); }
      }

      async function del(it) {
        const ok = await JZ.confirm('删除「' + it.name + '」？',
          '文件会进入回收站（~/.jiaozi/trash），可以手动找回。', true);
        if (!ok) return;
        try {
          await JZ.api.post('/api/fs/delete', { path: it.path });
          JZ.toast('已移入回收站', it.name, 'ok');
          refresh();
        } catch (e) { JZ.toast('删除失败', e.message, 'err'); }
      }

      // ---------------- 工具栏 ----------------
      root.querySelector('[data-nav="back"]').onclick = function () {
        const p = history.pop();
        if (p) go(p);
      };
      root.querySelector('[data-nav="up"]').onclick = function () { if (parentPath) go(parentPath); };
      root.querySelector('[data-nav="refresh"]').onclick = function () { refresh(); JZ.toast('已刷新', '', 'ok', 1200); };
      root.querySelector('[data-nav="newdir"]').onclick = async function () {
        const n = await JZ.prompt('新建文件夹', '新建文件夹', cwd);
        if (!n) return;
        try {
          await JZ.api.post('/api/fs/mkdir', { path: join(cwd, n) });
          refresh();
        } catch (e) { JZ.toast('创建失败', e.message, 'err'); }
      };
      root.querySelector('[data-nav="upload"]').onclick = function () { input.click(); };
      input.onchange = function () { uploadFiles(Array.from(input.files || [])); input.value = ''; };

      async function uploadFiles(files) {
        if (!files.length) return;
        for (const f of files) {
          if (f.size > 60 * 1024 * 1024) { JZ.toast('跳过超大文件', f.name, 'warn'); continue; }
          try {
            const b64 = await new Promise(function (res, rej) {
              const r = new FileReader();
              r.onload = () => res(r.result);
              r.onerror = rej;
              r.readAsDataURL(f);
            });
            await JZ.api.post('/api/fs/upload', { dir: cwd, name: f.name, data: b64 });
            JZ.toast('已上传', f.name, 'ok', 1800);
          } catch (e) { JZ.toast('上传失败 ' + f.name, e.message, 'err'); }
        }
        refresh();
      }

      // 拖拽上传
      ['dragover', 'dragenter'].forEach(function (ev) {
        list.addEventListener(ev, function (e) { e.preventDefault(); list.classList.add('drag-over'); });
      });
      ['dragleave', 'drop'].forEach(function (ev) {
        list.addEventListener(ev, function (e) { e.preventDefault(); list.classList.remove('drag-over'); });
      });
      list.addEventListener('drop', function (e) {
        e.preventDefault();
        uploadFiles(Array.from(e.dataTransfer.files || []));
      });

      // 搜索
      let stimer = null;
      searchInput.oninput = function () {
        clearTimeout(stimer);
        const q = searchInput.value.trim();
        stimer = setTimeout(async function () {
          if (!q) { searching = false; refresh(); return; }
          searching = true;
          try {
            const hits = await JZ.api.get('/api/fs/search', { path: cwd, q: q, limit: 200 });
            items = hits;
            renderList();
            stCount.textContent = hits.length + ' 个结果';
          } catch (e) { JZ.toast('搜索失败', e.message, 'err'); }
        }, 260);
      };

      // 键盘
      root.addEventListener('keydown', function (e) {
        if (e.key === 'Delete' && selected) { e.preventDefault(); del(selected); }
        if (e.key === 'F2' && selected) { e.preventDefault(); rename(selected); }
        if (e.key === 'Enter' && selected) { e.preventDefault(); open(selected); }
      });
      root.tabIndex = 0;

      // 空白处右键
      list.oncontextmenu = function (e) {
        if (e.target.closest('.fm-row')) return;
        e.preventDefault();
        JZ.menu(e.clientX, e.clientY, [
          { label: '新建文件夹', icon: 'plus', action: () => root.querySelector('[data-nav="newdir"]').click() },
          { label: '上传文件', icon: 'upload', action: () => input.click() },
          { label: '刷新', icon: 'refresh', action: refresh },
          { sep: true },
          { label: '在终端中打开', icon: 'terminal', action: () => JZ.WM.open('terminal', { cwd: cwd }) },
        ]);
      };

      // 外部变更自动刷新
      const off = JZ.on('ev:fs_change', function (ev) {
        const p = ev.d && ev.d.path;
        if (!p) return;
        if (p.indexOf(cwd) === 0 || (selected && p === selected.path)) {
          clearTimeout(root._t);
          root._t = setTimeout(refresh, 400);
        }
      });
      win.onClose = off;

      if (args.initialItems) { items = args.initialItems; renderList(); }
      renderSide();
      go(cwd);
    },
  });
})();
