const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf8');
const blocks = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const js = blocks.sort((a, b) => b.length - a.length)[0];

function makeEl(id) {
  return {
    id, style: {}, textContent: '', innerHTML: '', value: '', className: '',
    classList: { add() {}, remove() {}, contains() { return false; } },
    addEventListener() {}, appendChild() {}, removeChild() {}, click() {},
    querySelector() { return makeEl('sub'); }, querySelectorAll() { return []; },
    dataset: {}, files: []
  };
}
const elCache = {};
global.document = {
  getElementById(id) { return elCache[id] || (elCache[id] = makeEl(id)); },
  querySelector(s) { const id = String(s).replace(/^#/, ''); return elCache[id] || (elCache[id] = makeEl(id)); },
  querySelectorAll() { return []; }, addEventListener() {},
  createElement() { return makeEl('new'); },
  body: { appendChild() {}, removeChild() {} }, hidden: false
};
global.window = { addEventListener() {}, scrollTo() {} };
global.location = { pathname: '/repo/' };
const store = {};
global.localStorage = {
  getItem(k) { return k in store ? store[k] : null; },
  setItem(k, v) { store[k] = String(v); },
  removeItem(k) { delete store[k]; }
};
global.fetch = () => Promise.reject(new Error('NO_NETWORK'));
global.setInterval = () => 0;
global.setTimeout = () => 0;
global.clearInterval = () => {};

const probe = `
;globalThis.__probe = {
  isConfigured: isConfigured, openGate: openGate,
  setCfg: function(u,k){ CFG.url=u; CFG.key=k; },
  writeSession: writeSession, loadConfig: loadConfig, loadAll: loadAll,
  toDbRow: toDbRow, getCats: function(){ return CATS; },
  getMoods: function(){ return MOODS; }, SEED: SEED
};`;

new Function(js + probe)();
const P = globalThis.__probe;

console.log('--- 场景 1：内置配置、免填写首屏 ---');
console.log('isConfigured:', P.isConfigured(), '| gate:', elCache['auth-gate'].style.display,
  '| config:', elCache['gate-config'].style.display,
  '| form:', elCache['gate-form'].style.display,
  '| sync:', elCache['sync-text'].textContent);
if (P.isConfigured() !== true) throw new Error('内置配置未生效');
if (elCache['auth-gate'].style.display !== 'flex') throw new Error('未登录时应显示登录遮罩');
if (elCache['gate-config'].style.display !== 'none') throw new Error('不应再弹配置引导');
if (elCache['gate-form'].style.display !== 'block') throw new Error('应直接显示登录/注册表单');
P.openGate('config');
if (elCache['gate-config'].style.display !== 'block') throw new Error('手动更改配置入口失效');
if (String(elCache['cfg-url'].value).indexOf('sxailwwjfgcvyqsrzioq') < 0) throw new Error('配置框未预填内置 URL');
if (String(elCache['cfg-key'].value).indexOf('sb_publishable_') !== 0) throw new Error('配置框未预填内置 key');
P.openGate('login');
console.log('内置 URL 已预填，可手动覆盖：PASS');

console.log('--- 场景 2：配置齐全后读写云端 ---');
P.setCfg('https://demo.supabase.co', 'sb_publishable_test');
P.writeSession({
  access_token: 'tok', refresh_token: 'ref',
  expires_at: Date.now() + 3600000,
  user_id: '11111111-1111-1111-1111-111111111111', email: 'a@b.c'
});
const seedRows = P.SEED.map(s => ({
  user_id: 'u', no: s.no, title: s.title, category: s.category, status: s.status,
  done_date: s.done_date, mood: s.mood, note: s.note, photos: []
}));
let authChecked = 0;
global.fetch = (url, opts) => {
  if (!opts.headers || !opts.headers.apikey) throw new Error('缺少 apikey 头');
  if (String(url).indexOf('/rest/') >= 0) {
    if (opts.headers.Authorization !== 'Bearer tok') throw new Error('缺少 Bearer 头');
    authChecked++;
  }
  const body = String(url).indexOf('/love_config') >= 0
    ? [{ cats: ['甲', '乙'], moods: ['喜', '怒'] }]
    : String(url).indexOf('/love_items') >= 0 ? seedRows : null;
  return Promise.resolve({
    ok: true, status: 200,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body))
  });
};

(async () => {
  await P.loadConfig();
  const rows = await P.loadAll();
  console.log('REST 鉴权头校验次数:', authChecked);
  console.log('分类动态覆盖:', P.getCats(), '| 心情动态覆盖:', P.getMoods());
  console.log('读回行数:', rows.length, '| 首行:', rows[0]['编号'], rows[0]['小事'], rows[0]['状态']);
  const back = P.toDbRow(rows[4], 5);
  console.log('往返映射:', back.no, back.title, back.status, '| 照片字段:', JSON.stringify(back.photos));
  if (rows.length !== 100) throw new Error('行数不对');
  if (authChecked < 2) throw new Error('REST 鉴权头未生效');
  if (P.getCats().length !== 2 || P.getMoods().length !== 2) throw new Error('选项未从云端覆盖');
  if (back.no !== 5 || !back.title) throw new Error('字段映射错误');
  console.log('SMOKE: PASS');
})().catch(e => { console.error('SMOKE: FAIL', e); process.exit(1); });
