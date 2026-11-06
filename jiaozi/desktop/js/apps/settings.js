/* 设置 */
(function () {
  'use strict';
  const JZ = window.JZ;
  const esc = JZ.esc;
  const t = JZ.t;

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
      const langCfg = ui.language || 'auto';

      const tabs = [
        ['llm', 'sparkles', 'AI 模型'],
        ['image', 'image', '图像生成'],
        ['agent', 'bot', '智能体'],
        ['ui', 'eye', '外观'],
        ['lang', 'globe', '语言'],
        ['fs', 'hard-drive', '沙箱'],
        ['peer', 'wifi', '设备互联'],
        ['about', 'info', '关于'],
      ];

      root.innerHTML = `
        <div class="app">
          <div class="app-bar"><b style="font-size:12.5px">${esc(t('设置'))}</b><div style="flex:1"></div>
            <span class="tag" data-role="saveState"></span>
            <button class="btn sm primary" data-role="save">${JZ.icon('save', 13)}${esc(t('保存'))}</button></div>
          <div class="set">
            <div class="set-side">
              ${tabs.map((x, i) =>
                `<button class="set-nav${i === 0 ? ' on' : ''}" data-tab="${x[0]}">${JZ.icon(x[1], 15)}${esc(t(x[2]))}</button>`
              ).join('')}
            </div>
            <div class="set-main">

            <!-- 模型 -->
            <div data-pane="llm">
              <h3 class="set-h">${esc(t('AI 模型'))}</h3>
              <p class="set-desc">${esc(t('任何 OpenAI 兼容端点都能用。本机跑小模型推荐 Ollama 或 llama.cpp server，断网也能工作。'))}</p>
              <div class="set-field"><label class="hint">${esc(t('服务地址'))}</label>
                <input class="input" data-f="base_url" value="${esc(llm.base_url || '')}" placeholder="http://127.0.0.1:11434/v1"></div>
              <div class="set-grid2">
                <div class="set-field"><label class="hint">${esc(t('模型名'))}</label>
                  <input class="input" data-f="model" list="modelList" value="${esc(llm.model || '')}" placeholder="qwen2.5:1.5b-instruct">
                  <datalist id="modelList"></datalist></div>
                <div class="set-field"><label class="hint">${esc(t('API Key（本机模型留空）'))}</label>
                  <input class="input" data-f="api_key" type="password" value="" placeholder="${esc(llm.api_key_set ? t('已设置，留空则不修改') : 'sk-...')}"></div>
              </div>
              <div class="set-grid2">
                <div class="set-field"><label class="hint">${esc(t('温度（0 稳定 ~ 1 发散）'))}</label>
                  <input class="input" data-f="temperature" type="number" step="0.1" min="0" max="2" value="${(llm.temperature ?? 0.3)}"></div>
                <div class="set-field"><label class="hint">${esc(t('单次最大输出 tokens'))}</label>
                  <input class="input" data-f="max_tokens" type="number" min="128" max="8192" value="${(llm.max_tokens ?? 1024)}"></div>
              </div>
              <div class="set-row"><div class="sr-l"><b>${esc(t('原生函数调用'))}</b>
                <small>${esc(t('模型支持 tools 参数时开启；0.5B~3B 小模型建议关闭，走提示协议更稳。'))}</small></div>
                <div class="sr-r"><label class="switch"><input type="checkbox" data-f="native_tools" ${llm.native_tools ? 'checked' : ''}><i></i></label></div></div>
              <div class="set-row"><div class="sr-l"><b>${esc(t('流式输出'))}</b>
                <small>${esc(t('逐字显示回复；个别老服务端不支持可关闭。'))}</small></div>
                <div class="sr-r"><label class="switch"><input type="checkbox" data-f="stream" ${llm.stream ? 'checked' : ''}><i></i></label></div></div>
              <div style="display:flex;gap:8px;margin-top:14px;align-items:center">
                <button class="btn" data-role="test">${JZ.icon('zap', 14)}${esc(t('测试连接'))}</button>
                <button class="btn" data-role="models">${esc(t('拉取模型列表'))}</button>
                <span class="hint" data-role="testOut"></span></div>
            </div>

            <!-- 图像生成 -->
            <div data-pane="image" hidden>
              <h3 class="set-h">${esc(t('图像生成'))}</h3>
              <p class="set-desc">${esc(t('让 AI 真的画出图片，并保存成你硬盘上的文件。接口地址和 Key 留空时，会复用「AI 模型」里那套配置。'))}</p>
              <div class="set-field"><label class="hint">${esc(t('图像接口地址'))}</label>
                <input class="input" data-f="img_base_url" value="${esc(img.base_url || '')}" placeholder="${esc(t('留空复用上面的地址，例如 https://apihub.agnes-ai.com/v1'))}"></div>
              <div class="set-grid2">
                <div class="set-field"><label class="hint">${esc(t('图像模型'))}</label>
                  <input class="input" data-f="img_model" value="${esc(img.model || '')}" placeholder="agnes-image-2.5-flash"></div>
                <div class="set-field"><label class="hint">${esc(t('API Key（留空复用上面的）'))}</label>
                  <input class="input" data-f="img_api_key" type="password" value="" placeholder="${esc(img.api_key_set ? t('已单独设置，留空则不修改') : t('留空复用上面的 Key'))}"></div>
              </div>
              <div class="set-grid2">
                <div class="set-field"><label class="hint">${esc(t('默认尺寸'))}</label>
                  <input class="input" data-f="img_size" value="${esc(img.size || '1024x1024')}" placeholder="1024x1024 或 1024x1536"></div>
                <div class="set-field"><label class="hint">${esc(t('保存目录（须在沙箱内）'))}</label>
                  <input class="input" data-f="img_save_dir" value="${esc(img.save_dir || '~/Pictures/JiaoziAI')}"></div>
              </div>
              <div class="set-row"><div class="sr-l"><b>${esc(t('启用图像生成'))}</b>
                <small>${esc(t('关掉后 AI 调 image_gen 会直接报错，不会产生费用。'))}</small></div>
                <div class="sr-r"><label class="switch"><input type="checkbox" data-f="img_enabled" ${img.enabled !== false ? 'checked' : ''}><i></i></label></div></div>
              <div style="display:flex;gap:8px;margin-top:14px;align-items:center">
                <button class="btn" data-role="imgTest">${JZ.icon('zap', 14)}${esc(t('生成一张测试图'))}</button>
                <span class="hint" data-role="imgOut"></span></div>
            </div>

            <!-- 智能体 -->
            <div data-pane="agent" hidden>
              <h3 class="set-h">${esc(t('智能体行为'))}</h3>
              <p class="set-desc">${esc(t('决定饺子能做多大的事、需要多少次确认。开发板上建议把步数调小以控制延迟。'))}</p>
              <div class="set-field"><label class="hint">${esc(t('危险操作审批策略'))}</label>
                <select class="input" data-f="approval" style="max-width:360px">
                  <option value="auto"${agent.approval === 'auto' ? ' selected' : ''}>${esc(t('自动 —— 仅危险操作询问我（推荐）'))}</option>
                  <option value="always"${agent.approval === 'always' ? ' selected' : ''}>${esc(t('严格 —— 每次工具调用都要确认'))}</option>
                  <option value="never"${agent.approval === 'never' ? ' selected' : ''}>${esc(t('放手 —— 全自动，不询问'))}</option>
                </select></div>
              <div class="set-grid2">
                <div class="set-field"><label class="hint">${esc(t('单轮最大步数'))}</label>
                  <input class="input" data-f="max_steps" type="number" min="1" max="40" value="${(agent.max_steps ?? 12)}"></div>
                <div class="set-field"><label class="hint">${esc(t('命令超时（秒）'))}</label>
                  <input class="input" data-f="shell_timeout" type="number" min="5" max="600" value="${(agent.shell_timeout ?? 60)}"></div>
              </div>
              <div class="set-row"><div class="sr-l"><b>${esc(t('设备接口'))}</b>
                <small>${esc(t('允许机器人/外部设备通过 /api/device/task 调用本机大脑。'))}</small></div>
                <div class="sr-r"><label class="switch"><input type="checkbox" data-f="device_enabled" ${(cfg.device && cfg.device.enabled) ? 'checked' : ''}><i></i></label></div></div>
            </div>

            <!-- 外观 -->
            <div data-pane="ui" hidden>
              <h3 class="set-h">${esc(t('外观'))}</h3>
              <p class="set-desc">${esc(t('同样的桌面，手机和电脑上看起来都合适。'))}</p>
              <div class="set-row"><div class="sr-l"><b>${esc(t('主题'))}</b><small>${esc(t('浅色适合白天，深色适合夜间和开发板小屏。'))}</small></div>
                <div class="sr-r"><div class="seg" data-role="themeSeg">
                  <button data-v="light" class="${ui.theme !== 'dark' ? 'on' : ''}">${esc(t('浅色'))}</button>
                  <button data-v="dark" class="${ui.theme === 'dark' ? 'on' : ''}">${esc(t('深色'))}</button>
                </div></div></div>
              <div class="set-field" style="margin-top:16px"><label class="hint">${esc(t('壁纸'))}</label>
                <div class="wp-grid">${WALLS.map(function (w) {
                  return `<div class="wp-sw wp-${w.id}${ui.wallpaper === w.id ? ' on' : ''}" data-wp="${w.id}"><span>${esc(t(w.name))}</span></div>`;
                }).join('')}</div></div>
              <div class="set-field" style="margin-top:8px"><label class="hint">${esc(t('强调色'))}</label>
                <input class="input" data-f="accent" type="color" style="width:64px;padding:3px;height:34px" value="${esc(ui.accent || '#2f6bff')}"></div>
            </div>

            <!-- 语言 -->
            <div data-pane="lang" hidden>
              <h3 class="set-h">${esc(t('界面语言'))}</h3>
              <p class="set-desc">${esc(t('默认自动判断：先看你的系统和浏览器语言，认不出来再按 IP 归属地。手动选过一次之后，就不会再自动改。'))}</p>
              <div class="set-field"><label class="hint">${esc(t('语言'))}</label>
                <select class="input" data-f="language" style="max-width:360px">
                  <option value="auto"${langCfg === 'auto' ? ' selected' : ''}>${esc(t('自动（按系统语言，其次按 IP）'))}</option>
                  ${(JZ.i18n.meta.langs.length ? JZ.i18n.meta.langs : JZ.i18n.supported.map(c => ({ code: c, native: JZ.i18n.label(c) })))
                    .map(x => `<option value="${x.code}"${langCfg === x.code ? ' selected' : ''}>${esc(x.native)}${x.en && x.en !== x.native ? ' · ' + esc(x.en) : ''}</option>`).join('')}
                </select></div>
              <div class="lang-now">
                <b>${esc(JZ.i18n.label(JZ.i18n.lang))}</b>
                <span>${esc(JZ.i18n.describe())}</span>
                <small data-role="geoTip">${esc(t('选完会立即重新加载界面。'))}</small>
              </div>
              <div style="display:flex;gap:8px;margin-top:14px;align-items:center;flex-wrap:wrap">
                <button class="btn" data-role="geoDetect">${JZ.icon('wifi', 14)}${esc(t('按 IP 重新检测'))}</button>
                <span class="hint" data-role="geoOut"></span></div>
              <p class="set-desc" style="margin-top:18px">${esc(t('目前翻好的语言：简体中文、繁體中文、English、日本語、한국어、Deutsch、Français、Español、Português、Русский。新的语言只要往 desktop/i18n/ 里加一个 JSON，不需要改代码。'))}</p>
            </div>

            <!-- 沙箱 -->
            <div data-pane="fs" hidden>
              <h3 class="set-h">${esc(t('文件沙箱'))}</h3>
              <p class="set-desc">${esc(t('AI 和文件管理器只能在这些目录里活动。加一个根目录就等于把那份数据交给它。'))}</p>
              <div data-role="roots"></div>
              <div style="display:flex;gap:8px;margin-top:10px">
                <input class="input" data-role="newRoot" placeholder="${esc(t('例如 /home/pi 或 /sdcard'))}" style="max-width:300px">
                <button class="btn" data-role="addRoot">${esc(t('添加'))}</button></div>
              <div class="set-row" style="margin-top:10px"><div class="sr-l"><b>${esc(t('上传大小上限'))}</b>
                <small>${esc(t('超过这个大小的文件需要走命令行拷贝。'))}</small></div>
                <div class="sr-r"><input class="input" data-f="max_upload_mb" type="number" min="1" max="2048" style="width:100px" value="${Math.round((fs.max_upload_bytes || 67108864) / 1048576)}"><span class="hint">MB</span></div></div>
            </div>

            <!-- 设备互联 -->
            <div data-pane="peer" hidden>
              <h3 class="set-h">${esc(t('设备互联'))}</h3>
              <p class="set-desc">${esc(t('同一个 WiFi 下的其他饺子会出现在「设备」里，配对之后就能互相调用工具——比如用手机指挥这台电脑干活。改完保存立即生效。'))}</p>
              <div class="set-field"><label class="hint">${esc(t('本机设备名（留空用主机名）'))}</label>
                <input class="input" data-f="peer_name" value="${esc(peer.name || '')}" placeholder="${esc(hostname || t('例如 客厅电脑'))}"></div>
              <div class="set-row"><div class="sr-l"><b>${esc(t('局域网自动发现'))}</b>
                <small>${esc(t('每 5 秒向局域网发一次组播。公共 WiFi 常禁组播——关掉之后仍然可以在「设备」里手动填 IP 配对。'))}</small></div>
                <div class="sr-r"><label class="switch"><input type="checkbox" data-f="peer_discovery" ${peer.discovery !== false ? 'checked' : ''}><i></i></label></div></div>
              <div class="set-row"><div class="sr-l"><b>${esc(t('允许别的东西调用本机'))}</b>
                <small>${esc(t('关闭后本机不再提供跨设备执行接口，已配对的对端全部失效。给自己留条后路，别在远程操作时关。'))}</small></div>
                <div class="sr-r"><label class="switch"><input type="checkbox" data-f="peer_enabled" ${peer.enabled !== false ? 'checked' : ''}><i></i></label></div></div>
              <p class="set-desc" style="margin-top:14px">${esc(t('配对不需要密码，也不需要记 IP：在对方那台点「生成配对码」，在这台输入 6 位数字即可。码一次性、5 分钟过期、试错 6 次作废。'))}</p>
            </div>

            <!-- 关于 -->
            <div data-pane="about" hidden>
              <h3 class="set-h">${esc(t('关于'))}</h3>
              <div class="about-box"><div class="logo">${JZ.icon('bot', 26)}</div>
                <div><b style="font-size:15px">饺子AIWorld</b>
                <div class="hint">${esc(t('让每一台 Linux 设备都有一个能看、能动手的桌面'))}<br>${esc(t('人和 AI 共用同一张桌子'))}</div></div></div>
              <div class="kv" data-role="aboutKv"></div>
              <div class="set-row" style="margin-top:16px"><div class="sr-l"><b>${esc(t('局域网访问'))}</b>
                <small>${esc(t('用手机/平板打开同一地址即可进入这个桌面（需要带 token）。'))}</small></div>
                <div class="sr-r"><button class="btn sm" data-role="copyUrl">${esc(t('复制地址'))}</button></div></div>
              <p class="hint" style="margin-top:18px">${esc(t('开源项目 · 无遥测 · 数据全部留在本机'))}</p>
            </div>

            </div></div></div>`;

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
          // 这里必须覆盖全部面板。之前漏了 peer，点「设备互联」是一片空白。
          tabs.forEach(function (x) { pane(x[0]).hidden = x[0] !== b.dataset.tab; });
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
            (roots.length > 1 ? '<button class="ibtn" data-del="' + i + '" title="' + esc(t('移除')) + '">' + JZ.icon('x', 13) + '</button>' : '') +
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
        [t('版本'), 'v' + (cfg._meta ? cfg._meta.version : JZ.version)],
        [t('平台'), (cfg._meta && cfg._meta.platform) === 'posix' ? 'Linux / POSIX' : t('Windows（开发预览）')],
        ['Python', (cfg._meta && cfg._meta.python) || '—'],
        [t('数据目录'), (cfg._meta && cfg._meta.data_dir) || '~/.jiaozi'],
        [t('主机名'), (cfg._meta && cfg._meta.hostname) || location.hostname],
        [t('界面语言'), JZ.i18n.label(JZ.i18n.lang) + ' · ' + JZ.i18n.describe()],
      ].map(function (kv) { return '<b>' + esc(kv[0]) + '</b><span>' + esc(kv[1]) + '</span>'; }).join('');

      q('copyUrl').onclick = function () {
        const url = location.origin + '/';
        navigator.clipboard.writeText(url).then(function () {
          JZ.toast(t('已复制'), url, 'ok');
        }, function () { JZ.prompt(t('复制这个地址'), url); });
      };

      // ---- 语言：选完立即换，不要求先点保存 ----
      root.querySelector('[data-f="language"]').onchange = async function () {
        const v = this.value;
        try { await JZ.api.post('/api/i18n', { lang: v }); } catch (e) { /* 离线也让它切，本地会记住 */ }
        if (v === 'auto') JZ.i18n.useAuto();
        else JZ.i18n.setLang(v);
      };

      q('geoDetect').onclick = async function () {
        const out = q('geoOut');
        out.textContent = t('检测中…');
        out.style.color = '';
        try {
          const g = await JZ.api.get('/api/geo', { refresh: 1 });
          if (!g.ok) {
            out.textContent = t('定位失败：可能没有联网');
            out.style.color = 'var(--err)';
            return;
          }
          const name = JZ.i18n.label(g.suggest) || '—';
          out.textContent = (g.country || g.country_code) + (g.city ? ' · ' + g.city : '') +
            ' → ' + name + '（' + (g.source || '') + '）';
          out.style.color = 'var(--ok)';
          q('geoTip').textContent = t('如果和现在的界面语言不同，把上面选成「自动」再保存即可切过去。');
        } catch (e) {
          out.textContent = t('定位失败：') + e.message;
          out.style.color = 'var(--err)';
        }
      };

      // ---- 测试 / 模型列表 ----
      function num(f, d) { const v = parseFloat(f.value); return isNaN(v) ? d : v; }

      q('test').onclick = async function () {
        const out = q('testOut');
        out.textContent = t('测试中…');
        try {
          const d = await JZ.api.post('/api/llm/test', {
            base_url: root.querySelector('[data-f="base_url"]').value.trim(),
            model: root.querySelector('[data-f="model"]').value.trim(),
            api_key: root.querySelector('[data-f="api_key"]').value.trim(),
          });
          out.innerHTML = '<span style="color:var(--ok)">' + esc(t('连接正常')) + '</span> · ' +
            esc(t('回复：')) + esc((d.data && d.data.reply) || '');
        } catch (e) {
          out.innerHTML = '<span style="color:var(--err)">' + esc(t('失败：') + e.message) + '</span>';
        }
      };
      q('models').onclick = async function () {
        const out = q('testOut');
        out.textContent = t('读取中…');
        try {
          const base = root.querySelector('[data-f="base_url"]').value.trim();
          await JZ.api.post('/api/config', { llm: { base_url: base } });
          const list = await JZ.api.get('/api/llm/models');
          const dl = document.getElementById('modelList');
          dl.innerHTML = list.map(m => '<option value="' + esc(m) + '">').join('');
          out.textContent = t('找到 {n} 个模型：', { n: list.length }) + list.slice(0, 6).join('、');
        } catch (e) {
          out.innerHTML = '<span style="color:var(--err)">' + esc(e.message) + '</span>';
        }
      };

      // ---- 图像：真生成一张小图，能落盘才算通 ----
      q('imgTest').onclick = async function () {
        const out = q('imgOut');
        const g = (n) => root.querySelector('[data-f="' + n + '"]');
        out.textContent = t('生成中，通常 10~30 秒…');
        try {
          const d = await JZ.api.post('/api/image/test', {
            base_url: g('img_base_url').value.trim(),
            model: g('img_model').value.trim(),
            api_key: g('img_api_key').value.trim(),
          });
          const f = (d.files || [])[0];
          out.innerHTML = '<span style="color:var(--ok)">' + esc(t('成功')) + ' · ' + (d.elapsed || '?') + 's</span>';
          if (f) JZ.WM.open('viewer', { path: f });
        } catch (e) {
          out.innerHTML = '<span style="color:var(--err)">' + esc(t('失败：') + e.message) + '</span>';
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
          ui: { theme: theme, wallpaper: wallpaper, accent: g('accent').value, language: g('language').value },
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
          q('saveState').textContent = t('已保存');
          q('saveState').className = 'tag ok';
          JZ.toast(t('设置已保存'), t('新的参数立即生效'), 'ok');
          if (JZ.onConfig) JZ.onConfig(saved);
          setTimeout(function () { q('saveState').textContent = ''; q('saveState').className = 'tag'; }, 2400);
        } catch (e) {
          JZ.toast(t('保存失败'), e.message, 'err');
        }
      };

      renderRoots();
      JZ.paintIcons(root);
    },
  });
})();
