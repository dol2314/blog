# Claude Code setup

## Blog autoposter

`autoposter/` is a Python CLI (`python -m autoposter`) that uploads posts to WordPress (REST API), Naver Blog and Tistory (Playwright browser automation). Naver/Tistory selectors live in the `SELECTORS` dict at the top of each platform module. The Tkinter GUI is `autoposter/gui.py` (`python -m autoposter.gui`, launched by `실행.bat`); platform objects are only touched on its single worker thread because Playwright's sync API is thread-bound. GUI tests need tkinter and a display (`xvfb-run`). Run tests with `python -m pytest`; browser tests need Chromium (set `AUTOPOSTER_BROWSER_PATH`, e.g. `/opt/pw-browsers/chromium` in cloud sessions). User-facing text is Korean.

## REA (Reverse Engineer Anything)

This repo registers [REA](https://github.com/morluto/rea) for Claude Code:

- `.mcp.json` — project-scoped MCP server `rea`, launched with `npx -y rea-agents@6.4.0 mcp` (stdio). Requires Node.js 22.19+ / 24.11+ / 26+.
- `.claude/settings.json` — auto-approves the `rea` server from `.mcp.json`.
- `.claude/skills/reverse-engineer-anything/` — REA's workflow skill, copied from morluto/rea@2f3dee3 (MIT, see LICENSE in that folder).

Static JavaScript/Electron, archive, Go, PE resource and similar analyses work out of the box.
Native decompilation needs Hopper, Ghidra or IDA installed on the host; see https://rea.tools/guides/native/.

To upgrade, bump the version in `.mcp.json` and re-copy the skill from the matching REA release.
