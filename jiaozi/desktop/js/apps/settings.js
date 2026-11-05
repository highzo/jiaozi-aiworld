/* 设置 */
(function () {
  'use strict';
  const JZ = window.JZ;
  const esc = JZ.esc;

  const WALLS = [
    { id: 'aurora', name: '极光' }, { id: 'dawn', name: '晨雾' },
    { id: 'ocean', name: '深海' }, { id: 'forest', name: '苔原' },
    { id: 'graphite', name: '石墨' },
  ];

  JZ.registerApp({
    id: 'settings', name: '设置', icon: 'settings', color: '#5c6a7e',
    size: [820, 600], singleton: true,
    mount: function (root, win) {
      const cfg = JZ.state.config || {};
      const llm = cfg.llm || {}, agent = cfg.agent || {}, ui = cfg.ui || {}, fs = cfg.fs || {};
      const img = cfg.image || {};
      const peer = cfg.peer || {};
      const hostname = (cfg._meta || {}).hostname || '';

      root.innerHTML =
        '<div class="app">' +
          '<div class="app-bar"><b style="font-size:12.5px">设置</b><div style="flex:1"></div>' +
            '<span class="tag" data-role="saveState"></span>' +
            '<button class="btn sm primary" data-role="save">' + JZ.icon('save', 13) + '保存</button></div>' +
          '<div class="set">' +
            '<div class="set-side">' +
              '<button class="set-nav on" data-tab="llm">' + JZ.icon('sparkles', 15) + 'AI 模型</button>' +
              '<button class="set-nav" data-tab="image">' + JZ.icon('image', 15) + '图像生成</button>' +
              '<button class="set-nav" data-tab="agent">' + JZ.icon('bot', 15) + '智能体</button>' +
              '<button class="set-nav" data-tab="ui">' + JZ.icon('eye', 15) + '外观</button>' +
              '<button class="set-nav" data-tab="fs">' + JZ.icon('hard-drive', 15) + '沙箱</button>' +
              '<button class="set-nav" data-tab="peer">' + JZ.icon('wifi', 15) + '设备互联</button>' +
              '<button class="set-nav" data-tab="about">' + JZ.icon('info', 15) + '关于</button>' +
            '</div>' +
            '<div class="set-main">' +

            /* ---- 模型 ---- */
            '<div data-pane="llm">' +
              '<h3 class="set-h">AI 模型</h3>' +
              '<p class="set-desc">任何 OpenAI 兼容端点都能用。本机跑小模型推荐 Ollama 或 llama.cpp server，断网也能工作。</p>' +
              '<div class="set-field"><label class="hint">服务地址</label>' +
                '<input class="input" data-f="base_url" value="' + esc(llm.base_url || '') + '" placeholder="http://127.0.0.1:11434/v1"></div>' +
              '<div class="set-grid2">' +
                '<div class="set-field"><label class="hint">模型名</label>' +
                  '<input class="input" data-f="model" list="modelList" value="' + esc(llm.model || '') + '" placeholder="qwen2.5:1.5b-instruct">' +
                  '<datalist id="modelList"></datalist></div>' +
                '<div class="set-field"><label class="hint">API Key（本机模型留空）</label>' +
                  '<input class="input" data-f="api_key" type="password" value="" placeholder="' + (llm.api_key_set ? '已设置，留空则不修改' : 'sk-...') + '"></div>' +
              '</div>' +
              '<div class="set-grid2">' +
                '<div class="set-field"><label class="hint">温度（0 稳定 ~ 1 发散）</label>' +
                  '<input class="input" data-f="temperature" type="number" step="0.1" min="0" max="2" value="' + (llm.temperature ?? 0.3) + '"></div>' +
                '<div class="set-field"><label class="hint">单次最大输出 tokens</label>' +
                  '<input class="input" data-f="max_tokens" type="number" min="128" max="8192" value="' + (llm.max_tokens ?? 1024) + '"></div>' +
              '</div>' +
              '<div class="set-row"><div class="sr-l"><b>原生函数调用</b>' +
                '<small>模型支持 tools 参数时开启；0.5B~3B 小模型建议关闭，走提示协议更稳。</small></div>' +
                '<div class="sr-r"><label class="switch"><input type="checkbox" data-f="native_tools" ' +
                (llm.native_tools ? 'checked' : '') + '><i></i></label></div></div>' +
              '<div class="set-row"><div class="sr-l"><b>流式输出</b>' +
                '<small>逐字显示回复；个别老服务端不支持可关闭。</small></div>' +
                '<div class="sr-r"><label class="switch"><input type="checkbox" data-f="stream" ' +
                (llm.stream ? 'checked' : '') + '><i></i></label></div></div>' +
              '<div style="display:flex;gap:8px;margin-top:14px;align-items:center">' +
                '<button class="btn" data-role="test">' + JZ.icon('zap', 14) + '测试连接</button>' +
                '<button class="btn" data-role="models">拉取模型列表</button>' +
                '<span class="hint" data-role="testOut"></span></div>' +
            '</div>' +

            /* ---- 图像生成 ---- */
            '<div data-pane="image" hidden>' +
              '<h3 class="set-h">图像生成</h3>' +
              '<p class="set-desc">让 AI 真的画出图片，并保存成你硬盘上的文件。接口地址和 Key 留空时，会复用「AI 模型」里那套配置。</p>' +
              '<div class="set-field"><label class="hint">图像接口地址</label>' +
                '<input class="input" data-f="img_base_url" value="' + esc(img.base_url || '') + '" placeholder="留空复用上面的地址，例如 https://apihub.agnes-ai.com/v1"></div>' +
              '<div class="set-grid2">' +
                '<div class="set-field"><label class="hint">图像模型</label>' +
                  '<input class="input" data-f="img_model" value="' + esc(img.model || '') + '" placeholder="agnes-image-2.5-flash"></div>' +
                '<div class="set-field"><label class="hint">API Key（留空复用上面的）</label>' +
                  '<input class="input" data-f="img_api_key" type="password" value="" placeholder="' +
                  (img.api_key_set ? '已单独设置，留空则不修改' : '留空复用上面的 Key') + '"></div>' +
              '</div>' +
              '<div class="set-grid2">' +
                '<div class="set-field"><label class="hint">默认尺寸</label>' +
                  '<input class="input" data-f="img_size" value="' + esc(img.size || '1024x1024') + '" placeholder="1024x1024 或 1024x1536"></div>' +
                '<div class="set-field"><label class="hint">保存目录（须在沙箱内）</label>' +
                  '<input class="input" data-f="img_save_dir" value="' + esc(img.save_dir || '~/Pictures/JiaoziAI') + '"></div>' +
              '</div>' +
              '<div class="set-row"><div class="sr-l"><b>启用图像生成</b>' +
                '<small>关掉后 AI 调 image_gen 会直接报错，不会产生费用。</small></div>' +
                '<div class="sr-r"><label class="switch"><input type="checkbox" data-f="img_enabled" ' +
                (img.enabled !== false ? 'checked' : '') + '><i></i></label></div></div>' +
              '<div style="display:flex;gap:8px;margin-top:14px;align-items:center">' +
                '<button class="btn" data-role="imgTest">' + JZ.icon('zap', 14) + '生成一张测试图</button>' +
                '<span class="hint" data-role="imgOut"></span></div>' +
            '</div>' +

            /* ---- 智能体 ---- */
            '<div data-pane="agent" hidden>' +
              '<h3 class="set-h">智能体行为</h3>' +
              '<p class="set-desc">决定饺子能做多大的事、需要多少次确认。开发板上建议把步数调小以控制延迟。</p>' +
              '<div class="set-field"><label class="hint">危险操作审批策略</label>' +
                '<select class="input" data-f="approval" style="max-width:320px">' +
                  '<option value="auto"' + (agent.approval === 'auto' ? ' selected' : '') + '>自动 —— 仅危险操作询问我（推荐）</option>' +
                  '<option value="always"' + (agent.approval === 'always' ? ' selected' : '') + '>严格 —— 每次工具调用都要确认</option>' +
                  '<option value="never"' + (agent.approval === 'never' ? ' selected' : '') + '>放手 —— 全自动，不询问</option>' +
                '</select></div>' +
              '<div class="set-grid2">' +
                '<div class="set-field"><label class="hint">单轮最大步数</label>' +
                  '<input class="input" data-f="max_steps" type="number" min="1" max="40" value="' + (agent.max_steps ?? 12) + '"></div>' +
                '<div class="set-field"><label class="hint">命令超时（秒）</label>' +
                  '<input class="input" data-f="shell_timeout" type="number" min="5" max="600" value="' + (agent.shell_timeout ?? 60) + '"></div>' +
              '</div>' +
              '<div class="set-row"><div class="sr-l"><b>设备接口</b>' +
                '<small>允许机器人/外部设备通过 /api/device/task 调用本机大脑。</small></div>' +
                '<div class="sr-r"><label class="switch"><input type="checkbox" data-f="device_enabled" ' +
                ((cfg.device && cfg.device.enabled) ? 'checked' : '') + '><i></i></label></div></div>' +
            '</div>' +

            /* ---- 外观 ---- */
            '<div data-pane="ui" hidden>' +
              '<h3 class="set-h">外观</h3>' +
              '<p class="set-desc">同样的桌面，手机和电脑上看起来都合适。</p>' +
              '<div class="set-row"><div class="sr-l"><b>主题</b><small>浅色适合白天，深色适合夜间和开发板小屏。</small></div>' +
                '<div class="sr-r"><div class="seg" data-role="themeSeg">' +
                  '<button data-v="light" class="' + (ui.theme !== 'dark' ? 'on' : '') + '">浅色</button>' +
                  '<button data-v="dark" class="' + (ui.theme === 'dark' ? 'on' : '') + '">深色</button>' +
                '</div></div></div>' +
              '<div class="set-field" style="margin-top:16px"><label class="hint">壁纸</label>' +
                '<div class="wp-grid">' + WALLS.map(function (w) {
                  return '<div class="wp-sw wp-' + w.id + (ui.wallpaper === w.id ? ' on' : '') +
                    '" data-wp="' + w.id + '"><span>' + w.name + '</span></div>';
                }).join('') + '</div></div>' +
              '<div class="set-field" style="margin-top:8px"><label class="hint">强调色</label>' +
                '<input class="input" data-f="accent" type="color" style="width:64px;padding:3px;height:34px" value="' +
                esc(ui.accent || '#2f6bff') + '"></div>' +
            '</div>' +

            /* ---- 沙箱 ---- */
            '<div data-pane="fs" hidden>' +
              '<h3 class="set-h">文件沙箱</h3>' +
              '<p class="set-desc">AI 和文件管理器只能在这些目录里活动。加一个根目录就等于把那份数据交给它。</p>' +
              '<div data-role="roots"></div>' +
              '<div style="display:flex;gap:8px;margin-top:10px">' +
                '<input class="input" data-role="newRoot" placeholder="例如 /home/pi 或 /sdcard" style="max-width:300px">' +
                '<button class="btn" data-role="addRoot">添加</button></div>' +
              '<div class="set-row" style="margin-top:10px"><div class="sr-l"><b>上传大小上限</b>' +
                '<small>超过这个大小的文件需要走命令行拷贝。</small></div>' +
                '<div class="sr-r"><input class="input" data-f="max_upload_mb" type="number" min="1" max="2048" style="width:100px" value="' +
                Math.round((fs.max_upload_bytes || 67108864) / 1048576) + '"><span class="hint">MB</span></div></div>' +
            '</div>' +

            /* ---- 设备互联 ---- */
            '<div data-pane="peer" hidden>' +
              '<h3 class="set-h">设备互联</h3>' +
              '<p class="set-desc">同一个 WiFi 下的其他饺子会出现在「设备」里，配对之后就能互相调用工具——' +
                '比如用手机指挥这台电脑干活。改完保存立即生效。</p>' +
              '<div class="set-field"><label class="hint">本机设备名（留空用主机名）</label>' +
                '<input class="input" data-f="peer_name" value="' + esc(peer.name || '') + '" placeholder="' +
                esc(hostname || '例如 客厅电脑') + '"></div>' +
              '<div class="set-row"><div class="sr-l"><b>局域网自动发现</b>' +
                '<small>每 5 秒向局域网发一次组播。公共 WiFi 常禁组播——关掉之后仍然可以在「设备」里手动填 IP 配对。</small></div>' +
                '<div class="sr-r"><label class="switch"><input type="checkbox" data-f="peer_discovery" ' +
                (peer.discovery !== false ? 'checked' : '') + '><i></i></label></div></div>' +
              '<div class="set-row"><div class="sr-l"><b>允许别的东西调用本机</b>' +
                '<small>关闭后本机不再提供跨设备执行接口，已配对的对端全部失效。给自己留条后路，别在远程操作时关。</small></div>' +
                '<div class="sr-r"><label class="switch"><input type="checkbox" data-f="peer_enabled" ' +
                (peer.enabled !== false ? 'checked' : '') + '><i></i></label></div></div>' +
              '<p class="set-desc" style="margin-top:14px">配对不需要密码，也不需要记 IP：在对方那台点「生成配对码」，' +
                '在这台输入 6 位数字即可。码一次性、5 分钟过期、试错 6 次作废。</p>' +
            '</div>' +

            /* ---- 关于 ---- */
            '<div data-pane="about" hidden>' +
              '<h3 class="set-h">关于</h3>' +
              '<div class="about-box"><div class="logo">' + JZ.icon('bot', 26) + '</div>' +
                '<div><b style="font-size:15px">饺子AIWorld</b>' +
                '<div class="hint">让每一台 Linux 设备都有一个能看、能动手的桌面<br>人和 AI 共用同一张桌子</div></div></div>' +
              '<div class="kv" data-role="aboutKv"></div>' +
              '<div class="set-row" style="margin-top:16px"><div class="sr-l"><b>局域网访问</b>' +
                '<small>用手机/平板打开同一地址即可进入这个桌面（需要带 token）。</small></div>' +
                '<div class="sr-r"><button class="btn sm" data-role="copyUrl">复制地址</button></div></div>' +
              '<p class="hint" style="margin-top:18px">开源项目 · 无遥测 · 数据全部留在本机</p>' +
            '</div>' +

            '</div></div></div>';

      const q = (r) => root.querySelector('[data-role="' + r + '"]');
      const pane = (name) => root.querySelector('[data-pane="' + name + '"]');
      let theme = ui.theme || 'light';
      let wallpaper = ui.wallpaper || 'aurora';
      let roots = (JZ.state.roots || []).map(function (r) { return r.path; });
      let extraRoots = [];

      root.querySelectorAll('.set-nav').forEach(function (b) {
        b.onclick = function () {
          root.querySelectorAll('.set-nav').forEach(x => x.classList.remove('on'));
          b.classList.add('on');
          ['llm', 'image', 'agent', 'ui', 'fs', 'about'].forEach(function (n) { pane(n).hidden = n !== b.dataset.tab; });
        };
      });

      q('themeSeg').querySelectorAll('button').forEach(function (b) {
        b.onclick = function () {
          q('themeSeg').querySelectorAll('button').forEach(x => x.classList.remove('on'));
          b.classList.add('on');
          theme = b.dataset.v;
          applyTheme();
        };
      });
      root.querySelectorAll('.wp-sw').forEach(function (el) {
        el.onclick = function () {
          root.querySelectorAll('.wp-sw').forEach(x => x.classList.remove('on'));
          el.classList.add('on');
          wallpaper = el.dataset.wp;
          applyWp();
        };
      });

      function applyTheme() {
        document.documentElement.dataset.theme = theme;
        JZ.pref.set('theme', theme);
      }
      function applyWp() {
        const wp = document.getElementById('wallpaper');
        wp.className = 'wp-' + wallpaper;
        JZ.pref.set('wallpaper', wallpaper);
      }

      function renderRoots() {
        q('roots').innerHTML = roots.map(function (r, i) {
          return '<div class="root-item">' + JZ.icon('hard-drive', 14) +
            '<code>' + esc(r) + '</code>' +
            (roots.length > 1 ? '<button class="ibtn" data-del="' + i + '" title="移除">' + JZ.icon('x', 13) + '</button>' : '') +
            '</div>';
        }).join('');
        q('roots').querySelectorAll('[data-del]').forEach(function (b) {
          b.onclick = function () {
            roots.splice(+b.dataset.del, 1);
            renderRoots();
          };
        });
      }
      q('addRoot').onclick = function () {
        const v = q('newRoot').value.trim();
        if (!v) return;
        roots.push(v); extraRoots.push(v); q('newRoot').value = '';
        renderRoots();
      };

      q('aboutKv').innerHTML = [
        ['版本', 'v' + (cfg._meta ? cfg._meta.version : JZ.version)],
        ['平台', (cfg._meta && cfg._meta.platform) === 'posix' ? 'Linux / POSIX' : 'Windows（开发预览）'],
        ['Python', (cfg._meta && cfg._meta.python) || '—'],
        ['数据目录', (cfg._meta && cfg._meta.data_dir) || '~/.jiaozi'],
        ['主机名', (cfg._meta && cfg._meta.hostname) || location.hostname],
      ].map(function (kv) { return '<b>' + kv[0] + '</b><span>' + esc(kv[1]) + '</span>'; }).join('');

      q('copyUrl').onclick = function () {
        const url = location.origin + '/';
        navigator.clipboard.writeText(url).then(function () {
          JZ.toast('已复制', url, 'ok');
        }, function () { JZ.prompt('复制这个地址', url); });
      };

      // ---- 测试 / 模型列表 ----
      function num(f, d) { const v = parseFloat(f.value); return isNaN(v) ? d : v; }

      q('test').onclick = async function () {
        const out = q('testOut');
        out.textContent = '测试中…';
        try {
          const d = await JZ.api.post('/api/llm/test', {
            base_url: root.querySelector('[data-f="base_url"]').value.trim(),
            model: root.querySelector('[data-f="model"]').value.trim(),
            api_key: root.querySelector('[data-f="api_key"]').value.trim(),
          });
          out.innerHTML = '<span style="color:var(--ok)">连接正常</span> · 回复：' + esc((d.data && d.data.reply) || '');
        } catch (e) {
          out.innerHTML = '<span style="color:var(--err)">失败：' + esc(e.message) + '</span>';
        }
      };
      q('models').onclick = async function () {
        const out = q('testOut');
        out.textContent = '读取中…';
        try {
          const base = root.querySelector('[data-f="base_url"]').value.trim();
          await JZ.api.post('/api/config', { llm: { base_url: base } });
          const list = await JZ.api.get('/api/llm/models');
          const dl = document.getElementById('modelList');
          dl.innerHTML = list.map(m => '<option value="' + esc(m) + '">').join('');
          out.textContent = '找到 ' + list.length + ' 个模型：' + list.slice(0, 6).join('、');
        } catch (e) {
          out.innerHTML = '<span style="color:var(--err)">' + esc(e.message) + '</span>';
        }
      };

      // ---- 图像：真生成一张小图，能落盘才算通 ----
      q('imgTest').onclick = async function () {
        const out = q('imgOut');
        const g = (n) => root.querySelector('[data-f="' + n + '"]');
        out.textContent = '生成中，通常 10~30 秒…';
        try {
          const d = await JZ.api.post('/api/image/test', {
            base_url: g('img_base_url').value.trim(),
            model: g('img_model').value.trim(),
            api_key: g('img_api_key').value.trim(),
          });
          const f = (d.files || [])[0];
          out.innerHTML = '<span style="color:var(--ok)">成功 · ' + (d.elapsed || '?') + 's</span>';
          if (f) JZ.WM.open('viewer', { path: f });
        } catch (e) {
          out.innerHTML = '<span style="color:var(--err)">失败：' + esc(e.message) + '</span>';
        }
      };

      // ---- 保存 ----
      q('save').onclick = async function () {
        const g = (n) => root.querySelector('[data-f="' + n + '"]');
        const patch = {
          llm: {
            base_url: g('base_url').value.trim(),
            model: g('model').value.trim(),
            temperature: num(g('temperature'), 0.3),
            max_tokens: Math.round(num(g('max_tokens'), 1024)),
            native_tools: g('native_tools').checked,
            stream: g('stream').checked,
          },
          agent: {
            approval: g('approval').value,
            max_steps: Math.round(num(g('max_steps'), 12)),
            shell_timeout: Math.round(num(g('shell_timeout'), 60)),
          },
          ui: { theme: theme, wallpaper: wallpaper, accent: g('accent').value },
          fs: { roots: roots, max_upload_bytes: Math.round(num(g('max_upload_mb'), 64) * 1048576) },
          device: { enabled: g('device_enabled').checked },
          peer: {
            name: g('peer_name').value.trim(),
            discovery: g('peer_discovery').checked,
            enabled: g('peer_enabled').checked,
          },
          image: {
            base_url: g('img_base_url').value.trim(),
            model: g('img_model').value.trim(),
            size: g('img_size').value.trim(),
            save_dir: g('img_save_dir').value.trim(),
            enabled: g('img_enabled').checked,
          },
        };
        const key = g('api_key').value.trim();
        if (key) patch.llm.api_key = key;
        const ikey = g('img_api_key').value.trim();
        if (ikey) patch.image.api_key = ikey;
        try {
          const saved = await JZ.api.post('/api/config', patch);
          JZ.state.config = saved;
          q('saveState').textContent = '已保存';
          q('saveState').className = 'tag ok';
          JZ.toast('设置已保存', '新的参数立即生效', 'ok');
          if (JZ.onConfig) JZ.onConfig(saved);
          setTimeout(function () { q('saveState').textContent = ''; q('saveState').className = 'tag'; }, 2400);
        } catch (e) {
          JZ.toast('保存失败', e.message, 'err');
        }
      };

      renderRoots();
      JZ.paintIcons(root);
    },
  });
})();
