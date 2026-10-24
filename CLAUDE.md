# Claude Code setup

## Blog autoposter

`autoposter/` is a Python CLI (`python -m autoposter`) that uploads posts to WordPress (REST API), Naver Blog and Tistory (Playwright browser automation). Naver/Tistory selectors live in the `SELECTORS` dict at the top of each platform module. The desktop app is `autoposter/app/` (`python -m autoposter.app`, launched by `실행.bat`): a 127.0.0.1 HTTP server with a per-run token (`server.py`) serving a vanilla HTML/CSS/JS dashboard (`static/`), opened as an Edge/Chrome `--app` window. Long work runs as jobs on two single-thread runners (platform, ai); platform objects are only touched on the platform runner because Playwright's sync API is thread-bound. Local AI is Ollama + Qwen3 (`local_ai.py`, Apache 2.0); Claude is optional (`writer.py`). Post history lives in `~/.blog-autoposter/posts.json`. Structured AI calls for style analysis (`style.py`), refine and fact-check (`factcheck.py`) go through `llm.generate_json`; official-source search and page reading live in `web.py`. The WordPress "워프 공식" writing mode (`formula.py` + `keywords.py`) collects Naver autocomplete phrases, writes structured sections, assembles Gutenberg blocks with a CTA box and buttons, and checks that every phrase appears verbatim; `slug`/`meta` on `Post` are only sent when creating a WordPress post (DuckDuckGo/Bing HTML limited to government domains, headless-browser fallback for JS pages). Run tests with `python -m pytest`; browser tests need Chromium (set `AUTOPOSTER_BROWSER_PATH`, e.g. `/opt/pw-browsers/chromium` in cloud sessions). User-facing text is Korean.

## REA (Reverse Engineer Anything)

This repo registers [REA](https://github.com/morluto/rea) for Claude Code:

- `.mcp.json` — project-scoped MCP server `rea`, launched with `npx -y rea-agents@6.4.0 mcp` (stdio). Requires Node.js 22.19+ / 24.11+ / 26+.
- `.claude/settings.json` — auto-approves the `rea` server from `.mcp.json`.
- `.claude/skills/reverse-engineer-anything/` — REA's workflow skill, copied from morluto/rea@2f3dee3 (MIT, see LICENSE in that folder).

Static JavaScript/Electron, archive, Go, PE resource and similar analyses work out of the box.
Native decompilation needs Hopper, Ghidra or IDA installed on the host; see https://rea.tools/guides/native/.

To upgrade, bump the version in `.mcp.json` and re-copy the skill from the matching REA release.

## YouTube agent skills

`.claude/skills/yt-*` are the eleven YouTube skills from [Jakeschincariol/youtube-agent-skill](https://github.com/Jakeschincariol/youtube-agent-skill)@a2feb21 (MIT, licence in `.claude/youtube/LICENSE-youtube-agent-skill`). Their Python tools are stdlib-only and read local files. The voice profile template is `.claude/youtube/voice.md`; the skills were edited only to also read that project path. The hook scorer and title linter are calibrated on English.
