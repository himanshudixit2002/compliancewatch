"""ComplianceWatch control panel: one window over the whole project.

Its tabs start, stop and watch the dev stack, the services and their workers, the product, the
data, the quality gates, the pipeline, the flags and the checkout's processes. Every button runs a
make target of the repo or a plain program as an argument list, never a shell
(docs/onboarding/control-panel.md lists them); the logic lives in panel_core.py, which needs no
display. Standard library only (tkinter); run it with the repo's Python:

    .venv/bin/python tools/control-panel/control_panel.py

CW_CONTROL_PANEL_REPO points it at another checkout.
"""

from __future__ import annotations

import math
import queue
import threading
import time
import tkinter as tk
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path
from tkinter import messagebox, ttk
from typing import ClassVar, Final

import panel_core as core

# Palette
BG, PANEL, TEXT, MUTED = "#14171c", "#1d2128", "#e6e8eb", "#8b93a1"
GREEN, RED, AMBER, ACCENT = "#3fb950", "#f85149", "#d29922", "#4c8dff"
FIELD, SELECTED = "#0d1015", "#1f4fa8"

STATUS_MS: Final = 4000
SLOW_MS: Final = 30000
KAFKA_MS: Final = 31000  # a little over rpk's 30 s limit, so a tick never meets it
LINE_QUEUE_MAX: Final = 20000

type Action = Callable[[], object]


# ---- small widgets -----------------------------------------------------------------------------
def sentence(text: str) -> str:
    """Text with its first letter capitalised and the rest as written (UI-only stays UI-only)."""
    return text[:1].upper() + text[1:]


def link(parent: tk.Misc, text: str, action: Action, style: str = "Link.TLabel") -> ttk.Label:
    label = ttk.Label(parent, text=text, style=style, cursor="hand2")
    label.bind("<Button-1>", lambda _e: action())
    return label


def heading(parent: tk.Misc, text: str, pady: tuple[int, int] = (0, 6)) -> ttk.Label:
    label = ttk.Label(parent, text=text, style="Head.TLabel")
    label.pack(anchor="w", pady=pady)
    return label


def wrapping(label: ttk.Label, minimum: int = 160) -> ttk.Label:
    """Wrap a label at the width its parent gives it, so its text follows the window's width."""
    label.bind("<Configure>", lambda e: label.configure(wraplength=max(e.width - 4, minimum)))
    return label


def note(parent: tk.Misc, text: str) -> ttk.Label:
    label = ttk.Label(parent, text=text, style="Note.TLabel", wraplength=400, justify="left")
    label.pack(anchor="w", fill="x", pady=(4, 0))
    return wrapping(label)


def card(parent: tk.Misc) -> ttk.Frame:
    frame = ttk.Frame(parent, style="Panel.TFrame", padding=14)
    frame.pack(fill="x", pady=(0, 12))
    return frame


class DotRow:
    """A status line as the panel always drew it: a coloured dot, a name, a detail and links."""

    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        links: Sequence[tuple[str, Action]] = (),
        compact: bool = False,
    ) -> None:
        self.frame = ttk.Frame(parent, style="Panel.TFrame")
        self.frame.pack(fill="x", pady=1 if compact else 2)
        size = 12 if compact else 14
        self.dot = tk.Label(
            self.frame, text="●", fg=MUTED, bg=PANEL, font=("Helvetica", size), bd=0, pady=0
        )
        self.dot.pack(side="left")
        style = "Small.TLabel" if compact else "Panel.TLabel"
        ttk.Label(self.frame, text=text, style=style).pack(side="left", padx=(4 if compact else 6))
        self.detail = ttk.Label(self.frame, text="", style="Muted.TLabel")
        self.detail.pack(side="left")
        for label, action in reversed(links):
            link(self.frame, label, action, "Muted.TLabel").pack(side="right", padx=(8, 0))

    def set(self, state: str, detail: str = "") -> None:
        colours = {"up": GREEN, "down": RED, "partial": AMBER, "off": MUTED}
        self.dot.configure(fg=colours.get(state, MUTED))
        self.detail.configure(text=detail)


def make_tree(
    parent: tk.Misc, columns: Sequence[tuple[str, str, int, bool]], height: int
) -> tuple[ttk.Frame, ttk.Treeview]:
    frame = ttk.Frame(parent, style="Panel.TFrame")
    tree = ttk.Treeview(
        frame, columns=[c[0] for c in columns], show="headings", height=height, selectmode="browse"
    )
    for key, title, width, stretch in columns:
        tree.heading(key, text=title, anchor="w")
        tree.column(key, width=width, minwidth=40, stretch=stretch, anchor="w")
    bar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True)
    for tag, colour in (("up", GREEN), ("down", RED), ("warn", AMBER), ("muted", MUTED)):
        tree.tag_configure(tag, foreground=colour)
    return frame, tree


def sync_rows(tree: ttk.Treeview, rows: Sequence[tuple[str, Sequence[object], str]]) -> None:
    """Update a tree in place, keeping its selection and scroll position."""
    wanted = {iid for iid, _, _ in rows}
    for iid in tree.get_children():
        if iid not in wanted:
            tree.delete(iid)
    for index, (iid, values, tag) in enumerate(rows):
        tags = (tag,) if tag else ()
        if tree.exists(iid):
            tree.item(iid, values=list(values), tags=tags)
            if tree.index(iid) != index:
                tree.move(iid, "", index)
        else:
            tree.insert("", index, iid=iid, values=list(values), tags=tags)


def selected(tree: ttk.Treeview) -> str | None:
    chosen = tree.selection()
    return chosen[0] if chosen else None


def tab_index(book: ttk.Notebook) -> int:
    return int(book.index("current"))  # type: ignore[no-untyped-call]


def select_tab(book: ttk.Notebook, index: int) -> None:
    book.select(index)  # type: ignore[no-untyped-call]


class ScrollFrame(ttk.Frame):
    """A tab's body that scrolls when the window is shorter than its content."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, borderwidth=0)
        self.canvas.configure(yscrollincrement=1)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, padding=(0, 12, 8, 4))
        self._window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=bar.set)
        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

    def _on_inner(self, _event: tk.Event[ttk.Frame]) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, event: tk.Event[tk.Canvas]) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)

    def scroll(self, pixels: int) -> None:
        if self.inner.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(pixels, "units")


def choose(root: tk.Tk, title: str, message: str, options: Sequence[str]) -> str | None:
    """A question with named answers; None when the window is closed."""
    dialog = tk.Toplevel(root, bg=PANEL)
    dialog.title(title)
    dialog.transient(root)
    dialog.resizable(width=False, height=False)
    ttk.Label(
        dialog, text=message, style="Panel.TLabel", wraplength=520, justify="left", padding=18
    ).pack(fill="x")
    answer: list[str | None] = [None]
    row = ttk.Frame(dialog, style="Panel.TFrame", padding=(18, 0, 18, 18))
    row.pack(fill="x")

    def pick(option: str) -> None:
        answer[0] = option
        dialog.destroy()

    for index, option in enumerate(options):
        style = (
            "TButton" if option == "Cancel" else ("Danger.TButton" if index else "Accent.TButton")
        )
        ttk.Button(row, text=option, style=style, command=partial(pick, option)).pack(
            side="left", padx=(0, 8)
        )
    dialog.grab_set()
    dialog.wait_window()
    return answer[0]


# ---- the output pane ---------------------------------------------------------------------------
class Output:
    """Where every step and every read streams: two tabs, Cancel for the running step."""

    MAX_LINES: ClassVar[int] = 6000
    KEYS: ClassVar[tuple[str, ...]] = ("steps", "reads")

    def __init__(self, panel: Panel, parent: tk.Misc) -> None:
        self.panel = panel
        self.frame = ttk.Frame(parent, style="Panel.TFrame", padding=(14, 10, 14, 12))
        head = ttk.Frame(self.frame, style="Panel.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text="OUTPUT", style="Head.TLabel").pack(side="left")
        self.busy = ttk.Label(head, text="", style="Muted.TLabel")
        self.busy.pack(side="left", padx=10)
        ttk.Button(head, text="Clear", command=self.clear, cursor="hand2").pack(side="right")
        self.cancel_button = ttk.Button(
            head, text="Cancel", command=self.cancel, style="Danger.TButton", cursor="hand2"
        )
        self.cancel_button.pack(side="right", padx=6)
        self.cancel_button.state(["disabled"])
        self.book = ttk.Notebook(self.frame)
        self.book.pack(fill="both", expand=True, pady=(8, 0))
        self.texts: dict[str, tk.Text] = {}
        for key, title in zip(self.KEYS, ("Steps", "Logs and reads"), strict=True):
            holder = ttk.Frame(self.book, style="Panel.TFrame")
            text = tk.Text(
                holder,
                bg=FIELD,
                fg="#c9d1d9",
                insertbackground=TEXT,
                relief="flat",
                font=("Menlo", 11),
                wrap="word",
                highlightthickness=0,
                padx=8,
                pady=6,
                height=8,
            )
            bar = ttk.Scrollbar(holder, command=text.yview)
            text.configure(yscrollcommand=bar.set, state="disabled")
            bar.pack(side="right", fill="y")
            text.pack(side="left", fill="both", expand=True)
            text.tag_configure("step", foreground=ACCENT, font=("Menlo", 11, "bold"))
            text.tag_configure("err", foreground=RED)
            text.tag_configure("ok", foreground=GREEN)
            text.tag_configure("muted", foreground=MUTED)
            self.book.add(holder, text=title)
            self.texts[key] = text

    def show(self, key: str) -> None:
        select_tab(self.book, self.KEYS.index(key))

    def append(self, key: str, segments: Sequence[tuple[str, str | None]]) -> None:
        text = self.texts[key]
        at_end = text.yview()[1] >= 0.999
        text.configure(state="normal")
        for chunk, tag in segments:
            text.insert("end", chunk, tag or ())
        lines = int(text.index("end-1c").split(".")[0])
        if lines > self.MAX_LINES + 500:
            text.delete("1.0", f"{lines - self.MAX_LINES}.0")
        text.configure(state="disabled")
        if at_end:
            text.see("end")

    def clear(self) -> None:
        text = self.texts[self.KEYS[tab_index(self.book)]]
        text.configure(state="normal")
        text.delete("1.0", "end")
        text.configure(state="disabled")

    def cancel(self) -> None:
        current = self.panel.runners[self.KEYS[tab_index(self.book)]]
        for runner in (current, *self.panel.runners.values()):
            plan = runner.plan
            if plan is not None:
                if runner.name == "steps" and not messagebox.askokcancel(
                    "Cancel",
                    f"Cancel {plan.title}? Its process group gets SIGTERM (SIGKILL five seconds "
                    "later if it is still running); a make target stops where it is.",
                    icon="warning",
                    parent=self.panel.root,
                ):
                    return
                runner.cancel()
                self.panel.write(
                    runner.name, "cancelling: SIGTERM to the step's process group", "err"
                )
                return

    def refresh(self) -> None:
        parts = []
        steps, reads = self.panel.runners["steps"].plan, self.panel.runners["reads"].plan
        if steps is not None:
            parts.append(f"working: {steps.title}…")
        if reads is not None:
            parts.append(f"reading: {reads.title}…")
        self.busy.configure(text="   ".join(parts))
        self.cancel_button.state(["!disabled"] if parts else ["disabled"])


# ---- tabs --------------------------------------------------------------------------------------
class Tab:
    title: ClassVar[str] = ""

    def __init__(self, panel: Panel, book: ttk.Notebook) -> None:
        self.panel = panel
        self.scroller = ScrollFrame(book)
        book.add(self.scroller, text=self.title)
        self.body = self.scroller.inner
        self.build(self.body)

    def build(self, body: ttk.Frame) -> None:
        raise NotImplementedError

    def shown(self) -> None:
        """The tab was selected."""

    def on_status(self, status: core.Status) -> None:
        """A quick probe finished."""

    def on_processes(self, snapshot: core.ProcessSnapshot) -> None:
        """The process and port scan finished."""

    def on_git(self, state: core.GitState) -> None:
        """The checkout's git state was read."""

    def row(self, parent: tk.Misc, label: str, width: int = 12) -> ttk.Frame:
        """A labelled row of buttons, as the panel's action groups always were."""
        line = ttk.Frame(parent, style="Panel.TFrame")
        line.pack(fill="x", pady=2)
        ttk.Label(line, text=label, style="Panel.TLabel", width=width).pack(side="left")
        return line

    def act(
        self,
        parent: tk.Misc,
        text: str,
        command: Action,
        style: str = "TButton",
        guarded: bool = True,
    ) -> ttk.Button:
        button = self.panel.button(parent, text, command, style, guarded)
        button.pack(side="left", padx=(0, 6))
        return button


class OverviewTab(Tab):
    title = "Overview"

    def build(self, body: ttk.Frame) -> None:
        panel = self.panel
        project = panel.project
        big = ttk.Frame(body)
        big.pack(fill="x", pady=(0, 10))
        for text, command, style, guarded in (
            ("▶  Start everything", panel.start_everything, "Big.Primary.TButton", True),
            ("■  Stop everything", panel.stop_everything, "Big.Danger.TButton", True),
            ("Web app  ↗", lambda: panel.open_url(project.web_url), "Big.Accent.TButton", False),
            (
                "Product  ↗",
                lambda: panel.open_url(project.product_web_url),
                "Big.Accent.TButton",
                False,
            ),
        ):
            panel.button(big, text, command, style, guarded).pack(side="left", padx=(0, 10))

        columns = ttk.Frame(body)
        columns.pack(fill="both", expand=True)
        columns.columnconfigure(0, weight=0)
        columns.columnconfigure(1, weight=1)

        status = ttk.Frame(columns, style="Panel.TFrame", padding=14)
        status.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        heading(status, "STATUS")
        ports = project.ports
        self.dots = {
            "docker": DotRow(status, "Docker (Colima)"),
            "infra": DotRow(status, "Databases & queues"),
            "web": DotRow(
                status,
                f"Web app  :{ports['WEB_PORT']}",
                [("open", lambda: panel.open_url(project.web_url))],
            ),
            "product": DotRow(
                status,
                f"Product  :{ports['CW_MVP_INTERNAL_PORT']}",
                [("open", lambda: panel.open_url(project.product_web_url))],
            ),
        }
        base = ports["SERVICE_PORT_BASE"]
        heading(status, f"SERVICES  :{base + 1}-{base + len(core.SERVICES)}", (10, 4))
        grid = ttk.Frame(status, style="Panel.TFrame")
        grid.pack(fill="x")
        for index, name in enumerate(core.SERVICES):
            cell = ttk.Frame(grid, style="Panel.TFrame")
            cell.grid(row=index % 5, column=index // 5, sticky="w", padx=(0, 10))
            self.dots[name] = DotRow(cell, name, compact=True)

        right = ttk.Frame(columns)
        right.grid(row=0, column=1, sticky="nsew")
        code = ttk.Frame(right, style="Panel.TFrame", padding=14)
        code.pack(fill="x")
        heading(code, "THE CODE THE STACK RUNS")
        self.code_lines: dict[str, ttk.Label] = {}
        lines = ttk.Frame(code, style="Panel.TFrame")
        lines.pack(fill="x")
        lines.columnconfigure(1, weight=1)
        for row, key in enumerate(("branch", "commit", "changes", "main")):
            ttk.Label(lines, text=key.capitalize(), style="Muted.TLabel", width=9).grid(
                row=row, column=0, sticky="nw", pady=1
            )
            value = ttk.Label(lines, text="reading…", style="Panel.TLabel", wraplength=300)
            value.grid(row=row, column=1, sticky="ew", pady=1)
            self.code_lines[key] = wrapping(value)
        self.in_use = ttk.Frame(code, style="Panel.TFrame")
        self.in_use_text = wrapping(
            link(self.in_use, "", lambda: panel.show_tab("Processes"), "Warn.TLabel")
        )
        self.in_use_text.configure(wraplength=300, justify="left")
        self.in_use_text.pack(anchor="w", fill="x")

        acts = ttk.Frame(right, style="Panel.TFrame", padding=14)
        acts.pack(fill="x", pady=(12, 0))
        self.acts = acts
        plans = panel.plans
        line = self.row(acts, "Docker", 9)
        self.act(line, "Start", lambda: panel.run(plans.docker_start()))
        self.act(line, "Stop", lambda: panel.run(plans.docker_stop(), shared=True))
        ttk.Label(line, text="Databases", style="Panel.TLabel").pack(side="left", padx=(14, 8))
        self.act(line, "Start", lambda: panel.run(plans.databases_start()))
        self.act(line, "Stop", lambda: panel.run(plans.databases_stop(), shared=True))
        line = self.row(acts, "UI only", 9)
        self.act(line, "Start", lambda: panel.run(plans.ui_start()))
        self.act(line, "Stop", lambda: panel.run(plans.ui_stop(), mine="web-stack"))
        self.act(line, "Restart", lambda: panel.run(plans.ui_restart(), mine="web-stack"))
        line = self.row(acts, "Web app", 9)
        self.act(line, "Start", lambda: panel.run(plans.web_start()))
        self.act(line, "Stop", panel.stop_web_app)
        line = self.row(acts, "Product", 9)
        self.act(line, "Start", lambda: panel.run(plans.product_start()))
        self.act(line, "Stop", lambda: panel.run(plans.product_stop(), mine="product"))
        self.act(line, "Open ↗", lambda: panel.open_url(project.product_web_url), guarded=False)
        for text in project.notes:
            note(acts, text)

    def on_status(self, status: core.Status) -> None:
        self.dots["docker"].set(
            "up" if status.docker else "down", "running" if status.docker else "stopped"
        )
        count = status.infra_up
        total = len(core.INFRA)
        state = "up" if count == total else ("partial" if count else "down")
        self.dots["infra"].set(state, f"{count}/{total} healthy")
        self.dots["web"].set("up" if status.up["web"] else "down")
        product = status.up["product.internal"]
        self.dots["product"].set("up" if product else "down", "running" if product else "")
        for name in core.SERVICES:
            self.dots[name].set("up" if status.up[f"service:{name}"] else "down")

    def on_git(self, state: core.GitState) -> None:
        lines = self.code_lines
        if state.error:
            lines["branch"].configure(text=state.error, style="Warn.TLabel")
            return
        if state.on_main:
            lines["branch"].configure(text="main", style="Panel.TLabel")
        else:
            lines["branch"].configure(text=f"{state.branch}  (not main)", style="Warn.TLabel")
        subject = state.subject if len(state.subject) <= 52 else state.subject[:51] + "…"
        lines["commit"].configure(text=f"{state.sha}  {subject}")
        files = "file" if state.dirty == 1 else "files"
        lines["changes"].configure(
            text=f"{state.dirty} uncommitted {files}" if state.dirty else "nothing uncommitted",
            style="Warn.TLabel" if state.dirty else "Panel.TLabel",
        )
        if state.ahead is None or state.behind is None:
            lines["main"].configure(
                text=f"origin/main is not known here · last commit {state.when}"
            )
        else:
            lines["main"].configure(
                text=f"{state.ahead} ahead, {state.behind} behind origin/main · last commit "
                f"{state.when}"
            )

    def on_processes(self, snapshot: core.ProcessSnapshot) -> None:
        summary = snapshot.foreign_summary(self.panel.project.repo)
        if not summary:
            self.in_use.pack_forget()
            return
        shown = summary[:2] + ([f"{len(summary) - 2} more"] if len(summary) > 2 else [])
        self.in_use_text.configure(text="Not started by this panel: " + " · ".join(shown))
        self.in_use.pack(fill="x", pady=(10, 0))


class StackTab(Tab):
    title = "Stack"

    def build(self, body: ttk.Frame) -> None:
        panel, plans, ports = self.panel, self.panel.plans, self.panel.project.ports
        top = card(body)
        line = self.row(top, "Core stack")
        self.act(line, "Start (make dev)", lambda: panel.run(plans.databases_start()))
        self.act(
            line, "Stop (make dev-down)", lambda: panel.run(plans.databases_stop(), shared=True)
        )
        self.act(line, "make dev-ps", lambda: panel.run(plans.dev_ps(), read=True), guarded=False)
        line = self.row(top, "Profiles")
        self.act(line, "Observability", lambda: panel.run(plans.dev_observability()))
        self.act(line, "Fake LLM", lambda: panel.run(plans.dev_llm()))
        self.act(line, "Unleash", lambda: panel.run(plans.dev_flags()))
        note(
            top,
            "Observability adds Langfuse, the OTel collector, Prometheus, Tempo and Grafana; "
            "Fake LLM builds the llm-gateway image with the fake provider; Unleash serves flags "
            "for CW_FLAGS_PROVIDER=unleash. make dev-down stops every profile.",
        )

        box = card(body)
        heading(box, "CONTAINERS")
        frame, self.tree = make_tree(
            box,
            [
                ("service", "Service", 130, False),
                ("profile", "Profile", 100, False),
                ("state", "State", 90, False),
                ("health", "Health", 80, False),
                ("ports", "Ports", 150, False),
                ("what", "What", 260, True),
            ],
            height=8,
        )
        frame.pack(fill="x")
        line = ttk.Frame(box, style="Panel.TFrame")
        line.pack(fill="x", pady=(8, 0))
        self.act(line, "Logs (last 200 lines)", self.logs, guarded=False)

        links = card(body)
        heading(links, "WHAT THE STACK SERVES")
        grid = ttk.Frame(links, style="Panel.TFrame")
        grid.pack(fill="x")
        self.link_dots: list[tuple[tk.Label, str]] = []
        for index, (label, url, container) in enumerate(core.stack_links(ports)):
            cell = ttk.Frame(grid, style="Panel.TFrame")
            cell.grid(row=index // 3, column=index % 3, sticky="w", padx=(0, 24), pady=2)
            dot = tk.Label(cell, text="●", fg=MUTED, bg=PANEL, font=("Helvetica", 14))
            dot.pack(side="left")
            link(cell, f"{label}  ↗", partial(panel.open_url, url)).pack(side="left", padx=4)
            self.link_dots.append((dot, container))
        note(
            links,
            "Redpanda ships no console in this stack: its admin API and schema registry answer "
            "JSON. Tempo has no UI of its own; Grafana's Explore reads it.",
        )

    def logs(self) -> None:
        service = selected(self.tree)
        if service is None:
            self.panel.write("reads", "pick a container first", "err")
            return
        self.panel.run(self.panel.plans.container_logs(service), read=True)

    def on_status(self, status: core.Status) -> None:
        rows: list[tuple[str, Sequence[object], str]] = []
        for service in core.COMPOSE_SERVICES:
            container = status.containers.get(service.name)
            if container is None:
                values = ["—" if status.docker else "Docker stopped", "", "", service.what]
                tag = "muted"
            else:
                ports = ", ".join(str(p) for p in container.ports)
                values = [container.state, container.health, ports, service.what]
                failed = container.state == "exited" and container.exit_code != 0
                tag = "up" if container.up else ("down" if failed else "warn")
                if container.state == "exited" and container.exit_code == 0:
                    tag = "muted"
            rows.append((service.name, [service.name, service.profile or "core", *values], tag))
        sync_rows(self.tree, rows)
        for dot, name in self.link_dots:
            container = status.containers.get(name)
            dot.configure(fg=GREEN if container is not None and container.up else MUTED)


class ServicesTab(Tab):
    title = "Services"

    def build(self, body: ttk.Frame) -> None:
        panel, plans = self.panel, self.panel.plans
        top = card(body)
        line = self.row(top, "UI-only stack")
        self.act(line, "Start", lambda: panel.run(plans.ui_start()))
        self.act(line, "Stop", lambda: panel.run(plans.ui_stop(), mine="web-stack"))
        self.act(line, "Restart", lambda: panel.run(plans.ui_restart(), mine="web-stack"))
        self.act(line, "Wait", lambda: panel.run(plans.ui_wait()))
        self.act(
            line,
            "Logs folder",
            lambda: panel.open_file(panel.project.web_stack_dir),
            guarded=False,
        )
        note(
            top,
            "make web-stack STORE=postgres runs the ten services on the compose Postgres, with no "
            "worker. Workers and relays below run beside them; the product's own worker already "
            "runs every relay and consumer, so start these for the UI-only stack. Each starts with "
            "the crawl off (CW_PIPELINE_CRAWL_ENABLED=false) whatever .env says.",
        )
        box = card(body)
        frame, self.tree = make_tree(
            box,
            [
                ("service", "Service", 170, False),
                ("port", "Port", 60, False),
                ("api", "API", 70, False),
                ("worker", "Worker (make worker)", 200, True),
                ("relay", "Outbox relay (make relay)", 200, True),
            ],
            height=10,
        )
        frame.pack(fill="x")
        self.tree.bind("<Double-1>", lambda _e: self.docs())
        line = self.row(box, "API")
        self.act(line, "Docs ↗", self.docs, guarded=False)
        self.act(line, "Log", self.api_log, guarded=False)
        self.act(line, "Log in Console", self.api_console, guarded=False)
        line = self.row(box, "Worker")
        self.act(line, "Start", lambda: self.background("worker", True))
        self.act(line, "Stop", lambda: self.background("worker", False))
        self.act(line, "Log", lambda: self.background_log("worker"), guarded=False)
        line = self.row(box, "Relay")
        self.act(line, "Start", lambda: self.background("relay", True))
        self.act(line, "Stop", lambda: self.background("relay", False))
        self.act(line, "Log", lambda: self.background_log("relay"), guarded=False)

    def service(self) -> str | None:
        name = selected(self.tree)
        if name is None:
            self.panel.write("steps", "pick a service first", "err")
        return name

    def docs(self) -> None:
        if (name := self.service()) is not None:
            self.panel.open_url(f"http://localhost:{self.panel.project.ports.service(name)}/docs")

    def api_log(self) -> None:
        if (name := self.service()) is not None:
            path = self.panel.project.web_stack_dir / f"{name}.log"
            self.panel.run(self.panel.plans.tail(f"{name} log", path), read=True)

    def api_console(self) -> None:
        if (name := self.service()) is not None:
            path = self.panel.project.web_stack_dir / f"{name}.log"
            self.panel.open_console(path)

    def _available(self, kind: str, name: str) -> bool:
        project = self.panel.project
        names = project.workers if kind == "worker" else project.relays
        if name not in names:
            what = "no worker module" if kind == "worker" else "no outbox table in its migrations"
            self.panel.write("steps", f"{name} has {what}; nothing to start", "err")
            return False
        return True

    def background(self, kind: str, start: bool) -> None:
        name = self.service()
        if name is None or not self._available(kind, name):
            return
        plans = self.panel.plans
        if kind == "worker":
            plan = plans.worker_start(name) if start else plans.worker_stop(name)
        else:
            plan = plans.relay_start(name) if start else plans.relay_stop(name)
        self.panel.run(plan)

    def background_log(self, kind: str) -> None:
        name = self.service()
        if name is None:
            return
        repo = self.panel.project.repo
        spec = core.worker_spec(repo, name) if kind == "worker" else core.relay_spec(repo, name)
        self.panel.run(self.panel.plans.tail(spec.label + " log", spec.log_file), read=True)

    def on_status(self, status: core.Status) -> None:
        project = self.panel.project
        rows: list[tuple[str, Sequence[object], str]] = []
        for name in core.SERVICES:
            up = status.up[f"service:{name}"]
            cells = []
            for kind, names in (("worker", project.workers), ("relay", project.relays)):
                if name not in names:
                    cells.append("—")
                    continue
                pid = status.background.get(f"{kind}-{name}")
                cells.append(f"running (pid {pid})" if pid else "stopped")
            port = project.ports.service(name)
            rows.append(
                (name, [name, port, "up" if up else "down", *cells], "up" if up else "down")
            )
        sync_rows(self.tree, rows)


class ProductTab(Tab):
    title = "Product"

    def build(self, body: ttk.Frame) -> None:
        panel, plans, project = self.panel, self.panel.plans, self.panel.project
        ports = project.ports
        columns = ttk.Frame(body)
        columns.pack(fill="both", expand=True)
        columns.columnconfigure(0, weight=0, minsize=330)
        columns.columnconfigure(1, weight=1)
        left = ttk.Frame(columns, style="Panel.TFrame", padding=14)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        heading(left, "MAKE PRODUCT")
        internal, worker = project.product_internal_url, project.product_worker_url
        public = f"http://127.0.0.1:{ports['CW_MVP_PUBLIC_PORT']}"
        self.dots = {
            "product.internal": DotRow(
                left,
                f"App, internal  :{ports['CW_MVP_INTERNAL_PORT']}",
                [("ready", lambda: panel.open_url(internal + "/ready"))],
            ),
            "product.public": DotRow(
                left,
                f"App, public  :{ports['CW_MVP_PUBLIC_PORT']}",
                [("health", lambda: panel.open_url(public + "/health"))],
            ),
            "product.worker": DotRow(
                left,
                f"Worker  :{ports['PRODUCT_WORKER_PORT']}",
                [("loops", lambda: panel.open_url(worker + "/loops"))],
            ),
            "product.web": DotRow(
                left,
                f"Web app  :{core.PRODUCT_WEB_PORT}",
                [("open", lambda: panel.open_url(project.product_web_url))],
            ),
        }
        self.listeners: dict[str, str] = {}
        self.pids = ttk.Label(left, text="", style="Muted.TLabel", wraplength=300, justify="left")
        self.pids.pack(anchor="w", pady=(6, 0))
        heading(left, "MAKE PRODUCT-IMAGE", (12, 6))
        self.image = {name: DotRow(left, name) for name in ("mvp-app", "mvp-worker", "mvp-release")}

        right = ttk.Frame(columns, style="Panel.TFrame", padding=14)
        right.grid(row=0, column=1, sticky="nsew")
        heading(right, "ACTIONS")
        line = self.row(right, "Run", 10)
        self.act(line, "Start", lambda: panel.run(plans.product_start()))
        self.act(line, "Stop", lambda: panel.run(plans.product_stop(), mine="product"))
        self.act(line, "Wait", lambda: panel.run(plans.product_wait()))
        self.act(line, "Role", lambda: panel.run(plans.product_role()))
        line = self.row(right, "Prove it", 10)
        self.act(line, "Seed", lambda: panel.run(plans.product_seed()))
        self.act(line, "Check all", lambda: panel.run(plans.product_check()))
        self.act(line, "Web journey", lambda: panel.run(plans.product_e2e()))
        line = self.row(right, "One step", 10)
        steps = core.selectable_steps(project.check_steps)
        self.step = ttk.Combobox(line, values=steps, state="readonly", width=12)
        if steps:
            self.step.set(steps[0])
        self.step.pack(side="left", padx=(0, 6))
        self.act(line, "Check this step", lambda: panel.run(plans.product_check(self.step.get())))
        line = self.row(right, "Logs", 10)
        for proc in ("app", "worker", "web"):
            self.act(
                line,
                proc,
                partial(panel.run, plans.product_logs(proc), read=True),
                guarded=False,
            )
        self.act(line, "Folder", lambda: panel.open_file(project.product_dir), guarded=False)
        line = self.row(right, "Image", 10)
        self.act(line, "Build", lambda: panel.run(plans.mvp_image()))
        self.act(line, "Start", lambda: panel.run(plans.product_image()))
        self.act(line, "Stop", lambda: panel.run(plans.product_image_down()))
        line = self.row(right, "Image logs", 10)
        for proc in ("app", "worker", "release"):
            self.act(
                line,
                proc,
                partial(panel.run, plans.product_image_logs(proc), read=True),
                guarded=False,
            )
        note(
            right,
            f"Start runs make product WEB_PORT={core.PRODUCT_WEB_PORT}: make dev, migrate, the "
            "role, the seed calendar, then the app, the worker and next dev, opened at 127.0.0.1 "
            "so its session stays apart from the UI-only web app's. Web journey runs make "
            f"product-e2e on :{core.PRODUCT_E2E_PORT}. The check never runs --destructive (its "
            "rollback step withdraws gstr9_annual), and Seed runs only while the product answers.",
        )
        heading(right, "OPEN", (12, 6))
        line = ttk.Frame(right, style="Panel.TFrame")
        line.pack(fill="x")
        web = project.product_web_url
        for text, url in (
            ("Web app", web),
            ("Sign in", web + "/sign-in"),
            ("Admin", web + "/admin"),
        ):
            link(line, f"{text}  ↗", partial(panel.open_url, url)).pack(side="left", padx=(0, 16))
        pages, missing = core.admin_pages(project.screens, core.PRODUCT_ADMIN)
        grid = ttk.Frame(right, style="Panel.TFrame")
        grid.pack(fill="x", pady=(6, 0))
        for index, page in enumerate(pages[:12]):
            url = web + page.route
            link(grid, f"{page.title}  ↗", partial(panel.open_url, url)).grid(
                row=index // 2, column=index % 2, sticky="w", padx=(0, 18), pady=1
            )
        if missing:
            names = ", ".join(page.title for page in missing)
            note(right, f"Not built yet in this checkout's web app: {names}.")

    def on_processes(self, snapshot: core.ProcessSnapshot) -> None:
        ports = self.panel.project.ports
        for key, port in (
            ("product.internal", ports["CW_MVP_INTERNAL_PORT"]),
            ("product.public", ports["CW_MVP_PUBLIC_PORT"]),
            ("product.worker", ports["PRODUCT_WORKER_PORT"]),
            ("product.web", core.PRODUCT_WEB_PORT),
        ):
            listener = snapshot.listener_on(port)
            if listener is None:
                self.listeners[key] = ""
            else:
                origin = snapshot.origins.get(listener.pid, "")
                self.listeners[key] = f"pid {listener.pid}" + (f" · {origin}" if origin else "")

    def on_status(self, status: core.Status) -> None:
        for key, row in self.dots.items():
            row.set("up" if status.up[key] else "down", self.listeners.get(key, ""))
        pids = [f"{proc} {pid}" for proc, pid in status.product_pids.items() if pid]
        self.pids.configure(
            text="var/product pids: " + ", ".join(pids) if pids else "no var/product pid is alive"
        )
        for name, row in self.image.items():
            container = status.containers.get(name)
            if container is None:
                row.set("off", "not created")
            else:
                ok = container.up or (container.state == "exited" and container.exit_code == 0)
                row.set("up" if container.up else ("off" if ok else "down"), container.status)


class DataTab(Tab):
    title = "Data"

    def build(self, body: ttk.Frame) -> None:
        panel, plans, project = self.panel, self.panel.plans, self.panel.project
        box = card(body)
        line = self.row(box, "Migrate")
        self.act(line, "All services", lambda: panel.run(plans.migrate()))
        self.service = ttk.Combobox(line, values=list(core.SERVICES), state="readonly", width=20)
        self.service.set(core.SERVICES[0])
        self.service.pack(side="left", padx=(0, 6))
        self.act(line, "This service", lambda: panel.run(plans.migrate(self.service.get())))
        line = self.row(box, "Checks")
        migrations = next(g for g in core.GATES if g.target == "migrations-check")
        self.act(line, "migrations-check", lambda: panel.run(plans.gate(migrations)))
        self.act(line, "migrations-catalog", lambda: panel.run(plans.migrations_catalog()))
        self.act(line, "data-quality", lambda: panel.run(plans.data_quality()))
        self.act(line, "Seed calendar check", lambda: panel.run(plans.seed_check()))
        line = self.row(box, "Demo data")
        self.act(line, "Load demo data", lambda: panel.run(plans.load_demo_data()))
        self.act(line, "Run the demo", lambda: panel.run(plans.demo()))
        note(
            box,
            "Load demo data writes the seed calendar's drafts (make seed SERVICE=rulebook) and the "
            "demo tenant into the UI-only stack (make web-seed); the product's own seed is on the "
            "Product tab. Run the demo is make demo: the demo tenant in one process, no database.",
        )

        box = card(body)
        heading(box, "BACKUPS")
        line = self.row(box, "Back up")
        self.act(line, "Back up now", lambda: panel.run(plans.backup()))
        self.act(
            line,
            "Folder",
            lambda: panel.open_file(project.repo / "var" / "backups"),
            guarded=False,
        )
        line = self.row(box, "Restore")
        self.dump = ttk.Combobox(line, values=[], state="readonly", width=46)
        self.dumps: dict[str, core.Dump] = {}
        self.dump.pack(side="left", padx=(0, 6))
        self.act(line, "Restore…", self.restore, "Danger.TButton")
        self.act(line, "↻", self.refresh_backups, guarded=False)
        line = self.row(box, "Reset")
        self.act(line, "Reset DB…", self.reset, "Danger.TButton")
        line = self.row(box, "psql")
        self.act(line, "Open psql in Terminal", self.psql, guarded=False)
        note(
            box,
            "Back up runs make dev-backup (pg_dump into var/backups). Restore and Reset ask first "
            "and say what they remove; Reset can take a backup before it starts.",
        )

    def shown(self) -> None:
        self.refresh_backups()

    def refresh_backups(self) -> None:
        """The non-empty dumps of var/backups, newest first, each with its size and age."""
        previous = self.dumps.get(self.dump.get())
        now = time.time()
        self.dumps = {
            dump.describe(now): dump for dump in core.list_backups(self.panel.project.repo)
        }
        self.dump.configure(values=list(self.dumps))
        if not self.dumps:
            self.dump.set("no backups in var/backups yet")
            return
        same = (
            text for text, dump in self.dumps.items() if previous and dump.path == previous.path
        )
        self.dump.set(next(same, next(iter(self.dumps))))

    def restore(self) -> None:
        """Check the picked dump with pg_restore --list first; the confirm names what it read."""
        dump = self.dumps.get(self.dump.get())
        if dump is None:
            self.panel.write("steps", "pick a backup from var/backups first", "err")
            return
        panel = self.panel

        def work() -> Callable[[], None]:
            ok, text = core.check_dump(panel.project.repo, panel.project.env, dump.path)
            return lambda: self._confirm_restore(dump, ok, text)

        panel.write("steps", f"reading {dump.path} with pg_restore --list…", "muted")
        panel.output.show("steps")
        panel.background("restore-check", work)

    def _confirm_restore(self, dump: core.Dump, ok: bool, text: str) -> None:
        panel = self.panel
        if not ok:
            panel.write("steps", f"error: not restored: {text}", "err")
            return
        plan = panel.plans.restore(dump.path)
        message = f"{plan.confirm}\n\n{dump.describe(time.time())}\n{text}.{panel.shared_note()}"
        if messagebox.askokcancel("Restore", message, icon="warning", parent=panel.root):
            panel.run(plan, confirmed=True)

    def reset(self) -> None:
        plans = self.panel.plans
        message = plans.reset(backup_first=False).confirm or ""
        message += self.panel.shared_note()
        choice = choose(
            self.panel.root,
            "Reset database",
            message + "\n\nTake a backup into var/backups first?",
            ["Back up, then reset", "Reset without a backup", "Cancel"],
        )
        if choice in ("Back up, then reset", "Reset without a backup"):
            plan = plans.reset(backup_first=choice == "Back up, then reset")
            self.panel.run(plan, confirmed=True)

    def psql(self) -> None:
        try:
            script = core.open_psql_terminal(self.panel.project.repo, self.panel.project.env)
        except (core.RefusedError, OSError) as exc:
            self.panel.write("steps", f"error: cannot open Terminal: {exc}", "err")
            return
        self.panel.write("steps", f"Terminal opens make dev-psql ({script.name})", "muted")


class GatesTab(Tab):
    title = "Gates"
    STATES: ClassVar[dict[str, tuple[str, str]]] = {
        "running": ("running…", "warn"),
        "ok": ("passed", "up"),
        "failed": ("failed", "down"),
        "cancelled": ("cancelled", "muted"),
        "skipped": ("not run", "muted"),
        "queued": ("queued", "muted"),
    }

    def build(self, body: ttk.Frame) -> None:
        panel, plans = self.panel, self.panel.plans
        top = card(body)
        line = ttk.Frame(top, style="Panel.TFrame")
        line.pack(fill="x")
        self.act(
            line,
            "▶  Run the CI gates in order",
            lambda: panel.run(plans.gates_in_order()),
            "Big.Accent.TButton",
        )
        note(
            top,
            "In order: make check's gates one by one as CI's jobs run them, eval-check and eval, "
            "openapi-compat, the ops checks, the integration tests, sast and deps-scan; a failed "
            "gate does not stop the next. Left out: make check itself, web-e2e (it needs the "
            "seeded UI-only stack) and CI's dev-stack job (product-check --destructive needs a "
            "database made for the run).",
        )
        grid = ttk.Frame(top, style="Panel.TFrame")
        grid.pack(fill="x", pady=(10, 0))
        for index, gate in enumerate(core.GATES):
            button = panel.button(grid, gate.label, partial(panel.run, plans.gate(gate)))
            button.grid(row=index // 4, column=index % 4, sticky="ew", padx=(0, 6), pady=3)
        box = card(body)
        heading(box, "RESULTS")
        frame, self.tree = make_tree(
            box,
            [
                ("gate", "Gate", 190, False),
                ("result", "Result", 100, False),
                ("duration", "Duration", 90, False),
                ("when", "When", 70, False),
                ("note", "What", 360, True),
            ],
            height=10,
        )
        frame.pack(fill="x")
        self.results: dict[str, tuple[str, float, str]] = {}
        self.notes = {gate.label: gate.note for gate in core.GATES}
        for gate in core.ci_sequence(panel.project.checks, panel.project.known_targets):
            self.notes.setdefault(gate.label, "part of make check")
        self.render()

    def render(self) -> None:
        rows: list[tuple[str, Sequence[object], str]] = []
        for label, what in self.notes.items():
            state, seconds, when = self.results.get(label, ("", 0.0, ""))
            text, tag = self.STATES.get(state, ("", ""))
            duration = core.format_seconds(seconds) if seconds else ""
            rows.append((label, [label, text, duration, when, what], tag))
        sync_rows(self.tree, rows)

    def begin(self, plan: core.Plan) -> None:
        for step in plan.steps:
            self.results[step.label] = ("queued", 0.0, "")
        self.render()

    def update(self, event: core.StepUpdate) -> None:
        when = time.strftime("%H:%M") if event.state != "running" else ""
        self.results[event.label] = (event.state, event.seconds, when)
        self.render()


class PipelineTab(Tab):
    title = "Pipeline"

    def build(self, body: ttk.Frame) -> None:
        panel, project = self.panel, self.panel.project
        top = card(body)
        line = ttk.Frame(top, style="Panel.TFrame")
        line.pack(fill="x")
        self.act(
            line,
            "Crawl report",
            lambda: panel.run(panel.plans.crawl_report(), read=True),
            guarded=False,
        )
        self.act(line, "Read topics and groups", self.refresh, guarded=False)
        self.auto = tk.BooleanVar(value=False)
        self.limit = core.RateLimit(core.KAFKA_MIN_SECONDS)
        self.last: core.KafkaSnapshot | None = None
        ttk.Checkbutton(line, text="every 30 s while this tab is open", variable=self.auto).pack(
            side="left", padx=(6, 0)
        )
        self.read_at = wrapping(
            ttk.Label(top, text="", style="Muted.TLabel", wraplength=400, justify="left")
        )
        self.read_at.pack(anchor="w", fill="x", pady=(6, 0))
        note(
            top,
            "Everything here only reads: the crawl report over the pipeline store (make "
            "crawl-report), and the consumer groups and topics through rpk in the Redpanda "
            "container. Nothing here crawls; the regulator sites are never contacted.",
        )
        columns = ttk.Frame(body)
        columns.pack(fill="x")
        left = ttk.Frame(columns, style="Panel.TFrame", padding=14)
        left.pack(side="left", fill="both", expand=True, padx=(0, 12), pady=(0, 12))
        heading(left, "CONSUMER GROUPS")
        frame, self.groups = make_tree(
            left,
            [
                ("group", "Group", 190, True),
                ("state", "State", 70, False),
                ("members", "Members", 70, False),
                ("lag", "Lag", 60, False),
            ],
            height=7,
        )
        frame.pack(fill="both", expand=True)
        right = ttk.Frame(columns, style="Panel.TFrame", padding=14)
        right.pack(side="left", fill="both", expand=True, pady=(0, 12))
        heading(right, "TOPICS")
        frame, self.topics = make_tree(
            right,
            [
                ("topic", "Topic", 270, True),
                ("partitions", "Parts", 50, False),
                ("messages", "Messages", 80, False),
            ],
            height=7,
        )
        frame.pack(fill="both", expand=True)

        links = card(body)
        heading(links, "OPEN")
        line = ttk.Frame(links, style="Panel.TFrame")
        line.pack(fill="x")
        internal, worker = project.product_internal_url, project.product_worker_url
        temporal = f"http://localhost:{project.ports['TEMPORAL_UI_PORT']}"
        for text, url in (
            ("Temporal UI", temporal),
            ("Worker loops", worker + "/loops"),
            ("Sources (JSON)", internal + "/v1/pipeline/sources"),
            ("Tasks (JSON)", internal + "/v1/pipeline/tasks?status=open"),
        ):
            link(line, f"{text}  ↗", partial(panel.open_url, url)).pack(side="left", padx=(0, 16))
        pages, missing = core.admin_pages(project.screens, core.PIPELINE_ADMIN, only=True)
        if pages:
            line = ttk.Frame(links, style="Panel.TFrame")
            line.pack(fill="x", pady=(6, 0))
            for page in pages:
                url = project.product_web_url + page.route
                link(line, f"{page.title}  ↗", partial(panel.open_url, url)).pack(
                    side="left", padx=(0, 16)
                )
        if missing:
            names = ", ".join(page.title for page in missing)
            note(links, f"Admin pages not built yet in this checkout's web app: {names}.")
        note(
            links,
            "The JSON links read the product's internal listener; the loops and sources answer "
            "while make product runs.",
        )
        self.panel.root.after(KAFKA_MS, self._tick)

    def shown(self) -> None:
        if self.auto.get():
            self.refresh()

    def _tick(self) -> None:
        if self.auto.get() and self.panel.current_tab() is self:
            self.refresh()
        self.panel.root.after(KAFKA_MS, self._tick)

    def refresh(self) -> None:
        """Read the groups and topics, unless rpk ran less than 30 seconds ago."""
        wait = self.limit.wait()
        if wait > 0:
            done = ""
            if self.last is not None:
                done = time.strftime("read %H:%M:%S · ", time.localtime(self.last.taken_at))
            self.read_at.configure(
                text=f"{done}rpk runs at most every {core.KAFKA_MIN_SECONDS:.0f} s; "
                f"the next read can start in {math.ceil(wait)} s"
            )
            return
        project = self.panel.project

        def work() -> Callable[[], None]:
            snapshot = core.probe_kafka(project.repo, project.env)
            return lambda: self.show(snapshot)

        self.read_at.configure(text="reading…")
        self.panel.background("kafka", work)

    def show(self, snapshot: core.KafkaSnapshot) -> None:
        self.last = snapshot
        stamp = time.strftime("%H:%M:%S", time.localtime(snapshot.taken_at))
        self.read_at.configure(
            text=f"read {stamp}" + (f" · {snapshot.error}" if snapshot.error else "")
        )
        sync_rows(
            self.groups,
            [
                (
                    group.group,
                    [group.group, group.state, group.members, group.total_lag],
                    "warn" if group.total_lag else ("up" if group.members else "muted"),
                )
                for group in snapshot.groups
            ],
        )
        sync_rows(
            self.topics,
            [
                (
                    topic.name,
                    [
                        topic.name,
                        topic.partitions,
                        "" if topic.messages is None else topic.messages,
                    ],
                    "down" if topic.dead_letters and topic.messages else "",
                )
                for topic in snapshot.topics
            ],
        )


class FlagsTab(Tab):
    title = "Flags"

    def build(self, body: ttk.Frame) -> None:
        panel = self.panel
        top = card(body)
        line = ttk.Frame(top, style="Panel.TFrame")
        line.pack(fill="x")
        self.act(line, "Refresh", self.refresh, guarded=False)
        self.act(line, "make flags-check", lambda: panel.run(panel.plans.flags_check()))
        self.act(line, "Open .env", self.open_env, guarded=False)
        note(
            top,
            "Read only: packages/flags/registry.json with the value .env sets (or "
            "apps/web/.env.local for a web flag, apps/whatsapp-bot/.env for the bot's). Change a "
            "flag in those files; the panel never writes them.",
        )
        box = card(body)
        frame, self.tree = make_tree(
            box,
            [
                ("flag", "Flag", 190, False),
                ("type", "Type", 46, False),
                ("owner", "Owner", 115, False),
                ("default", "Default", 60, False),
                ("env", "Variable", 250, True),
                ("value", "Value", 60, False),
                ("source", "Set in", 120, False),
            ],
            height=12,
        )
        frame.pack(fill="x")
        self.detail = ttk.Label(box, text="", style="Note.TLabel", wraplength=860, justify="left")
        self.detail.pack(anchor="w", fill="x", pady=(8, 0))
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.describe())
        self.rows: dict[str, core.FlagRow] = {}
        self.loaded = False

    def shown(self) -> None:
        if not self.loaded:
            self.refresh()

    def refresh(self) -> None:
        rows, error = core.load_flags(self.panel.project.repo)
        self.loaded = True
        self.rows = {row.name: row for row in rows}
        sync_rows(
            self.tree,
            [
                (
                    row.name,
                    [
                        row.name,
                        row.type,
                        row.owner,
                        row.default,
                        row.env,
                        row.value or "",
                        row.source,
                    ],
                    "warn" if row.value is not None and row.value != row.default else "",
                )
                for row in rows
            ],
        )
        self.detail.configure(text=error or "Pick a flag to read what it does.")

    def describe(self) -> None:
        name = selected(self.tree)
        row = self.rows.get(name or "")
        if row is not None:
            self.detail.configure(
                text=f"{row.description}\n\nRemoved when: {row.removal}  (expires {row.expires})"
            )

    def open_env(self) -> None:
        path = self.panel.project.repo / ".env"
        if not path.exists():
            self.panel.write(
                "steps", ".env does not exist yet; make dev creates it from .env.example", "err"
            )
            return
        self.panel.open_file(path, text_editor=True)


class ProcessesTab(Tab):
    title = "Processes"

    def build(self, body: ttk.Frame) -> None:
        top = card(body)
        line = ttk.Frame(top, style="Panel.TFrame")
        line.pack(fill="x")
        self.act(line, "Refresh", self.panel.refresh_processes, guarded=False)
        self.act(line, "Stop selected…", self.stop, "Danger.TButton")
        self.read_at = wrapping(
            ttk.Label(top, text="", style="Muted.TLabel", wraplength=400, justify="left")
        )
        self.read_at.pack(anchor="w", fill="x", pady=(6, 0))
        note(
            top,
            "Stop sends SIGTERM to the process group when every member belongs to this checkout "
            "and none is this window, else to the process and its children, after a confirm that "
            "names each of them. It never touches the panel or a process outside the checkout.",
        )
        box = card(body)
        heading(box, "PORTS")
        frame, self.ports = make_tree(
            box,
            [
                ("port", "Port", 60, False),
                ("what", "What", 210, False),
                ("group", "Stack", 110, False),
                ("pid", "Pid", 60, False),
                ("command", "Listening", 380, True),
            ],
            height=8,
        )
        frame.pack(fill="x")
        box = card(body)
        heading(box, "THIS CHECKOUT'S PROCESSES")
        frame, self.procs = make_tree(
            box,
            [
                ("pid", "Pid", 60, False),
                ("pgid", "Group", 60, False),
                ("elapsed", "Running", 80, False),
                ("origin", "Started by", 150, False),
                ("command", "Command", 420, True),
            ],
            height=10,
        )
        frame.pack(fill="x")
        self.ports.bind("<<TreeviewSelect>>", lambda _e: self._pick(self.ports))
        self.procs.bind("<<TreeviewSelect>>", lambda _e: self._pick(self.procs))
        self.chosen: int | None = None

    def _pick(self, tree: ttk.Treeview) -> None:
        iid = selected(tree)
        if iid is None:
            return
        pid = str(tree.set(iid, "pid"))
        self.chosen = int(pid) if pid.isdigit() else None

    def shown(self) -> None:
        self.panel.refresh_processes()

    def on_processes(self, snapshot: core.ProcessSnapshot) -> None:
        repo = self.panel.project.repo
        stamp = time.strftime("%H:%M:%S", time.localtime(snapshot.taken_at))
        self.read_at.configure(
            text=f"read {stamp} · {len(snapshot.project)} processes of this checkout"
            + (f" · {snapshot.error}" if snapshot.error else "")
        )
        rows: list[tuple[str, Sequence[object], str]] = []
        for entry in core.port_catalogue(self.panel.project.ports):
            listener = snapshot.listener_on(entry.port)
            if listener is None:
                rows.append(
                    (str(entry.port), [entry.port, entry.what, entry.group, "", ""], "muted")
                )
                continue
            proc = snapshot.procs.get(listener.pid)
            if listener.command == "ssh" and proc is not None and "colima" in proc.command:
                command = "ssh (Colima's port forwarding to the container)"
            else:
                command = core.short_command(proc.command if proc else listener.command, repo, 80)
            values = [entry.port, entry.what, entry.group, listener.pid, command]
            rows.append((str(entry.port), values, "up"))
        sync_rows(self.ports, rows)
        rows = []
        for pid in sorted(snapshot.project):
            proc = snapshot.procs[pid]
            origin = snapshot.origins.get(pid, "other")
            tag = "up" if origin.startswith("this panel") else ("warn" if origin == "other" else "")
            values = [
                pid,
                proc.pgid,
                core.format_seconds(proc.elapsed),
                origin,
                core.short_command(proc.command, repo, 110),
            ]
            rows.append((str(pid), values, tag))
        sync_rows(self.procs, rows)

    def stop(self) -> None:
        snapshot = self.panel.snapshot
        if self.chosen is None or snapshot is None:
            self.panel.write("steps", "pick a process (or a port that has one) first", "err")
            return
        options = core.stop_options(self.chosen, snapshot)
        if options[0].refused:
            self.panel.write("steps", f"not stopped: {options[0].refused}", "err")
            return
        repo = self.panel.project.repo
        texts = [core.describe_stop(option, snapshot, repo) for option in options]
        pids = {pid for option in options for pid in option.pids}
        warning = ""
        if not all(snapshot.origins.get(p, "").startswith("this panel") for p in pids):
            warning = (
                "\n\nThis panel did not start every one of these; another session may be "
                "using them (for example a make check in a terminal)."
            )
        proc = snapshot.procs[self.chosen]
        if len(options) == 1:
            if not messagebox.askokcancel(
                "Stop a process", texts[0] + warning, icon="warning", parent=self.panel.root
            ):
                return
            mode = options[0].mode
        else:
            choice = choose(
                self.panel.root,
                "Stop a process",
                f"{texts[0]}\n\nor only the process and its children:\n{texts[1]}{warning}",
                ["Stop the process group", "Stop the process and its children", "Cancel"],
            )
            if choice not in ("Stop the process group", "Stop the process and its children"):
                return
            mode = "group" if choice == "Stop the process group" else "tree"
        plan = self.panel.plans.stop_process(
            proc.pid, proc.command, "tree" if mode == "tree" else "group"
        )
        self.panel.run(plan, confirmed=True)


class DocsTab(Tab):
    title = "Docs"
    DOCS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("Onboarding", "docs/onboarding/README.md"),
        ("Local development", "docs/onboarding/local-dev.md"),
        ("The local product", "docs/onboarding/product.md"),
        ("The demo", "docs/onboarding/demo.md"),
        ("This control panel", "docs/onboarding/control-panel.md"),
        ("Repository settings", "docs/onboarding/repository-settings.md"),
        ("README", "README.md"),
        ("Contributing", "CONTRIBUTING.md"),
        ("Web screens", "docs/web/screens.md"),
    )
    FOLDERS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("Runbooks", "docs/runbooks"),
        ("Onboarding", "docs/onboarding"),
        ("ADRs", "docs/adr"),
    )

    def build(self, body: ttk.Frame) -> None:
        project = self.panel.project
        box = card(body)
        heading(box, "IN THIS CHECKOUT")
        grid = ttk.Frame(box, style="Panel.TFrame")
        grid.pack(fill="x")
        docs = [
            (text, project.repo / path)
            for text, path in self.DOCS
            if (project.repo / path).exists()
        ]
        for index, (text, path) in enumerate(docs):
            button = self.panel.button(
                grid, text, partial(self.panel.open_file, path), guarded=False
            )
            button.grid(row=index // 4, column=index % 4, sticky="ew", padx=(0, 6), pady=3)
        line = self.row(box, "Folders")
        for text, folder in self.FOLDERS:
            if (project.repo / folder).is_dir():
                self.act(
                    line,
                    text,
                    partial(self.panel.open_file, project.repo / folder),
                    guarded=False,
                )
        line = self.row(box, "Tools")
        self.act(
            line,
            "Which tools are installed (make doctor)",
            lambda: self.panel.run(self.panel.plans.doctor(), read=True),
            guarded=False,
        )
        box = card(body)
        heading(box, "GITHUB")
        self.github = ttk.Frame(box, style="Panel.TFrame")
        self.github.pack(fill="x")
        self.github_note = note(box, "reading the origin remote…")

    def on_git(self, state: core.GitState) -> None:
        base = self.panel.github
        for child in self.github.winfo_children():
            child.destroy()
        if base is None:
            self.github_note.configure(text="The origin remote is not a GitHub repository.")
            return
        self.github_note.configure(text=base)
        for text, url in core.github_links(base, state.branch):
            link(self.github, f"{text}  ↗", partial(self.panel.open_url, url)).pack(
                side="left", padx=(0, 18)
            )


TABS: Final = (
    OverviewTab,
    StackTab,
    ServicesTab,
    ProductTab,
    DataTab,
    GatesTab,
    PipelineTab,
    FlagsTab,
    ProcessesTab,
    DocsTab,
)


# ---- the window --------------------------------------------------------------------------------
class Panel:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.project = core.Project.load()
        self.registry = core.Registry(self.project.panel_dir)
        known = self.project.known_targets
        self.manager = core.BackgroundManager(
            self.project.repo, self.project.env, self.registry, known
        )
        self.plans = core.Plans(self.project, self.manager)
        self.lines: queue.Queue[tuple[str, str, str | None]] = queue.Queue(LINE_QUEUE_MAX)
        self._dropped: dict[str, int] = {}
        self._dropped_lock = threading.Lock()
        self.calls: queue.Queue[Callable[[], None]] = queue.Queue()
        repo, env = self.project.repo, self.project.env
        self.runners = {
            "steps": core.Runner("steps", repo, env, self._emit, self.registry, None, known),
            "reads": core.Runner("reads", repo, env, self._emit, self.registry, 180, known),
        }
        self.guarded: list[ttk.Button] = []
        self.status: core.Status | None = None
        self.snapshot: core.ProcessSnapshot | None = None
        self.git: core.GitState | None = None
        self.github: str | None = None
        self._inflight: set[str] = set()

        root.title("ComplianceWatch")
        root.configure(bg=BG)
        root.geometry("980x720")
        root.minsize(860, 600)
        self._styles()
        self._build()
        root.protocol("WM_DELETE_WINDOW", self._close)
        root.bind_all("<MouseWheel>", self._wheel)
        if tk.TkVersion >= 9:
            root.bind_all("<TouchpadScroll>", self._touchpad)
        self._poll_status()
        self._poll_slow()
        root.after(80, self._drain)

    # styles
    def _styles(self) -> None:
        s = ttk.Style()
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=TEXT, font=("Helvetica", 13))
        s.configure("TFrame", background=BG)
        s.configure("Panel.TFrame", background=PANEL)
        s.configure("TLabel", background=BG, foreground=TEXT)
        s.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        s.configure("Muted.TLabel", background=PANEL, foreground=MUTED, font=("Helvetica", 11))
        s.configure("Small.TLabel", background=PANEL, foreground=TEXT, font=("Helvetica", 12))
        s.configure("Note.TLabel", background=PANEL, foreground=MUTED, font=("Helvetica", 11))
        s.configure("Warn.TLabel", background=PANEL, foreground=AMBER)
        s.configure("Link.TLabel", background=PANEL, foreground=ACCENT, font=("Helvetica", 12))
        s.configure("Title.TLabel", font=("Helvetica", 22, "bold"))
        s.configure("Sub.TLabel", foreground=MUTED, font=("Helvetica", 12))
        s.configure("Branch.TLabel", foreground=MUTED, font=("Helvetica", 12))
        s.configure("BranchWarn.TLabel", foreground=AMBER, font=("Helvetica", 12, "bold"))
        s.configure(
            "Head.TLabel", background=PANEL, foreground=MUTED, font=("Helvetica", 11, "bold")
        )
        for name, colour, hover in (
            ("TButton", "#2a303a", "#353c48"),
            ("Primary.TButton", "#238636", "#2ea043"),
            ("Danger.TButton", "#8b2c2c", "#a83636"),
            ("Accent.TButton", "#1f4fa8", "#2a62c9"),
        ):
            s.configure(
                name,
                background=colour,
                foreground="#ffffff",
                borderwidth=0,
                focusthickness=0,
                padding=(11, 5),
                font=("Helvetica", 12),
                width=-6,
            )
            s.map(
                name,
                background=[("disabled", "#2a2e35"), ("active", hover)],
                foreground=[("disabled", "#6b7280")],
            )
        s.configure("Big.Primary.TButton", padding=(18, 10), font=("Helvetica", 14, "bold"))
        s.configure("Big.Danger.TButton", padding=(18, 10), font=("Helvetica", 14, "bold"))
        s.configure("Big.Accent.TButton", padding=(18, 10), font=("Helvetica", 14, "bold"))
        s.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 4, 0, 0))
        s.configure(
            "TNotebook.Tab",
            background="#20252d",
            foreground=MUTED,
            padding=(11, 5),
            borderwidth=0,
            font=("Helvetica", 12),
        )
        s.map(
            "TNotebook.Tab",
            background=[("selected", PANEL), ("active", "#2a303a")],
            foreground=[("selected", TEXT)],
        )
        s.configure(
            "Treeview",
            background=FIELD,
            fieldbackground=FIELD,
            foreground=TEXT,
            rowheight=22,
            borderwidth=0,
            font=("Helvetica", 12),
        )
        s.map("Treeview", background=[("selected", SELECTED)], foreground=[("selected", "#ffffff")])
        s.configure(
            "Treeview.Heading",
            background=PANEL,
            foreground=MUTED,
            relief="flat",
            font=("Helvetica", 11, "bold"),
        )
        s.map("Treeview.Heading", background=[("active", "#2a303a")])
        s.configure(
            "TCombobox",
            fieldbackground=FIELD,
            background="#2a303a",
            foreground=TEXT,
            arrowcolor=TEXT,
            borderwidth=0,
        )
        s.map(
            "TCombobox",
            fieldbackground=[("readonly", FIELD)],
            foreground=[("readonly", TEXT)],
            selectbackground=[("readonly", FIELD)],
            selectforeground=[("readonly", TEXT)],
        )
        s.configure("TCheckbutton", background=PANEL, foreground=TEXT, font=("Helvetica", 12))
        s.map("TCheckbutton", background=[("active", PANEL)], indicatorcolor=[("selected", ACCENT)])
        s.configure(
            "TScrollbar",
            background="#2a303a",
            troughcolor=PANEL,
            bordercolor=PANEL,
            arrowcolor=MUTED,
        )
        s.configure("TPanedwindow", background=BG)
        self.root.option_add("*TCombobox*Listbox.background", FIELD)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", SELECTED)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

    def button(
        self,
        parent: tk.Misc,
        text: str,
        command: Action,
        style: str = "TButton",
        guarded: bool = True,
    ) -> ttk.Button:
        """A button; a guarded one waits while a step runs (one mutating step at a time)."""
        widget = ttk.Button(parent, text=text, command=command, style=style, cursor="hand2")
        if guarded:
            self.guarded.append(widget)
            if self.runners["steps"].busy:
                widget.state(["disabled"])
        return widget

    # layout
    def _build(self) -> None:
        top = ttk.Frame(self.root, padding=(20, 14, 20, 4))
        top.pack(fill="x")
        ttk.Label(top, text="ComplianceWatch", style="Title.TLabel").pack(side="left")
        self.summary = ttk.Label(top, text="checking…", style="Sub.TLabel")
        self.summary.pack(side="left", padx=16, pady=(6, 0))
        self.branch = ttk.Label(top, text="", style="Branch.TLabel")
        self.branch.pack(side="right", pady=(6, 0))

        paned = ttk.Panedwindow(self.root, orient="vertical")
        paned.pack(fill="both", expand=True, padx=20)
        self.book = ttk.Notebook(paned)
        paned.add(self.book, weight=3)
        self.output = Output(self, paned)
        paned.add(self.output.frame, weight=2)
        self.tabs = [tab(self, self.book) for tab in TABS]
        self.book.bind("<<NotebookTabChanged>>", lambda _e: self._tab_changed())
        self.paned = paned
        self.root.after(250, self._place_sash)

        foot = ttk.Frame(self.root, padding=(20, 6))
        foot.pack(fill="x")
        build = core.describe_build(core.read_build(Path(__file__).resolve().parent))
        ttk.Label(foot, text=build, style="Sub.TLabel").pack(side="left")
        ttk.Label(
            foot,
            text="Closing the window leaves everything running.",
            style="Sub.TLabel",
        ).pack(side="right")

    def _place_sash(self) -> None:
        height = self.paned.winfo_height()
        if height > 100:
            self.paned.sashpos(0, int(height * 0.74))  # type: ignore[no-untyped-call]

    def current_tab(self) -> Tab | None:
        index = tab_index(self.book)
        return self.tabs[index] if 0 <= index < len(self.tabs) else None

    def show_tab(self, title: str) -> None:
        for index, tab in enumerate(self.tabs):
            if tab.title == title:
                select_tab(self.book, index)

    def _tab_changed(self) -> None:
        tab = self.current_tab()
        if tab is not None:
            tab.shown()

    # scrolling the tab bodies (trees and text scroll themselves)
    def _scroller(self, widget: object) -> ScrollFrame | None:
        while isinstance(widget, tk.Misc):
            if isinstance(widget, (ttk.Treeview, tk.Text, tk.Listbox)):
                return None
            if isinstance(widget, ScrollFrame):
                return widget
            widget = widget.master
        return None

    def _wheel(self, event: tk.Event[tk.Misc]) -> None:
        frame = self._scroller(event.widget)
        if frame is not None and event.delta:
            notches = event.delta // 120 if abs(event.delta) >= 120 else event.delta
            frame.scroll(-notches * 24)

    def _touchpad(self, event: tk.Event[tk.Misc]) -> None:
        frame = self._scroller(event.widget)
        if frame is None:
            return
        try:
            deltas = self.root.tk.splitlist(
                self.root.tk.call("tk::PreciseScrollDeltas", event.delta)
            )
            frame.scroll(-int(float(deltas[1])))
        except (tk.TclError, ValueError, IndexError):
            return

    # output plumbing
    def _emit(self, event: core.RunnerEvent) -> None:
        if isinstance(event, core.Line):
            self._put_line(event.runner, event.text, event.tag)
        else:
            self.calls.put(lambda: self._on_runner(event))

    def _put_line(self, runner: str, text: str, tag: str | None) -> None:
        """Queue one output line; when the window falls that far behind, count it as dropped."""
        try:
            self.lines.put_nowait((runner, text, tag))
        except queue.Full:
            with self._dropped_lock:
                self._dropped[runner] = self._dropped.get(runner, 0) + 1

    def write(self, runner: str, text: str, tag: str | None = None) -> None:
        """A line of the panel's own into one of the output tabs."""
        self._put_line(runner, text, tag)

    def _drain(self) -> None:
        batches: dict[str, list[tuple[str, str | None]]] = {}
        for _ in range(3000):
            try:
                runner, text, tag = self.lines.get_nowait()
            except queue.Empty:
                break
            batch = batches.setdefault(runner, [])
            if batch and batch[-1][1] == tag:
                batch[-1] = (batch[-1][0] + text + "\n", tag)
            else:
                batch.append((text + "\n", tag))
        for runner, segments in batches.items():
            self.output.append(runner, segments)
        with self._dropped_lock:
            dropped, self._dropped = self._dropped, {}
        for runner, count in dropped.items():
            notice = f"… {count} lines not shown: they came faster than the window draws\n"
            self.output.append(runner, [(notice, "muted")])
        deadline = time.monotonic() + 0.05
        while time.monotonic() < deadline:
            try:
                call = self.calls.get_nowait()
            except queue.Empty:
                break
            call()
        self.root.after(80, self._drain)

    def _on_runner(self, event: core.RunnerEvent) -> None:
        gates = next(tab for tab in self.tabs if isinstance(tab, GatesTab))
        if isinstance(event, core.Begin):
            self.output.show(event.runner)
            if event.runner == "steps":
                for widget in self.guarded:
                    widget.state(["disabled"])
            if event.plan.gates and event.plan.keep_going:
                gates.begin(event.plan)
        elif isinstance(event, core.StepUpdate):
            if event.plan.gates:
                gates.update(event)
        elif isinstance(event, core.End):
            if event.runner == "steps":
                for widget in self.guarded:
                    widget.state(["!disabled"])
                self.root.after(300, self._poll_status_once)
                self.root.after(600, self.refresh_processes)
                for tab in self.tabs:
                    if isinstance(tab, DataTab):
                        tab.refresh_backups()
        self.output.refresh()

    # running plans
    def run(
        self,
        plan: core.Plan,
        *,
        read: bool = False,
        confirmed: bool = False,
        shared: bool = False,
        mine: str = "",
    ) -> None:
        """Start a plan after its checks and, where it asks for one, a confirm.

        ``shared``: the plan affects every session using the stack, so the confirm names the
        other sessions running in the checkout. ``mine``: the plan stops processes of that kind
        (web-stack, product, web); the confirm names those this panel did not start.
        """
        key = "reads" if read else "steps"
        problems = core.plan_problems(plan, self.project.known_targets)
        if problems:
            for problem in problems:
                self.write(key, f"error: {problem}", "err")
            self.output.show(key)
            return
        if not confirmed:
            text = plan.confirm or ""
            if shared:
                text += self.shared_note()
            if mine and (others := self.not_mine(mine)):
                text += (
                    ("\n\n" if text else "")
                    + f"{sentence(plan.title)} stops these, which this panel did not start:\n  "
                    + "\n  ".join(others)
                )
            if text and not messagebox.askokcancel(
                sentence(plan.title), text.strip(), icon="warning", parent=self.root
            ):
                return
        if not self.runners[key].start(plan):
            self.output.show(key)

    def shared_note(self) -> str:
        if self.snapshot is None:
            return ""
        others = self.snapshot.foreign_summary(self.project.repo)
        if not others:
            return ""
        return (
            "\n\nOther sessions are using this checkout right now:\n  "
            + "\n  ".join(others[:6])
            + "\nThis affects them too."
        )

    def not_mine(self, kind: str) -> list[str]:
        """Running processes of a kind (web-stack, product) this panel did not start: what make
        web-stack-down or make product-down would stop from their pid files."""
        repo = self.project.repo
        directory = {"web-stack": "web-stack", "product": "product"}[kind]
        # make web-stack-down stops every pid of var/web-stack, the web app's included
        recorded = {
            name: pid
            for name, pid in core.pid_files(repo / "var" / directory).items()
            if core.pid_alive(pid)
        }
        origins = self.snapshot.origins if self.snapshot is not None else {}
        groups = self.registry.groups()
        found = []
        for name, pid in sorted(recorded.items()):
            origin = origins.get(pid, "")
            if origin.startswith("this panel"):
                continue
            proc = self.snapshot.procs.get(pid) if self.snapshot is not None else None
            if proc is not None and proc.pgid in groups:
                continue
            command = core.short_command(proc.command, repo, 60) if proc else name
            found.append(f"{pid}  {command}  [{origin or 'recorded in var/' + directory}]")
        return found

    def open_console(self, path: Path) -> None:
        self.open_file(path)

    def open_url(self, url: str) -> None:
        self.open_file(url)

    def open_file(self, target: str | Path, *, text_editor: bool = False) -> None:
        """Open a URL, file or folder with macOS's open (an argument list, checked like every
        other program); a refusal or a missing program goes to the output instead."""
        try:
            core.open_path(target, self.project.env, text_editor=text_editor)
        except (core.RefusedError, OSError) as exc:
            self.write("reads", f"error: cannot open {target}: {exc}", "err")
            self.output.show("reads")

    # probes on threads
    def background(self, key: str, work: Callable[[], Callable[[], None]]) -> None:
        """Run work() on a thread unless one of this kind is in flight; its result is a callback
        the window runs."""
        if key in self._inflight:
            return
        self._inflight.add(key)

        def run() -> None:
            callback: Callable[[], None]
            try:
                callback = work()
            except Exception as exc:  # a probe's defect must not stop the window's polling
                callback = partial(
                    self.write, "reads", f"error: the {key} probe failed: {exc!r}", "err"
                )
            self.calls.put(callback)
            self.calls.put(lambda: self._inflight.discard(key))

        threading.Thread(target=run, daemon=True, name=f"probe-{key}").start()

    def _poll_status(self) -> None:
        self._poll_status_once()
        self.root.after(STATUS_MS, self._poll_status)

    def _poll_status_once(self) -> None:
        def work() -> Callable[[], None]:
            status = core.probe_status(self.project, self.manager)
            return lambda: self._show_status(status)

        self.background("status", work)

    def _poll_slow(self) -> None:
        self.refresh_git()
        self.refresh_processes()
        self.root.after(SLOW_MS, self._poll_slow)

    def refresh_git(self) -> None:
        def work() -> Callable[[], None]:
            state = core.probe_git(self.project.repo, self.project.env)
            if self.github is None:
                self.github = core.probe_remote(self.project.repo, self.project.env)
            return lambda: self._show_git(state)

        self.background("git", work)

    def refresh_processes(self) -> None:
        def work() -> Callable[[], None]:
            snapshot = core.probe_processes(self.project.repo, self.project.env, self.registry)
            return lambda: self._show_processes(snapshot)

        self.background("processes", work)

    def _show_status(self, status: core.Status) -> None:
        self.status = status
        for tab in self.tabs:
            tab.on_status(status)
        up = sum(status.up[f"service:{name}"] for name in core.SERVICES)
        infra = status.infra_up
        all_up = status.docker and infra == len(core.INFRA) and up == len(core.SERVICES)
        all_up = all_up and status.up["web"]
        if all_up:
            text = "Everything is running"
        elif not status.docker:
            text = "Stopped — click Start everything"
        else:
            web = "up" if status.up["web"] else "down"
            text = f"{up}/{len(core.SERVICES)} services up · web app {web}"
        if status.up["product.internal"]:
            text += " · product up"
        self.summary.configure(text=text, foreground=GREEN if all_up else MUTED)

    def _show_git(self, state: core.GitState) -> None:
        self.git = state
        if state.error:
            self.branch.configure(text="git: " + state.error[:60], style="BranchWarn.TLabel")
        elif state.on_main:
            self.branch.configure(text=f"main @ {state.sha}", style="Branch.TLabel")
        else:
            self.branch.configure(
                text=f"{state.branch} @ {state.sha} (not main)", style="BranchWarn.TLabel"
            )
        for tab in self.tabs:
            tab.on_git(state)

    def _show_processes(self, snapshot: core.ProcessSnapshot) -> None:
        self.snapshot = snapshot
        for tab in self.tabs:
            tab.on_processes(snapshot)

    # the big buttons
    def start_everything(self) -> None:
        self.run(self.plans.start_everything())

    def stop_everything(self) -> None:
        self._web_stop_preview(everything=True)

    def stop_web_app(self) -> None:
        self._web_stop_preview(everything=False)

    def _web_stop_preview(self, everything: bool) -> None:
        """Scan the processes first, so the confirm names exactly the pids the web app's stop
        reaches; the stop then leaves alone any pid the confirm did not name."""
        if (running := self.runners["steps"].plan) is not None:
            self.write(
                "steps", f"{running.title} is still running; wait for it or cancel it", "err"
            )
            self.output.show("steps")
            return

        def work() -> Callable[[], None]:
            snapshot = core.probe_processes(self.project.repo, self.project.env, self.registry)
            targets, notes = core.web_stop_targets(self.project, snapshot)
            return lambda: self._confirm_web_stop(snapshot, targets, notes, everything)

        self.write("steps", "reading the processes before the stop…", "muted")
        self.output.show("steps")
        self.background("stop-preview", work)

    def _confirm_web_stop(
        self,
        snapshot: core.ProcessSnapshot,
        targets: Sequence[core.StopTarget],
        notes: Sequence[str],
        everything: bool,
    ) -> None:
        self._show_processes(snapshot)
        repo = self.project.repo
        pids = [pid for target in targets for pid in target.pids]
        reach = "\n".join(core.describe_stop(target, snapshot, repo) for target in targets)
        left = "\n".join(notes)
        if everything:
            plan = self.plans.stop_everything(expected_web=pids)
            text = plan.confirm or ""
            text += f"\n\nThe web app's stop reaches:\n{reach}" if reach else ""
            text += f"\n\n{left}" if left else ""
            text += self.shared_note()
            if not messagebox.askokcancel(
                "Stop everything", text, icon="warning", parent=self.root
            ):
                return
        else:
            plan = self.plans.web_stop(expected=pids)
            if any(not snapshot.origins.get(p, "").startswith("this panel") for p in pids):
                text = (
                    f"Stop the web app:\n{reach}\n\nThis panel did not start every one of "
                    "these. Nothing else in their process groups is signalled."
                )
                text += f"\n\n{left}" if left else ""
                if not messagebox.askokcancel(
                    "Stop the web app", text, icon="warning", parent=self.root
                ):
                    return
        self.run(plan, confirmed=True)

    def _close(self) -> None:
        running = self.runners["steps"].plan
        if running is not None:
            if not messagebox.askokcancel(
                "Close the panel",
                f"{sentence(running.title)} is still running. Closing the window cancels it "
                "(SIGTERM to its process group). Close anyway?",
                icon="warning",
                parent=self.root,
            ):
                return
            self.runners["steps"].cancel()
        self.runners["reads"].cancel()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    Panel(root)
    root.lift()
    root.attributes("-topmost", True)
    root.after(300, lambda: root.attributes("-topmost", False))
    root.mainloop()


if __name__ == "__main__":
    main()
