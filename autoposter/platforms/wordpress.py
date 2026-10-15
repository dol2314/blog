"""WordPress: 공식 REST API + 애플리케이션 비밀번호로 접속한다."""

from __future__ import annotations

import html as html_lib
import os

import requests

from ..models import Category, Post, PublishResult
from .base import Platform, PlatformError


class WordPress(Platform):
    key = "wordpress"
    display_name = "WordPress"

    def __init__(self, settings: dict, session: requests.Session | None = None):
        super().__init__(settings)
        self.http = session or requests.Session()
        self._api_style: str | None = None  # "pretty" (/wp-json/) 또는 "query" (?rest_route=)

    # ---- 접속 -------------------------------------------------------------

    def login(self, prompt) -> None:
        site = prompt("워드프레스 사이트 주소 (예: https://myblog.com)").strip().rstrip("/")
        if not site.startswith("http"):
            site = "https://" + site
        user = prompt("사용자명 (관리자 로그인 아이디)").strip()
        password = prompt(
            "애플리케이션 비밀번호 (관리자 > 사용자 > 프로필 > 애플리케이션 비밀번호에서 발급)",
            secret=True,
        ).strip()
        self.settings.update(site=site, username=user, app_password=password)
        self._api_style = None
        if not self.is_logged_in():
            raise PlatformError("로그인에 실패했습니다. 사이트 주소, 사용자명, 애플리케이션 비밀번호를 확인하세요.")

    def is_logged_in(self) -> bool:
        if not self.settings.get("site") or not self.settings.get("username"):
            return False
        try:
            resp = self._request("GET", "users/me", params={"context": "edit"})
        except PlatformError:
            return False
        return resp.status_code == 200

    # ---- 카테고리 -----------------------------------------------------------

    def get_categories(self) -> list[Category]:
        raw: list[dict] = []
        page = 1
        while True:
            resp = self._request("GET", "categories", params={"per_page": 100, "page": page, "hide_empty": "false"})
            self._raise_for_status(resp, "카테고리를 가져오지 못했습니다")
            raw.extend(resp.json())
            total_pages = int(resp.headers.get("X-WP-TotalPages", "1") or 1)
            if page >= total_pages:
                break
            page += 1
        names = {c["id"]: c["name"] for c in raw}
        return [
            Category(id=str(c["id"]), name=c["name"], parent=names.get(c.get("parent")) if c.get("parent") else None)
            for c in raw
        ]

    # ---- 발행 -------------------------------------------------------------

    def publish(self, post: Post, category: Category, draft: bool = False) -> PublishResult:
        body = {
            "title": post.title,
            "content": post.html,
            "status": "draft" if draft else "publish",
            "categories": [int(category.id)],
            "tags": [self._tag_id(name) for name in post.tags],
        }
        if post.slug:
            body["slug"] = post.slug  # 새 글을 만들 때만 보낸다. 이미 발행한 글의 주소는 바꾸지 않는다
        if post.excerpt:
            body["excerpt"] = post.excerpt
        if post.meta:
            body["meta"] = post.meta  # 사이트에 등록되지 않은 항목은 워드프레스가 무시한다
        resp = self._request("POST", "posts", json=body)
        self._raise_for_status(resp, "글을 올리지 못했습니다")
        data = resp.json()
        return PublishResult(url=data.get("link"), draft=draft)

    def find_similar(self, query: str, limit: int = 8) -> list[dict]:
        """제목·본문에 검색어가 들어간 기존 글 (중복 글 방지용)."""
        resp = self._request("GET", "posts", params={
            "search": query, "per_page": limit, "status": "publish,future,draft,pending",
            "_fields": "id,title,link,status,date",
        })
        if resp.status_code == 400:  # 권한이 없으면 발행된 글만 본다
            resp = self._request("GET", "posts", params={"search": query, "per_page": limit, "_fields": "id,title,link,status,date"})
        self._raise_for_status(resp, "기존 글을 조회하지 못했습니다")
        return [
            {"title": html_lib.unescape(p["title"]["rendered"]), "link": p.get("link"), "status": p.get("status"),
             "date": p.get("date")}
            for p in resp.json()
        ]

    def _tag_id(self, name: str) -> int:
        resp = self._request("GET", "tags", params={"search": name, "per_page": 100})
        self._raise_for_status(resp, "태그를 조회하지 못했습니다")
        for tag in resp.json():
            if tag["name"].casefold() == name.casefold():
                return tag["id"]
        resp = self._request("POST", "tags", json={"name": name})
        if resp.status_code == 400 and resp.json().get("code") == "term_exists":
            return resp.json()["data"]["term_id"]
        self._raise_for_status(resp, f"태그 '{name}'를 만들지 못했습니다")
        return resp.json()["id"]

    # ---- HTTP -------------------------------------------------------------

    def _auth(self):
        password = os.environ.get("WP_APP_PASSWORD") or self.settings.get("app_password", "")
        return (self.settings.get("username", ""), password.replace(" ", ""))

    def _url(self, route: str, style: str) -> tuple[str, dict]:
        site = self.settings["site"].rstrip("/")
        if style == "pretty":
            return f"{site}/wp-json/wp/v2/{route}", {}
        return f"{site}/", {"rest_route": f"/wp/v2/{route}"}

    def _request(self, method: str, route: str, params: dict | None = None, **kwargs) -> requests.Response:
        # 고유주소(permalink)를 끈 사이트는 /wp-json/ 대신 ?rest_route= 로만 API가 열린다.
        styles = [self._api_style] if self._api_style else ["pretty", "query"]
        resp = None
        for style in styles:
            url, extra = self._url(route, style)
            try:
                resp = self.http.request(
                    method, url, params={**extra, **(params or {})}, auth=self._auth(), timeout=30, **kwargs
                )
            except requests.RequestException as exc:
                raise PlatformError(f"사이트에 연결하지 못했습니다: {exc}") from exc
            if resp.status_code == 404 and self._api_style is None and _not_rest(resp):
                continue
            self._api_style = style
            return resp
        raise PlatformError("이 사이트에서 워드프레스 REST API를 찾지 못했습니다. 주소를 확인하세요.")

    @staticmethod
    def _raise_for_status(resp: requests.Response, message: str) -> None:
        if resp.ok:
            return
        try:
            detail = resp.json().get("message", "")
        except ValueError:
            detail = resp.text[:200]
        raise PlatformError(f"{message} (HTTP {resp.status_code}) {detail}".strip())


def _not_rest(resp: requests.Response) -> bool:
    """404가 REST API 자체가 없어서인지(True), API가 돌려준 404인지(False)."""
    try:
        return "code" not in resp.json()
    except ValueError:
        return True
