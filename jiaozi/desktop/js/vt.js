/* VT 屏幕缓冲 + 解析器（独立模块，便于单测）
   支持：SGR 颜色/256色/真彩、光标移动、清屏清行、插入删除行列、滚动、制表、折行
   不支持：滚动区域(CSI r)、鼠标上报、字符集切换 —— 这些对 bash/日志/脚本足够，全屏 TUI 有局限
*/
(function () {
  'use strict';
  const JZ = window.JZ = window.JZ || {};

  const PALETTE = [
    '#3b4252', '#e05561', '#3fb950', '#d9a441', '#4d8cf5', '#b57ce0', '#33b8c8', '#c9d4e3',
    '#5c6a7e', '#ff6b6b', '#56d364', '#f2cc60', '#74a8ff', '#d2a8ff', '#56d4dd', '#ffffff',
  ];
  const DEF_FG = '#cdd6e4';

  function blank() { return { c: ' ', fg: null, bg: null, b: 0, u: 0, i: 0, inv: 0 }; }

  //: 东亚宽字符 / 常用 emoji 占两格 —— 中文文件名不会把整行挤歪
  function isWide(ch) {
    const code = ch.codePointAt(0);
    if (code < 0x1100) return false;
    return (
      code <= 0x115f ||
      code === 0x2329 || code === 0x232a ||
      (code >= 0x2e80 && code <= 0xa4cf) ||
      (code >= 0xac00 && code <= 0xd7a3) ||
      (code >= 0xf900 && code <= 0xfaff) ||
      (code >= 0xfe30 && code <= 0xfe6f) ||
      (code >= 0xff00 && code <= 0xff60) ||
      (code >= 0xffe0 && code <= 0xffe6) ||
      (code >= 0x1f300 && code <= 0x1f64f) ||
      (code >= 0x1f900 && code <= 0x1f9ff) ||
      (code >= 0x20000 && code <= 0x3fffd)
    );
  }

  function x256(n) {
    n = n | 0;
    if (n < 16) return PALETTE[n];
    if (n < 232) {
      n -= 16;
      const r = Math.floor(n / 36), g = Math.floor((n % 36) / 6), b = n % 6;
      const f = (v) => (v === 0 ? 0 : 55 + v * 40);
      return 'rgb(' + f(r) + ',' + f(g) + ',' + f(b) + ')';
    }
    const v = 8 + (n - 232) * 10;
    return 'rgb(' + v + ',' + v + ',' + v + ')';
  }

  function Screen(cols, rows) {
    this.cols = cols; this.rows = rows;
    this.grid = [];
    for (let r = 0; r < rows; r++) {
      const row = [];
      for (let c = 0; c < cols; c++) row.push(blank());
      this.grid.push(row);
    }
    this.x = 0; this.y = 0;
    this.fg = null; this.bg = null;
    this.b = 0; this.u = 0; this.i = 0; this.inv = 0;
    this.wrap = false;
    this.top = 0; this.bottom = rows - 1;
    this.onScrollOut = null;
  }

  Screen.prototype.resize = function (cols, rows) {
    const n = [];
    for (let r = 0; r < rows; r++) {
      const row = this.grid[r] || [];
      const nr = [];
      for (let c = 0; c < cols; c++) nr.push(row[c] || blank());
      n.push(nr);
    }
    this.grid = n; this.cols = cols; this.rows = rows;
    if (this.x >= cols) this.x = cols - 1;
    if (this.y >= rows) this.y = rows - 1;
    this.bottom = rows - 1;
  };

  Screen.prototype.scrollUp = function () {
    if (this.onScrollOut) this.onScrollOut(this.grid[0]);
    this.grid.shift();
    this.grid.push(Array.from({ length: this.cols }, blank));
  };

  Screen.prototype.newline = function () {
    this.wrap = false;
    if (this.y >= this.bottom) this.scrollUp();
    else this.y++;
  };

  Screen.prototype.put = function (ch) {
    const w = isWide(ch) ? 2 : 1;
    if (this.wrap || this.x + w > this.cols) { this.x = 0; this.newline(); }
    const style = { fg: this.fg, bg: this.bg, b: this.b, u: this.u, i: this.i, inv: this.inv };
    const cell = this.grid[this.y][this.x];
    Object.assign(cell, style, { c: ch });
    if (w === 2) {
      Object.assign(this.grid[this.y][this.x + 1], style, { c: '' });  // 占位，不输出字符
    }
    this.x += w;
    if (this.x >= this.cols) { this.x = this.cols - 1; this.wrap = true; }
  };

  Screen.prototype.eraseLine = function (mode) {
    const row = this.grid[this.y];
    let from, to;
    if (mode === 1) { from = 0; to = this.x; }
    else if (mode === 2) { from = 0; to = this.cols - 1; }
    else { from = this.x; to = this.cols - 1; }
    for (let c = from; c <= to && c < this.cols; c++) row[c] = Object.assign(blank(), { bg: this.bg });
  };

  Screen.prototype.eraseScreen = function (mode) {
    if (mode === 2 || mode === 3) {
      for (let r = 0; r < this.rows; r++) for (let c = 0; c < this.cols; c++) this.grid[r][c] = blank();
    } else if (mode === 1) {
      for (let r = 0; r < this.y; r++) for (let c = 0; c < this.cols; c++) this.grid[r][c] = blank();
      this.eraseLine(1);
    } else {
      this.eraseLine(0);
      for (let r = this.y + 1; r < this.rows; r++) for (let c = 0; c < this.cols; c++) this.grid[r][c] = blank();
    }
  };

  Screen.prototype.sgr = function (ps) {
    if (!ps.length) ps = [0];
    for (let i = 0; i < ps.length; i++) {
      const p = ps[i] | 0;
      if (p === 0) { this.fg = null; this.bg = null; this.b = 0; this.u = 0; this.i = 0; this.inv = 0; }
      else if (p === 1) this.b = 1;
      else if (p === 2) this.b = 0;
      else if (p === 3) this.i = 1;
      else if (p === 4) this.u = 1;
      else if (p === 7) this.inv = 1;
      else if (p === 22) this.b = 0;
      else if (p === 23) this.i = 0;
      else if (p === 24) this.u = 0;
      else if (p === 27) this.inv = 0;
      else if (p >= 30 && p <= 37) this.fg = PALETTE[p - 30];
      else if (p === 39) this.fg = null;
      else if (p >= 40 && p <= 47) this.bg = PALETTE[p - 40];
      else if (p === 49) this.bg = null;
      else if (p >= 90 && p <= 97) this.fg = PALETTE[p - 90 + 8];
      else if (p >= 100 && p <= 107) this.bg = PALETTE[p - 100 + 8];
      else if (p === 38 || p === 48) {
        const target = p === 38 ? 'fg' : 'bg';
        if (ps[i + 1] === 5 && ps[i + 2] !== undefined) { this[target] = x256(ps[i + 2]); i += 2; }
        else if (ps[i + 1] === 2 && ps[i + 4] !== undefined) {
          this[target] = 'rgb(' + ps[i + 2] + ',' + ps[i + 3] + ',' + ps[i + 4] + ')'; i += 4;
        }
      }
    }
  };

  /* -------- 解析器 -------- */
  function Parser(screen) {
    this.s = screen;
    this.state = 0; // 0 ground, 1 esc, 2 csi, 3 osc, 4 charset, 5 osc-esc
    this.params = '';
  }

  Parser.prototype.feed = function (text) {
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      const code = text.charCodeAt(i);
      switch (this.state) {
        case 0:
          if (ch === '\x1b') { this.state = 1; }
          else if (ch === '\r') { this.s.x = 0; this.s.wrap = false; }
          else if (ch === '\n') { this.s.x = 0; this.s.newline(); }  // 管道输出只有 LF，按 CRLF 处理
          else if (ch === '\b') { if (this.s.x > 0) this.s.x--; this.s.wrap = false; }
          else if (ch === '\t') { this.s.x = Math.min(this.s.cols - 1, (Math.floor(this.s.x / 8) + 1) * 8); }
          else if (code === 7) { /* bell */ }
          else if (code < 32) { /* 其它控制符 */ }
          else this.s.put(ch);
          break;
        case 1:
          if (ch === '[') { this.state = 2; this.params = ''; }
          else if (ch === ']') { this.state = 3; }
          else if (ch === '(' || ch === ')') { this.state = 4; }
          else { this.state = 0; }
          break;
        case 2:
          if (code >= 0x40 && code <= 0x7e) {
            this.csi(ch, this.params);
            this.state = 0;
          } else {
            this.params += ch;
            if (this.params.length > 64) this.state = 0;
          }
          break;
        case 3:
          if (code === 7) this.state = 0;
          else if (ch === '\x1b') this.state = 5;
          break;
        case 5:
          this.state = 0;
          break;
        case 4:
          this.state = 0;
          break;
      }
    }
  };

  Parser.prototype.csi = function (final, raw) {
    const s = this.s;
    const priv = raw[0] === '?';
    const body = priv ? raw.slice(1) : raw;
    const ps = body === '' ? [] : body.split(';').map(function (v) {
      const n = parseInt(v.replace(/[^\d]/g, ''), 10);
      return isNaN(n) ? 0 : n;
    });
    const n = ps[0] || 1;
    switch (final) {
      case 'm': s.sgr(ps); break;
      case 'A': s.y = Math.max(0, s.y - n); s.wrap = false; break;
      case 'B': s.y = Math.min(s.rows - 1, s.y + n); s.wrap = false; break;
      case 'C': s.x = Math.min(s.cols - 1, s.x + n); s.wrap = false; break;
      case 'D': s.x = Math.max(0, s.x - n); s.wrap = false; break;
      case 'E': s.y = Math.min(s.rows - 1, s.y + n); s.x = 0; s.wrap = false; break;
      case 'F': s.y = Math.max(0, s.y - n); s.x = 0; s.wrap = false; break;
      case 'G': s.x = Math.max(0, Math.min(s.cols - 1, n - 1)); break;
      case 'd': s.y = Math.max(0, Math.min(s.rows - 1, n - 1)); break;
      case 'H': case 'f':
        s.y = Math.max(0, Math.min(s.rows - 1, (ps[0] || 1) - 1));
        s.x = Math.max(0, Math.min(s.cols - 1, (ps[1] || 1) - 1));
        s.wrap = false;
        break;
      case 'J': s.eraseScreen(ps[0] || 0); break;
      case 'K': s.eraseLine(ps[0] || 0); break;
      case 'L':
        for (let k = 0; k < n; k++) {
          s.grid.splice(s.y, 0, Array.from({ length: s.cols }, blank));
          if (s.grid.length > s.rows) s.grid.pop();
        }
        break;
      case 'M':
        for (let k = 0; k < n; k++) {
          s.grid.splice(s.y, 1);
          s.grid.push(Array.from({ length: s.cols }, blank));
        }
        break;
      case 'P':
        s.grid[s.y].splice(s.x, n);
        while (s.grid[s.y].length < s.cols) s.grid[s.y].push(blank());
        break;
      case '@':
        for (let k = 0; k < n; k++) s.grid[s.y].splice(s.x, 0, blank());
        s.grid[s.y].length = s.cols;
        break;
      case 'S': for (let k = 0; k < n; k++) s.scrollUp(); break;
      default: break;
    }
  };

  /* -------- 渲染 -------- */
  function wrapSpan(text, key) {
    const safe = text.replace(/[&<>]/g, function (c) {
      return c === '&' ? '&amp;' : c === '<' ? '&lt;' : '&gt;';
    });
    if (!key) return safe;
    const p = key.split('|');
    let style = '';
    if (p[0]) style += 'color:' + p[0] + ';';
    if (p[1]) style += 'background:' + p[1] + ';';
    if (p[2] === '1') style += 'font-weight:600;';
    if (p[3] === '1') style += 'text-decoration:underline;';
    if (p[4] === '1') style += 'font-style:italic;';
    return style ? '<span style="' + style + '">' + safe + '</span>' : safe;
  }

  function renderRow(cells) {
    let last = -1;
    for (let i = cells.length - 1; i >= 0; i--) {
      if (cells[i].c !== ' ' || cells[i].bg) { last = i; break; }
    }
    let out = '', run = '', st = null;
    for (let i = 0; i <= last; i++) {
      const cell = cells[i];
      const bg = cell.inv ? (cell.fg || DEF_FG) : cell.bg;
      const fg = cell.inv ? (cell.bg || '#0c1119') : cell.fg;
      const key = fg + '|' + bg + '|' + cell.b + '|' + cell.u + '|' + cell.i;
      if (key !== st) {
        if (run) out += wrapSpan(run, st);
        run = ''; st = key;
      }
      run += cell.c;
    }
    if (run) out += wrapSpan(run, st);
    return out;
  }

  JZ.VT = { Screen, Parser, renderRow, PALETTE, DEF_FG, x256 };
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = JZ.VT;
  }
})();
