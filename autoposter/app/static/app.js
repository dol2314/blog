"use strict";

const TOKEN = new URLSearchParams(location.search).get("t") || "";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const STATUS = {
  draft: { label: "초안", cls: "s-draft", color: "#7b8494" },
  saved: { label: "임시저장", cls: "s-saved", color: "#d0862b" },
  published: { label: "발행", cls: "s-published", color: "#3c8c3f" },
};

const S = {
  data: null, // /api/state
  ai: null, // /api/ai
  verified: false, // 이번 실행에서 접속(카테고리 불러오기)을 확인했는지
  filter: { q: "", status: "all", platform: "all", unpublished: false },
  openId: null,
  busy: { platform: false, ai: false },
  pull: null, // 모델 내려받기 진행 { fraction, text }
};

// ---- 서버 호출 ----------------------------------------------------------------

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: { "X-Token": TOKEN, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `오류 (HTTP ${res.status})`);
  return data;
}

async function refresh() {
  S.data = await api("GET", "/api/state");
  render();
}

async function refreshAI() {
  try {
    S.ai = await api("GET", "/api/ai");
  } catch {
    S.ai = { running: false, installed: false, models: [] };
  }
  renderAI();
}

// ---- 작업 (오래 걸리는 일) ------------------------------------------------------

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function runJob(name, body, { lane, onProgress } = {}) {
  S.busy[lane] = true;
  renderBusy();
  let job;
  try {
    job = await api("POST", `/api/jobs/${name}`, body || {});
    let shownSeq = 0;
    showToast(job.message, { spin: true });
    while (job.state === "running" || job.state === "input") {
      if (job.state === "input" && job.prompt && job.prompt.seq !== shownSeq) {
        shownSeq = job.prompt.seq;
        const answer = await askForJob(job.prompt);
        await api("POST", `/api/jobs/${job.id}/answer`, answer === null ? { cancel: true } : { answer });
      }
      await sleep(600);
      job = await api("GET", `/api/jobs/${job.id}`);
      if (job.state === "running") {
        showToast(job.message, { spin: true, progress: job.progress });
        if (onProgress) onProgress(job);
      }
    }
    if (job.state === "error") throw new Error(job.error);
    return job.result;
  } finally {
    S.busy[lane] = false;
    renderBusy();
  }
}

function askForJob(prompt) {
  if (prompt.kind === "confirm") {
    return showModal({
      title: "로그인",
      text: "열린 브라우저 창에서 로그인을 마친 뒤 [확인]을 눌러 주세요.\n로그인이 확인되면 자동으로 다음 단계로 넘어갑니다.",
      ok: "로그인 완료",
    }).then((v) => (v === null ? null : ""));
  }
  return showModal({ title: "접속 정보", text: prompt.question, input: true, secret: prompt.secret, value: prompt.default || "" });
}

// ---- 알림 · 질문 창 ---------------------------------------------------------------

let toastTimer = null;
function showToast(text, { spin = false, progress = null, kind = "", hideAfter = 0 } = {}) {
  const t = $("toast");
  clearTimeout(toastTimer);
  t.hidden = false;
  t.className = `toast ${kind}`;
  $("toast-text").textContent = text;
  $("toast-spin").hidden = !spin;
  $("toast-bar").hidden = progress === null || progress === undefined;
  if (progress !== null && progress !== undefined) $("toast-fill").style.width = `${Math.round(progress * 100)}%`;
  if (hideAfter) toastTimer = setTimeout(() => (t.hidden = true), hideAfter);
}
const toastOk = (text) => showToast(text, { kind: "ok", hideAfter: 3500 });
const toastError = (err) => showToast(err.message || String(err), { kind: "error", hideAfter: 9000 });

function showModal({ title, text, input = false, secret = false, value = "", ok = "확인", cancel = "취소" }) {
  return new Promise((resolve) => {
    $("modal-title").textContent = title;
    $("modal-text").textContent = text || "";
    const field = $("modal-input");
    field.hidden = !input;
    field.type = secret ? "password" : "text";
    field.value = value;
    $("modal-ok").textContent = ok;
    $("modal-cancel").textContent = cancel;
    $("modal").hidden = false;
    if (input) setTimeout(() => field.focus(), 30);
    const done = (v) => {
      $("modal").hidden = true;
      $("modal-ok").onclick = $("modal-cancel").onclick = field.onkeydown = null;
      resolve(v);
    };
    $("modal-ok").onclick = () => done(input ? field.value : "");
    $("modal-cancel").onclick = () => done(null);
    field.onkeydown = (e) => {
      if (e.key === "Enter") done(field.value);
      if (e.key === "Escape") done(null);
    };
  });
}

// ---- 그리기 ----------------------------------------------------------------------

const platformName = (key) => (S.data.platforms.find((p) => p.key === key) || {}).name || "-";
const currentEngine = () => S.data.engines.find((e) => e.id === $("engine").value) || S.data.engines[0];
const textOf = (html) => {
  const d = document.createElement("div");
  d.innerHTML = html || "";
  return (d.textContent || "").replace(/\s+/g, " ").trim();
};
const fmtDate = (ts) => {
  const d = new Date(ts * 1000);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}.${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};
const fmtDay = (ts) => {
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

function render() {
  renderPlatform();
  renderCategories();
  renderEngines();
  renderAI();
  renderStats();
  renderFilters();
  renderRows();
  renderBusy();
  if (S.openId) fillDrawer(S.openId, { keepEdits: true });
}

function renderPlatform() {
  const seg = $("platform-seg");
  seg.innerHTML = "";
  for (const p of S.data.platforms) {
    const b = document.createElement("button");
    b.textContent = p.name.replace(" 블로그", "");
    b.className = p.key === S.data.platform ? "active" : "";
    b.onclick = () => switchPlatform(p.key);
    seg.appendChild(b);
  }
  const cur = S.data.platforms.find((p) => p.key === S.data.platform);
  const dot = $("conn-dot");
  if (S.verified && S.data.categories.length) {
    dot.className = "dot ok";
    $("conn-text").textContent = `${cur.target} · 접속됨`;
  } else if (cur && cur.target) {
    dot.className = "dot warn";
    $("conn-text").textContent = `${cur.target} · 저장된 접속 정보`;
  } else {
    dot.className = "dot";
    $("conn-text").textContent =
      S.data.platform === "wordpress" ? "사이트 주소와 앱 비밀번호로 접속합니다" : "브라우저 창에서 직접 로그인합니다";
  }
  $("login-btn").textContent = cur && cur.target ? "다시 접속" : "접속하기";
}

function categoryOptions(select, selectedLabel, placeholder) {
  const cats = S.data.categories;
  select.innerHTML = "";
  if (!cats.length) {
    select.innerHTML = `<option value="">${esc(placeholder)}</option>`;
    return;
  }
  if (!selectedLabel) select.innerHTML = `<option value="">카테고리 선택</option>`;
  for (const c of cats) {
    const o = document.createElement("option");
    o.value = c.label;
    o.textContent = c.label;
    select.appendChild(o);
  }
  if (selectedLabel && cats.some((c) => c.label === selectedLabel)) select.value = selectedLabel;
}

function renderCategories() {
  const sel = $("category");
  const prev = sel.value || localStorage.getItem(`cat:${S.data.platform}`) || "";
  categoryOptions(sel, prev || (S.data.categories[0] || {}).label, "카테고리를 불러와 주세요");
}

function renderEngines() {
  const sel = $("engine");
  if (sel.options.length !== S.data.engines.length) {
    sel.innerHTML = S.data.engines
      .map((e) => `<option value="${esc(e.id)}">${esc(e.label)} · ${e.kind === "local" ? "무료" : "유료"}</option>`)
      .join("");
  }
  if (!sel.dataset.touched) sel.value = S.data.engine;
}

function renderAI() {
  if (!S.data) return;
  const box = $("ai-status");
  const engine = currentEngine();
  $("engine").title = `${engine.label} — ${engine.note}`;
  if (engine.kind === "claude") {
    box.innerHTML = S.data.has_api_key
      ? `<div class="line"><span class="dot ok"></span>API 키가 설정되어 있습니다</div>`
      : `<div class="line"><span class="dot warn"></span>Claude를 쓰려면 API 키가 필요합니다</div>
         <button class="btn btn-light btn-sm" data-act="key">API 키 입력</button>`;
    $("foot-note").textContent = "Claude · 유료(글 한 편 약 100원 안팎) · 약 1분";
  } else {
    const ai = S.ai;
    $("foot-note").textContent = `내 PC AI · 무료 · ${engine.model === "qwen3:8b" ? "글 한 편 약 1~3분" : "글 한 편 약 5~10분"}`;
    if (!ai) {
      box.textContent = "상태 확인 중...";
    } else if (S.pull) {
      const pct = S.pull.fraction == null ? 0 : Math.round(S.pull.fraction * 100);
      box.innerHTML = `<div class="line"><span class="spinner" style="border-color:#dfe5f3;border-top-color:var(--primary)"></span>${esc(S.pull.text)}</div>
        <div class="mini-bar"><div style="width:${pct}%"></div></div>`;
    } else if (!ai.running) {
      box.innerHTML = ai.installed
        ? `<div class="line"><span class="dot warn"></span>Ollama가 꺼져 있습니다</div>
           <div class="row gap8"><button class="btn btn-light btn-sm" data-act="start">Ollama 켜기</button>
           <button class="btn btn-light btn-sm" data-act="recheck">다시 확인</button></div>`
        : `<div class="line"><span class="dot warn"></span>Ollama가 응답하지 않습니다. 설치하지 않았다면 먼저 설치해 주세요 (무료)</div>
           <div class="row gap8"><button class="btn btn-light btn-sm" data-act="download">설치 페이지</button>
           <button class="btn btn-light btn-sm" data-act="start">Ollama 켜기</button>
           <button class="btn btn-light btn-sm" data-act="recheck">다시 확인</button></div>`;
    } else if (!ai.models.some((m) => m === engine.model || m === `${engine.model}:latest`)) {
      box.innerHTML = `<div class="line"><span class="dot warn"></span>모델을 처음 한 번 내려받아야 합니다 (${esc(engine.size)})</div>
        <button class="btn btn-light btn-sm" data-act="pull">모델 내려받기</button>`;
    } else {
      box.innerHTML = `<div class="line"><span class="dot ok"></span>준비됨 · Apache 2.0 (상업적 이용 가능)</div>`;
    }
  }
  box.querySelectorAll("[data-act]").forEach((b) => (b.onclick = () => aiAction(b.dataset.act)));
}

function renderStats() {
  const posts = S.data.posts;
  const count = (st) => posts.filter((p) => p.status === st).length;
  const range = posts.length ? `${fmtDay(posts[posts.length - 1].created)} ~ ${fmtDay(posts[0].created)}` : "아직 없음";
  const now = new Date();
  const thisMonth = posts.filter((p) => {
    const d = new Date((p.published_at || p.created) * 1000);
    return p.status === "published" && d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear();
  }).length;
  const cards = [
    ["전체 글", posts.length.toLocaleString(), range],
    ["발행", count("published"), `이번 달 ${thisMonth}건`],
    ["임시저장", count("saved"), "블로그에 저장된 글"],
    ["AI 초안", count("draft"), "확인 후 발행 대기"],
  ];
  $("stats").innerHTML = cards
    .map(([l, v, s]) => `<div class="stat"><div class="stat-label">${l}</div><div class="stat-value">${v}</div><div class="stat-sub">${esc(s)}</div></div>`)
    .join("");
  $("head-sub").textContent = `${platformName(S.data.platform)}에 올릴 글을 만들고 관리합니다`;
}

function renderFilters() {
  const chips = $("status-chips");
  const items = [["all", "전체", "#3a4150"], ...Object.entries(STATUS).map(([k, v]) => [k, v.label, v.color])];
  chips.innerHTML = items
    .map(([k, l, c]) => `<button class="chip-btn ${S.filter.status === k ? "active" : ""}" data-k="${k}" style="background:${c}">${l}</button>`)
    .join("");
  chips.querySelectorAll("button").forEach((b) => (b.onclick = () => ((S.filter.status = b.dataset.k), renderFilters(), renderRows())));
  const pf = $("platform-filter");
  if (!pf.options.length) {
    pf.innerHTML = `<option value="all">블로그 전체</option>` + S.data.platforms.map((p) => `<option value="${p.key}">${esc(p.name)}</option>`).join("");
  }
}

function filteredPosts() {
  const f = S.filter;
  const q = f.q.trim().toLowerCase();
  return S.data.posts.filter(
    (p) =>
      (f.status === "all" || p.status === f.status) &&
      (f.platform === "all" || p.platform === f.platform) &&
      (!f.unpublished || p.status !== "published") &&
      (!q || p.title.toLowerCase().includes(q) || p.tags.some((t) => t.toLowerCase().includes(q))),
  );
}

function enginePill(engine) {
  if (!engine) return "";
  if (engine === "file") return `<span class="pill file">직접 작성</span>`;
  if (engine.startsWith("claude:")) return `<span class="pill claude">Claude</span>`;
  return `<span class="pill local">내 PC AI</span>`;
}

function renderRows() {
  const rows = filteredPosts();
  $("empty").hidden = S.data.posts.length > 0;
  $("post-rows").innerHTML = rows
    .map((p, i) => {
      const len = textOf(p.html).length;
      const pct = Math.min(100, Math.round((len / 4000) * 100));
      const st = STATUS[p.status] || STATUS.draft;
      return `<tr data-id="${p.id}" class="${p.id === S.openId ? "selected" : ""}">
        <td class="num">${i + 1}</td>
        <td><span class="t-title">${esc(p.title || "(제목 없음)")}</span>${enginePill(p.engine)}</td>
        <td><div class="lenbar"><div class="track"><div class="fill" style="width:${pct}%"></div></div><span class="val">${len.toLocaleString()}</span></div></td>
        <td><span class="status ${st.cls}">${st.label}</span></td>
        <td class="nowrap">${esc(platformName(p.platform).replace(" 블로그", ""))}</td>
        <td class="cat" title="${esc(p.category ? p.category.label : "")}">${esc(p.category ? p.category.label : "-")}</td>
        <td class="muted nowrap">${fmtDate(p.created)}</td>
      </tr>`;
    })
    .join("");
  $("post-rows").querySelectorAll("tr").forEach((tr) => (tr.onclick = () => openDrawer(tr.dataset.id)));
}

function renderBusy() {
  const p = S.busy.platform;
  const a = S.busy.ai;
  $("login-btn").disabled = p;
  $("cat-btn").disabled = p;
  $("d-draft").disabled = p;
  $("d-publish").disabled = p;
  $("write-btn").disabled = a;
  $("write-btn").textContent = a ? "AI 작업 중..." : "▶ 글 생성 시작";
  $("platform-seg").querySelectorAll("button").forEach((b) => (b.disabled = p));
}

// ---- 상세 창 ---------------------------------------------------------------------

const post = (id) => S.data.posts.find((p) => p.id === id);

function openDrawer(id) {
  S.openId = id;
  fillDrawer(id);
  $("overlay").hidden = false;
  $("drawer").classList.add("open");
  $("drawer").setAttribute("aria-hidden", "false");
  renderRows();
}

function closeDrawer() {
  S.openId = null;
  $("overlay").hidden = true;
  $("drawer").classList.remove("open");
  $("drawer").setAttribute("aria-hidden", "true");
  renderRows();
}

function previewDoc(p) {
  return `<!doctype html><meta charset="utf-8"><style>
    body{font:16px/1.85 "Pretendard","Malgun Gothic",sans-serif;color:#1d2230;margin:22px 26px;word-break:keep-all}
    h2{font-size:20px;margin:28px 0 10px;padding-left:10px;border-left:4px solid #2b5ce6}h3{font-size:17px}
    blockquote{margin:14px 0;padding:10px 16px;background:#f4f6fa;border-radius:8px;color:#4a5160}
    li{margin:4px 0}</style>${p.html}`;
}

function fillDrawer(id, { keepEdits = false } = {}) {
  const p = post(id);
  if (!p) return closeDrawer();
  const text = textOf(p.html);
  const heads = (p.html.match(/<h[23][\s>]/gi) || []).length;
  const st = STATUS[p.status] || STATUS.draft;
  const mismatch = p.platform && p.platform !== S.data.platform;

  const notice = $("d-notice");
  notice.className = `notice ${mismatch || !p.category ? "warn" : ""}`;
  if (mismatch) {
    notice.innerHTML = `이 글은 <b>${esc(platformName(p.platform))}</b>용 카테고리로 만들었습니다. 지금 선택한 <b>${esc(platformName(S.data.platform))}</b>에 올리려면 아래에서 카테고리를 다시 고르세요.`;
  } else if (!p.category) {
    notice.innerHTML = `<b>카테고리</b>를 골라야 올릴 수 있습니다. 왼쪽에서 카테고리를 불러온 뒤 아래에서 선택하세요.`;
  } else if (p.status === "published") {
    notice.innerHTML = `<b>발행 완료</b>된 글입니다. ${p.published_at ? fmtDate(p.published_at) + "에 " : ""}${esc(platformName(p.platform))}에 올렸습니다.`;
  } else if (p.status === "saved") {
    notice.innerHTML = `블로그에 <b>임시저장</b>된 글입니다. 블로그 관리 화면에서 마무리하거나, 여기서 다시 <b>발행하기</b>를 누를 수 있습니다.`;
  } else {
    notice.innerHTML = `<b>AI 초안</b>입니다. 소제목 <b>${heads}개</b>, 약 <b>${text.length.toLocaleString()}자</b>로 작성됐습니다. 사실과 다른 내용이 없는지 확인하고 고친 뒤 <b>발행하기</b>를 누르세요.`;
  }

  categoryOptions($("d-category"), !mismatch && p.category ? p.category.label : "", "왼쪽에서 카테고리를 먼저 불러와 주세요");

  const engineLabel = p.engine === "file" ? "직접 작성" : (S.data.engines.find((e) => e.id === p.engine) || {}).label || "-";
  const metrics = [
    ["글자수", `${text.length.toLocaleString()}자`],
    ["상태", st.label],
    ["소제목", `${heads}개`],
    ["태그", `${p.tags.length}개`],
    ["예상 읽기 시간", `약 ${Math.max(1, Math.round(text.length / 500))}분`],
    ["작성", engineLabel],
  ];
  $("d-metrics").innerHTML = metrics
    .map(([l, v]) => `<div class="metric"><div class="metric-label">${l}</div><div class="metric-value">${esc(v)}</div></div>`)
    .join("");

  if (!keepEdits || document.activeElement !== $("d-title")) $("d-title").value = p.title;
  if (!keepEdits || document.activeElement !== $("d-tags")) $("d-tags").value = p.tags.join(", ");
  if (!keepEdits || document.activeElement !== $("d-html")) $("d-html").value = p.html;
  renderTagList(p.tags);
  $("d-preview").srcdoc = previewDoc(p);
  $("d-link").hidden = !p.url;
  $("d-publish").textContent = p.status === "published" ? "다시 발행" : "발행하기";

  const list = filteredPosts();
  const idx = list.findIndex((x) => x.id === id);
  $("d-prev").disabled = idx <= 0;
  $("d-next").disabled = idx < 0 || idx >= list.length - 1;
}

function renderTagList(tags) {
  $("d-tag-list").innerHTML = tags.map((t) => `<span class="tag">#${esc(t)}</span>`).join("");
}

let saveTimer = null;
function scheduleSave(fields) {
  const id = S.openId;
  const p = post(id);
  Object.assign(p, fields);
  if (typeof fields.tags === "string") p.tags = fields.tags.split(/[,\s]+/).map((t) => t.replace(/^#/, "")).filter(Boolean);
  renderTagList(p.tags);
  if (fields.html !== undefined) $("d-preview").srcdoc = previewDoc(p);
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    try {
      const saved = await api("POST", `/api/posts/${id}`, fields);
      Object.assign(post(id), saved);
      renderRows();
      renderStats();
    } catch (e) {
      toastError(e);
    }
  }, 500);
}

async function flushSave() {
  if (!saveTimer) return;
  clearTimeout(saveTimer);
  saveTimer = null;
  const p = post(S.openId);
  const saved = await api("POST", `/api/posts/${p.id}`, { title: p.title, html: p.html, tags: p.tags });
  Object.assign(p, saved);
}

async function publish(draft) {
  const p = post(S.openId);
  const action = draft ? "임시저장" : "발행";
  const cat = p.category ? p.category.label : "-";
  const ok = await showModal({
    title: `${action}할까요?`,
    text: `${platformName(S.data.platform)} · ${cat}\n\n${p.title}`,
    ok: `${action}하기`,
  });
  if (ok === null) return;
  try {
    await flushSave();
    const result = await runJob("publish", { post_id: p.id, draft }, { lane: "platform" });
    Object.assign(post(p.id), result);
    render();
    toastOk(`${action} 완료!`);
  } catch (e) {
    toastError(e);
  }
}

// ---- 동작 ------------------------------------------------------------------------

async function switchPlatform(key) {
  if (key === S.data.platform) return;
  try {
    S.data = await api("POST", "/api/platform", { key });
    S.verified = false;
    render();
  } catch (e) {
    toastError(e);
  }
}

async function login() {
  try {
    const cats = await runJob("login", {}, { lane: "platform" });
    S.verified = true;
    await refresh();
    toastOk(`접속 완료 · 카테고리 ${cats.length}개를 불러왔습니다`);
  } catch (e) {
    toastError(e);
  }
}

async function loadCategories() {
  try {
    const cats = await runJob("categories", {}, { lane: "platform" });
    S.verified = true;
    await refresh();
    toastOk(`카테고리 ${cats.length}개를 불러왔습니다`);
  } catch (e) {
    toastError(e);
  }
}

async function writePost() {
  const category = $("category").value;
  if (!category) return toastError(new Error("카테고리를 먼저 불러와 골라 주세요. (왼쪽 위 [카테고리 불러오기])"));
  const engine = currentEngine();
  if (engine.kind === "claude" && !S.data.has_api_key) {
    const ok = await askApiKey();
    if (!ok) return;
  }
  try {
    const created = await runJob(
      "write",
      {
        category,
        topic: $("topic").value.trim(),
        tone: $("tone").value,
        length: Number($("length").value),
        extra: $("extra").value.trim(),
        engine: engine.id,
      },
      { lane: "ai" },
    );
    await refresh();
    toastOk("글이 완성됐습니다. 확인하고 발행하세요.");
    openDrawer(created.id);
  } catch (e) {
    toastError(e);
  }
}

async function askApiKey() {
  const key = await showModal({
    title: "Claude API 키",
    text: "Claude로 글을 쓰려면 API 키가 필요합니다.\nhttps://console.anthropic.com 에서 발급할 수 있습니다.\n(비워 두고 확인을 누르면 저장된 키를 지웁니다)",
    input: true,
    secret: true,
  });
  if (key === null) return false;
  S.data = await api("POST", "/api/settings", { anthropic_api_key: key });
  render();
  toastOk(key ? "API 키를 저장했습니다" : "API 키를 지웠습니다");
  return Boolean(key);
}

async function aiAction(act) {
  const engine = currentEngine();
  try {
    if (act === "key") return askApiKey();
    if (act === "download") return api("POST", "/api/open", { url: (S.ai && S.ai.download_page) || "https://ollama.com/download" });
    if (act === "recheck") {
      showToast("내 PC AI(Ollama) 상태를 확인하는 중...", { spin: true });
      await refreshAI();
      if (S.ai.running) return toastOk(`Ollama 연결됨 (버전 ${S.ai.version || "?"})`);
      return showModal({
        title: "Ollama에 연결하지 못했습니다",
        text:
          "1. 화면 오른쪽 아래 작업 표시줄에 라마 아이콘이 있는지 확인하세요.\n" +
          "   없으면 시작 메뉴에서 'Ollama'를 찾아 실행하거나 [Ollama 켜기]를 누르세요.\n" +
          "2. 브라우저 주소창에 http://127.0.0.1:11434 를 입력했을 때\n" +
          "   'Ollama is running'이 보이면 정상입니다.\n" +
          "3. 설치 직후라면 PC를 한 번 재시작해 보세요.\n\n" +
          `자세한 원인: ${S.ai.reason || "알 수 없음"}`,
        ok: "확인",
        cancel: "닫기",
      }).then(() => (document.getElementById("toast").hidden = true));
    }
    if (act === "start") {
      const { started } = await api("POST", "/api/ai/start");
      if (!started) {
        return toastError(new Error("이 PC에서 Ollama 실행 파일을 찾지 못했습니다. 설치 페이지에서 설치했는지 확인하거나, 시작 메뉴에서 Ollama를 직접 실행해 주세요."));
      }
      showToast("Ollama를 켜는 중...", { spin: true });
      for (let i = 0; i < 10 && !(S.ai && S.ai.running); i++) {
        await sleep(1500);
        await refreshAI();
      }
      return S.ai.running ? toastOk("Ollama가 켜졌습니다") : toastError(new Error("Ollama를 켜지 못했습니다. 시작 메뉴에서 Ollama를 직접 실행해 주세요."));
    }
    if (act === "pull") {
      S.pull = { fraction: 0, text: "내려받기 준비 중" };
      renderAI();
      await runJob("pull", { model: engine.model }, {
        lane: "ai",
        onProgress: (job) => {
          S.pull = { fraction: job.progress, text: job.message };
          renderAI();
        },
      });
      S.pull = null;
      await refreshAI();
      toastOk("모델 준비 완료! 이제 무료로 글을 쓸 수 있습니다");
    }
  } catch (e) {
    S.pull = null;
    renderAI();
    toastError(e);
  }
}

async function importFile(file) {
  try {
    const content = await file.text();
    const created = await api("POST", "/api/posts/import", { name: file.name, content });
    await refresh();
    openDrawer(created.id);
    toastOk(`불러왔습니다: ${file.name}`);
  } catch (e) {
    toastError(e);
  }
}

function bind() {
  $("login-btn").onclick = login;
  $("cat-btn").onclick = loadCategories;
  $("write-btn").onclick = writePost;
  $("settings-btn").onclick = askApiKey;
  $("category").onchange = (e) => localStorage.setItem(`cat:${S.data.platform}`, e.target.value);
  $("engine").onchange = async (e) => {
    e.target.dataset.touched = "1";
    renderAI();
    try {
      await api("POST", "/api/settings", { engine: e.target.value });
    } catch (err) {
      toastError(err);
    }
  };
  $("import-btn").onclick = () => $("import-file").click();
  $("import-file").onchange = (e) => {
    if (e.target.files[0]) importFile(e.target.files[0]);
    e.target.value = "";
  };
  $("search").oninput = (e) => ((S.filter.q = e.target.value), renderRows());
  $("platform-filter").onchange = (e) => ((S.filter.platform = e.target.value), renderRows());
  $("unpublished-only").onchange = (e) => ((S.filter.unpublished = e.target.checked), renderRows());

  $("overlay").onclick = closeDrawer;
  $("drawer-close").onclick = closeDrawer;
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && $("modal").hidden && S.openId) closeDrawer();
  });
  $("d-title").oninput = (e) => scheduleSave({ title: e.target.value });
  $("d-tags").oninput = (e) => scheduleSave({ tags: e.target.value });
  $("d-html").oninput = (e) => scheduleSave({ html: e.target.value });
  $("d-category").onchange = async (e) => {
    if (!e.target.value) return;
    try {
      const saved = await api("POST", `/api/posts/${S.openId}`, { category: e.target.value });
      Object.assign(post(S.openId), saved);
      render();
    } catch (err) {
      toastError(err);
    }
  };
  $("d-tabs").querySelectorAll(".tab").forEach(
    (t) =>
      (t.onclick = () => {
        $("d-tabs").querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
        $("d-preview").hidden = t.dataset.tab !== "preview";
        $("d-html").hidden = t.dataset.tab !== "html";
      }),
  );
  $("d-draft").onclick = () => publish(true);
  $("d-publish").onclick = () => publish(false);
  $("d-link").onclick = () => api("POST", "/api/open", { url: post(S.openId).url });
  $("d-delete").onclick = async () => {
    const p = post(S.openId);
    const ok = await showModal({ title: "글을 지울까요?", text: `${p.title}\n\n이 프로그램의 기록에서만 지워집니다. 이미 블로그에 올린 글은 그대로 남습니다.`, ok: "지우기" });
    if (ok === null) return;
    await api("POST", `/api/posts/${p.id}/delete`);
    closeDrawer();
    await refresh();
  };
  const step = (dir) => {
    const list = filteredPosts();
    const idx = list.findIndex((x) => x.id === S.openId);
    const next = list[idx + dir];
    if (next) openDrawer(next.id);
  };
  $("d-prev").onclick = () => step(-1);
  $("d-next").onclick = () => step(1);

  // 앱 창이 열려 있다는 신호. 창을 닫으면 프로그램(서버)도 같이 꺼진다.
  setInterval(() => api("POST", "/api/ping").catch(() => {}), 20000);
  setInterval(() => {
    if (!S.busy.ai && !S.pull) refreshAI();
  }, 15000);
  window.addEventListener("pagehide", () => navigator.sendBeacon(`/api/bye?t=${encodeURIComponent(TOKEN)}`));
}

(async function init() {
  bind();
  try {
    await refresh();
    await refreshAI();
  } catch (e) {
    toastError(e);
  }
})();
