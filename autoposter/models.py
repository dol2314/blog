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


@dataclass
class PublishResult:
    url: str | None
    draft: bool
