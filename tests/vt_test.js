/* VT 解析器单元测试：node tests/vt_test.js */
'use strict';
global.window = {};
const VT = require('../jiaozi/desktop/js/vt.js');

let pass = 0, fail = 0;
function eq(name, actual, expected) {
  const a = JSON.stringify(actual), b = JSON.stringify(expected);
  if (a === b) { pass++; console.log('  ✓ ' + name); }
  else { fail++; console.log('  ✗ ' + name + '\n      期望 ' + b + '\n      实际 ' + a); }
}
function ok(name, cond, detail) {
  if (cond) { pass++; console.log('  ✓ ' + name); }
  else { fail++; console.log('  ✗ ' + name + '  ' + (detail || '')); }
}
function line(s, r) { return s.grid[r].map(c => c.c).join('').replace(/\s+$/, ''); }

console.log('[VT] 基础写入');
{
  const s = new VT.Screen(10, 3);
  const p = new VT.Parser(s);
  p.feed('hello');
  eq('普通文本写入', line(s, 0), 'hello');
  eq('光标位置', [s.x, s.y], [5, 0]);
  p.feed('\r\nworld');
  eq('回车换行', line(s, 1), 'world');
}

console.log('[VT] 自动折行与滚动');
{
  const s = new VT.Screen(5, 3);
  const p = new VT.Parser(s);
  p.feed('abcdefgh');
  eq('第一行折满', line(s, 0), 'abcde');
  eq('第二行续写', line(s, 1), 'fgh');
}
{
  const s = new VT.Screen(6, 2);
  const p = new VT.Parser(s);
  const out = [];
  s.onScrollOut = row => out.push(row.map(c => c.c).join('').trim());
  p.feed('1\r\n2\r\n3');
  eq('滚动丢出顶部行', out, ['1']);
  eq('滚动后第一行', line(s, 0), '2');
  eq('滚动后第二行', line(s, 1), '3');
}

console.log('[VT] SGR 颜色');
{
  const s = new VT.Screen(20, 2);
  const p = new VT.Parser(s);
  p.feed('\x1b[31mred\x1b[0m plain');
  eq('前景色 31', s.grid[0][0].fg, VT.PALETTE[1]);
  eq('重置后默认色', s.grid[0][4].fg, null);
  const html = VT.renderRow(s.grid[0]);
  ok('渲染出 color 样式', /color:#e05561/.test(html), html);
  ok('渲染内容正确', /red/.test(html) && /plain/.test(html));
}
{
  const s = new VT.Screen(20, 1);
  const p = new VT.Parser(s);
  p.feed('\x1b[1;38;5;208mX\x1b[0m');
  ok('256 色解析', /rgb\(255,135,0\)/.test(String(s.grid[0][0].fg)), s.grid[0][0].fg);
  eq('粗体标记', s.grid[0][0].b, 1);
}
{
  const s = new VT.Screen(20, 1);
  const p = new VT.Parser(s);
  p.feed('\x1b[38;2;12;34;56mZ');
  eq('真彩色', s.grid[0][0].fg, 'rgb(12,34,56)');
}

console.log('[VT] 光标与清屏');
{
  const s = new VT.Screen(10, 5);
  const p = new VT.Parser(s);
  p.feed('\x1b[2;3HX');
  eq('CSI H 定位', [s.grid[1][2].c, s.y, s.x], ['X', 1, 3]);
  p.feed('\x1b[2K');
  eq('清整行', line(s, 1), '');
  p.feed('\x1b[Habc');
  eq('回到原点', line(s, 0), 'abc');
  p.feed('\x1b[2J');
  eq('清全屏', [line(s, 0), line(s, 1)], ['', '']);
}
{
  const s = new VT.Screen(10, 2);
  const p = new VT.Parser(s);
  p.feed('abcdef\b\bXY');
  eq('退格覆盖', line(s, 0), 'abcdXY');
}

console.log('[VT] 宽字符');
{
  const s = new VT.Screen(10, 2);
  const p = new VT.Parser(s);
  p.feed('中文ab');
  eq('汉字占两格', s.grid[0].slice(0, 6).map(c => c.c), ['中', '', '文', '', 'a', 'b']);
  eq('光标推进正确', s.x, 6);
  ok('渲染时不丢字', /中文/.test(VT.renderRow(s.grid[0])));
}

console.log('[VT] 安全');
{
  const s = new VT.Screen(20, 1);
  const p = new VT.Parser(s);
  p.feed('<script>x</script>');
  const html = VT.renderRow(s.grid[0]);
  ok('HTML 被转义', !/<script>/.test(html) && /&lt;script&gt;/.test(html), html);
}

console.log('\n结果：' + pass + ' 通过，' + fail + ' 失败');
process.exit(fail ? 1 : 0);
