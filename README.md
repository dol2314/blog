# 블로그 자동 업로드 프로그램

WordPress, 네이버 블로그, 티스토리 중 하나를 골라 접속한 뒤,
**내 블로그에 실제로 있는 카테고리**를 불러와 고르고,
AI(Claude)가 쓴 글이나 내가 쓴 파일을 자동으로 올려 주는 프로그램입니다.

## 동작 방식

| 플랫폼 | 접속 방법 | 올리는 방법 |
|---|---|---|
| WordPress | 사이트 주소 + 애플리케이션 비밀번호 | 공식 REST API |
| 네이버 블로그 | 열린 브라우저 창에서 **직접 로그인** (최초 1회) | 브라우저 자동 조작 (공식 글쓰기 API 없음) |
| 티스토리 | 열린 브라우저 창에서 **직접 로그인** (최초 1회) | 브라우저 자동 조작 (오픈 API 종료) |

- 네이버·티스토리 비밀번호는 프로그램이 받지도, 저장하지도 않습니다. 로그인 상태(쿠키)만
  `~/.blog-autoposter/profiles/`에 저장해 다음 실행부터 다시 씁니다.
- 설정은 `~/.blog-autoposter/config.json`에 저장됩니다 (워드프레스 애플리케이션 비밀번호 포함).

## Windows에서 가장 쉽게 실행하기

1. [Python](https://www.python.org/downloads/)을 설치합니다. 설치 첫 화면에서 **"Add python.exe to PATH"를 체크**하세요.
2. 이 폴더의 **`실행.bat`을 더블클릭**합니다.
   - 처음 한 번은 필요한 부품을 자동으로 설치합니다(몇 분 걸림). 다음부터는 바로 프로그램 창이 열립니다.
3. 창에서 순서대로 진행합니다.
   - **① 블로그 선택** → [접속하기]
   - **② 카테고리** → [블로그에서 카테고리 불러오기] 후 선택
   - **③ 글 준비** → [AI로 글쓰기] 또는 [파일 선택...]
   - **④ 확인하고 고치기** → 제목·태그·본문 수정, [브라우저로 미리보기]
   - 아래 **[임시저장]** 또는 **[발행하기]**
4. AI 글쓰기는 처음 누를 때 Claude API 키를 물어봅니다. 메뉴 **설정 > Claude API 키 설정**에서 바꿀 수 있습니다.

명령창 메뉴를 쓰고 싶으면 명령창에서 `실행.bat cli`를 실행하세요.
문제가 생기면 `.venv` 폴더를 지우고 다시 실행하면 처음부터 다시 설치합니다.
예상하지 못한 오류 내용은 `%USERPROFILE%\.blog-autoposter\error.log`에 저장됩니다.

## 설치 (직접 하기)

Python 3.10 이상이 필요합니다.

```bash
pip install -r requirements.txt
python -m playwright install chromium   # 크롬이 설치돼 있으면 생략 가능
```

AI 글쓰기를 쓰려면 [Anthropic 콘솔](https://console.anthropic.com)에서 API 키를 발급받아 환경 변수로 넣어 주세요.

```bash
# Windows (PowerShell)
$env:ANTHROPIC_API_KEY = "sk-ant-..."
# macOS / Linux
export ANTHROPIC_API_KEY="sk-ant-..."
```

## 사용법

### 메뉴로 쓰기 (추천)

```bash
python -m autoposter
```

1. 블로그 선택 (WordPress / 네이버 블로그 / 티스토리)
2. 처음이면 접속 (네이버·티스토리는 브라우저 창에서 직접 로그인 후 Enter)
3. 블로그의 카테고리 목록에서 선택
4. AI가 쓰기(주제·말투·분량 입력) 또는 내 파일(.md / .html) 올리기
5. 미리보기 확인 후 **발행 / 임시저장 / 다시 쓰기 / 취소**

### 명령으로 쓰기 (예약 실행용)

```bash
python -m autoposter login naver                 # 접속 정보 저장
python -m autoposter categories naver            # 카테고리 목록 보기
python -m autoposter post naver --category 여행 --topic "제주 3박4일 코스"
python -m autoposter post tistory --category "개발 > 파이썬" --file post.md --tags "파이썬,팁"
python -m autoposter post wordpress --category 일상 --draft --yes
```

- `--draft`: 발행하지 않고 임시저장
- `--yes`: 미리보기 확인 없이 바로 올리기 (예약 실행할 때)
- `--model`: AI 모델 변경 (기본 `claude-opus-5-5`, 더 저렴하게는 `claude-sonnet-5-5`)

### 플랫폼별 준비

- **WordPress**: 관리자 화면 > 사용자 > 프로필 > *애플리케이션 비밀번호*에서 새 비밀번호를 발급하세요.
  설치형 워드프레스 기준입니다. WordPress.com 무료 요금제는 REST API 쓰기가 막혀 있을 수 있습니다.
- **네이버 블로그**: 블로그 아이디는 로그인 후 자동으로 찾습니다. 못 찾으면 직접 물어봅니다.
- **티스토리**: 접속할 때 블로그 주소(`myblog.tistory.com`)를 입력합니다.

## 주의할 점

- **네이버·티스토리는 화면이 바뀌면 동작이 멈출 수 있습니다.** 화면 요소 위치는
  `autoposter/platforms/naver.py`, `tistory.py` 맨 위 `SELECTORS`에 모아 두었으니 그 부분만 고치면 됩니다.
- **자동 업로드는 각 플랫폼 운영정책에 걸릴 수 있습니다.** 짧은 시간에 많은 글을 올리거나
  같은 글을 반복해서 올리면 계정이 제한될 수 있습니다. 하루 1~2편, 사람이 확인한 글을 권장합니다.
- AI가 쓴 글에는 틀린 정보가 섞일 수 있으니, 발행 전 미리보기를 꼭 확인하세요.
- 브라우저 창 없이 실행하려면 `AUTOPOSTER_HEADLESS=1` (로그인할 때는 창이 필요합니다).

## 개발

```bash
pip install pytest
python -m pytest
```

네이버·티스토리 테스트는 실제 사이트 대신 가짜 편집기 화면으로 클릭·입력 흐름을 확인합니다.
실제 사이트 화면이 바뀌었는지는 직접 실행해 봐야 알 수 있습니다.
