"""유튜브 자동 업로드 모듈 (YouTube Data API v3).

준비 (한 번만):
1. https://console.cloud.google.com → 새 프로젝트 → 「API 및 서비스 → 라이브러리」에서 YouTube Data API v3 사용
2. 「OAuth 동의 화면」 구성(외부, 테스트 사용자에 내 구글 계정 추가)
3. 「사용자 인증 정보 → OAuth 클라이언트 ID → 데스크톱 앱」 만들고 JSON 을 client_secret.json 으로 저장
첫 업로드 때 브라우저가 열려 로그인·허용하면 youtube_token.json 이 저장되어 다음부터는 자동입니다.

주의: 검수(감사)를 받지 않은 API 프로젝트로 올린 영상은 유튜브 정책상 「비공개」로 고정될 수 있습니다.
공개 업로드가 필요하면 Google 의 API 감사(Audit)를 신청하세요. 기본 할당량은 하루 10,000 단위(업로드 1회 약 1,600).
"""
from __future__ import annotations

import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import ROOT, env

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube"]
KST = timezone(timedelta(hours=9))
RETRY_STATUS = {500, 502, 503, 504}


def get_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    secrets = Path(env("YOUTUBE_CLIENT_SECRETS", "client_secret.json"))
    token = Path(env("YOUTUBE_TOKEN_FILE", "youtube_token.json"))
    secrets = secrets if secrets.is_absolute() else ROOT / secrets
    token = token if token.is_absolute() else ROOT / token
    creds = Credentials.from_authorized_user_file(str(token), SCOPES) if token.exists() else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not secrets.exists():
            raise FileNotFoundError(f"OAuth 클라이언트 파일이 없습니다: {secrets} (youtube_uploader.py 맨 위 안내 참고)")
        creds = InstalledAppFlow.from_client_secrets_file(str(secrets), SCOPES).run_local_server(port=0)
    token.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds)


def parse_publish_at(value: str | None) -> str | None:
    """'2026-11-06 18:00'(한국 시간) 또는 ISO 8601 → YouTube 가 받는 UTC RFC3339."""
    if not value:
        return None
    v = value.strip().replace(" ", "T")
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    if dt <= datetime.now(timezone.utc) + timedelta(minutes=15):
        raise ValueError("예약 발행 시각은 지금보다 15분 이상 뒤여야 합니다.")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def upload_video(path: Path, title: str, description: str = "", tags: list[str] | None = None,
                 privacy: str = "private", publish_at: str | None = None, category_id: str = "22",
                 made_for_kids: bool = False, thumbnail: Path | None = None, captions: Path | None = None,
                 shorts: bool = True) -> str:
    """영상을 올리고 video id 를 돌려준다. publish_at 을 주면 비공개로 올린 뒤 그 시각에 자동 공개."""
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    yt = get_service()
    if shorts and "#shorts" not in (title + description).lower():
        description = (description + "\n\n#Shorts").strip()
    status = {"privacyStatus": privacy, "selfDeclaredMadeForKids": made_for_kids}
    when = parse_publish_at(publish_at)
    if when:
        status.update(privacyStatus="private", publishAt=when)  # 예약 발행은 private 이어야 함
    body = {
        "snippet": {"title": title[:100], "description": description[:4900], "tags": (tags or [])[:30],
                    "categoryId": category_id, "defaultLanguage": "ko", "defaultAudioLanguage": "ko"},
        "status": status,
    }
    media = MediaFileUpload(str(path), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response, attempt = None, 0
    while response is None:
        try:
            progress, response = request.next_chunk()
            if progress:
                print(f"  업로드 {int(progress.progress() * 100)}%")
        except HttpError as e:
            if e.resp.status not in RETRY_STATUS or attempt >= 5:
                raise
            attempt += 1
            time.sleep(min(60, 2 ** attempt + random.random()))
    video_id = response["id"]
    if thumbnail and Path(thumbnail).exists():
        try:  # 맞춤 썸네일은 휴대폰 인증된 채널만 가능
            yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumbnail))).execute()
        except HttpError as e:
            print(f"  썸네일 설정 실패(채널 인증 필요할 수 있음): {e}")
    if captions and Path(captions).exists():
        try:
            yt.captions().insert(part="snippet", body={"snippet": {"videoId": video_id, "language": "ko",
                                                                   "name": "한국어", "isDraft": False}},
                                 media_body=MediaFileUpload(str(captions), mimetype="application/octet-stream")).execute()
        except HttpError as e:
            print(f"  자막 업로드 실패: {e}")
    return video_id
