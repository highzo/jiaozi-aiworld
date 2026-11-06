/* ============================================================
   饺子AIWorld · 多语言内核
   ------------------------------------------------------------
   设计取舍（写给以后改这个文件的人）：

   1. **key 就是中文原文**，不另造 `app.files.title` 这类键名。
      原因：源码是中文写的，333 条文案里大半是短句和 HTML 片段；
      造键名要额外维护一张表，而且改一处文案就得改两处。
      用原文当 key，翻译文件长这样：{"文件": "Files"}，对照着就能翻，
      贡献者不需要读代码。缺翻译时自动回落中文，永远不会显示空白。

   2. **不做到处自动替换文本节点**。试过：文件管理器里一个叫「图片」
      的文件夹会被翻译成 Pictures，终端输出也会被改写。翻译必须发生在
      「确定这是 UI 文案」的位置，也就是代码里显式调 t() 的地方。

   3. **语言字典是独立的 JSON 文件**，不是打包进 JS 的大对象。
      加一门语言 = 往 i18n/ 放一个文件 + 在 i18n.py 的 LANGS 里加一行。
   ============================================================ */
(function () {
  'use strict';

  var JZ = window.JZ;
  var LS_LANG = 'jz.lang';          // 用户显式选择
  var LS_GEO = 'jz.lang.geo';       // 上次按 IP 自动判定的结果 {cc, lang}
  var LS_RELOADED = 'jz.lang.reloaded';

  var dicts = {};                   // code -> {中文: 译文}
  var cur = 'zh-CN';                // 当前语言
  var curDict = null;               // 当前字典（zh-CN 时为 null，直接用原文）
  var fallback = null;              // 英文兜底：德语气泡里缺一条时给英文，不要甩中文
  var meta = { source: 'default', country: '', langs: [], auto: false };

  var SUPPORTED = ['zh-CN', 'zh-TW', 'en', 'ja', 'ko', 'de', 'fr', 'es', 'pt-BR', 'ru'];
  var RTL = [];                     // 目前没有 RTL 语言；有的话在这里加

  /* ---------------- 基础 ---------------- */

  function norm(code) {
    code = String(code || '').trim();
    if (!code) return '';
    var low = code.toLowerCase().replace(/_/g, '-');
    for (var i = 0; i < SUPPORTED.length; i++) {
      if (SUPPORTED[i].toLowerCase() === low) return SUPPORTED[i];
    }
    var base = low.split('-')[0];
    var alias = { zh: 'zh-CN', en: 'en', ja: 'ja', ko: 'ko', de: 'de',
      fr: 'fr', es: 'es', pt: 'pt-BR', ru: 'ru' };
    if (alias[base]) return alias[base];
    for (var j = 0; j < SUPPORTED.length; j++) {
      if (SUPPORTED[j].toLowerCase() === base) return SUPPORTED[j];
    }
    return '';
  }

  /** 翻译。查找顺序：当前语言 → 英文 → 中文原文。
      第三级回落很重要：宁可给一门用户大概读得懂的语言，也别甩一句中文。 */
  function t(s, vars) {
    if (s == null) return '';
    var out = s;
    if (curDict && Object.prototype.hasOwnProperty.call(curDict, s)) out = curDict[s];
    else if (fallback && Object.prototype.hasOwnProperty.call(fallback, s)) out = fallback[s];
    if (vars) {
      out = String(out).replace(/\{(\w+)\}/g, function (m, k) {
        return (vars[k] !== undefined && vars[k] !== null) ? vars[k] : m;
      });
    }
    return out;
  }
  JZ.t = t;

  function getJSON(url) {
    return fetch(url, { credentials: 'same-origin' }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }

  function loadDict(code) {
    if (code === 'zh-CN') { dicts[code] = {}; return Promise.resolve({}); }
    // 非英文语言都先把英文装上当兜底；英文自己不需要
    if (code !== 'en' && !fallback) {
      getJSON('i18n/en.json').then(function (d) {
        fallback = (d && d.strings) || d || {};
        // 兜底晚到一步时，把已经画出来的文字补一遍
        if (JZ.i18n) JZ.i18n.apply(document);
      }).catch(function () { fallback = {}; });
    }
    if (dicts[code]) return Promise.resolve(dicts[code]);
    return getJSON('i18n/' + code + '.json').then(function (d) {
      dicts[code] = (d && d.strings) || d || {};
      return dicts[code];
    }).catch(function () {
      // 字典拿不到不能白屏：回落中文，只是界面还是中文
      dicts[code] = {};
      return {};
    });
  }

  /* ---------------- 静态 HTML 翻译 ---------------- */

  function apply(root) {
    root = root || document;
    var box = root.querySelectorAll ? root : document;

    box.querySelectorAll('[data-i18n]').forEach(function (el) {
      el.textContent = t(el.dataset.i18n);
    });
    box.querySelectorAll('[data-i18n-title]').forEach(function (el) {
      el.title = t(el.dataset.i18nTitle);
    });
    box.querySelectorAll('[data-i18n-ph]').forEach(function (el) {
      el.placeholder = t(el.dataset.i18nPh);
    });
    box.querySelectorAll('[data-i18n-html]').forEach(function (el) {
      el.innerHTML = t(el.dataset.i18nHtml);
    });
    if (root === document || (root.documentElement && root === root.documentElement)) {
      document.documentElement.lang = cur;
      document.documentElement.dir = RTL.indexOf(cur) >= 0 ? 'rtl' : 'ltr';
      document.title = t('饺子AIWorld');
    }
  }

  /* ---------------- 语言切换 ---------------- */

  function remember(code, opts) {
    opts = opts || {};
    try {
      if (opts.user) localStorage.setItem(LS_LANG, code);
      if (code === 'auto') localStorage.removeItem(LS_LANG);
    } catch (e) { /* 隐私模式下 localStorage 可能抛错，忽略即可 */ }
  }

  /** 切换到某语言并重载页面。桌面窗口状态不做保留 —— 重载比"半个界面还
      是旧语言"干净得多。 */
  function setLang(code, opts) {
    opts = opts || {};
    code = norm(code);
    if (!code) code = 'en';
    remember(code, { user: true });
    try { localStorage.removeItem(LS_GEO); } catch (e) {}
    if (opts.reload === false) return Promise.resolve(code);
    location.reload();
    return Promise.resolve(code);
  }

  /** 恢复"自动"：清掉用户选择，下次启动重新按浏览器/ IP 判断 */
  function useAuto() {
    try {
      localStorage.removeItem(LS_LANG);
      localStorage.removeItem(LS_GEO);
    } catch (e) {}
    location.reload();
  }

  /* ---------------- 启动流程 ---------------- */

  function explicitLang() {
    try {
      var v = localStorage.getItem(LS_LANG);
      if (v) return norm(v) || '';
    } catch (e) {}
    return '';
  }

  function cachedGeo() {
    try {
      var raw = localStorage.getItem(LS_GEO);
      if (!raw) return null;
      var d = JSON.parse(raw);
      if (d && d.lang && norm(d.lang)) return d;
    } catch (e) {}
    return null;
  }

  function saveGeo(cc, lang) {
    try {
      localStorage.setItem(LS_GEO, JSON.stringify({ cc: cc, lang: lang, ts: Date.now() }));
    } catch (e) {}
  }

  function onceReloaded() {
    // 防止「判定 → 重载 → 又判定 → 又重载」的死循环
    try {
      if (sessionStorage.getItem(LS_RELOADED)) return true;
      sessionStorage.setItem(LS_RELOADED, '1');
    } catch (e) {}
    return false;
  }

  /** 启动：确定语言并加载字典。返回 Promise<code>。 */
  function init() {
    var pick = explicitLang();
    if (pick) {
      return loadDict(pick).then(function () { return finish(pick, 'user', ''); });
    }

    var geo = cachedGeo();
    if (geo) {
      return loadDict(geo.lang).then(function () { return finish(geo.lang, 'ip', geo.cc); });
    }

    // 让服务端判定：它知道配置、Accept-Language，也能给出建议
    return getJSON('api/i18n').then(function (res) {
      var d = (res && res.data) || {};
      meta.langs = d.langs || [];
      var code = norm(d.lang) || 'en';
      return loadDict(code).then(function () { return finish(code, d.source || 'default', d.country || ''); });
    }).catch(function () {
      // 未授权 / 离线：用浏览器语言兜底
      return loadDict(norm(navigator.language) || 'en')
        .then(function () { return finish(norm(navigator.language) || 'en', 'browser', ''); });
    });
  }

  function finish(code, source, country) {
    cur = code;
    curDict = dicts[code] || {};
    meta.source = source;
    meta.country = country || '';
    meta.auto = source !== 'user';
    return code;
  }

  /** 首屏之后按 IP 再判一次。只有当用户没选过、浏览器语言也不匹配时才有意义。 */
  function refineByIP() {
    if (explicitLang()) return Promise.resolve(cur);
    if (cachedGeo()) return Promise.resolve(cur);
    if (onceReloaded()) return Promise.resolve(cur);
    return getJSON('api/geo').then(function (res) {
      var g = (res && res.data) || {};
      if (!g.ok || !g.suggest) return cur;
      var code = norm(g.suggest);
      if (!code || code === cur) {
        saveGeo(g.country_code || '', code || cur);
        return cur;
      }
      saveGeo(g.country_code || '', code);
      location.reload();
      return code;
    }).catch(function () { return cur; });
  }

  /* ---------------- 对外 ---------------- */

  JZ.i18n = {
    get lang() { return cur; },
    get locale() {
      return { 'zh-CN': 'zh-CN', 'zh-TW': 'zh-TW', en: 'en-US', ja: 'ja-JP',
        ko: 'ko-KR', de: 'de-DE', fr: 'fr-FR', es: 'es-ES', 'pt-BR': 'pt-BR',
        ru: 'ru-RU' }[cur] || 'en-US';
    },
    get meta() { return meta; },
    get dict() { return curDict || {}; },
    supported: SUPPORTED,
    norm: norm,
    load: loadDict,
    init: init,
    refineByIP: refineByIP,
    apply: apply,
    setLang: setLang,
    useAuto: useAuto,
    /** 供设置页显示"当前是自动判断来的" */
    describe: function () {
      if (meta.source === 'user') return t('手动选择');
      if (meta.source === 'browser') return t('跟随系统和浏览器语言');
      if (meta.source === 'ip') return t('按 IP 归属地自动选择');
      return t('默认语言');
    },
    /** 语言自己的写法，列表里永远显示母语，别让日文用户看英文名 */
    label: function (code) {
      var m = (meta.langs || []).filter(function (x) { return x.code === code; })[0];
      if (m) return m.native;
      var fallback = { 'zh-CN': '简体中文', 'zh-TW': '繁體中文', en: 'English',
        ja: '日本語', ko: '한국어', de: 'Deutsch', fr: 'Français',
        es: 'Español', 'pt-BR': 'Português', ru: 'Русский' };
      return fallback[code] || code;
    },
  };

  // 页面一加载就先把静态 HTML 里的中文挡住？做不到（还没字典）。
  // 所以启动画面本来就该极短，且 boot 文案在 init 之后立刻 apply。
})();
