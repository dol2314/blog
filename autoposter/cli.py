"""실행 화면. `python -m autoposter`로 메뉴를 띄우거나, 하위 명령으로 바로 실행한다."""

from __future__ import annotations

import argparse
import getpass
import html as html_lib
import re
import sys
from pathlib import Path

from . import config
from .models import Category, Post
from .platforms.base import Platform, PlatformError
from .textutil import markdown_to_html
from .writer import DEFAULT_MODEL, WriterError, write_post

PLATFORMS = {
    "wordpress": ("WordPress", "autoposter.platforms.wordpress", "WordPress"),
    "naver": ("네이버 블로그", "autoposter.platforms.naver", "NaverBlog"),
    "tistory": ("티스토리", "autoposter.platforms.tistory", "Tistory"),
}


# ---- 입력 도우미 ------------------------------------------------------------


def ask(question: str, secret: bool = False, allow_empty: bool = False, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        text = f"{question}{suffix}: "
        answer = getpass.getpass(text) if secret else input(text)
        answer = answer.strip()
        if not answer and default is not None:
            return default
        if answer or allow_empty:
            return answer
        print("값을 입력해 주세요.")


def choose(title: str, options: list[str]) -> int:
    print(f"\n{title}")
    for number, option in enumerate(options, 1):
        print(f"  {number}) {option}")
    while True:
        answer = input("번호 선택: ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return int(answer) - 1
        print(f"1~{len(options)} 사이 번호를 입력해 주세요.")


# ---- 플랫폼 -----------------------------------------------------------------


def open_platform(key: str, cfg: dict) -> Platform:
    import importlib

    _, module_name, class_name = PLATFORMS[key]
    cls = getattr(importlib.import_module(module_name), class_name)
    return cls(config.section(cfg, key))


def ensure_login(platform: Platform, cfg: dict, force: bool = False) -> None:
    if not force and platform.is_logged_in() and _has_target(platform):
        return
    print(f"\n[{platform.display_name}] 접속을 시작합니다.")
    platform.login(ask)
    config.save(cfg)
    print("접속 완료. 다음부터는 저장된 접속 정보를 씁니다.")


def _has_target(platform: Platform) -> bool:
    s = platform.settings
    return bool(s.get("site") or s.get("blog_id") or s.get("blog_name"))


def find_category(categories: list[Category], name: str) -> Category:
    for category in categories:
        if name in (category.name, category.label, category.id):
            return category
    available = ", ".join(c.label for c in categories)
    raise PlatformError(f"카테고리 '{name}'가 없습니다. 있는 카테고리: {available}")


# ---- 글 준비 ----------------------------------------------------------------


def post_from_file(path: Path, tags: list[str]) -> Post:
    return post_from_text(path.name, path.read_text(encoding="utf-8"), tags)


def post_from_text(name: str, text: str, tags: list[str]) -> Post:
    stem = Path(name).stem
    if Path(name).suffix.lower() in (".html", ".htm"):
        match = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", text)
        title = re.sub(r"<[^>]+>", "", match.group(1)).strip() if match else stem
        body = text.replace(match.group(0), "", 1) if match else text
        return Post(title=title, html=body.strip(), tags=tags)
    title, body = markdown_to_html(text)
    return Post(title=title or stem, html=body, tags=tags)


def preview(post: Post) -> None:
    text = re.sub(r"<[^>]+>", " ", post.html)
    text = re.sub(r"\s+", " ", html_lib.unescape(text)).strip()
    print("\n" + "=" * 60)
    print(f"제목: {post.title}")
    print(f"태그: {', '.join(post.tags) or '(없음)'}")
    print(f"본문 ({len(text)}자): {text[:300]}{'...' if len(text) > 300 else ''}")
    print("=" * 60)


def parse_tags(value: str) -> list[str]:
    return [t.strip().lstrip("#") for t in re.split(r"[,\s]+", value) if t.strip().lstrip("#")]


# ---- 메뉴 모드 --------------------------------------------------------------


def interactive() -> int:
    cfg = config.load()
    keys = list(PLATFORMS)
    key = keys[choose("어느 블로그에 올릴까요?", [PLATFORMS[k][0] for k in keys])]

    with open_platform(key, cfg) as platform:
        ensure_login(platform, cfg)

        print("\n블로그 카테고리를 가져오는 중...")
        categories = platform.get_categories()
        if not categories:
            raise PlatformError("카테고리를 하나도 찾지 못했습니다. 블로그에 카테고리를 먼저 만들어 주세요.")
        category = categories[choose("어느 카테고리에 올릴까요?", [c.label for c in categories])]

        source = choose("글은 어떻게 준비할까요?", ["AI(Claude)가 쓰기", "내가 쓴 파일 올리기 (.md / .html)"])
        if source == 0:
            topic = ask("주제나 키워드 (비우면 카테고리에 맞춰 AI가 정함)", allow_empty=True) or None
            tone = ask("말투", default="친근한 존댓말")
            length_text = ask("본문 분량(글자 수)", default="2000")
            length = int(length_text) if length_text.isdigit() else 2000
            extra = ask("추가 요청 (없으면 Enter)", allow_empty=True) or None

            def generate() -> Post:
                print("\nClaude가 글을 쓰는 중... (1~2분 걸릴 수 있습니다)")
                return write_post(category.name, topic, tone, length, extra)

            post = generate()
        else:
            path = Path(ask("파일 경로")).expanduser()
            post = post_from_file(path, parse_tags(ask("태그 (쉼표로 구분, 없으면 Enter)", allow_empty=True)))
            generate = None

        while True:
            preview(post)
            actions = ["발행하기", "임시저장하기"] + (["다시 쓰기"] if generate else []) + ["취소"]
            action = actions[choose("어떻게 할까요?", actions)]
            if action == "다시 쓰기":
                post = generate()
                continue
            if action == "취소":
                print("취소했습니다.")
                return 0
            break

        print(f"\n{platform.display_name}에 올리는 중...")
        result = platform.publish(post, category, draft=(action == "임시저장하기"))
        done = "임시저장 완료" if result.draft else "발행 완료"
        print(f"{done}! {result.url or '(글 주소는 블로그에서 확인해 주세요)'}")
    return 0


# ---- 명령 모드 --------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autoposter", description="WordPress / 네이버 블로그 / 티스토리 자동 업로드")
    sub = parser.add_subparsers(dest="command")

    login = sub.add_parser("login", help="블로그 접속(로그인) 정보 저장")
    login.add_argument("platform", choices=PLATFORMS)

    cats = sub.add_parser("categories", help="블로그 카테고리 목록 보기")
    cats.add_argument("platform", choices=PLATFORMS)

    post = sub.add_parser("post", help="글 쓰고 올리기")
    post.add_argument("platform", choices=PLATFORMS)
    post.add_argument("--category", required=True, help="카테고리 이름 (categories 명령으로 확인)")
    source = post.add_mutually_exclusive_group()
    source.add_argument("--topic", help="AI가 쓸 주제/키워드 (생략하면 AI가 정함)")
    source.add_argument("--file", type=Path, help="직접 쓴 .md/.html 파일")
    post.add_argument("--tags", default="", help="파일로 올릴 때 태그 (쉼표 구분)")
    post.add_argument("--tone", default="친근한 존댓말")
    post.add_argument("--length", type=int, default=2000)
    post.add_argument("--model", default=DEFAULT_MODEL)
    post.add_argument("--draft", action="store_true", help="발행하지 않고 임시저장")
    post.add_argument("--yes", action="store_true", help="미리보기 확인 없이 바로 올리기")
    return parser


def run_command(args) -> int:
    cfg = config.load()
    with open_platform(args.platform, cfg) as platform:
        if args.command == "login":
            ensure_login(platform, cfg, force=True)
            return 0

        if not platform.is_logged_in() or not _has_target(platform):
            raise PlatformError(f"먼저 접속하세요: python -m autoposter login {args.platform}")
        categories = platform.get_categories()

        if args.command == "categories":
            for category in categories:
                print(category.label)
            return 0

        category = find_category(categories, args.category)
        if args.file:
            post = post_from_file(args.file, parse_tags(args.tags))
        else:
            post = write_post(category.name, args.topic, args.tone, args.length, model=args.model)
        preview(post)
        if not args.yes and ask("이대로 올릴까요? (y/n)", default="n").lower() != "y":
            print("취소했습니다.")
            return 0
        result = platform.publish(post, category, draft=args.draft)
        print(("임시저장 완료: " if result.draft else "발행 완료: ") + (result.url or "(글 주소는 블로그에서 확인)"))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run_command(args) if args.command else interactive()
    except (PlatformError, WriterError) as exc:
        print(f"\n오류: {exc}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\n중단했습니다.")
        return 130
