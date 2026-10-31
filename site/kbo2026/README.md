# 2026 프로야구 일정 중계 (데모)

정적 사이트: `index.html`(랜딩·남은 일정), `day.html#YYYY-MM-DD`(날짜별 중계 안내), `guide-tv.html`(TV 채널 표기·번호 찾는 법), `guide-tving.html`(모바일 시청법). 글 구조는 질문형 도입 3문단 → 배경색 H2 → 짧은 문단 → "▼" 안내 → 표 또는 빨간 전폭 버튼이며, 버튼과 채널 칩은 모두 사이트 안 페이지로 연결합니다(방송사 사이트로 바로 보내지 않음).

- 데이터: `python site/kbo2026/update_schedule.py` 가 KBO 공식 일정을 받아 `schedule.json` 을 만듭니다. 운영 시 cron 으로 10~30분마다 돌리세요.
- 지난 경기는 페이지가 KST 기준 시작 4시간 뒤(취소 경기는 시작 시각)에 목록에서 빼고, 1분마다 다시 계산합니다. `schedule.json` 은 10분마다 다시 읽습니다.
- 중계 표기: K-2T KBS 2TV, M-T MBC, S-T SBS, KN-T KBS N SPORTS, MS-T MBC SPORTS+, SS-T SBS Sports, SPO-T SPOTV, SPO-2T SPOTV2 (`common.js` 의 `CHANNELS`).
- 미리보기: `cd site/kbo2026 && python -m http.server` 후 http://127.0.0.1:8000
