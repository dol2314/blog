"""KBO 공식 일정(koreabaseball.com)을 받아 schedule.json 으로 저장한다.

    python site/kbo2026/update_schedule.py            # 2026 시즌 전체
    python site/kbo2026/update_schedule.py --season 2027

운영 사이트에서는 경기일 동안 10~30분마다(cron 등) 돌리면 점수·취소·새 일정
(한국시리즈 대진 확정 등)이 페이지에 반영된다. 지난 경기를 숨기는 일은 페이지가
방문자 시각(KST)으로 직접 한다.
"""
import argparse
import html
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

URL = "https://www.koreabaseball.com/ws/Schedule.asmx/GetScheduleList"
HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Referer": "https://www.koreabaseball.com/Schedule/Schedule.aspx",
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": "Mozilla/5.0",
}
# KBO 일정 API 의 경기 구분 코드
SERIES = {"0": "정규시즌", "1": "시범경기", "4": "와일드카드", "3": "준플레이오프",
          "5": "플레이오프", "7": "한국시리즈", "8": "국제대회", "9": "올스타전"}


def strip(text):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def fetch(season, month, sr):
    body = urllib.parse.urlencode({"leId": "1", "srIdList": sr, "seasonId": season,
                                   "gameMonth": f"{month:02d}", "teamId": ""}).encode()
    req = urllib.request.Request(URL, data=body, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as res:
        return json.load(res)


def parse(data, season, series):
    games, day = [], None
    for row in data.get("rows", []):
        cells = row["row"]
        if cells and cells[0].get("Class") == "day":
            day = strip(cells[0]["Text"])
            cells = cells[1:]
        if len(cells) < 8 or not day:
            continue
        play = cells[1]["Text"] or ""
        spans = re.findall(r"<span[^>]*>(.*?)</span>", play)
        teams = [s for s in spans if s != "vs" and not s.isdigit()]
        score = re.findall(r'<span class="(?:win|lose|same)">(\d+)</span>', play)
        month, dd = re.match(r"(\d+)\.(\d+)", day).groups()
        gid = re.search(r"gameId=(\w+)", cells[2]["Text"] or "")
        note = strip(cells[7]["Text"])
        games.append({
            "d": f"{season}-{int(month):02d}-{int(dd):02d}",
            "t": strip(cells[0]["Text"]),
            "a": teams[0] if teams else "",
            "h": teams[-1] if teams else "",
            "sc": [int(x) for x in score] if len(score) == 2 else None,
            "tv": strip(cells[4]["Text"]).split(),
            "st": strip(cells[6]["Text"]),
            "n": "" if note == "-" else note,
            "sr": series,
            "id": gid.group(1) if gid else "",
        })
    return games


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2026")
    ap.add_argument("--out", default=str(Path(__file__).with_name("schedule.json")))
    args = ap.parse_args()
    games = []
    for sr, name in SERIES.items():
        for month in range(2, 13):
            games += parse(fetch(args.season, month, sr), args.season, name)
            time.sleep(0.2)
    games.sort(key=lambda g: (g["d"], g["t"]))
    out = {"season": args.season, "updated": time.strftime("%Y-%m-%dT%H:%M:%S+09:00",
           time.gmtime(time.time() + 9 * 3600)), "source": "KBO 공식 일정", "games": games}
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(games)}경기 저장 → {args.out}")


if __name__ == "__main__":
    main()
