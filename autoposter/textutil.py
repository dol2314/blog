"""글 형식 변환 도구."""

from __future__ import annotations

import html as html_lib
import re


def markdown_to_html(text: str) -> tuple[str | None, str]:
    """간단한 마크다운(제목, 목록, 굵게, 기울임, 인용) → HTML. 첫 '# 제목'은 글 제목으로 쓴다."""
    title = None
    out: list[str] = []
    paragraph: list[str] = []
    list_tag: str | None = None

    def inline(s: str) -> str:
        s = html_lib.escape(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        return re.sub(r"(?<!\*)\*(?!\*)(.+?)\*", r"<em>\1</em>", s)

    def flush():
        nonlocal list_tag
        if paragraph:
            out.append(f"<p>{inline(' '.join(paragraph))}</p>")
            paragraph.clear()
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None

    for line in text.splitlines():
        stripped = line.strip()
        heading = re.match(r"^(#{1,6})\s+(.*)", stripped)
        bullet = re.match(r"^[-*]\s+(.*)", stripped)
        numbered = re.match(r"^\d+[.)]\s+(.*)", stripped)
        if not stripped:
            flush()
        elif heading:
            flush()
            level = len(heading.group(1))
            if level == 1 and title is None:
                title = heading.group(2).strip()
            else:
                out.append(f"<h{max(level, 2)}>{inline(heading.group(2))}</h{max(level, 2)}>")
        elif bullet or numbered:
            tag = "ul" if bullet else "ol"
            if paragraph or list_tag != tag:
                flush()
                out.append(f"<{tag}>")
                list_tag = tag
            out.append(f"<li>{inline((bullet or numbered).group(1))}</li>")
        elif stripped.startswith(">"):
            flush()
            out.append(f"<blockquote>{inline(stripped.lstrip('> '))}</blockquote>")
        else:
            if list_tag:
                flush()
            paragraph.append(stripped)
    flush()
    return title, "\n".join(out)
