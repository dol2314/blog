# TubeForge — AI 유튜브 쇼츠/롱폼 자동 제작

주제 한 줄 → **대본(훅-본문-CTA, 타임스탬프)** → **한국어 음성(edge-tts)** → **자막·배경·BGM 덕킹 영상(.mp4)** → **유튜브 업로드/예약 발행**까지 한 번에 처리합니다.

## 앱으로 쓰기 (윈도우: `TubeForge 실행.bat` 두 번 클릭)

Edge/크롬 앱 창이 열립니다. 화면 구성:

| 화면 | 하는 일 |
|---|---|
| 홈 | 주제 빠른 입력, 제작 종류 카드(나레이션 쇼츠 · 롱폼 · 기사 기반 쇼츠, 준비 중 기능 표시), 제작 흐름, 최근 프로젝트 |
| 새 영상 만들기 ① 소재 | 쇼츠/롱폼, 주제, 길이, 대본 AI, 참고 원문 |
| ② 대본 | 제목·설명·태그, 장면별 문장 편집(훅/본문/마무리, 순서 바꾸기·추가·삭제, 글자 수·예상 초) |
| ③ 목소리·스타일 | 목소리 카드 + 미리듣기, 말하기 속도, 배경·BGM 고르기/올리기 |
| ④ 렌더링 | 진행률 (화면을 떠나도 계속, 왼쪽 아래에 진행 표시) |
| ⑤ 결과·업로드 | 영상 재생, 영상·썸네일·자막 내려받기, 유튜브 업로드·예약, 설명란·타임스탬프 |
| 내 프로젝트 | 썸네일 카드 목록, 눌러서 이어서 작업, 오른쪽 클릭 삭제 |
| 설정 | 대본 AI·API 키·목소리·BGM 볼륨·폰트(.env 저장), 유튜브 연결 안내 |

명령줄로 쓰려면:

```bash
python main.py --topic "오늘의 연예 이슈" --type shorts
```

## 디렉터리 구조

```
tubeforge/
├── main.py                     # CLI: 대본 → 음성 → 영상 → (업로드)
├── TubeForge 실행.bat           # 윈도우: 앱 실행 (처음엔 설치까지)
├── app/                        # 앱: python -m app (127.0.0.1 서버 + Edge/크롬 앱 창)
│   ├── server.py               # 실행마다 새 토큰, 작업 큐, 프로젝트·설정·파일(Range) API
│   └── static/                 # 화면 (index.html · style.css · app.js)
├── requirements.txt
├── .env.example                # 복사해서 .env 로 사용
├── 쇼츠만들기.bat               # 윈도우: 명령줄 버전 (주제 입력 → 바로 영상)
├── modules/
│   ├── config.py               # .env 읽기, 한글 폰트 자동 탐색
│   ├── pipeline.py             # CLI·앱 공용 단계: 대본 → 렌더링 → 업로드, 프로젝트 폴더 관리
│   ├── script_generator.py     # 대본 생성 (Claude / OpenAI / Ollama / template)
│   ├── tts_engine.py           # 음성 합성 (edge-tts 기본, ElevenLabs, dummy) + 단어 타이밍 → 자막 큐, SRT
│   ├── video_composer.py       # moviepy 렌더링: 9:16/16:9, 켄 번스 배경, 싱크 자막, 제목, 진행 막대, BGM 덕킹, 썸네일
│   └── youtube_uploader.py     # YouTube Data API v3 업로드, 예약 발행, 썸네일·자막 업로드
├── assets/
│   ├── backgrounds/            # 배경 이미지/영상 (선택)
│   ├── bgm/                    # 배경음악 (선택)
│   └── fonts/                  # 원하는 한글 폰트 (선택)
├── tests/test_pipeline.py      # 오프라인 테스트 (인터넷·키 불필요)
└── output/<날짜_주제>/          # 결과물 (git 에 안 올라감)
    ├── script.json · script.md  # 대본 + 실제 음성 기준 타임스탬프
    ├── audio/voice.mp3          # 내레이션
    ├── captions.srt             # 자막 파일 (업로드 시 함께 올라감)
    ├── thumbnail.jpg
    └── final.mp4
```

## 설치

Python 3.10 이상이 필요합니다. FFmpeg 는 따로 설치하지 않아도 됩니다 (`imageio-ffmpeg` 가 자동으로 받습니다).

**윈도우**
```bat
cd tubeforge
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```
또는 `쇼츠만들기.bat` 을 두 번 클릭하면 설치부터 실행까지 알아서 합니다.

**macOS / Linux**
```bash
cd tubeforge
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 실행 예시

```bash
# 1) 가장 빠른 확인: 키 없이 (예시 대본 + 무료 edge-tts 음성)
python main.py --topic "오늘의 연예 이슈" --type shorts --provider template

# 2) AI 대본 (.env 에 ANTHROPIC_API_KEY 또는 OPENAI_API_KEY, 또는 PC에서 Ollama 실행 중)
python main.py --topic "오늘의 연예 이슈" --type shorts

# 3) 기사 원문을 근거로, 60초, 남성 음성, 배경 폴더 + BGM
python main.py --topic "전기요금 개편" --source article.txt --duration 60 \
  --voice ko-KR-InJoonNeural --bg assets/backgrounds --bgm assets/bgm/calm.mp3

# 4) 롱폼 (16:9, 약 5분)
python main.py --topic "AI 반도체 전쟁 정리" --type long --duration 300

# 5) 대본만 먼저 보고 → 손본 뒤 렌더링
python main.py --topic "청년도약계좌" --script-only
python main.py --from-script output/<폴더>/script.json

# 6) 유튜브 예약 발행 (한국 시간)
python main.py --topic "오늘의 연예 이슈" --upload --publish-at "2026-11-07 18:00"

# 인터넷 없이 렌더링만 시험 (무음)
python main.py --topic "테스트" --provider template --tts dummy

# 테스트
python -m pytest tests -q
```

| 옵션 | 설명 |
|---|---|
| `--type shorts\|long` | 1080x1920(9:16) / 1920x1080(16:9) |
| `--duration` | 목표 초 (기본 쇼츠 30, 롱폼 300) |
| `--provider` | `auto`(기본) · `claude` · `openai` · `ollama` · `template` |
| `--tts` | `edge`(기본, 무료) · `elevenlabs` · `dummy` |
| `--voice`, `--rate` | 예: `ko-KR-SunHiNeural`(여), `ko-KR-InJoonNeural`(남), `+15%` |
| `--bg` | 이미지/영상 파일 또는 폴더 (장면마다 돌아가며) — 없으면 그라데이션 자동 |
| `--bgm` | 배경음악 — 말할 때 자동으로 작아짐(`BGM_VOLUME` / `BGM_DUCK_VOLUME`) |
| `--upload`, `--privacy`, `--publish-at` | 업로드, 공개 범위, 예약 발행 |

## 동작 방식

1. **대본**: 장면 단위 JSON(`section`=hook/body/cta, `text`, `visual`)을 받습니다. Claude 는 JSON 스키마 강제 출력(`output_config.format`)을 쓰고, 안전 분류기가 거절하면 서버에서 다른 모델로 다시 시도하도록 `fallbacks: "default"` 를 켜 둡니다. 원문(`--source`)이 있으면 그 안의 사실만 쓰도록 지시합니다.
2. **음성**: 장면마다 따로 합성하고 0.25초 쉼을 넣어 잇습니다. edge-tts 의 단어 경계(WordBoundary) 타이밍을 받아 16자 이내 자막 덩어리로 묶으므로 자막이 말과 맞습니다. 실제 음성 길이로 `script.md` 타임스탬프를 다시 씁니다.
3. **영상**: 장면 경계에서 배경이 바뀌고, 정지 이미지는 천천히 확대됩니다. 자막·제목은 미리 그려 둔 이미지를 필요한 영역만 섞는 방식이라 moviepy 레이어 합성보다 약 3배 빠릅니다 (클라우드 테스트 기준 30초 쇼츠 렌더링 약 55초).
4. **BGM 덕킹**: 말하는 구간(앞 0.12초 ~ 뒤 0.35초)에서 BGM 을 `BGM_DUCK_VOLUME` 으로 낮추고 쉬는 구간에서 `BGM_VOLUME` 으로 올립니다. 0.2초 이동 평균으로 부드럽게 바뀝니다.
5. **업로드**: OAuth(데스크톱 앱) 로그인 1회 후 토큰 저장. 재개 가능 업로드, 5xx 재시도, `publishAt` 예약 발행, 썸네일·SRT 자막 업로드.

## 유튜브 업로드 준비 (한 번만)

1. [Google Cloud 콘솔](https://console.cloud.google.com) → 프로젝트 만들기 → **YouTube Data API v3** 사용 설정
2. **OAuth 동의 화면**: 외부, 테스트 사용자에 내 구글 계정 추가
3. **사용자 인증 정보 → OAuth 클라이언트 ID → 데스크톱 앱** → JSON 다운로드 → `tubeforge/client_secret.json`
4. 첫 `--upload` 때 브라우저 로그인 → `youtube_token.json` 저장, 이후 자동

> Google 의 API 감사를 받지 않은 프로젝트로 올린 영상은 **비공개로 고정**될 수 있습니다. 공개 자동 업로드가 필요하면 감사를 신청하세요. 기본 할당량은 하루 10,000 단위(업로드 1회 약 1,600).

## 주의

- 배경·BGM 은 사용 허가된 소재만 쓰세요. 비워 두면 저작권 걱정 없는 그라데이션 배경을 씁니다.
- AI 대본은 사실 확인 후 올리세요. 연예·시사 주제는 루머·실명 비방이 없는지 특히 확인하세요.
- 유튜브는 AI로 만든 사실적인 합성 콘텐츠에 **변경/합성 콘텐츠 표시**를 요구할 수 있습니다 (업로드 후 스튜디오에서 설정).
- edge-tts 는 Microsoft 의 공개 읽기 기능을 쓰는 비공식 라이브러리입니다. 대량·상업 운영에는 ElevenLabs 등 정식 TTS 를 검토하세요 (`--tts elevenlabs`).
