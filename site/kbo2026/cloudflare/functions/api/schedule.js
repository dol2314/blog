// Cloudflare Pages Function: GET /api/schedule
// 함께 올린 schedule.json 을 바탕으로, 이번 달·다음 달 일정만 KBO 공식 일정에서 새로 받아 덮어쓴다.
// 결과는 Cloudflare 캐시에 30분 보관한다 (무료 요금제 하위 요청 50개 제한 안에서 16개만 사용).
// KBO 연결이 안 되면 schedule.json 을 그대로 돌려준다.
const KBO = "https://www.koreabaseball.com/ws/Schedule.asmx/GetScheduleList";
const SERIES = { "0": "정규시즌", "1": "시범경기", "4": "와일드카드", "3": "준플레이오프",
  "5": "플레이오프", "7": "한국시리즈", "8": "국제대회", "9": "올스타전" };
const TTL = 1800;

const decode = s => s.replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
  .replace(/&quot;/g, '"').replace(/&#39;/g, "'");
const strip = s => decode(String(s || "").replace(/<[^>]+>/g, " ")).replace(/\s+/g, " ").trim();

function parse(data, season, series) {
  const games = [];
  let day = null;
  for (const row of data.rows || []) {
    let cells = row.row || [];
    if (cells.length && cells[0].Class === "day") { day = strip(cells[0].Text); cells = cells.slice(1); }
    const md = day && day.match(/(\d+)\.(\d+)/);
    if (cells.length < 8 || !md) continue;
    const play = cells[1].Text || "";
    const spans = [...play.matchAll(/<span[^>]*>(.*?)<\/span>/g)].map(m => m[1]);
    const teams = spans.filter(x => x !== "vs" && !/^\d+$/.test(x));
    const score = [...play.matchAll(/<span class="(?:win|lose|same)">(\d+)<\/span>/g)].map(m => +m[1]);
    const gid = (cells[2].Text || "").match(/gameId=(\w+)/);
    const note = strip(cells[7].Text), tv = strip(cells[4].Text);
    games.push({
      d: `${season}-${md[1].padStart(2, "0")}-${md[2].padStart(2, "0")}`,
      t: strip(cells[0].Text), a: teams[0] || "", h: teams[teams.length - 1] || "",
      sc: score.length === 2 ? score : null, tv: tv ? tv.split(" ") : [],
      st: strip(cells[6].Text), n: note === "-" ? "" : note, sr: series, id: gid ? gid[1] : "",
    });
  }
  return games;
}

async function fetchMonth(season, month, sr) {
  const body = new URLSearchParams({ leId: "1", srIdList: sr, seasonId: season,
    gameMonth: String(month).padStart(2, "0"), teamId: "" });
  const res = await fetch(KBO, { method: "POST", body, headers: {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Referer": "https://www.koreabaseball.com/Schedule/Schedule.aspx",
    "X-Requested-With": "XMLHttpRequest", "User-Agent": "Mozilla/5.0" } });
  if (!res.ok) throw new Error("KBO " + res.status);
  return res.json();
}

function kstNow() {
  const n = new Date(Date.now() + 9 * 3600e3);
  return { iso: n.toISOString().slice(0, 19) + "+09:00", month: n.getUTCMonth() + 1 };
}

async function build(env, origin) {
  const base = await (await env.ASSETS.fetch(new URL("/schedule.json", origin))).json();
  const season = String(env.SEASON || base.season || "2026");
  const { iso, month } = kstNow();
  const months = month === 12 ? [12] : [month, month + 1];
  const jobs = [];
  for (const [sr, name] of Object.entries(SERIES))
    for (const m of months) jobs.push(fetchMonth(season, m, sr).then(d => parse(d, season, name)));
  const fresh = (await Promise.all(jobs)).flat();
  const keep = base.season === season ? base.games.filter(g => !months.includes(+g.d.slice(5, 7))) : [];
  const games = keep.concat(fresh).sort((x, y) => (x.d + x.t).localeCompare(y.d + y.t));
  return { season, updated: iso, source: "KBO 공식 일정", games };
}

export async function onRequestGet({ request, env, waitUntil }) {
  const url = new URL(request.url);
  const key = new Request(url.origin + "/api/schedule");
  const cache = caches.default;
  const hit = await cache.match(key);
  if (hit) return hit;
  let data, ok = true;
  try { data = await build(env, url.origin); }
  catch (e) { ok = false; data = await (await env.ASSETS.fetch(new URL("/schedule.json", url.origin))).json(); }
  const res = new Response(JSON.stringify(data), { headers: {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": `public, max-age=${ok ? 300 : 60}`,
    "X-Schedule-Source": ok ? "kbo" : "bundled" } });
  if (ok) {
    const stored = new Response(res.clone().body, res);
    stored.headers.set("Cache-Control", `public, max-age=${TTL}`);
    waitUntil(cache.put(key, stored));
  }
  return res;
}
