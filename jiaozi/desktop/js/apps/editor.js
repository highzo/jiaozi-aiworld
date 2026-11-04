/* 文本编辑器 */
(function () {
  'use strict';
  const JZ = window.JZ;
  const esc = JZ.esc;

  JZ.registerApp({
    id: 'editor', name: '编辑器', icon: 'file-text', color: '#4f7df3',
    size: [820, 620], multi: true,
    mount: function (root, win, args) {
      root.innerHTML =
        '<div class="app">' +
          '<div class="app-bar">' +
            '<button class="btn sm" data-a="save">' + JZ.icon('save', 14) + '保存</button>' +
            '<button class="btn sm" data-a="saveas">另存为</button>' +
            '<button class="btn sm" data-a="reload">重新载入</button>' +
            '<div style="flex:1"></div>' +
            '<span class="tag" data-role="enc">UTF-8</span>' +
          '</div>' +
          '<div class="ed"><div class="ed-gutter">1</div><textarea class="ed-area" spellcheck="false"></textarea></div>' +
          '<div class="app-status"><span data-role="pos">行 1，列 1</span><span data-role="cnt"></span>' +
            '<span class="grow"></span><span data-role="path"></span></div>' +
        '</div>';

      const area = root.querySelector('.ed-area');
      const gutter = root.querySelector('.ed-gutter');
      const posEl = root.querySelector('[data-role="pos"]');
      const cntEl = root.querySelector('[data-role="cnt"]');
      const pathEl = root.querySelector('[data-role="path"]');
      const encEl = root.querySelector('[data-role="enc"]');
      let path = args.path || '';
      let dirty = false;
      let loadedText = '';

      function setDirty(v) {
        dirty = v;
        win.setTitle((dirty ? '● ' : '') + (path ? path.split(/[\\/]/).pop() : '未命名') + ' — 编辑器');
      }

      function renderGutter() {
        const lines = area.value.split('\n').length;
        if (gutter.dataset.n !== String(lines)) {
          let s = '';
          for (let i = 1; i <= lines; i++) s += i + '\n';
          gutter.textContent = s;
          gutter.dataset.n = String(lines);
        }
        gutter.scrollTop = area.scrollTop;
        const chars = area.value.length;
        const words = (area.value.match(/[\u4e00-\u9fa5]|[A-Za-z0-9_]+/g) || []).length;
        cntEl.textContent = lines + ' 行 · ' + chars + ' 字符 · ' + words + ' 词';
      }

      function updatePos() {
        const upto = area.value.slice(0, area.selectionStart);
        const line = upto.split('\n').length;
        const col = upto.length - upto.lastIndexOf('\n');
        posEl.textContent = '行 ' + line + '，列 ' + col;
        renderGutter();
      }

      async function load(p) {
        if (!p) { setDirty(false); return; }
        try {
          const d = await JZ.api.get('/api/fs/read', { path: p });
          path = d.path;
          loadedText = d.text;
          area.value = d.text;
          setDirty(false);
          pathEl.textContent = d.path;
          encEl.textContent = d.binary ? '含二进制' : (d.encoding || 'UTF-8');
          if (d.truncated) JZ.toast('文件较大已截断', '仅载入前部分内容，保存会覆盖全文', 'warn');
          updatePos();
        } catch (e) {
          JZ.toast('打开失败', e.message, 'err');
        }
      }

      async function save() {
        if (!path) return saveAs();
        try {
          await JZ.api.post('/api/fs/write', { path: path, content: area.value });
          loadedText = area.value;
          setDirty(false);
          JZ.toast('已保存', path.split(/[\\/]/).pop(), 'ok', 1600);
        } catch (e) { JZ.toast('保存失败', e.message, 'err'); }
      }

      async function saveAs() {
        const base = JZ.state.home || '';
        const s = base.indexOf('\\') >= 0 ? '\\' : '/';
        const def = path || (base.replace(/[\\/]$/, '') + s + 'untitled.txt');
        const p = await JZ.prompt('另存为', def, '输入完整路径');
        if (!p) return;
        path = p;
        pathEl.textContent = p;
        await save();
      }

      root.querySelector('[data-a="save"]').onclick = save;
      root.querySelector('[data-a="saveas"]').onclick = saveAs;
      root.querySelector('[data-a="reload"]').onclick = async function () {
        if (dirty) {
          const ok = await JZ.confirm('放弃未保存的修改？', '重新载入会用磁盘上的内容覆盖当前编辑。', true);
          if (!ok) return;
        }
        load(path);
      };

      area.addEventListener('input', function () { setDirty(area.value !== loadedText); updatePos(); });
      area.addEventListener('click', updatePos);
      area.addEventListener('keyup', updatePos);
      area.addEventListener('scroll', function () { gutter.scrollTop = area.scrollTop; });
      area.addEventListener('keydown', function (e) {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
          e.preventDefault(); save();
        }
        if (e.key === 'Tab') {
          e.preventDefault();
          const st = area.selectionStart, en = area.selectionEnd;
          area.value = area.value.slice(0, st) + '  ' + area.value.slice(en);
          area.selectionStart = area.selectionEnd = st + 2;
          setDirty(area.value !== loadedText);
          updatePos();
        }
      });

      win.onClose = function () {
        if (dirty) JZ.toast('窗口已关闭', '未保存的修改已丢弃', 'warn');
      };

      pathEl.textContent = path || '未命名';
      if (path) load(path); else { setDirty(false); updatePos(); }
      setTimeout(function () { area.focus(); }, 60);
    },
  });
})();
