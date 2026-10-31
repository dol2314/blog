/* 2026 프로야구 일정 중계 — [kbo_*] 숏코드 화면 */
(function () {
  "use strict";
  const CFG = window.KBO26 || {};
  // KBO 일정 TV 칸 표기 → 채널 (끝의 'T' 는 TV 중계 표시). key 는 TV 안내 페이지의 앵커 이름
  const CHANNELS = {
    "K-2T":  { key: "kbs2",      name: "KBS 2TV",      kind: "지상파" },
    "M-T":   { key: "mbc",       name: "MBC",          kind: "지상파" },
    "S-T":   { key: "sbs",       name: "SBS",          kind: "지상파" },
    "KN-T":  { key: "kbsn",      name: "KBS N SPORTS", kind: "스포츠 채널" },
    "MS-T":  { key: "mbcsports", name: "MBC SPORTS+",  kind: "스포츠 채널" },
    "SS-T":  { key: "sbssports", name: "SBS Sports",   kind: "스포츠 채널" },
    "SPO-T": { key: "spotv",     name: "SPOTV",        kind: "스포츠 채널" },
    "SPO-2T":{ key: "spotv2",    name: "SPOTV2",       kind: "스포츠 채널" },
  };
  const TEAM_COLORS = { LG:"#C30452", KT:"#222222", SSG:"#CE0E2D", NC:"#315288", "두산":"#131230", KIA:"#EA0029",
    "롯데":"#041E42", "삼성":"#074CA1", "한화":"#FC4E00", "키움":"#820024", "대한민국":"#0047A0", "일본":"#BC002D", "대만":"#00247D", "호주":"#00843D" };
  const POST = ["와일드카드", "준플레이오프", "플레이오프", "한국시리즈"];
  const GAME_HOURS = 4; // 시작 후 이 시간이 지나면 지난 경기로 보고 뺀다
  const WD = ["일", "월", "화", "수", "목", "금", "토"];

  const channel = c => CHANNELS[c] || { key: "", name: c, kind: "" };
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const startOf = g => new Date(`${g.d}T${g.t || "00:00"}:00+09:00`);
  const cancelled = g => /취소|사정/.test(g.n || "");
  function status(g, now) {
    const s = startOf(g).getTime(), n = now.getTime();
    if (cancelled(g)) return n >= s ? "done" : "cancel";
    if (n >= s + GAME_HOURS * 3600e3) return "done";
    return n >= s ? "live" : "upcoming";
  }
  const dateLabel = d => { const x = new Date(d + "T12:00:00+09:00"); return `${+d.slice(5, 7)}월 ${+d.slice(8, 10)}일 (${WD[x.getUTCDay()]})`; };
  const shortDate = d => `${+d.slice(5, 7)}월 ${+d.slice(8, 10)}일`;
  const kstToday = now => new Date(now.getTime() + 9 * 3600e3).toISOString().slice(0, 10);
  function dday(d, now) {
    const diff = Math.round((Date.parse(d) - Date.parse(kstToday(now))) / 864e5);
    return diff === 0 ? "오늘" : diff === 1 ? "내일" : diff > 0 ? `D-${diff}` : "";
  }
  const withQuery = (url, q) => url + (url.includes("?") ? "&" : "?") + q;
  const L = {
    day: d => withQuery(CFG.day || "/kbo-day/", "d=" + d),
    tv: key => (CFG.tv || "/kbo-tv-channel/") + (key ? "#" + key : ""),
    tving: hash => (CFG.tving || "/kbo-tving/") + (hash ? "#" + hash : ""),
    home: () => (CFG.home || "/") + "#kbo-schedule",
  };
  const team = n => `<span class="team"><i style="background:${TEAM_COLORS[n] || "#888"}"></i>${esc(n)}</span>`;
  const seriesBadge = g => `<span class="badge ${POST.includes(g.sr) ? "ps" : g.sr === "국제대회" ? "intl" : ""}">${esc(g.sr)}</span>`;
  function tvChips(g) {
    if (!g.tv.length) return `<span class="chip muted">중계 채널 발표 전</span>`;
    return g.tv.map(c => { const ch = channel(c);
      return ch.key ? `<a class="chip" href="${L.tv(ch.key)}">📺 ${esc(ch.name)}</a>` : `<span class="chip">${esc(ch.name)}</span>`;
    }).join("") + `<a class="chip" href="${L.tving()}">📱 티빙</a>`;
  }

  let DATA = null, AT = null;
  const now = () => (AT ? new Date(AT) : new Date());
  async function load() {
    const res = await fetch(withQuery(CFG.api, "v=" + Math.floor(Date.now() / 300e3)));
    if (!res.ok) throw new Error("일정을 불러오지 못했습니다");
    DATA = await res.json();
    DATA.games = (DATA.games || []).filter(g => g.a);
  }

  /* [kbo_next] */
  function renderNext(el) {
    const n = now(), g = DATA.games.find(g => ["live", "upcoming"].includes(status(g, n)));
    el._next = g;
    if (!g) { el.innerHTML = `<div class="next"><p class="where" style="padding-bottom:16px">남은 경기가 없습니다. 다음 시즌 일정이 발표되면 자동으로 올라옵니다.</p></div>`; return; }
    const live = status(g, n) === "live";
    el.innerHTML = `<div class="next">
      <div class="next-head"><span>${live ? '<span class="badge live">진행 중</span>' : "다음 경기"} ${seriesBadge(g)}</span><span>${dateLabel(g.d)} ${esc(g.t)}</span></div>
      <div class="match">${team(g.a)}<small>vs</small>${team(g.h)}</div>
      <p class="where">${esc(g.st)} · ${dday(g.d, n) || shortDate(g.d)}</p>
      <div class="cd" aria-label="경기 시작까지 남은 시간"></div>
      <div class="chips">${tvChips(g)}</div>
      <a class="kbo26-a" href="${L.day(g.d)}">${shortDate(g.d)} 중계 채널·시청법 바로가기 &gt;&gt;</a></div>`;
    tickNext(el);
  }
  function tickNext(el) {
    const cd = el.querySelector(".cd"); if (!cd || !el._next) return;
    const s = Math.max(0, Math.floor((startOf(el._next) - now()) / 1000));
    if (!s) { cd.innerHTML = `<div style="min-width:160px"><b>경기 중</b><span>지금 중계 중입니다</span></div>`; return; }
    cd.innerHTML = [[Math.floor(s / 86400), "일"], [Math.floor(s % 86400 / 3600), "시간"], [Math.floor(s % 3600 / 60), "분"], [s % 60, "초"]]
      .map(([v, l]) => `<div><b>${String(v).padStart(2, "0")}</b><span>${l}</span></div>`).join("");
  }

  /* [kbo_schedule days="30" demo="0"] */
  function renderSchedule(el) {
    if (!el._built) {
      el._filter = "all";
      el.id = el.id || "kbo-schedule";
      el.innerHTML = `${el.dataset.demo === "1" ? `<div class="demo"><b>데모: 기준 시각 바꿔 보기</b>
          <div class="filters" data-g="at"><button type="button" data-v="" aria-pressed="true">지금</button>
          <button type="button" data-v="2026-10-14T17:00:00+09:00">10월 14일 오후 5시</button>
          <button type="button" data-v="2026-10-01T15:00:00+09:00">10월 1일 오후 3시</button></div></div>` : ""}
        <div class="stats"></div>
        <div class="filters" data-g="f"><button type="button" data-v="all" aria-pressed="true">전체</button>
          <button type="button" data-v="kbo" aria-pressed="false">KBO 리그</button><button type="button" data-v="intl" aria-pressed="false">국제대회</button></div>
        <p class="kbo26-pointer">▼ 날짜별 남은 경기 (날짜 아래 버튼을 누르면 그날 중계 안내로 이동)</p>
        <div class="list"></div>`;
      el.querySelectorAll(".filters button").forEach(b => b.addEventListener("click", () => {
        b.parentNode.querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", x === b));
        if (b.parentNode.dataset.g === "at") AT = b.dataset.v || null; else el._filter = b.dataset.v;
        renderAll();
      }));
      el._built = true;
    }
    const n = now(), f = el._filter, max = parseInt(el.dataset.days, 10) || 30;
    const rows = DATA.games.filter(g => status(g, n) !== "done")
      .filter(g => f === "all" || (f === "intl") === (g.sr === "국제대회"));
    const byDay = new Map();
    rows.forEach(g => { if (!byDay.has(g.d)) byDay.set(g.d, []); byDay.get(g.d).push(g); });
    const kboLeft = DATA.games.filter(g => g.sr !== "국제대회" && status(g, n) !== "done").length;
    const first = byDay.keys().next().value;
    el.querySelector(".stats").innerHTML = `<div><b>${rows.length}</b>남은 경기</div><div><b>${first ? shortDate(first) : "-"}</b>다음 경기일</div><div><b>${kboLeft}</b>KBO 리그 남은 경기</div>`;
    const list = el.querySelector(".list");
    if (!byDay.size) { list.innerHTML = `<div class="empty">남은 경기가 없습니다.<br>새 일정이 KBO에 올라오면 자동으로 추가됩니다.</div>`; return; }
    list.innerHTML = [...byDay].slice(0, max).map(([d, gs]) => `
      <article class="day">
        <div class="day-head"><span>${dateLabel(d)}</span><span class="dday">${dday(d, n)}</span></div>
        ${gs.map(g => { const st = status(g, n); return `<div class="game">
          <div class="g-time">${esc(g.t)}</div>
          <div class="g-match">${team(g.a)} <small style="color:#7a8392">vs</small> ${team(g.h)}</div>
          <div class="g-sub">${seriesBadge(g)} ${st === "live" ? '<span class="badge live">진행 중</span>' : ""}${st === "cancel" ? `<span class="badge">${esc(g.n)}</span>` : ""}<span>${esc(g.st)}</span></div>
          <div class="g-tv chips">${tvChips(g)}</div></div>`; }).join("")}
        <a class="kbo26-a" href="${L.day(d)}">${shortDate(d)} 중계 안내 바로가기 &gt;&gt;</a>
      </article>`).join("") + (byDay.size > max ? `<p class="note">이후 ${byDay.size - max}일 일정은 날짜가 가까워지면 표시됩니다.</p>` : "");
  }

  /* [kbo_day] — 주소의 ?d=YYYY-MM-DD 날짜 안내 (없으면 다음 경기일) */
  function renderDay(el) {
    const n = now(), days = [...new Set(DATA.games.map(g => g.d))];
    const upcoming = days.find(x => DATA.games.some(g => g.d === x && status(g, n) !== "done"));
    let d = new URLSearchParams(location.search).get("d");
    if (!days.includes(d)) d = upcoming || days[days.length - 1];
    if (!d) { el.innerHTML = `<p>일정이 없습니다.</p>`; return; }
    const gs = DATA.games.filter(g => g.d === d), i = days.indexOf(d), prev = days[i - 1], next = days[i + 1];
    const one = gs.length === 1 ? gs[0] : null;
    const allDone = gs.every(g => status(g, n) === "done");
    const chs = [...new Map(gs.flatMap(g => g.tv).map(c => [c, channel(c)])).values()];
    const ps = gs.some(g => POST.includes(g.sr)), intl = gs.every(g => g.sr === "국제대회");
    const matchup = one ? `${one.a} vs ${one.h}` : `${gs.length}경기`;
    const title = one ? `${shortDate(d)} ${one.sr} ${one.a} vs ${one.h} 중계 채널 및 시청 방법 총정리`
                      : `${shortDate(d)} 프로야구 중계 채널 및 경기 일정 총정리 (${gs.length}경기)`;
    document.title = title + (document.title.includes(" - ") ? " - " + document.title.split(" - ").pop() : "");
    const stateCell = g => { const s = status(g, n);
      if (cancelled(g)) return esc(g.n);
      if (s === "done") return g.sc ? `종료 ${g.sc[0]}:${g.sc[1]}` : "종료";
      return s === "live" ? '<span class="badge live">진행 중</span>' : (dday(g.d, n) || "예정"); };
    el.innerHTML = `
      <p class="title">${esc(title)}</p>
      <div class="meta">${dateLabel(d)} · KBO 공식 일정 기준 · 갱신 ${esc((DATA.updated || "").slice(0, 16).replace("T", " "))}</div>
      ${allDone ? `<div class="note">이 날 경기는 모두 끝났습니다. ${upcoming && upcoming !== d ? `다음 경기는 <a href="${L.day(upcoming)}">${dateLabel(upcoming)}</a>입니다.` : "남은 경기가 없습니다."}</div>` : ""}
      <p>${shortDate(d)} ${esc(matchup)} 경기, 어느 채널에서 하는지 찾고 계신가요?</p>
      <p>${ps ? "포스트시즌은 경기마다 중계 방송사가 바뀌어서" : intl ? "국제대회는 방송사 편성이 늦게 확정되는 경우가 많아서" : "정규시즌은 하루 다섯 경기를 채널 다섯 곳이 나눠 맡아서"} 평소 보던 채널을 틀면 다른 경기가 나오기 쉽습니다.</p>
      <p>오늘은 ${shortDate(d)} 경기 일정과 중계 채널, TV가 없을 때 휴대폰으로 보는 법까지 순서대로 알려드리도록 하겠습니다.</p>

      <h2>1. ${shortDate(d)} 경기 일정</h2>
      <p>경기 시간과 구장은 아래 표와 같습니다. 우천 등으로 일정이 바뀌면 이 표도 자동으로 바뀝니다.</p>
      <p class="kbo26-pointer">▼ ${shortDate(d)} 경기 일정표</p>
      <div class="tw"><table><thead><tr><th>시간</th><th>경기</th><th>구장</th><th>구분</th><th>상태</th></tr></thead>
      <tbody>${gs.map(g => `<tr><td>${esc(g.t)}</td><td><b>${esc(g.a)} vs ${esc(g.h)}</b></td><td>${esc(g.st)}</td><td>${esc(g.sr)}</td><td>${stateCell(g)}</td></tr>`).join("")}</tbody></table></div>

      <h2>2. TV 중계 채널</h2>
      ${chs.length ? `<p>${shortDate(d)} 경기는 아래 채널에서 중계합니다. 채널 번호는 쓰시는 IPTV·케이블마다 다르니 버튼을 눌러 찾는 법을 확인해 보세요.</p>
        ${gs.map(g => `<p class="kbo26-check">✅ ${esc(g.a)} vs ${esc(g.h)} : ${g.tv.length ? g.tv.map(c => esc(channel(c).name)).join(", ") : "발표 전"}</p>`).join("")}
        <p class="kbo26-pointer">▼ 채널 번호 찾는 법 바로가기</p>
        ${chs.slice(0, 3).map(c => `<a class="kbo26-a" href="${L.tv(c.key)}">${esc(c.name)} 채널 번호 확인하기 &gt;&gt;</a>`).join("")}
        ${chs.length > 3 ? `<div class="chips">${chs.slice(3).map(c => `<a class="chip" href="${L.tv(c.key)}">📺 ${esc(c.name)}</a>`).join("")}</div>` : ""}`
      : `<p>아직 KBO 일정에 TV 중계 방송사가 올라오지 않았습니다. 방송사가 정해지면 이 자리에 자동으로 표시됩니다.</p>
        ${gs.map(g => `<p class="kbo26-check">✅ ${esc(g.a)} vs ${esc(g.h)} : 중계 채널 발표 전</p>`).join("")}
        <p class="kbo26-pointer">▼ 그동안 채널별 중계 안내를 확인해 보세요</p>
        <a class="kbo26-a" href="${L.tv()}">프로야구 TV 중계 채널 총정리 &gt;&gt;</a>`}

      <h2>3. 휴대폰·PC로 보는 법</h2>
      <p>TV 앞에 없다면 휴대폰으로도 볼 수 있습니다. ${intl ? "국제대회는 대회마다 온라인 중계사가 달라 발표를 확인해야 합니다." : "2026 시즌 KBO 리그 경기는 티빙에서 생중계합니다."}</p>
      <p>다만 이용권을 아무거나 결제하면 손해일 수 있으니 먼저 고르는 법을 확인해 보세요.</p>
      <p class="kbo26-pointer">▼ 아래 버튼을 눌러 확인해 보세요</p>
      <a class="kbo26-a" href="${L.tving()}">티빙으로 프로야구 보는 법 &gt;&gt;</a>

      <h2>4. 놓친 경기 다시보기</h2>
      <p>경기 시간을 놓쳤다면 다시보기나 하이라이트로 확인할 수 있습니다. 경기가 끝난 뒤 보통 몇 시간 안에 올라옵니다.</p>
      <p class="kbo26-pointer">▼ 다시보기 방법 바로가기</p>
      <a class="kbo26-a" href="${L.tving("replay")}">프로야구 다시보기·하이라이트 보는 법 &gt;&gt;</a>

      <nav class="pager" aria-label="다른 날짜">
        ${prev ? `<a href="${L.day(prev)}"><small>← 이전 경기일</small>${dateLabel(prev)}</a>` : "<span></span>"}
        ${next ? `<a class="nx" href="${L.day(next)}"><small>다음 경기일 →</small>${dateLabel(next)}</a>` : "<span></span>"}
      </nav>
      <a class="kbo26-a ghost" href="${L.home()}" style="margin-top:14px">남은 경기 전체 일정 보기 &gt;&gt;</a>`;
  }

  /* [kbo_channels] */
  function renderChannels(el) {
    el.innerHTML = `<div class="chgrid">${Object.values(CHANNELS).map(c =>
      `<a class="chcard" href="${L.tv(c.key)}"><b>📺 ${esc(c.name)}</b><small>${c.kind} · 보는 법 &gt;</small></a>`).join("")}
      <a class="chcard" href="${L.tving()}"><b>📱 티빙 (모바일·PC)</b><small>전 경기 · 보는 법 &gt;</small></a></div>`;
  }
  /* [kbo_channel_codes] */
  function renderCodes(el) {
    el.innerHTML = `<div class="tw"><table><thead><tr><th>일정표 표기</th><th>채널</th><th>구분</th></tr></thead><tbody>${
      Object.entries(CHANNELS).map(([code, c]) => `<tr><td><b>${esc(code)}</b></td><td><a href="#${c.key}">${esc(c.name)}</a></td><td>${c.kind}</td></tr>`).join("")}</tbody></table></div>`;
  }

  const R = { next: renderNext, schedule: renderSchedule, day: renderDay, channels: renderChannels, codes: renderCodes };
  const els = () => document.querySelectorAll(".kbo26[data-kbo]");
  function renderAll() { els().forEach(el => { try { R[el.dataset.kbo] && R[el.dataset.kbo](el); } catch (e) { console.error(e); } }); }

  async function start() {
    if (!els().length) return;
    const needsData = [...els()].some(el => !["channels", "codes"].includes(el.dataset.kbo));
    if (!needsData) { renderAll(); return; }
    try { await load(); renderAll(); }
    catch (e) { els().forEach(el => { el.innerHTML = `<p class="kbo26-loading">${esc(e.message)}. 잠시 후 다시 시도해 주세요.</p>`; }); return; }
    setInterval(() => document.querySelectorAll('.kbo26[data-kbo="next"]').forEach(tickNext), 1000);
    setInterval(() => document.querySelectorAll('.kbo26[data-kbo="next"],.kbo26[data-kbo="schedule"]').forEach(el => R[el.dataset.kbo](el)), 60e3); // 지난 경기 자동 제외
    setInterval(async () => { try { await load(); document.querySelectorAll('.kbo26[data-kbo="next"],.kbo26[data-kbo="schedule"]').forEach(el => R[el.dataset.kbo](el)); } catch (e) {} }, 10 * 60e3);
  }
  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", start) : start();
})();
