"""작성한 글 기록 (~/.blog-autoposter/posts.json)."""

from __future__ import annotations

import json
import threading
import time
import uuid

from .. import config

STATUSES = ("draft", "saved", "published")  # AI 초안 / 임시저장 / 발행


class PostStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.path = config.HOME / "posts.json"
        self.posts: list[dict] = self._load()

    def _load(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _save(self) -> None:
        config.HOME.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.posts, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def all(self) -> list[dict]:
        with self.lock:
            return sorted(self.posts, key=lambda p: p["created"], reverse=True)

    def get(self, post_id: str) -> dict | None:
        with self.lock:
            return next((p for p in self.posts if p["id"] == post_id), None)

    def add(self, **fields) -> dict:
        now = time.time()
        post = {
            "id": uuid.uuid4().hex[:10],
            "title": "",
            "html": "",
            "tags": [],
            "category": None,
            "platform": None,
            "status": "draft",
            "url": None,
            "engine": None,
            "topic": None,
            "created": now,
            "updated": now,
        }
        post.update(fields)
        with self.lock:
            self.posts.append(post)
            self._save()
        return post

    def update(self, post_id: str, **fields) -> dict | None:
        with self.lock:
            post = next((p for p in self.posts if p["id"] == post_id), None)
            if post is None:
                return None
            post.update(fields)
            post["updated"] = time.time()
            self._save()
            return dict(post)

    def delete(self, post_id: str) -> bool:
        with self.lock:
            before = len(self.posts)
            self.posts = [p for p in self.posts if p["id"] != post_id]
            self._save()
            return len(self.posts) != before
