from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Category, Post, PublishResult


class PlatformError(RuntimeError):
    """사용자에게 그대로 보여줄 수 있는 오류."""


class Platform(ABC):
    key: str
    display_name: str

    def __init__(self, settings: dict):
        # settings는 config.json의 플랫폼 섹션. 값을 바꾸면 호출한 쪽에서 저장한다.
        self.settings = settings

    @abstractmethod
    def login(self, prompt) -> None:
        """접속 정보를 받거나 브라우저 로그인을 진행한다. prompt(질문) -> 답."""

    @abstractmethod
    def is_logged_in(self) -> bool: ...

    @abstractmethod
    def get_categories(self) -> list[Category]: ...

    @abstractmethod
    def publish(self, post: Post, category: Category, draft: bool = False) -> PublishResult: ...

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
