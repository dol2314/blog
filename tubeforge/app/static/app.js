/* TubeForge 화면 — 바닐라 JS, 해시 주소로 화면 전환 */
"use strict";
const TOKEN = new URLSearchParams(location.search).get("t") || "";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const view = () => $("#view");
let STATE = null;
const watching = new Map(); // job id → 끝났을 때 실행할 함수

async function api(path, opts = {}) {
  const res = await fetch(path, {
    method: opts.method || "GET",
    headers: { "X-Token": TOKEN, ...(opts.body && !(opts.body instanceof Blob) ? { "Content-Type": "application/json" } : {}), ...(opts.headers || {}) },
    body: opts.body instanceof Blob ? opts.body : opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.error && res.status >= 400) throw new Error(data.error || `오류 ${res.status}`);
  return data;
}
const fileUrl = (pid, name, bust) => `/files/${encodeURIComponent(pid)}/${name}?t=${TOKEN}${bust ? "&v=" + bust : ""}`;

function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast" + (err ? " err" : ""); t.hidden = false;
  clearTimeout(t._h); t._h = setTimeout(() => (t.hidden = true), err ? 7000 : 3500);
}

const PROVIDERS = { auto: "자동 선택", claude: "Claude", openai: "OpenAI", ollama: "Ollama (내 PC, 무료)", template: "예시 대본 (AI 없이)" };
const TYPES = [
  { key: "shorts", ic: "📱", bg: "#eeedff", tag: "쇼츠 · 9:16", tagc: "#4f46e5", name: "나레이션 쇼츠", desc: "주제 한 줄로 대본·목소리·자막·배경까지 30~60초 세로 영상", go: "#/new/shorts" },
  { key: "long", ic: "🖥️", bg: "#e6f4ff", tag: "롱폼 · 16:9", tagc: "#0369a1", name: "롱폼 나레이션", desc: "파트별로 전개되는 3~10분 가로 영상, 설명란 타임스탬프 자동", go: "#/new/long" },
  { key: "article", ic: "📰", bg: "#e8f7ef", tag: "정보 · 사실 기반", tagc: "#0f9d6b", name: "기사·보도자료 쇼츠", desc: "원문을 붙여 넣으면 그 안의 사실로만 대본을 씁니다", go: "#/new/article" },
  { soon: true, ic: "✂️", bg: "#f3f4f6", tag: "16:9 → 9:16", tagc: "#6b7280", name: "롱폼 → 쇼츠 변환", desc: "긴 영상에서 하이라이트 구간을 찾아 쇼츠로" },
  { soon: true, ic: "🛒", bg: "#f3f4f6", tag: "쇼핑", tagc: "#6b7280", name: "상품 소개 쇼츠", desc: "상품 정보·사진으로 판매용 쇼츠" },
  { soon: true, ic: "🔮", bg: "#f3f4f6", tag: "매일 반복", tagc: "#6b7280", name: "운세 쇼츠", desc: "날짜만 고르면 12띠 운세 영상" },
  { soon: true, ic: "🗂️", bg: "#f3f4f6", tag: "카드뉴스", tagc: "#6b7280", name: "인스타 카드뉴스", desc: "같은 대본으로 카드 이미지와 게시 문구" },
  { soon: true, ic: "📡", bg: "#f3f4f6", tag: "게시", tagc: "#6b7280", name: "여러 플랫폼 동시 게시", desc: "릴스·틱톡 등에 맞춘 게시 문구" },
];

/* ──────────────── 공통: 상태·작업 표시 ──────────────── */
async function refreshState() {
  try {
    STATE = await api("/api/state");
  } catch (e) { return; }
  const p = STATE.provider === "auto" ? `자동 → ${PROVIDERS[STATE.provider_auto] || STATE.provider_auto}` : PROVIDERS[STATE.provider] || STATE.provider;
  $("#engineInfo").innerHTML = `대본 AI <b>${esc(p)}</b><br>목소리 <b>${esc(voiceLabel(STATE.default_voice))}</b>`;
  const dock = $("#jobDock"), running = STATE.jobs.filter(j => j.kind !== "preview");
  dock.hidden = !running.length;
  if (running.length) {
    const j = running[0];
    dock.innerHTML = `<div>${j.kind === "render" ? "🎬 렌더링" : j.kind === "upload" ? "⬆️ 업로드" : "✍️ 대본"} · ${esc(j.message)}</div>${barHtml(j.progress)}`;
    dock.onclick = () => { if (j.project) location.hash = `#/p/${j.project}/${j.kind === "script" ? "script" : "render"}`; };
  }
}
const voiceLabel = id => (STATE?.voices.find(v => v.id === id)?.label.split(" · ")[0]) || id;
const barHtml = p => `<div class="bar${p == null ? " indet" : ""}"><i style="width:${Math.round((p || 0) * 100)}%"></i></div>`;

async function watchJob(job, onDone, onTick) {
  while (true) {
    let j;
    try { j = await api(`/api/jobs/${job.id}`); } catch (e) { toast(e.message, true); return; }
    onTick && onTick(j);
    if (j.status === "done") { await refreshState(); onDone && onDone(j); return j; }
    if (j.status === "error") { toast(j.error || "실패했습니다", true); onTick && onTick(j); refreshState(); return j; }
    await new Promise(r => setTimeout(r, 900));
  }
}

/* ──────────────── 라우터 ──────────────── */
async function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/");
  const page = parts[0] || "home";
  $$(".side nav a").forEach(a => a.classList.toggle("on", a.dataset.nav === (page === "p" ? "projects" : page)));
  try {
    if (page === "home") return await renderHome();
    if (page === "new") return renderNew(parts[1] || "shorts");
    if (page === "projects") return await renderProjects();
    if (page === "settings") return await renderSettings();
    if (page === "p") return await renderProject(decodeURIComponent(parts[1]), parts[2] || "script");
    location.hash = "#/home";
  } catch (e) {
    view().innerHTML = `<div class="empty">${esc(e.message)}<br><br><a class="btn ghost" href="#/home">홈으로</a></div>`;
  }
}

/* ──────────────── 홈 ──────────────── */
async function renderHome() {
  const projects = await api("/api/projects");
  view().innerHTML = `
  <section class="hero">
    <span class="eyebrow">● 유튜브 자동 제작</span>
    <h1>주제 한 줄이면,<br><em>쇼츠가 완성됩니다.</em></h1>
    <p class="sub" style="margin:0">대본 → 목소리 → 자막·배경·음악 → 렌더링 → 업로드까지. 단계마다 멈춰서 직접 고칠 수 있어요.</p>
    <form class="quick" id="quick">
      <input type="text" name="topic" placeholder="무엇에 대한 영상을 만들까요? 예: 겨울철 난방비 아끼는 방법" autocomplete="off">
      <select name="type"><option value="shorts">쇼츠 30초</option><option value="shorts60">쇼츠 60초</option><option value="long">롱폼 5분</option></select>
      <button class="btn">대본 만들기 →</button>
    </form>
    <div class="hints">${["겨울철 난방비 아끼는 방법", "전기요금 누진제 쉽게 정리", "청년도약계좌 조건", "자취생 냉장고 정리 꿀팁"].map(h => `<button type="button">${h}</button>`).join("")}</div>
  </section>

  <div class="row" style="margin-bottom:12px"><h2 style="margin:0">제작 종류</h2><span class="muted">고르면 해당 방식으로 시작합니다</span></div>
  <div class="types">${TYPES.map(t => `
    <div class="type${t.soon ? " soon" : ""}" ${t.go ? `data-go="${t.go}"` : ""}>
      <div class="ic" style="background:${t.bg}">${t.ic}</div>
      <div><small style="color:${t.tagc}">${t.tag}${t.soon ? " · 준비 중" : ""}</small><b>${t.name}</b><p>${t.desc}</p></div>
    </div>`).join("")}</div>

  <h2>이렇게 만들어져요</h2>
  <div class="flow">
    <div><span>1</span><b>소재 입력</b><p>주제나 기사 원문, 길이와 대본 AI 선택</p></div>
    <div><span>2</span><b>AI 대본</b><p>훅 → 본문 → 구독 유도, 장면별로</p></div>
    <div><span>3</span><b>대본 다듬기</b><p>문장·순서를 고치고 장면 추가·삭제</p></div>
    <div><span>4</span><b>목소리·렌더링</b><p>목소리 미리듣기, 배경·BGM 고르고 영상 생성</p></div>
    <div><span>5</span><b>확인·업로드</b><p>미리보기 후 유튜브 업로드·예약</p></div>
  </div>

  <div class="row" style="margin-bottom:12px"><h2 style="margin:0">최근 프로젝트</h2><span class="spacer"></span><a class="btn ghost sm" href="#/projects">전체 보기</a></div>
  ${projectGrid(projects.slice(0, 5))}`;
  $("#quick").onsubmit = e => {
    e.preventDefault();
    const f = new FormData(e.target), topic = f.get("topic").trim(), t = f.get("type");
    if (!topic) return toast("주제를 입력하세요", true);
    createProject({ topic, type: t === "long" ? "long" : "shorts", seconds: t === "shorts60" ? 60 : t === "long" ? 300 : 30, provider: "" });
  };
  $$(".hints button").forEach(b => b.onclick = () => { $("#quick [name=topic]").value = b.textContent; $("#quick [name=topic]").focus(); });
  $$(".type[data-go]").forEach(c => c.onclick = () => (location.hash = c.dataset.go));
  bindProjectCards();
}

function projectGrid(items) {
  if (!items.length) return `<div class="empty">아직 만든 영상이 없습니다. 위에서 주제를 넣어 첫 영상을 만들어 보세요.</div>`;
  return `<div class="grid">${items.map(p => `
    <div class="pcard" data-id="${esc(p.id)}" data-step="${p.has_video ? "result" : "script"}">
      <div class="thumb ${p.type === "long" ? "long" : ""}">${p.has_thumb ? `<img loading="lazy" src="${fileUrl(p.id, "thumbnail.jpg")}" alt="">` : "영상 만들기 전"}</div>
      <div class="meta">
        <b>${esc(p.title)}</b>
        <div class="row">
          <span class="chip ${p.type === "long" ? "" : "brand"}">${p.type === "long" ? "롱폼" : "쇼츠"}</span>
          ${p.youtube ? `<span class="chip ok">업로드됨</span>` : p.has_video ? `<span class="chip ok">완성</span>` : `<span class="chip warn">대본</span>`}
          <span class="muted" style="font-size:12px">${new Date(p.created * 1000).toLocaleDateString("ko-KR")}</span>
        </div>
      </div>
    </div>`).join("")}</div>`;
}
function bindProjectCards() {
  $$(".pcard").forEach(c => c.onclick = () => (location.hash = `#/p/${encodeURIComponent(c.dataset.id)}/${c.dataset.step}`));
}

/* ──────────────── 1단계: 소재 ──────────────── */
function stepper(pid, cur, has) {
  const steps = [["source", "소재"], ["script", "대본"], ["voice", "목소리·스타일"], ["render", "렌더링"], ["result", "결과·업로드"]];
  const order = steps.map(s => s[0]), ci = order.indexOf(cur);
  return `<div class="stepper">${steps.map(([k, label], i) => {
    const enabled = pid && i > 0 && (i <= 2 || (k === "render") || (k === "result" && has.video));
    const cls = i === ci ? "on" : i < ci ? "done" : "";
    return `<a class="${cls}${enabled ? "" : " off"}" href="${enabled ? `#/p/${encodeURIComponent(pid)}/${k}` : "#"}"><span>${i < ci ? "✓" : i + 1}</span>${label}</a>`;
  }).join("")}</div>`;
}

function renderNew(kind) {
  const isLong = kind === "long", isArticle = kind === "article";
  view().innerHTML = `
  <h1>새 영상 만들기</h1><p class="sub">소재를 넣으면 AI 가 장면별 대본을 씁니다. 다음 단계에서 직접 고칠 수 있어요.</p>
  ${stepper(null, "source", {})}
  <form class="card" id="srcForm">
    <div class="form-grid">
      <div class="full row">
        <div class="seg" id="typeSeg"><button type="button" data-v="shorts" class="${isLong ? "" : "on"}">📱 쇼츠 (9:16)</button><button type="button" data-v="long" class="${isLong ? "on" : ""}">🖥️ 롱폼 (16:9)</button></div>
      </div>
      <label class="f full">주제 / 키워드<input type="text" name="topic" placeholder="예: 겨울철 난방비 아끼는 방법" autocomplete="off" required></label>
      <label class="f">길이
        <select name="seconds" id="secSel"></select></label>
      <label class="f">대본 AI
        <select name="provider">${Object.entries(PROVIDERS).map(([k, v]) => `<option value="${k}" ${k === "auto" ? "selected" : ""}>${v}${k === "auto" && STATE ? ` (지금: ${PROVIDERS[STATE.provider_auto] || STATE.provider_auto})` : ""}</option>`).join("")}</select></label>
      <label class="f full">참고 원문 <span class="muted" style="font-weight:400">(선택 · 기사나 보도자료를 붙여 넣으면 그 안의 사실로만 씁니다)</span>
        <textarea name="source" rows="${isArticle ? 9 : 4}" placeholder="${isArticle ? "기사·보도자료 본문을 붙여 넣으세요" : "없으면 비워 두세요"}"></textarea></label>
    </div>
    <div class="row section"><span class="muted" id="srcHint">AI 대본은 보통 10초~3분 걸립니다 (내 PC Ollama 는 더 걸릴 수 있어요).</span><span class="spacer"></span><button class="btn big" id="goBtn">대본 만들기 →</button></div>
    <div id="srcProg" class="section" hidden></div>
  </form>`;
  let vtype = isLong ? "long" : "shorts";
  const fillSec = () => {
    $("#secSel").innerHTML = (vtype === "long" ? [[180, "약 3분"], [300, "약 5분"], [600, "약 10분"]] : [[30, "30초"], [45, "45초"], [60, "60초"]])
      .map(([v, l], i) => `<option value="${v}" ${i === (vtype === "long" ? 1 : 0) ? "selected" : ""}>${l}</option>`).join("");
  };
  fillSec();
  $$("#typeSeg button").forEach(b => b.onclick = () => { vtype = b.dataset.v; $$("#typeSeg button").forEach(x => x.classList.toggle("on", x === b)); fillSec(); });
  $("#srcForm").onsubmit = e => {
    e.preventDefault();
    const f = new FormData(e.target);
    if (isArticle && !f.get("source").trim()) return toast("기사·보도자료 원문을 붙여 넣으세요", true);
    createProject({ topic: f.get("topic").trim(), type: vtype, seconds: +f.get("seconds"), provider: f.get("provider"), source: f.get("source") });
  };
}

async function createProject(body) {
  if (!body.topic) return toast("주제를 입력하세요", true);
  if (location.hash.indexOf("#/new") !== 0) { location.hash = "#/new/" + body.type; await new Promise(r => setTimeout(r, 50)); $("#srcForm [name=topic]").value = body.topic; }
  const btn = $("#goBtn"), prog = $("#srcProg");
  btn.disabled = true; prog.hidden = false;
  prog.innerHTML = `<div class="row"><b>✍️ 대본을 쓰는 중…</b><span class="muted" id="srcMsg"></span></div>${barHtml(null)}`;
  try {
    const job = await api("/api/projects", { method: "POST", body });
    await watchJob(job, j => {
      if (j.result.provider === "template") toast("API 키·Ollama 가 없어 예시 대본으로 만들었습니다. 설정에서 대본 AI 를 연결하세요.");
      location.hash = `#/p/${encodeURIComponent(j.result.project)}/script`;
    }, j => {
      const m = $("#srcMsg"); if (m) m.textContent = `${j.message} · ${Math.round(j.elapsed)}초`;
      if (j.status === "error") { btn.disabled = false; prog.innerHTML = `<div class="note">❌ ${esc(j.error)}</div>`; }
    });
  } catch (e) { toast(e.message, true); btn.disabled = false; prog.hidden = true; }
}

/* ──────────────── 프로젝트 화면 (2~5단계) ──────────────── */
async function renderProject(pid, step) {
  const P = await api(`/api/projects/${encodeURIComponent(pid)}`);
  const has = { video: P.files["final.mp4"] };
  const running = STATE?.jobs.find(j => j.project === pid && (j.kind === "render" || j.kind === "upload"));
  if (running && running.kind === "render" && step !== "render") step = "render";
  const head = `<div class="row"><h1 style="margin:0">${esc(P.script.title)}</h1><span class="chip ${P.script.video_type === "long" ? "" : "brand"}">${P.script.video_type === "long" ? "롱폼 16:9" : "쇼츠 9:16"}</span></div>
    <p class="sub">주제: ${esc(P.script.topic)} · 대본 AI: ${esc(PROVIDERS[P.script.provider] || P.script.provider)}</p>${stepper(pid, step, has)}`;
  if (step === "script") return stepScript(pid, P, head);
  if (step === "voice") return stepVoice(pid, P, head);
  if (step === "render") return stepRender(pid, P, head, running);
  if (step === "result") return stepResult(pid, P, head);
}

/* 2단계: 대본 다듬기 (+ 장면 이미지) */
function stepScript(pid, P, head) {
  const s = P.script, long = s.video_type === "long";
  let scenes = s.scenes.map(x => ({ section: x.section, text: x.text, visual: x.visual, image_prompt: x.image_prompt || "", image: x.image || "" }));
  const bust = Date.now();
  view().innerHTML = `${head}
  <div class="card">
    <div class="form-grid">
      <label class="f full">영상 제목 <span class="muted" style="font-weight:400">(유튜브 제목 · 쇼츠 상단에 표시)</span><input type="text" id="title" value="${esc(s.title)}" maxlength="100"></label>
      <label class="f">설명란<textarea id="desc" rows="3">${esc(s.description)}</textarea></label>
      <label class="f">태그 <span class="muted" style="font-weight:400">(쉼표로 구분)</span><textarea id="tags" rows="3">${esc(s.tags.join(", "))}</textarea></label>
    </div>
  </div>
  <div class="card section">
    <div class="row" style="margin-bottom:6px"><h2 style="margin:0">장면별 대본 · 이미지</h2><span class="muted" id="total"></span><span class="spacer"></span>
      ${STATE.images_ready ? `<button class="btn sm" id="genAll">🎨 빈 장면 이미지 모두 만들기</button>` : ""}<button class="btn ghost sm" id="addScene">＋ 장면 추가</button></div>
    <p class="muted" style="margin:0 0 6px;font-size:13px">한 장면 = 1~2문장. 첫 장면(훅)에서 3초 안에 궁금하게 만들고, 마지막 장면에서 구독·댓글을 부탁하세요.
      ${STATE.images_ready ? `그림체: <b>${esc(STATE.image_styles[STATE.image_style] || STATE.image_style)}</b> (설정에서 변경)` : `<br>장면마다 AI 실사 이미지를 넣으려면 <a href="#/settings" style="color:var(--brand);font-weight:700">설정</a>에서 Google(Gemini) API 키를 넣으세요.`}</p>
    <div id="imgStatus" hidden></div>
    <div id="scenes"></div>
  </div>
  <div class="row section"><button class="btn ghost" id="saveOnly">저장</button><span class="spacer"></span><button class="btn big" id="next">저장하고 목소리 고르기 →</button></div>`;
  const CPS = 6.8;
  const draw = () => {
    const total = scenes.reduce((a, x) => a + x.text.replace(/\s/g, "").length / CPS + 0.25, 0);
    const withImg = scenes.filter(x => x.image).length;
    $("#total").textContent = `· ${scenes.length}장면 · 예상 ${Math.round(total)}초${STATE.images_ready ? ` · 이미지 ${withImg}/${scenes.length}` : ""}`;
    $("#scenes").innerHTML = scenes.map((x, i) => `
      <div class="scene">
        <div class="no">${i + 1}</div>
        <a class="sthumb ${long ? "long" : ""}" ${x.image ? `href="${fileUrl(pid, x.image, bust)}" target="_blank" title="크게 보기"` : ""}>${x.image ? `<img src="${fileUrl(pid, x.image, bust)}" alt="">` : "<span>이미지<br>없음</span>"}</a>
        <div class="sbody">
          <div class="row">
            <select data-i="${i}" data-k="section" style="width:auto"><option value="hook" ${x.section === "hook" ? "selected" : ""}>훅</option><option value="body" ${x.section === "body" ? "selected" : ""}>본문</option><option value="cta" ${x.section === "cta" ? "selected" : ""}>마무리(CTA)</option></select>
            <span class="info"><span>${x.text.replace(/\s/g, "").length}자 · 약 ${(x.text.replace(/\s/g, "").length / CPS).toFixed(1)}초</span>${x.visual ? ` · ${esc(x.visual)}` : ""}</span>
            <span class="spacer"></span>
            ${STATE.images_ready ? `<button class="btn ghost sm" data-gen="${i}">🎨 ${x.image ? "다시 만들기" : "이미지 만들기"}</button>` : ""}
          </div>
          <textarea class="sec-${x.section}" data-i="${i}" data-k="text" rows="2">${esc(x.text)}</textarea>
          <details${x.image_prompt ? "" : " open"}><summary>이미지 묘사 (영어 · 고치면 그림이 바뀝니다)</summary>
            <textarea data-i="${i}" data-k="image_prompt" rows="2" placeholder="예: close-up of hands adjusting a thermostat in a cozy Korean apartment, warm evening light">${esc(x.image_prompt)}</textarea></details>
        </div>
        <div class="tools"><button data-a="up" data-i="${i}" title="위로">↑</button><button data-a="down" data-i="${i}" title="아래로">↓</button><button data-a="del" data-i="${i}" title="삭제">✕</button></div>
      </div>`).join("");
    $$("#scenes [data-k]").forEach(el => el.oninput = el.onchange = () => {
      scenes[+el.dataset.i][el.dataset.k] = el.value;
      if (el.dataset.k === "section") draw();
      else if (el.dataset.k === "text") { const n = el.value.replace(/\s/g, "").length; el.closest(".sbody").querySelector(".info span").textContent = `${n}자 · 약 ${(n / CPS).toFixed(1)}초`; }
    });
    $$("#scenes [data-a]").forEach(b => b.onclick = () => {
      const i = +b.dataset.i;
      if (b.dataset.a === "del") { if (scenes.length > 1) scenes.splice(i, 1); }
      else { const j = b.dataset.a === "up" ? i - 1 : i + 1; if (j >= 0 && j < scenes.length) [scenes[i], scenes[j]] = [scenes[j], scenes[i]]; }
      draw();
    });
    $$("#scenes [data-gen]").forEach(b => b.onclick = () => genImages([+b.dataset.gen], true));
  };
  draw();
  $("#addScene").onclick = () => { scenes.splice(Math.max(0, scenes.length - 1), 0, { section: "body", text: "", visual: "", image_prompt: "", image: "" }); draw(); };
  const save = async () => {
    const body = { title: $("#title").value, description: $("#desc").value, tags: $("#tags").value.split(","), scenes };
    await api(`/api/projects/${encodeURIComponent(pid)}/script`, { method: "PUT", body });
  };
  const lock = on => $$("[data-gen], #genAll, #next").forEach(b => (b.disabled = on));
  const genImages = async (indices, force) => {
    const status = $("#imgStatus");
    lock(true);
    status.hidden = false;
    status.innerHTML = `<div class="note" style="margin:6px 0 10px;background:var(--brand-soft);border-color:#d9d6ff;color:var(--ink)"><b id="imgMsg">🎨 이미지 만드는 중…</b>${barHtml(null)}</div>`;
    try {
      await save();
      const job = await api(`/api/projects/${encodeURIComponent(pid)}/images`, { method: "POST", body: { indices, force } });
      await watchJob(job, j => {
        const failed = j.result.failed || [];
        if (failed.length) toast(`장면 ${failed.map(f => f.scene).join(", ")} 실패: ${failed[0].error}`, true);
        else toast("이미지를 만들었습니다");
        route();
      }, j => {
        const m = $("#imgMsg"); if (m) m.textContent = `🎨 ${j.message}`;
        const bar = status.querySelector(".bar"); if (bar && j.progress != null) bar.outerHTML = barHtml(j.progress);
        if (j.status === "error") { status.innerHTML = `<div class="note">❌ ${esc(j.error)}</div>`; lock(false); }
      });
    } catch (e) { toast(e.message, true); status.hidden = true; lock(false); }
  };
  if ($("#genAll")) $("#genAll").onclick = () => genImages(null, false);
  $("#saveOnly").onclick = async () => { try { await save(); toast("저장했습니다"); } catch (e) { toast(e.message, true); } };
  $("#next").onclick = async () => { try { await save(); location.hash = `#/p/${encodeURIComponent(pid)}/voice`; } catch (e) { toast(e.message, true); } };
}

/* 3단계: 목소리·스타일 */
function stepVoice(pid, P, head) {
  const meta = P.meta || {};
  let voice = meta.voice || STATE.default_voice, rate = STATE.default_rate, bg = meta.bg ? meta.bg.split(/[\\/]/).pop() : "", bgm = meta.bgm ? meta.bgm.split(/[\\/]/).pop() : "";
  const tts = STATE.tts;
  view().innerHTML = `${head}
  <div class="card">
    <div class="row" style="margin-bottom:10px"><h2 style="margin:0">목소리</h2><span class="muted">${tts === "edge" ? "Microsoft 무료 음성 (인터넷 필요)" : tts === "elevenlabs" ? "ElevenLabs" : "무음 테스트 모드"}</span></div>
    ${tts === "edge" ? `<div class="voices">${STATE.voices.map(v => `
      <div class="voice ${v.id === voice ? "on" : ""}" data-v="${v.id}"><div><b>${esc(v.label.split(" · ")[0])}</b><small>${esc(v.label.split(" · ").slice(1).join(" · "))}</small></div>
      <button class="btn ghost sm play" data-play="${v.id}">▶ 듣기</button></div>`).join("")}</div>` : `<p class="muted">설정에서 음성 엔진을 바꿀 수 있습니다.</p>`}
    <div class="row section"><label class="f" style="width:220px">말하기 속도
      <select id="rate">${["-10%", "+0%", "+10%", "+15%", "+20%", "+30%"].map(r => `<option ${r === rate ? "selected" : ""}>${r}</option>`).join("")}</select></label>
      <audio id="player" hidden></audio></div>
  </div>
  <div class="card section">
    <h2>배경</h2>
    ${P.script.scenes.some(x => x.image) ? `<div class="note" style="margin-bottom:10px;background:#e6f7f0;border-color:#bfe8d6;color:#0b5e40">🎨 AI 장면 이미지가 있는 장면은 그 이미지를 씁니다. 아래 배경은 이미지가 없는 장면에만 쓰입니다.</div>` : STATE.images_ready ? `<div class="note" style="margin-bottom:10px">「영상 만들기」를 누르면 비어 있는 장면 이미지를 먼저 자동으로 만듭니다 (배경을 직접 고르면 건너뜀).</div>` : ""}
    <p class="muted" style="margin:-6px 0 10px;font-size:13px">이미지·영상을 고르면 장면마다 돌아가며 쓰고, 고르지 않으면 장면마다 색이 다른 그라데이션을 만듭니다. 저작권이 확인된 소재만 쓰세요.</p>
    <div class="assets" id="bgList"></div>
    <label class="btn ghost sm section" style="display:inline-flex">＋ 배경 올리기<input type="file" id="bgFile" accept="image/*,video/*" hidden></label>
  </div>
  <div class="card section">
    <h2>배경음악 (BGM)</h2>
    <p class="muted" style="margin:-6px 0 10px;font-size:13px">말하는 동안에는 자동으로 작아지고, 쉬는 구간에서 다시 커집니다.</p>
    <div class="assets" id="bgmList"></div>
    <label class="btn ghost sm section" style="display:inline-flex">＋ 음악 올리기<input type="file" id="bgmFile" accept="audio/*" hidden></label>
  </div>
  <div class="row section"><a class="btn ghost" href="#/p/${encodeURIComponent(pid)}/script">← 대본으로</a><span class="spacer"></span><button class="btn big" id="render">🎬 영상 만들기</button></div>`;
  const drawAssets = () => {
    const a = STATE.assets;
    $("#bgList").innerHTML = [`<div class="asset ${!bg ? "on" : ""}" data-bg="">🎨 자동 그라데이션</div>`, ...a.backgrounds.map(n => `<div class="asset ${n === bg ? "on" : ""}" data-bg="${esc(n)}">🖼️ ${esc(n)}</div>`)].join("");
    $("#bgmList").innerHTML = [`<div class="asset ${!bgm ? "on" : ""}" data-bgm="">🔇 없음</div>`, ...a.bgm.map(n => `<div class="asset ${n === bgm ? "on" : ""}" data-bgm="${esc(n)}">🎵 ${esc(n)}</div>`)].join("");
    $$("[data-bg]").forEach(el => el.onclick = () => { bg = el.dataset.bg; drawAssets(); });
    $$("[data-bgm]").forEach(el => el.onclick = () => { bgm = el.dataset.bgm; drawAssets(); });
  };
  drawAssets();
  $$(".voice").forEach(el => el.onclick = e => { if (e.target.dataset.play) return; voice = el.dataset.v; $$(".voice").forEach(x => x.classList.toggle("on", x === el)); });
  $("#rate").onchange = e => (rate = e.target.value);
  $$("[data-play]").forEach(b => b.onclick = async () => {
    b.disabled = true; b.textContent = "만드는 중…";
    try {
      const first = P.script.scenes[0]?.text;
      const job = await api("/api/voice-preview", { method: "POST", body: { voice: b.dataset.play, rate, text: first } });
      await watchJob(job, j => { const pl = $("#player"); pl.src = `${j.result.url}?t=${TOKEN}`; pl.play(); });
    } catch (e) { toast(e.message, true); }
    b.disabled = false; b.textContent = "▶ 듣기";
  });
  const uploader = (input, kind, set) => input.onchange = async () => {
    const f = input.files[0]; if (!f) return;
    toast(`${f.name} 올리는 중…`);
    try {
      const r = await api(`/api/assets/${kind}`, { method: "POST", body: f, headers: { "X-Filename": encodeURIComponent(f.name), "Content-Type": "application/octet-stream" } });
      STATE.assets = r.assets; set(r.name); drawAssets(); toast("올렸습니다");
    } catch (e) { toast(e.message, true); }
  };
  uploader($("#bgFile"), "backgrounds", n => (bg = n));
  uploader($("#bgmFile"), "bgm", n => (bgm = n));
  $("#render").onclick = async () => {
    try {
      await api(`/api/projects/${encodeURIComponent(pid)}/render`, { method: "POST", body: { voice, rate, bg, bgm } });
      await refreshState();
      location.hash = `#/p/${encodeURIComponent(pid)}/render`;
    } catch (e) { toast(e.message, true); }
  };
}

/* 4단계: 렌더링 진행 */
function stepRender(pid, P, head, running) {
  if (!running) {
    view().innerHTML = `${head}<div class="card progress-card"><div class="big">🎬</div><h2>아직 렌더링 중인 작업이 없습니다</h2>
      <p class="muted">목소리·스타일 단계에서 「영상 만들기」를 누르세요.</p>
      <div class="row" style="justify-content:center"><a class="btn" href="#/p/${encodeURIComponent(pid)}/voice">목소리·스타일로</a>${P.files["final.mp4"] ? `<a class="btn ghost" href="#/p/${encodeURIComponent(pid)}/result">결과 보기</a>` : ""}</div></div>`;
    return;
  }
  view().innerHTML = `${head}<div class="card progress-card"><div class="big">🎬</div><h2 id="rMsg">${esc(running.message)}</h2>
    <div id="rBar">${barHtml(running.progress)}</div><p class="muted" id="rSub">이 화면을 떠나도 계속 만들어집니다. 30초 쇼츠 기준 보통 1~3분.</p></div>`;
  const myHash = location.hash;
  watchJob(running, () => { if (location.hash === myHash) location.hash = `#/p/${encodeURIComponent(pid)}/result`; }, j => {
    if (location.hash !== myHash) return;
    $("#rMsg").textContent = j.status === "error" ? "실패했습니다" : j.message;
    $("#rBar").innerHTML = barHtml(j.progress);
    $("#rSub").textContent = j.status === "error" ? j.error : `${Math.round((j.progress || 0) * 100)}% · ${Math.round(j.elapsed)}초 경과`;
    if (j.status === "error") $("#rSub").insertAdjacentHTML("afterend", `<a class="btn" href="#/p/${encodeURIComponent(pid)}/voice">다시 시도</a>`);
  });
}

/* 5단계: 결과·업로드 */
function stepResult(pid, P, head) {
  if (!P.files["final.mp4"]) { location.hash = `#/p/${encodeURIComponent(pid)}/voice`; return; }
  const m = P.meta || {}, s = P.script, v = Math.round(m.updated || 0), yt = m.youtube;
  const now = new Date(Date.now() + 2 * 3600e3), local = new Date(now - now.getTimezoneOffset() * 60e3).toISOString().slice(0, 16);
  view().innerHTML = `${head}
  <div class="result">
    <div><video class="${s.video_type === "long" ? "long" : ""}" src="${fileUrl(pid, "final.mp4", v)}" controls playsinline poster="${fileUrl(pid, "thumbnail.jpg", v)}"></video></div>
    <div>
      <div class="card">
        <h2>완성 영상</h2>
        <dl class="kv">
          <dt>길이</dt><dd>${m.duration ? m.duration + "초" : "-"}</dd>
          <dt>목소리</dt><dd>${esc(voiceLabel(m.voice) || m.tts || "-")}</dd>
          <dt>파일</dt><dd class="row">
            <a class="btn ghost sm" href="${fileUrl(pid, "final.mp4", v)}" download="${esc(s.title)}.mp4">⬇ 영상</a>
            <a class="btn ghost sm" href="${fileUrl(pid, "thumbnail.jpg", v)}" download>⬇ 썸네일</a>
            <a class="btn ghost sm" href="${fileUrl(pid, "captions.srt", v)}" download>⬇ 자막(SRT)</a></dd>
        </dl>
        <div class="row section"><a class="btn ghost sm" href="#/p/${encodeURIComponent(pid)}/script">✏️ 대본 고쳐서 다시 만들기</a><a class="btn ghost sm" href="#/p/${encodeURIComponent(pid)}/voice">🎙️ 목소리·배경 바꾸기</a></div>
      </div>
      <div class="card section">
        <h2>유튜브 업로드</h2>
        ${yt ? `<p>✅ 업로드됨: <a href="https://youtu.be/${esc(yt.id)}" target="_blank" style="color:var(--brand);font-weight:700">youtu.be/${esc(yt.id)}</a> ${yt.publish_at ? `· ${esc(yt.publish_at)} 공개 예약` : `· ${esc(yt.privacy)}`}</p>` : ""}
        ${STATE.youtube_ready ? "" : `<div class="note" style="margin-bottom:12px">유튜브 연결 파일(client_secret.json)이 아직 없습니다. 설정 화면의 안내를 따라 한 번만 준비하세요.</div>`}
        <div class="form-grid">
          <label class="f">공개 범위<select id="privacy"><option value="private">비공개</option><option value="unlisted">일부 공개</option><option value="public">공개</option></select></label>
          <label class="f">예약 발행 <span class="muted" style="font-weight:400">(선택 · 한국 시간)</span><input type="datetime-local" id="publishAt" min="${local}"></label>
        </div>
        <div class="row section"><span class="muted" style="font-size:13px">예약하면 비공개로 올라간 뒤 그 시각에 자동 공개됩니다.</span><span class="spacer"></span><button class="btn" id="upload" ${STATE.youtube_ready ? "" : "disabled"}>⬆ 업로드</button></div>
        <div id="upProg"></div>
      </div>
      <div class="card section"><h2>설명란 · 타임스탬프</h2><p style="margin-top:0">${esc(s.description)}</p><p class="muted">${s.tags.map(t => "#" + esc(t.replace(/\s/g, ""))).join(" ")}</p><pre class="ts">${esc(P.timestamps)}</pre></div>
    </div>
  </div>`;
  $("#upload").onclick = async () => {
    const at = $("#publishAt").value;
    const body = { privacy: $("#privacy").value, publish_at: at ? at.replace("T", " ") : "" };
    $("#upload").disabled = true;
    $("#upProg").innerHTML = `<div class="section">${barHtml(null)}<p class="muted" id="upMsg">업로드 준비 중… (처음이면 브라우저에서 구글 로그인 창이 열립니다)</p></div>`;
    try {
      const job = await api(`/api/projects/${encodeURIComponent(pid)}/upload`, { method: "POST", body });
      await watchJob(job, j => { toast("업로드 완료!"); route(); }, j => { const el = $("#upMsg"); if (el) el.textContent = j.status === "error" ? j.error : j.message; if (j.status === "error") $("#upload").disabled = false; });
    } catch (e) { toast(e.message, true); $("#upload").disabled = false; }
  };
}

/* ──────────────── 내 프로젝트 ──────────────── */
async function renderProjects() {
  const items = await api("/api/projects");
  view().innerHTML = `<div class="row"><h1 style="margin:0">내 프로젝트</h1><span class="spacer"></span><a class="btn" href="#/new">＋ 새 영상</a></div>
    <p class="sub">${items.length}개 · 카드를 누르면 이어서 작업합니다.</p>${projectGrid(items)}`;
  bindProjectCards();
  $$(".pcard").forEach(c => c.oncontextmenu = async e => {
    e.preventDefault();
    if (!confirm("이 프로젝트를 삭제할까요? 영상 파일도 함께 지워집니다.")) return;
    try { await api(`/api/projects/${encodeURIComponent(c.dataset.id)}`, { method: "DELETE" }); toast("삭제했습니다"); route(); } catch (err) { toast(err.message, true); }
  });
  if (items.length) view().insertAdjacentHTML("beforeend", `<p class="muted section" style="font-size:12.5px">카드를 오른쪽 클릭하면 삭제할 수 있습니다.</p>`);
}

/* ──────────────── 설정 ──────────────── */
async function renderSettings() {
  const items = await api("/api/settings");
  const field = it => {
    if (it.key === "SCRIPT_PROVIDER") return `<select name="${it.key}">${Object.entries(PROVIDERS).map(([k, v]) => `<option value="${k}" ${k === it.value ? "selected" : ""}>${v}</option>`).join("")}</select>`;
    if (it.key === "TTS_ENGINE") return `<select name="${it.key}">${[["edge", "Edge 무료 음성"], ["elevenlabs", "ElevenLabs (유료)"], ["dummy", "무음 테스트"]].map(([k, v]) => `<option value="${k}" ${k === it.value ? "selected" : ""}>${v}</option>`).join("")}</select>`;
    if (it.key === "IMAGE_STYLE") return `<select name="${it.key}">${Object.entries(STATE.image_styles).map(([k, v]) => `<option value="${k}" ${k === it.value ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>`;
    if (it.key === "EDGE_VOICE") return `<select name="${it.key}">${STATE.voices.map(v => `<option value="${v.id}" ${v.id === it.value ? "selected" : ""}>${esc(v.label)}</option>`).join("")}</select>`;
    if (it.secret) return `<input type="password" name="${it.key}" placeholder="${it.set ? "저장됨 · 바꿀 때만 입력" : "입력하세요"}" autocomplete="off">`;
    return `<input type="text" name="${it.key}" value="${esc(it.value)}">`;
  };
  const groups = [["대본 AI", ["SCRIPT_PROVIDER", "ANTHROPIC_API_KEY", "CLAUDE_MODEL", "OPENAI_API_KEY", "OPENAI_MODEL", "OLLAMA_HOST", "OLLAMA_MODEL"]],
    ["장면 이미지 (Google)", ["GEMINI_API_KEY", "GEMINI_IMAGE_MODEL", "IMAGE_STYLE"]],
    ["목소리", ["TTS_ENGINE", "EDGE_VOICE", "EDGE_RATE", "ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID"]],
    ["영상", ["BGM_VOLUME", "BGM_DUCK_VOLUME", "FONT_PATH"]]];
  const byKey = Object.fromEntries(items.map(i => [i.key, i]));
  view().innerHTML = `<h1>설정</h1><p class="sub">tubeforge/.env 파일에 저장됩니다. API 키는 이 PC 밖으로 보내지 않습니다.</p>
  <form id="setForm">${groups.map(([g, keys]) => `<div class="card section"><h2>${g}</h2><div class="settings-grid">${keys.map(k => byKey[k]).filter(Boolean).map(it => `<label class="f">${esc(it.label)}${it.secret && it.set ? ' <span class="chip ok">저장됨</span>' : ""}${field(it)}</label>`).join("")}</div></div>`).join("")}
  <div class="card section"><h2>유튜브 연결</h2>${STATE.youtube_ready ? `<p>✅ client_secret.json 이 있습니다. 첫 업로드 때 구글 로그인 창이 한 번 열립니다.</p>` : `
    <ol style="margin:0;padding-left:20px;line-height:1.9">
      <li><b>console.cloud.google.com</b> → 새 프로젝트 → API 라이브러리에서 <b>YouTube Data API v3</b> 사용</li>
      <li>OAuth 동의 화면: 외부 · 테스트 사용자에 내 구글 계정 추가</li>
      <li>사용자 인증 정보 → OAuth 클라이언트 ID → <b>데스크톱 앱</b> → JSON 다운로드</li>
      <li>받은 파일 이름을 <b>client_secret.json</b> 으로 바꿔 <b>tubeforge</b> 폴더에 넣고 앱을 다시 실행</li>
    </ol><p class="muted" style="font-size:13px">구글 API 감사를 받지 않은 프로젝트로 올린 영상은 비공개로 고정될 수 있습니다.</p>`}</div>
  <div class="row section"><span class="spacer"></span><button class="btn big">저장</button></div></form>`;
  $("#setForm").onsubmit = async e => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target));
    try { await api("/api/settings", { method: "PUT", body }); toast("저장했습니다"); await refreshState(); renderSettings(); } catch (err) { toast(err.message, true); }
  };
}

/* ──────────────── 시작 ──────────────── */
window.addEventListener("hashchange", route);
(async () => {
  if (!TOKEN) { view().innerHTML = `<div class="empty">앱을 「TubeForge 실행.bat」으로 열어 주세요.</div>`; return; }
  await refreshState();
  if (!STATE) { view().innerHTML = `<div class="empty">앱 서버에 연결하지 못했습니다. 앱을 다시 실행하세요.</div>`; return; }
  route();
  setInterval(refreshState, 4000);
})();
