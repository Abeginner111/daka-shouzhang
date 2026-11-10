# -*- coding: utf-8 -*-
"""把资料库版恋爱手账改造成 GitHub Pages + Supabase 版（只替换数据层）。"""
import io, os, json, csv, re

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "tpl", "恋爱四年想做的100件小事.html")
OUT = os.path.join(HERE, "index.html")

lines = io.open(SRC, encoding="utf-8").readlines()

# ---------- 100 条种子数据 ----------
rows = list(csv.DictReader(io.open(os.path.join(HERE, "seed.csv"), encoding="utf-8-sig", newline="")))
seed = []
for r in rows:
    seed.append({
        "no": int(r["编号"]),
        "title": r["小事"].strip(),
        "category": r["分类"].strip(),
        "status": r["状态"].strip(),
        "done_date": r["完成日期"].strip() or None,
        "mood": r["心情"].strip() or None,
        "note": r["一句话记录"].strip(),
        "photos": [],
    })
assert len(seed) == 100, len(seed)
SEED_JSON = json.dumps(seed, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")

cats, moods = [], []
for s in seed:
    if s["category"] not in cats:
        cats.append(s["category"])
SEED_CATS = json.dumps(cats, ensure_ascii=False)
SEED_MOODS = json.dumps(["平静", "期待", "惊喜", "感动", "放松", "疲惫", "迷茫", "想念", "自由", "其他"], ensure_ascii=False)

# ---------- 新数据层（替换原 502-598 行） ----------
DATA_LAYER = r"""
/* ============ 配置 ============
   两种方式：① 直接在页面的「连接配置」里填；② 改下面这两行硬编码。
   值来自 Supabase → Project Settings → API：Project URL + publishable key（旧版叫 anon key）。
   绝不要用 service_role / secret key，那会绕过行级权限。
   页面里填的值存本机 localStorage，不写回仓库；源码里硬编码的值会随公开仓库公开。
*/
var CFG_STORE_KEY = "love100_gh_cfg";
var CFG = (function(){
  try {
    var c = JSON.parse(localStorage.getItem(CFG_STORE_KEY) || "null");
    if(c && c.url && c.key) return { url: c.url, key: c.key };
  } catch(e){}
  return { url: "https://YOUR_PROJECT.supabase.co", key: "YOUR_PUBLISHABLE_OR_ANON_KEY" };
})();
var TABLE = "love_items";
var CFG_TABLE = "love_config";

var CATS = ["初见心动", "日常甜度", "两个人的饭", "给彼此留白", "周末出走", "一起热爱", "勇敢一点", "一起看世界", "留下痕迹", "关于以后"];
var MOODS = ["平静", "期待", "惊喜", "感动", "放松", "疲惫", "迷茫", "想念", "自由", "其他"];
var ITEMS = [];         // {id, name, cat, _id}
var records = {};       // _id → 页面内部扁平行
var STATUS_TEXT = {todo:"想去做", wait:"等待发生", done:"已经珍藏", later:"留给以后"};
var REV_STATUS = {"想去做":"todo", "等待发生":"wait", "已经珍藏":"done", "留给以后":"later"};
var CHAPTERS = [
  {lv:1,name:"第一章 · 心动",say:"故事刚开始，连风都是甜的。",min:0},
  {lv:2,name:"第二章 · 靠近",say:"你们开始把彼此放进日常里。",min:20},
  {lv:3,name:"第三章 · 并肩",say:"日子有了两个人的节奏。",min:40},
  {lv:4,name:"第四章 · 远行",say:"一起看过的地方，比想象中更远。",min:60},
  {lv:5,name:"第五章 · 珍藏",say:"四年攒下的小事，都好好地放在这里。",min:80},
  {lv:6,name:"终章 · 慢慢来",say:"一百件写完了，我们还在一起写。",min:100}
];
var SEED = @@SEED@@;
var SEED_CATS = @@SEED_CATS@@;
var SEED_MOODS = @@SEED_MOODS@@;

var SESS_KEY = "love100_gh_session";
var QUEUE_KEY = "love100_gh_queue";
var CACHE_KEY = "love100_gh_cache";
var session = null;
var pollTimer = null;
var pollStarted = false;

function isConfigured(){
  return !!(CFG.url && CFG.url.indexOf("YOUR_PROJECT") === -1 && CFG.key && CFG.key.indexOf("YOUR_") === -1);
}
function readSession(){ try { return JSON.parse(localStorage.getItem(SESS_KEY)) || null; } catch(e){ return null; } }
function writeSession(s){
  session = s;
  try { if(s) localStorage.setItem(SESS_KEY, JSON.stringify(s)); else localStorage.removeItem(SESS_KEY); } catch(e){}
}
function readQueue(){ try { return JSON.parse(localStorage.getItem(QUEUE_KEY)) || []; } catch(e){ return []; } }
function writeQueue(q){ try { localStorage.setItem(QUEUE_KEY, JSON.stringify(q)); } catch(e){} }
function saveAuth(r, email){
  writeSession({
    access_token: r.access_token,
    refresh_token: r.refresh_token || "",
    expires_at: Date.now() + (r.expires_in || 3600) * 1000,
    user_id: (r.user && r.user.id) || null,
    email: email
  });
}

/* ---------- 认证（GoTrue REST，纯 fetch，不引 SDK） ---------- */
function authPost(path, payload){
  return fetch(CFG.url + path, {
    method: "POST",
    headers: {"Content-Type": "application/json", "apikey": CFG.key},
    body: JSON.stringify(payload)
  }).then(function(res){
    return res.text().then(function(txt){
      var r = {};
      try { r = txt ? JSON.parse(txt) : {}; } catch(e){ r = {}; }
      if(!res.ok) throw new Error(r.msg || r.error_description || r.message || ("HTTP " + res.status));
      return r;
    });
  });
}
function signIn(email, password){
  return authPost("/auth/v1/token?grant_type=password", {email: email, password: password})
    .then(function(r){ saveAuth(r, email); return r; });
}
function signUp(email, password){
  return authPost("/auth/v1/signup", {email: email, password: password})
    .then(function(r){
      if(r.access_token){ saveAuth(r, email); return true; }
      return false;   // 需要再登录一次（如邮箱确认已关闭但 signup 不返回 token）
    });
}
function refreshSession(){
  if(!session || !session.refresh_token) return Promise.reject(new Error("NO_REFRESH"));
  return authPost("/auth/v1/token?grant_type=refresh_token", {refresh_token: session.refresh_token})
    .then(function(r){ saveAuth(r, session.email); return session; });
}
function ensureToken(){
  if(!session || !session.access_token) return Promise.reject(new Error("NO_SESSION"));
  if(!session.expires_at || Date.now() < session.expires_at - 60000) return Promise.resolve(session);
  return refreshSession();
}
function friendlyAuthError(e){
  var m = String(e && e.message || e);
  if(/Invalid login|invalid_grant|Invalid credentials/i.test(m)) return "邮箱或密码不对";
  if(/Email not confirmed|confirm your email/i.test(m)) return "需要先到 Supabase → Authentication → Providers → Email 关闭 Confirm email";
  if(/weak password|password.*short/i.test(m)) return "密码太短，至少 6 位";
  if(/User already registered|already exists/i.test(m)) return "这个邮箱已注册，请直接登录";
  if(/NO_REFRESH|refresh/i.test(m)) return "登录已过期，请重新登录";
  if(/Failed to fetch|NetworkError|Load failed/i.test(m)) return "连不上 Supabase，检查项目 URL / 网络 / 项目是否被暂停";
  return m.slice(0, 120);
}

/* ---------- PostgREST ---------- */
function apiFetch(path, opts){
  opts = opts || {};
  var h = {"apikey": CFG.key, "Accept": "application/json"};
  var extra = opts.headers || {};
  for(var k in extra){ if(Object.prototype.hasOwnProperty.call(extra, k)) h[k] = extra[k]; }
  if(session && session.access_token) h["Authorization"] = "Bearer " + session.access_token;
  return fetch(CFG.url + path, {
    method: opts.method || "GET",
    headers: h,
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body)
  }).then(function(res){
    if(!res.ok) return res.text().then(function(t){ throw new Error("HTTP " + res.status + " " + String(t).slice(0, 160)); });
    if(res.status === 204 || res.status === 205) return null;
    return res.json().catch(function(){ return null; });
  });
}
function uid(){ return encodeURIComponent(session.user_id || ""); }

/* 数据库行 → 页面内部扁平行（保持原 UI 数据模型不变） */
function fromRow(row){
  return {
    _id: String(row.no),
    "编号": row.no,
    "小事": row.title || "",
    "分类": row.category || "",
    "状态": row.status || "想去做",
    "完成日期": row.done_date || null,
    "心情": row.mood || "",
    "一句话记录": row.note || "",
    "照片": Array.isArray(row.photos) ? row.photos : []
  };
}
function toDbRow(r, no){
  return {
    user_id: session.user_id,
    no: no,
    title: r["小事"] || "",
    category: r["分类"] || "",
    status: r["状态"] || "想去做",
    done_date: r["完成日期"] || null,
    mood: r["心情"] || null,
    note: r["一句话记录"] || "",
    photos: Array.isArray(r["照片"]) ? r["照片"] : [],
    updated_at: new Date().toISOString()
  };
}
function loadConfig(){
  return ensureToken().then(function(){
    return apiFetch("/rest/v1/" + CFG_TABLE + "?select=cats,moods&user_id=eq." + uid());
  }).then(function(rows){
    if(rows && rows[0]){
      if(rows[0].cats && rows[0].cats.length) CATS = rows[0].cats.slice();
      if(rows[0].moods && rows[0].moods.length) MOODS = rows[0].moods.slice();
    }
  });
}
function loadAll(){
  return ensureToken().then(function(){
    return apiFetch("/rest/v1/" + TABLE + "?select=*&user_id=eq." + uid() + "&order=no.asc");
  }).then(function(rows){ return (rows || []).map(fromRow); });
}
function upsertRows(dbRows){
  return ensureToken().then(function(){
    return apiFetch("/rest/v1/" + TABLE + "?on_conflict=user_id,no", {
      method: "POST",
      headers: {"Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"},
      body: dbRows
    });
  });
}
function patchRow(p){
  return ensureToken().then(function(){
    return apiFetch("/rest/v1/" + TABLE + "?user_id=eq." + uid() + "&no=eq." + p.no, {
      method: "PATCH",
      headers: {"Content-Type": "application/json", "Prefer": "return=minimal"},
      body: p.body
    });
  });
}
function seedAll(){
  setSync("busy", "初始化清单");
  var dbRows = SEED.map(function(s){
    return {
      user_id: session.user_id, no: s.no, title: s.title, category: s.category,
      status: s.status, done_date: s.done_date || null, mood: s.mood || null,
      note: s.note || "", photos: [], updated_at: new Date().toISOString()
    };
  });
  return upsertRows(dbRows).then(function(){
    return ensureToken().then(function(){
      return apiFetch("/rest/v1/" + CFG_TABLE + "?on_conflict=user_id", {
        method: "POST",
        headers: {"Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"},
        body: [{user_id: session.user_id, cats: SEED_CATS, moods: SEED_MOODS}]
      });
    });
  });
}
function initData(){
  setSync("busy", "同步中");
  return loadConfig().then(function(){ return loadAll(); }).then(function(rows){
    if(!rows.length) return seedAll().then(loadAll);
    return rows;
  }).then(function(rows){
    applyRows(rows);
    saveCache(rows);
    setSync("ok", "已同步");
  }).catch(function(err){ setSync("off", "离线模式"); throw err; });
}
function applyRows(rows){
  rows.sort(function(a,b){ return (a["编号"] || 0) - (b["编号"] || 0); });
  records = {};
  ITEMS = rows.map(function(row){
    records[row._id] = row;
    return { id: row["编号"], name: row["小事"] || "", cat: row["分类"] || "", _id: row._id };
  });
  buildCatFilter();
  renderList();
}

/* ---------- 离线队列 + 准实时同步 ---------- */
function enqueue(p){
  var q = readQueue(); q.push(p); writeQueue(q);
  setSync("off", "待同步 " + q.length + " 条");
}
function flushQueue(){
  var q = readQueue();
  if(!q.length || !session) return Promise.resolve();
  var chain = Promise.resolve();
  q.forEach(function(p){
    chain = chain.then(function(){ return patchRow(p); });
  });
  return chain.then(function(){ writeQueue([]); })
    .catch(function(){ /* 网络还没恢复，队列保留，下次重试 */ });
}
function startPolling(){
  if(pollStarted) return;
  pollStarted = true;
  pollTimer = setInterval(syncNow, 15000);
  document.addEventListener("visibilitychange", function(){ if(!document.hidden) syncNow(); });
  window.addEventListener("online", syncNow);
}
function syncNow(){
  if(!isConfigured() || !session) return Promise.resolve();
  if(typeof editingId !== "undefined" && editingId !== null) return Promise.resolve();  // 正在编辑，避免打断
  return flushQueue().then(initData).catch(function(){
    var n = readQueue().length;
    setSync("off", n ? ("离线 · 待同步 " + n + " 条") : "离线模式");
  });
}

/* ---------- 登录遮罩 ---------- */
function openGate(mode){
  if(mode === "switch" && !session) mode = "login";
  var g = document.getElementById("auth-gate");
  if(!g) return;
  g.style.display = "flex";
  var isCfg = (mode === "config");
  document.getElementById("gate-config").style.display = isCfg ? "block" : "none";
  document.getElementById("gate-form").style.display = isCfg ? "none" : "block";
  document.getElementById("gate-logout").style.display = (mode === "switch") ? "block" : "none";
  document.getElementById("gate-title").textContent = isCfg ? "还差一步配置" : (mode === "switch" ? "账号" : "登录以同步手账");
  document.getElementById("gate-desc").textContent = isCfg
    ? "把下面两项填上，就能连到你自己的云端项目。"
    : (mode === "switch" ? ("当前账号：" + ((session && session.email) || "未知")) : "数据存在你自己的云端项目里，登录后多设备自动同步。");
  document.getElementById("gate-error").textContent = "";
  document.getElementById("cfg-error").textContent = "";
  document.getElementById("gate-reconfig").style.display = (mode === "switch") ? "block" : "none";
  if(isCfg){
    document.getElementById("cfg-url").value = CFG.url.indexOf("YOUR_PROJECT") === -1 ? CFG.url : "";
    document.getElementById("cfg-key").value = CFG.key.indexOf("YOUR_") === -1 ? CFG.key : "";
  }
}
function saveCfgFromGate(){
  var u = document.getElementById("cfg-url").value.trim().replace(/\/+$/, "");
  var k = document.getElementById("cfg-key").value.trim();
  var err = document.getElementById("cfg-error");
  err.textContent = "";
  if(!/^https:\/\/[a-z0-9-]+\.supabase\.co$/i.test(u)){ err.textContent = "Project URL 形如 https://xxxx.supabase.co"; return; }
  if(!k || k.indexOf("YOUR_") === 0){ err.textContent = "请填 publishable key（旧版叫 anon key）"; return; }
  if(/^sb_secret_/i.test(k) || /service_role/i.test(k)){ err.textContent = "这是服务端密钥，会绕过权限控制，请换 publishable / anon key"; return; }
  CFG.url = u; CFG.key = k;
  try { localStorage.setItem(CFG_STORE_KEY, JSON.stringify({url: u, key: k})); } catch(e){}
  if(session) bootSession();
  else { setSync("off", "未登录"); openGate("login"); }
}
function reconfigure(){ openGate("config"); }
function closeGate(){
  var g = document.getElementById("auth-gate");
  if(g) g.style.display = "none";
}
function gateSubmit(kind){
  var email = document.getElementById("gate-email").value.trim();
  var pass = document.getElementById("gate-pass").value;
  var err = document.getElementById("gate-error");
  err.textContent = "";
  if(!email || !pass){ err.textContent = "请填写邮箱和密码"; return; }
  if(!isConfigured()){ err.textContent = "还没填 Supabase 配置"; return; }
  setSync("busy", "连接中");
  var p = (kind === "signup")
    ? signUp(email, pass).then(function(ok){ return ok ? null : signIn(email, pass); })
    : signIn(email, pass);
  p.then(function(){ bootSession(); })
   .catch(function(e){ err.textContent = friendlyAuthError(e); setSync("off", "未登录"); });
}
function logout(){
  writeSession(null);
  openGate("login");
  setSync("off", "未登录");
}

/* ---------- 启动 ---------- */
function bootSession(){
  closeGate();
  setSync("busy", "同步中");
  return ensureToken().then(initData).then(function(){
    startPolling();
    return syncNow();
  }).catch(function(err){
    var cached = loadCache();
    setSync("off", "离线模式");
    if(cached.length){ applyRows(cached); showToast("离线模式 · 显示上次同步的内容"); }
    if(/NO_SESSION|NO_REFRESH|401|JWT|refresh/i.test(String(err && err.message || err))){
      openGate("login");
    } else if(!cached.length){
      document.getElementById("list-body").innerHTML = '<div class="grid"><div class="grid-empty">连接失败：请检查 Supabase 配置、建表 SQL 与网络</div></div>';
    }
  });
}
""".replace("@@SEED@@", SEED_JSON).replace("@@SEED_CATS@@", SEED_CATS).replace("@@SEED_MOODS@@", SEED_MOODS)

# ---------- 照片：不再上传资料库，压缩后直接以 data URL 存进 jsonb ----------
ON_PICK = r"""
function onPickPhotos(e){
  const files = Array.from(e.target.files || []);
  if(!files.length) return;
  cachePendingPhotos(files);
  const room = 9 - tmpPhotos.length;
  if(room <= 0){ showToast("每条记录最多 9 张照片"); e.target.value = ""; return; }
  const picked = files.slice(0, room);
  let remain = picked.length;
  const doneOne = () => { if(--remain === 0) renderModalPhotos(); };
  for(const f of picked){
    shrinkFile(f, (base64, contentType, fileName) => {
      if(base64){
        tmpPhotos.push({ title: fileName, imageUrl: "data:" + contentType + ";base64," + base64 });
      } else {
        showToast("照片处理失败");
      }
      doneOne();
    });
  }
  if(files.length > room) showToast("每条记录最多 9 张，多余的已忽略");
  e.target.value = "";
}
"""

# ---------- 保存：增量 PATCH，失败进离线队列 ----------
SAVE_RECORD = r"""
function saveRecord(){
  const it = ITEMS.find(x=>x.id===editingId);
  if(!it) return;
  const dateVal = $("#m-date").value || "";
  const noteVal = $("#m-note").value.trim();
  const body = {
    status: STATUS_TEXT[tmpStatus],
    done_date: dateVal || null,
    mood: tmpMood || null,
    note: noteVal,
    photos: tmpPhotos.slice(),
    updated_at: new Date().toISOString()
  };
  // 乐观更新本地，界面即时响应
  const row = records[it._id];
  if(row){
    row["状态"] = STATUS_TEXT[tmpStatus];
    row["完成日期"] = dateVal || null;
    row["心情"] = tmpMood || null;
    row["一句话记录"] = noteVal;
    row["照片"] = tmpPhotos.slice();
  }
  clearDraft(it._id);
  clearPhotoCache();
  closeModal();
  renderList();
  setSync("busy", "同步中");
  patchRow({no: it.id, body: body}).then(function(){
    saveCache(ITEMS.map(x=>recOf(x)));
    setSync("ok", "已同步");
    showToast("已保存并同步");
  }).catch(function(){
    enqueue({no: it.id, body: body});
    showToast("网络异常 · 已排队，联网后自动同步");
  });
}
"""

# ---------- 初始化 + 导入备份 ----------
INIT = r"""
/* ============ 初始化 ============ */
(function init(){
  setSync("busy", "连接中");
  $("#list-body").innerHTML = '<div class="grid"><div class="grid-empty">正在加载清单…</div></div>';
  var imp = document.getElementById("import-file");
  if(imp){
    imp.addEventListener("change", function(e){
      var f = e.target.files && e.target.files[0];
      e.target.value = "";
      if(!f) return;
      if(!session){ openGate("login"); showToast("请先登录再导入"); return; }
      var reader = new FileReader();
      reader.onload = function(ev){
        try {
          var data = JSON.parse(String(ev.target.result || ""));
          var src = data.rows || [];
          var dbRows = src.map(function(r){ return toDbRow(r, Number(r["编号"])); })
                          .filter(function(r){ return r.no >= 1 && r.no <= 100; });
          if(!dbRows.length) throw new Error("empty");
          setSync("busy", "恢复中");
          upsertRows(dbRows).then(function(){
            showToast("已恢复 " + dbRows.length + " 条记录");
            return syncNow();
          }).catch(function(){ setSync("off", "恢复失败"); showToast("恢复失败，请检查账号与网络"); });
        } catch(err){ showToast("备份文件格式不对"); }
      };
      reader.readAsText(f);
    });
  }

  if(!isConfigured()){ setSync("off", "待配置"); openGate("config"); return; }

  var cached = loadCache();
  if(cached.length){ applyRows(cached); setSync("busy", "连接中"); }
  session = readSession();
  if(!session){ setSync("off", "未登录"); openGate("login"); return; }
  bootSession();
})();
"""

# ---------- 遮罩层 HTML ----------
GATE_HTML = r"""
<div id="auth-gate" style="position:fixed;inset:0;z-index:9999;background:rgba(250,250,250,.97);display:none;align-items:center;justify-content:center;padding:20px">
  <div style="width:100%;max-width:400px;background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:26px 22px;box-shadow:0 8px 30px rgba(0,0,0,.06)">
    <div id="gate-title" style="font-size:19px;font-weight:600;margin-bottom:8px">登录以同步手账</div>
    <div id="gate-desc" style="font-size:13px;color:var(--ink-soft);line-height:1.7;margin-bottom:18px">数据存在你自己的云端项目里，登录后多设备自动同步。</div>
    <div id="gate-config" style="display:none;font-size:13px;line-height:1.8;color:var(--ink-soft);background:var(--line-soft);border-radius:10px;padding:14px;margin-bottom:16px">
      先按 <b>schema.sql</b> 建表、关闭邮箱确认，再填这两项（来自 Supabase → Project Settings → API）：<br>
      <input id="cfg-url" type="url" placeholder="https://xxxx.supabase.co" style="width:100%;font-size:16px;padding:11px;border:1px solid var(--line);border-radius:10px;margin:10px 0 8px">
      <input id="cfg-key" type="text" placeholder="publishable key（sb_publishable_…）" style="width:100%;font-size:16px;padding:11px;border:1px solid var(--line);border-radius:10px;margin-bottom:8px">
      <div id="cfg-error" style="font-size:13px;color:#a32d2d;min-height:20px"></div>
      <button onclick="saveCfgFromGate()" style="width:100%;min-height:44px;font-size:15px;border:0;border-radius:10px;background:var(--accent);color:#fff;cursor:pointer">保存并连接</button>
      <div style="margin-top:10px"><span style="color:#a32d2d">切勿填 service_role / secret key</span>，那会绕过权限控制。这两个值只存在你本机浏览器里，不会写回仓库。</div>
    </div>
    <div id="gate-form">
      <input id="gate-email" type="email" autocomplete="username" placeholder="邮箱" style="width:100%;font-size:16px;padding:12px;border:1px solid var(--line);border-radius:10px;margin-bottom:10px">
      <input id="gate-pass" type="password" autocomplete="current-password" placeholder="密码（至少 6 位）" style="width:100%;font-size:16px;padding:12px;border:1px solid var(--line);border-radius:10px;margin-bottom:12px">
      <div id="gate-error" style="font-size:13px;color:#a32d2d;min-height:20px;margin-bottom:8px"></div>
      <button onclick="gateSubmit('login')" style="width:100%;min-height:44px;font-size:15px;border:0;border-radius:10px;background:var(--accent);color:#fff;cursor:pointer;margin-bottom:8px">登录</button>
      <button onclick="gateSubmit('signup')" style="width:100%;min-height:44px;font-size:15px;border:1px solid var(--line);border-radius:10px;background:var(--paper);color:var(--ink);cursor:pointer">注册并初始化 100 件小事</button>
    </div>
    <button id="gate-logout" onclick="logout()" style="display:none;width:100%;min-height:44px;font-size:14px;border:1px solid var(--line);border-radius:10px;background:var(--paper);color:var(--ink-soft);cursor:pointer">退出登录</button>
    <button id="gate-reconfig" onclick="reconfigure()" style="display:none;width:100%;min-height:44px;font-size:14px;border:1px solid var(--line);border-radius:10px;background:var(--paper);color:var(--ink-soft);cursor:pointer;margin-top:8px">更改云端连接配置</button>
    <div style="font-size:12px;color:var(--ink-faint);line-height:1.7;margin-top:14px">公开链接 + 匿名可写是两回事：本页必须登录，且行级权限按账号隔离，别人拿到链接也看不到你的记录。</div>
  </div>
</div>

"""

ACCOUNT_BTN = '<button class="backup-btn" id="btn-account" onclick="openGate(\'switch\')" style="margin-left:8px">账号</button>\n'
IMPORT_BTN = ('<button class="backup-btn" id="btn-import" onclick="importBackup()" style="margin-left:8px">导入备份</button>\n'
              '<input type="file" id="import-file" accept="application/json,.json" style="display:none">\n')
IMPORT_FN = r"""
function importBackup(){
  var el = document.getElementById("import-file");
  if(el) el.click();
}
"""

ops = []
def replace_range(start, end, text):
    ops.append((start, end, text if text.endswith("\n") else text + "\n"))

replace_range(2, 2, "<!-- GitHub Pages 版 · 数据存于 Supabase（PostgREST + Auth）· 单文件零外部依赖 -->")
replace_range(5, 5, "")                                   # 去掉资料库注入脚本
replace_range(366, 366, lines[365].rstrip("\n") + "\n" + ACCOUNT_BTN.rstrip("\n"))  # 导航加账号按钮
replace_range(397, 397, lines[396].rstrip("\n") + "\n" + IMPORT_BTN.rstrip("\n"))    # 加导入备份按钮
replace_range(499, 499, GATE_HTML.rstrip("\n") + "\n" + lines[498].rstrip("\n"))    # 登录遮罩
replace_range(502, 598, DATA_LAYER)
replace_range(858, 879, ON_PICK)
replace_range(901, 934, SAVE_RECORD)
replace_range(1040, 1040, "")                              # 去掉旧 CACHE_KEY 定义
replace_range(1079, 1079, IMPORT_FN.rstrip("\n") + "\n" + lines[1078].rstrip("\n"))
replace_range(1080, 1097, INIT)

for s, e, text in sorted(ops, key=lambda x: -x[0]):
    lines[s-1:e] = [text]

out = "".join(lines)

# 清理资料库平台元数据：绑定标记在 GitHub Pages 上无意义，且会泄露旧表 ID
out = re.sub(r'\s+data-page-node-id="[^"]*"', '', out)
out = re.sub(r'\s+data-pnid-children="[^"]*"', '', out)
out = re.sub(r'\s+data-sp-bindable="[^"]*"', '', out)
out = re.sub(r'\s+data-sp-database-id="[^"]*"', '', out)
out = re.sub(r'<!--pnid:[^>]*-->', '', out)

# 照片现在直接存 jsonb，收紧压缩参数，控制单条记录体积
out = out.replace('const MAX = 720;', 'const MAX = 640;')
out = out.replace('cv.toDataURL("image/jpeg", 0.82)', 'cv.toDataURL("image/jpeg", 0.72)')

io.open(OUT, "w", encoding="utf-8", newline="").write(out)
print("index.html bytes:", len(out.encode("utf-8")))
print("seed rows:", len(seed), "| cats:", len(cats), "| moods:", 10)
