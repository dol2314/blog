"""창 화면(GUI). `python -m autoposter.gui`로 실행한다.

화면은 메인 스레드에서만 다루고, 로그인·카테고리·글쓰기·발행처럼 오래 걸리는 일은
작업 스레드 하나에서 차례로 처리한다. Playwright 브라우저는 만든 스레드에서만
쓸 수 있으므로 플랫폼 객체도 항상 그 작업 스레드에서만 다룬다.
"""

from __future__ import annotations

import os
import queue
import tempfile
import threading
import traceback
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

from . import config
from .cli import PLATFORMS, _has_target, open_platform, parse_tags, post_from_file
from .models import Category, Post
from .platforms.base import PlatformError
from .writer import DEFAULT_MODEL, WriterError, write_post

APP_TITLE = "블로그 자동 업로드"
MODELS = {
    "고품질 (Claude Opus 5.5)": "claude-opus-5-5",
    "절약형 (Claude Sonnet 5.5)": "claude-sonnet-5-5",
}
TONES = ["친근한 존댓말", "전문적인 존댓말", "편안한 반말", "정보 전달 위주"]
APP_DIR = Path(__file__).resolve().parent.parent


class Cancelled(Exception):
    """사용자가 입력 창에서 취소를 눌렀다."""


class Worker:
    """작업 스레드 하나에서 일을 차례로 처리하고, 결과를 화면 스레드로 돌려준다."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.tasks: queue.Queue = queue.Queue()
        self.ui_calls: queue.Queue = queue.Queue()
        threading.Thread(target=self._loop, daemon=True).start()
        self._poll()

    def submit(self, fn, on_done=None, on_error=None) -> None:
        self.tasks.put((fn, on_done, on_error))

    def call_ui(self, fn) -> None:
        self.ui_calls.put(fn)

    def ask_ui(self, fn):
        """작업 스레드에서 화면 스레드의 대화상자를 띄우고 답을 기다린다."""
        done = threading.Event()
        box: dict = {}

        def run():
            try:
                box["value"] = fn()
            except BaseException as exc:  # noqa: BLE001
                box["error"] = exc
            done.set()

        self.call_ui(run)
        done.wait()
        if "error" in box:
            raise box["error"]
        return box["value"]

    def _loop(self):
        while True:
            fn, on_done, on_error = self.tasks.get()
            if fn is None:
                break
            try:
                result = fn()
            except BaseException as exc:  # noqa: BLE001
                if on_error:
                    self.call_ui(lambda exc=exc: on_error(exc))
            else:
                if on_done:
                    self.call_ui(lambda result=result: on_done(result))

    def _poll(self):
        try:
            while True:
                self.ui_calls.get_nowait()()
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def stop(self, timeout: float = 5.0):
        done = threading.Event()
        self.tasks.put((done.set, None, None))
        self.tasks.put((None, None, None))
        done.wait(timeout)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = config.load()
        self.worker = Worker(root)
        self.platform = None  # 작업 스레드에서만 다룬다
        self.platform_key: str | None = None
        self.categories: list[Category] = []
        self.last_url: str | None = None
        self.busy_widgets: list[tk.Widget] = []

        root.title(APP_TITLE)
        height = min(820, root.winfo_screenheight() - 80)  # 작업 표시줄에 가리지 않게
        root.geometry(f"1100x{height}+40+20")
        root.minsize(900, 600)
        self._setup_style()
        self._build()
        self._load_api_key()
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        default_key = self.cfg.get("last_platform", "naver")
        self.platform_var.set(default_key if default_key in PLATFORMS else "naver")
        self.on_platform_change()

    # ---- 화면 구성 ----------------------------------------------------------

    def _setup_style(self):
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
        family = "맑은 고딕" if os.name == "nt" else "WenQuanYi Zen Hei"
        self.font = (family, 10)
        self.root.option_add("*Font", self.font)
        style.configure(".", font=self.font)
        style.configure("Title.TLabel", font=(family, 16, "bold"), foreground="#1f3b73")
        style.configure("Step.TLabelframe.Label", font=(family, 11, "bold"))
        style.configure("Accent.TButton", font=(family, 11, "bold"), padding=(16, 8))
        style.configure("Status.TLabel", foreground="#555555")

    def _build(self):
        root = self.root
        menubar = tk.Menu(root)
        settings = tk.Menu(menubar, tearoff=False)
        settings.add_command(label="Claude API 키 설정...", command=self.edit_api_key)
        settings.add_command(label="설정 폴더 열기", command=lambda: _open_path(config.HOME))
        menubar.add_cascade(label="설정", menu=settings)
        root.config(menu=menubar)

        outer = ttk.Frame(root, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=APP_TITLE, style="Title.TLabel").pack(anchor="w", pady=(0, 10))
        self._build_bottom(outer)  # 창이 작아져도 발행 버튼이 가려지지 않게 먼저 아래에 붙인다

        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body, width=340)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 14))
        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")

        self._build_platform_step(left)
        self._build_category_step(left)
        self._build_source_step(left)
        self._build_editor(right)

    def _build_platform_step(self, parent):
        box = ttk.Labelframe(parent, text="① 블로그 선택", style="Step.TLabelframe", padding=10)
        box.pack(fill="x", pady=(0, 10))
        self.platform_var = tk.StringVar()
        for key, (name, _, _) in PLATFORMS.items():
            radio = ttk.Radiobutton(
                box, text=name, value=key, variable=self.platform_var, command=self.on_platform_change
            )
            radio.pack(anchor="w", pady=1)
            self.busy_widgets.append(radio)
        row = ttk.Frame(box)
        row.pack(fill="x", pady=(8, 0))
        self.login_button = ttk.Button(row, text="접속하기", command=self.on_login)
        self.login_button.pack(side="left")
        self.busy_widgets.append(self.login_button)
        self.login_status = ttk.Label(box, text="", style="Status.TLabel", wraplength=300)
        self.login_status.pack(anchor="w", pady=(6, 0))

    def _build_category_step(self, parent):
        box = ttk.Labelframe(parent, text="② 카테고리", style="Step.TLabelframe", padding=10)
        box.pack(fill="x", pady=(0, 10))
        self.category_var = tk.StringVar()
        self.category_box = ttk.Combobox(box, textvariable=self.category_var, state="readonly", width=32)
        self.category_box.pack(fill="x")
        load = ttk.Button(box, text="블로그에서 카테고리 불러오기", command=self.on_load_categories)
        load.pack(anchor="w", pady=(8, 0))
        self.busy_widgets.append(load)

    def _build_source_step(self, parent):
        box = ttk.Labelframe(parent, text="③ 글 준비", style="Step.TLabelframe", padding=10)
        box.pack(fill="both", expand=True)
        tabs = ttk.Notebook(box)
        tabs.pack(fill="both", expand=True)

        ai = ttk.Frame(tabs, padding=8)
        tabs.add(ai, text="AI로 쓰기")
        ai.columnconfigure(1, weight=1)
        self.topic_var = tk.StringVar()
        self.tone_var = tk.StringVar(value=TONES[0])
        self.length_var = tk.StringVar(value="2000")
        self.extra_var = tk.StringVar()
        self.model_var = tk.StringVar(value=_model_label(DEFAULT_MODEL))
        rows = [
            ("주제/키워드", ttk.Entry(ai, textvariable=self.topic_var)),
            ("말투", ttk.Combobox(ai, textvariable=self.tone_var, values=TONES)),
            ("분량(글자)", ttk.Spinbox(ai, textvariable=self.length_var, from_=500, to=6000, increment=500)),
            ("추가 요청", ttk.Entry(ai, textvariable=self.extra_var)),
            ("AI 모델", ttk.Combobox(ai, textvariable=self.model_var, values=list(MODELS), state="readonly")),
        ]
        for i, (label, widget) in enumerate(rows):
            ttk.Label(ai, text=label).grid(row=i, column=0, sticky="w", pady=3, padx=(0, 6))
            widget.grid(row=i, column=1, sticky="ew", pady=3)
        ttk.Label(ai, text="주제를 비우면 카테고리에 맞춰 AI가 정합니다.", style="Status.TLabel").grid(
            row=len(rows), column=0, columnspan=2, sticky="w", pady=(2, 6)
        )
        write = ttk.Button(ai, text="AI로 글쓰기", command=self.on_write)
        write.grid(row=len(rows) + 1, column=0, columnspan=2, sticky="ew")
        self.busy_widgets.append(write)

        file_tab = ttk.Frame(tabs, padding=8)
        tabs.add(file_tab, text="파일 불러오기")
        ttk.Label(
            file_tab, text="직접 쓴 마크다운(.md) 또는 HTML(.html) 파일을\n불러와 오른쪽 편집 칸에 채웁니다.", justify="left"
        ).pack(anchor="w")
        pick = ttk.Button(file_tab, text="파일 선택...", command=self.on_open_file)
        pick.pack(anchor="w", pady=(10, 0))
        self.busy_widgets.append(pick)

    def _build_editor(self, parent):
        box = ttk.Labelframe(parent, text="④ 확인하고 고치기", style="Step.TLabelframe", padding=10)
        box.pack(fill="both", expand=True)
        box.columnconfigure(1, weight=1)
        box.rowconfigure(2, weight=1)
        self.title_var = tk.StringVar()
        self.tags_var = tk.StringVar()
        ttk.Label(box, text="제목").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(box, textvariable=self.title_var).grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Label(box, text="태그").grid(row=1, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(box, textvariable=self.tags_var).grid(row=1, column=1, sticky="ew", pady=3)
        ttk.Label(box, text="본문\n(HTML)").grid(row=2, column=0, sticky="nw", padx=(0, 6), pady=3)
        self.body_text = ScrolledText(box, wrap="word", undo=True, font=self.font, height=20)
        self.body_text.grid(row=2, column=1, sticky="nsew", pady=3)
        tools = ttk.Frame(box)
        tools.grid(row=3, column=1, sticky="w", pady=(4, 0))
        ttk.Button(tools, text="브라우저로 미리보기", command=self.on_preview).pack(side="left")
        ttk.Label(tools, text="  태그는 쉼표로 구분합니다.", style="Status.TLabel").pack(side="left")

    def _build_bottom(self, parent):
        bar = ttk.Frame(parent)
        bar.pack(side="bottom", fill="x", pady=(12, 0))
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=160)
        self.progress.pack(side="left")
        self.status = ttk.Label(bar, text="준비됨", style="Status.TLabel")
        self.status.pack(side="left", padx=10)
        publish = ttk.Button(bar, text="발행하기", style="Accent.TButton", command=lambda: self.on_publish(False))
        publish.pack(side="right")
        draft = ttk.Button(bar, text="임시저장", command=lambda: self.on_publish(True))
        draft.pack(side="right", padx=8)
        self.open_post_button = ttk.Button(bar, text="올린 글 열기", command=self.on_open_post, state="disabled")
        self.open_post_button.pack(side="right")
        self.busy_widgets += [publish, draft]

    # ---- 공통 동작 ----------------------------------------------------------

    def run(self, message: str, fn, on_done=None):
        """오래 걸리는 일을 작업 스레드에서 돌리고, 그동안 버튼을 잠근다."""
        self._set_busy(True, message)

        def done(result):
            self._set_busy(False, "완료")
            if on_done:
                on_done(result)

        def failed(exc):
            self._set_busy(False, "오류")
            if isinstance(exc, Cancelled):
                self.status.config(text="취소했습니다")
                return
            if isinstance(exc, (PlatformError, WriterError)):
                messagebox.showerror(APP_TITLE, str(exc), parent=self.root)
            else:
                _log_error(exc)
                messagebox.showerror(
                    APP_TITLE,
                    f"예상하지 못한 오류가 났습니다.\n\n{type(exc).__name__}: {exc}\n\n"
                    f"자세한 내용은 {config.HOME / 'error.log'} 에 저장했습니다.",
                    parent=self.root,
                )

        self.worker.submit(fn, done, failed)

    def _set_busy(self, busy: bool, message: str):
        for widget in self.busy_widgets:
            widget.config(state="disabled" if busy else "normal")
        self.category_box.config(state="disabled" if busy else "readonly")
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()
        self.status.config(text=message)

    def gui_prompt(self, question: str, secret: bool = False, allow_empty: bool = False, default: str | None = None):
        """플랫폼 login()이 부르는 질문 함수를 대화상자로 바꾼다 (작업 스레드에서 호출)."""

        def show():
            if "Enter를 누르세요" in question:
                ok = messagebox.askokcancel(
                    "로그인",
                    "열린 브라우저 창에서 로그인을 마친 뒤 [확인]을 눌러 주세요.\n"
                    "로그인이 확인되면 자동으로 다음 단계로 넘어갑니다.",
                    parent=self.root,
                )
                if not ok:
                    raise Cancelled()
                return ""
            answer = simpledialog.askstring(
                "접속 정보", question, parent=self.root, show="*" if secret else None, initialvalue=default or ""
            )
            if answer is None:
                raise Cancelled()
            return answer

        while True:
            answer = self.worker.ask_ui(show).strip()
            if answer or allow_empty:
                return answer
            if default is not None:
                return default

    # ---- 블로그 / 접속 ------------------------------------------------------

    def on_platform_change(self):
        key = self.platform_var.get()
        self.cfg["last_platform"] = key
        self.categories = []
        self.category_box.config(values=[])
        self.category_var.set("")
        self._refresh_login_status()

        def switch():
            if self.platform is not None:
                self.platform.close()
            self.platform = open_platform(key, self.cfg)
            self.platform_key = key

        self.worker.submit(switch)

    def _refresh_login_status(self):
        key = self.platform_var.get()
        s = self.cfg.get(key, {})
        target = s.get("site") or s.get("blog_id") or s.get("blog_name")
        if target:
            self.login_status.config(text=f"저장된 접속 정보: {target}\n카테고리를 불러오면 접속 상태를 확인합니다.")
            self.login_button.config(text="다시 접속하기")
        else:
            hint = (
                "사이트 주소와 애플리케이션 비밀번호로 접속합니다."
                if key == "wordpress"
                else "브라우저 창이 열리면 직접 로그인해 주세요. 비밀번호는 저장하지 않습니다."
            )
            self.login_status.config(text=f"아직 접속하지 않았습니다.\n{hint}")
            self.login_button.config(text="접속하기")

    def on_login(self):
        def task():
            self.platform.login(self.gui_prompt)
            config.save(self.cfg)
            return self.platform.get_categories()

        def done(categories):
            self._refresh_login_status()
            self._set_categories(categories)
            self.status.config(text="접속 완료")

        self.run("접속하는 중...", task, done)

    def on_load_categories(self):
        def task():
            if not _has_target(self.platform) or not self.platform.is_logged_in():
                raise PlatformError("먼저 [접속하기]를 눌러 블로그에 접속해 주세요.")
            return self.platform.get_categories()

        self.run("카테고리를 불러오는 중...", task, self._set_categories)

    def _set_categories(self, categories: list[Category]):
        self.categories = categories
        labels = [c.label for c in categories]
        self.category_box.config(values=labels)
        if labels and self.category_var.get() not in labels:
            self.category_var.set(labels[0])
        if not labels:
            messagebox.showwarning(APP_TITLE, "카테고리가 없습니다. 블로그에서 카테고리를 먼저 만들어 주세요.")

    def selected_category(self) -> Category | None:
        label = self.category_var.get()
        return next((c for c in self.categories if c.label == label), None)

    # ---- 글 준비 ------------------------------------------------------------

    def on_write(self):
        category = self.selected_category()
        if not category:
            messagebox.showinfo(APP_TITLE, "먼저 ② 카테고리를 불러와 골라 주세요.\n카테고리에 맞춰 글을 씁니다.")
            return
        if not os.environ.get("ANTHROPIC_API_KEY") and not self.edit_api_key():
            return
        length = int(self.length_var.get()) if self.length_var.get().isdigit() else 2000
        args = dict(
            category=category.name,
            topic=self.topic_var.get().strip() or None,
            tone=self.tone_var.get().strip() or TONES[0],
            length=length,
            extra=self.extra_var.get().strip() or None,
            model=MODELS.get(self.model_var.get(), DEFAULT_MODEL),
        )
        self.run("AI가 글을 쓰는 중... (1~2분 걸릴 수 있습니다)", lambda: write_post(**args), self._fill_editor)

    def on_open_file(self):
        path = filedialog.askopenfilename(
            parent=self.root,
            title="글 파일 선택",
            filetypes=[("글 파일", "*.md *.markdown *.html *.htm *.txt"), ("모든 파일", "*.*")],
        )
        if not path:
            return
        try:
            post = post_from_file(Path(path), parse_tags(self.tags_var.get()))
        except (OSError, UnicodeDecodeError) as exc:
            messagebox.showerror(APP_TITLE, f"파일을 읽지 못했습니다.\n{exc}")
            return
        self._fill_editor(post)
        self.status.config(text=f"불러옴: {Path(path).name}")

    def _fill_editor(self, post: Post):
        self.title_var.set(post.title)
        self.tags_var.set(", ".join(post.tags))
        self.body_text.delete("1.0", "end")
        self.body_text.insert("1.0", post.html)
        self.status.config(text="글이 준비됐습니다. 확인하고 고친 뒤 발행하세요.")

    def current_post(self) -> Post | None:
        title = self.title_var.get().strip()
        body = self.body_text.get("1.0", "end").strip()
        if not title or not body:
            messagebox.showinfo(APP_TITLE, "제목과 본문을 채워 주세요.")
            return None
        return Post(title=title, html=body, tags=parse_tags(self.tags_var.get()))

    def on_preview(self):
        post = self.current_post()
        if not post:
            return
        page = (
            "<!doctype html><meta charset='utf-8'><title>미리보기</title>"
            "<body style='max-width:760px;margin:40px auto;font-family:sans-serif;line-height:1.7'>"
            f"<h1>{_escape(post.title)}</h1>{post.html}"
            f"<p style='color:#888'>태그: {_escape(', '.join(post.tags))}</p></body>"
        )
        path = Path(tempfile.gettempdir()) / "blog-autoposter-preview.html"
        path.write_text(page, encoding="utf-8")
        webbrowser.open(path.as_uri())

    # ---- 발행 ---------------------------------------------------------------

    def on_publish(self, draft: bool):
        post = self.current_post()
        category = self.selected_category()
        if not post:
            return
        if not category:
            messagebox.showinfo(APP_TITLE, "② 카테고리를 불러와 골라 주세요.")
            return
        name = PLATFORMS[self.platform_var.get()][0]
        action = "임시저장" if draft else "발행"
        if not messagebox.askyesno(
            APP_TITLE, f"{name}의 '{category.label}' 카테고리에 {action}할까요?\n\n제목: {post.title}", parent=self.root
        ):
            return

        def done(result):
            self.last_url = result.url
            self.open_post_button.config(state="normal" if result.url else "disabled")
            where = result.url or "글 주소는 블로그에서 확인해 주세요."
            self.status.config(text=f"{action} 완료")
            messagebox.showinfo(APP_TITLE, f"{action} 완료!\n\n{where}", parent=self.root)

        self.run(f"{name}에 {action}하는 중...", lambda: self.platform.publish(post, category, draft=draft), done)

    def on_open_post(self):
        if self.last_url:
            webbrowser.open(self.last_url)

    # ---- API 키 -------------------------------------------------------------

    def _load_api_key(self):
        if os.environ.get("ANTHROPIC_API_KEY"):
            return
        key = self.cfg.get("anthropic_api_key")
        legacy = APP_DIR / "api_key.txt"  # 예전 실행.bat이 저장한 키
        if not key and legacy.exists():
            key = legacy.read_text(encoding="utf-8").strip()
        if key:
            os.environ["ANTHROPIC_API_KEY"] = key

    def edit_api_key(self) -> bool:
        key = simpledialog.askstring(
            "Claude API 키",
            "AI 글쓰기에 쓸 Claude API 키를 입력하세요.\n(https://console.anthropic.com 에서 발급)",
            parent=self.root,
            show="*",
        )
        if not key or not key.strip():
            return False
        os.environ["ANTHROPIC_API_KEY"] = key.strip()
        self.cfg["anthropic_api_key"] = key.strip()
        config.save(self.cfg)
        self.status.config(text="API 키를 저장했습니다")
        return True

    # ---- 종료 ---------------------------------------------------------------

    def on_close(self):
        config.save(self.cfg)

        def shutdown():
            if self.platform is not None:
                self.platform.close()

        self.worker.submit(shutdown)
        self.worker.stop()
        self.root.destroy()


def _model_label(model_id: str) -> str:
    return next((label for label, mid in MODELS.items() if mid == model_id), next(iter(MODELS)))


def _escape(text: str) -> str:
    import html

    return html.escape(text)


def _open_path(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(path)  # noqa: S606 - 탐색기로 설정 폴더 열기
    else:
        webbrowser.open(path.as_uri())


def _log_error(exc: BaseException):
    try:
        config.HOME.mkdir(parents=True, exist_ok=True)
        with open(config.HOME / "error.log", "a", encoding="utf-8") as fh:
            fh.write("".join(traceback.format_exception(exc)) + "\n")
    except OSError:
        pass


def main():
    root = tk.Tk()
    try:
        App(root)
    except Exception as exc:  # noqa: BLE001 - 창 없이 실행돼 콘솔이 없으므로 알림 창으로 보여 준다
        _log_error(exc)
        messagebox.showerror(APP_TITLE, f"프로그램을 시작하지 못했습니다.\n{exc}")
        raise
    root.report_callback_exception = lambda *info: (_log_error(info[1]), messagebox.showerror(APP_TITLE, str(info[1])))
    root.mainloop()


if __name__ == "__main__":
    main()
