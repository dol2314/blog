from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Category:
    """블로그에 실제로 존재하는 카테고리."""

    id: str
    name: str
    parent: str | None = None  # 상위 카테고리 이름 (없으면 None)

    @property
    def label(self) -> str:
        return f"{self.parent} > {self.name}" if self.parent else self.name


@dataclass
class Post:
    title: str
    html: str
    tags: list[str] = field(default_factory=list)
    slug: str | None = None  # 워드프레스 주소 (발행 후에는 바꾸지 않는다)
    meta: dict = field(default_factory=dict)  # 워드프레스 추가 정보 (예: Rank Math 포커스 키워드)
    excerpt: str | None = None


@dataclass
class PublishResult:
    url: str | None
    draft: bool
