/* 图片查看器 */
(function () {
  'use strict';
  const JZ = window.JZ;
  const esc = JZ.esc;

  JZ.registerApp({
    id: 'viewer', name: '图片', icon: 'image', color: '#22a06b',
    size: [760, 560], multi: true,
    mount: function (root, win, args) {
      const path = args.path || '';
      const name = path.split(/[\\/]/).pop() || '图片';
      root.innerHTML =
        '<div class="app">' +
          '<div class="app-bar"><span style="font-size:12.5px;color:var(--text-2);max-width:45%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' +
            esc(name) + '</span><div style="flex:1"></div>' +
            '<button class="btn sm" data-z="out">缩小</button>' +
            '<button class="btn sm" data-z="fit">适应</button>' +
            '<button class="btn sm" data-z="in">放大</button>' +
            '<button class="btn sm" data-z="open">外部打开</button>' +
          '</div>' +
          '<div class="viewer"><img alt=""></div>' +
          '<div class="app-status"><span data-role="sz"></span></div>' +
        '</div>';
      const img = root.querySelector('img');
      const url = JZ.api.raw('/api/fs/raw', { path: path });
      img.src = url;
      img.onload = function () {
        root.querySelector('[data-role="sz"]').textContent = img.naturalWidth + ' × ' + img.naturalHeight + ' px';
      };
      img.onerror = function () {
        root.querySelector('.viewer').innerHTML = '<div class="empty">' + JZ.icon('alert-triangle', 36) + '<div>无法显示这张图片</div></div>';
      };
      let zoom = 1;
      function applyZoom() {
        img.style.maxWidth = zoom === 1 ? '100%' : 'none';
        img.style.maxHeight = zoom === 1 ? '100%' : 'none';
        img.style.transform = 'scale(' + zoom + ')';
      }
      root.querySelector('[data-z="in"]').onclick = function () { zoom = Math.min(6, zoom * 1.25); applyZoom(); };
      root.querySelector('[data-z="out"]').onclick = function () { zoom = Math.max(0.1, zoom / 1.25); applyZoom(); };
      root.querySelector('[data-z="fit"]').onclick = function () { zoom = 1; applyZoom(); };
      root.querySelector('[data-z="open"]').onclick = function () { window.open(url, '_blank'); };
      win.setTitle(name + ' — 图片');
    },
  });
})();
