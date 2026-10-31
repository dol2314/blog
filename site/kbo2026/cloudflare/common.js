/* 2026 프로야구 일정 중계 — 공용 데이터·도우미 */
// KBO 일정 TV 칸 표기 → 채널 (끝의 'T' 는 TV 중계 표시)
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
const POST = ["와일드카드","준플레이오프","플레이오프","한국시리즈"];
const GAME_HOURS = 4; // 시작 후 이 시간이 지나면 '지난 경기'로 보고 목록에서 뺀다
const WD = ["일","월","화","수","목","금","토"];

function channel(code){ return CHANNELS[code] || { key:"", name: code, kind:"" }; }
function esc(s){ return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
function startOf(g){ return new Date(`${g.d}T${g.t || "00:00"}:00+09:00`); }
function cancelled(g){ return /취소|사정/.test(g.n || ""); }
function status(g, now){
  const s = startOf(g).getTime(), n = now.getTime();
  if (cancelled(g)) return n >= s ? "done" : "cancel";
  if (n >= s + GAME_HOURS * 3600e3) return "done";
  if (n >= s) return "live";
  return "upcoming";
}
function dateLabel(d){ const x = new Date(d + "T12:00:00+09:00"); return `${+d.slice(5,7)}월 ${+d.slice(8,10)}일 (${WD[x.getUTCDay()]})`; }
function shortDate(d){ return `${+d.slice(5,7)}월 ${+d.slice(8,10)}일`; }
function kstToday(now){ return new Date(now.getTime() + 9*3600e3).toISOString().slice(0,10); }
function dday(d, now){
  const diff = Math.round((Date.parse(d) - Date.parse(kstToday(now))) / 864e5);
  return diff === 0 ? "오늘" : diff === 1 ? "내일" : diff > 0 ? `D-${diff}` : "";
}
function team(name){ return `<span class="team"><i style="background:${TEAM_COLORS[name] || "#888"}"></i>${esc(name)}</span>`; }
function seriesBadge(g){
  const cls = POST.includes(g.sr) ? "ps" : g.sr === "국제대회" ? "intl" : "";
  return `<span class="badge ${cls}">${esc(g.sr)}</span>`;
}
function tvChips(g, base = ""){
  if (!g.tv.length) return `<span class="chip muted">중계 채널 발표 전</span>`;
  return g.tv.map(c => { const ch = channel(c);
    return ch.key ? `<a class="chip" href="${base}guide-tv.html#${ch.key}">📺 ${esc(ch.name)}</a>` : `<span class="chip">${esc(ch.name)}</span>`;
  }).join("") + `<a class="chip" href="${base}guide-tving.html">📱 티빙</a>`;
}
async function loadSchedule(){
  // 1순위: Cloudflare 함수(/api/schedule)가 KBO에서 받아 30분 보관한 최신 일정
  // 2순위: 함께 올린 schedule.json (함수가 없거나 KBO 연결이 안 될 때)
  for (const url of ["api/schedule", "schedule.json"]) {
    try {
      const res = await fetch(url + "?v=" + Math.floor(Date.now() / 600e3));
      if (res.ok) { const d = await res.json(); if (d.games && d.games.length) return d; }
    } catch (e) {}
  }
  throw new Error("일정을 불러오지 못했습니다");
}
