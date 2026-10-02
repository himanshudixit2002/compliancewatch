"""ComplianceWatch control panel: one window that starts, stops and watches the local dev stack.

Every button runs the same `make` targets as docs/onboarding/local-dev.md, so the panel adds no
behaviour of its own. Standard library only (tkinter); run it with the repo's Python:

    .venv/bin/python tools/control-panel/control_panel.py
"""

from __future__ import annotations

import contextlib
import os
import queue
import signal
import subprocess
import threading
import time
import tkinter as tk
import urllib.request
import webbrowser
from pathlib import Path
from tkinter import ttk

REPO = Path(__file__).resolve().parents[2]
STACK_DIR = REPO / "var" / "web-stack"
WEB_PID = STACK_DIR / "web.pid"
WEB_LOG = STACK_DIR / "web.log"
WEB_URL = "http://localhost:3000"
TEMPORAL_UI = "http://localhost:8233"

SERVICES = [
    ("identity", 8001),
    ("profile", 8002),
    ("rulebook", 8003),
    ("applicability-engine", 8004),
    ("obligation", 8005),
    ("notification", 8006),
    ("qa", 8007),
    ("llm-gateway", 8008),
    ("eval", 8009),
    ("pipeline", 8010),
]
INFRA = ["postgres", "redis", "redpanda", "temporal", "temporal-ui"]
COLIMA_START = "colima start --cpu 4 --memory 8 --disk 60 --dns 1.1.1.1 --dns 8.8.8.8"

# A Finder-launched app gets a bare PATH; put Homebrew's tools first.
ENV = dict(os.environ)
ENV["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + ENV.get("PATH", "/usr/bin:/bin")

# Palette
BG, PANEL, TEXT, MUTED = "#14171c", "#1d2128", "#e6e8eb", "#8b93a1"
GREEN, RED, AMBER, ACCENT = "#3fb950", "#f85149", "#d29922", "#4c8dff"


# ---- probes (background thread) ---------------------------------------------------------------
def _ok(cmd: list[str], timeout: float = 4) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, cwd=REPO, env=ENV, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False, ""


def _http_up(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=0.8) as r:
            return r.status < 500
    except Exception:
        return False


def probe() -> dict:
    docker, _ = _ok(["docker", "info"])
    healthy = 0
    if docker:
        _, out = _ok(["docker", "compose", "ps", "--format", "{{.Service}} {{.Health}} {{.State}}"])
        for line in out.splitlines():
            parts = line.split()
            if parts and parts[0] in INFRA and ("healthy" in parts[1:] or parts[1:] == ["running"]):
                healthy += 1
    services = {name: _http_up(f"http://localhost:{port}/health") for name, port in SERVICES}
    return {"docker": docker, "infra": healthy, "services": services, "web": _http_up(WEB_URL)}


# ---- web app process --------------------------------------------------------------------------
def start_web(log) -> bool:
    if _http_up(WEB_URL):
        log("web app already running on " + WEB_URL)
        return True
    STACK_DIR.mkdir(parents=True, exist_ok=True)
    with open(WEB_LOG, "ab") as fh:
        proc = subprocess.Popen(
            ["pnpm", "--filter", "web", "dev"],
            cwd=REPO,
            env=ENV,
            stdout=fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    WEB_PID.write_text(str(proc.pid))
    log(f"web app starting (pid {proc.pid}, log {WEB_LOG.relative_to(REPO)})")
    for _ in range(60):
        if _http_up(WEB_URL):
            log("web app ready on " + WEB_URL)
            return True
        if proc.poll() is not None:
            break
        time.sleep(1)
    log("error: web app did not start; see " + str(WEB_LOG))
    return False


def stop_web(log) -> bool:
    if WEB_PID.exists():
        with contextlib.suppress(ProcessLookupError, ValueError, PermissionError):
            os.killpg(int(WEB_PID.read_text()), signal.SIGTERM)
        WEB_PID.unlink(missing_ok=True)
    # Also catch a web app started from a terminal.
    _, pids = _ok(["lsof", "-ti", "tcp:3000", "-sTCP:LISTEN"])
    for pid in pids.split():
        with contextlib.suppress(ProcessLookupError, ValueError):
            os.kill(int(pid), signal.SIGTERM)
    log("web app stopped")
    return True


# ---- the window -------------------------------------------------------------------------------
class Panel:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self.buttons: list[ttk.Button] = []
        self.status: dict = {}

        root.title("ComplianceWatch")
        root.configure(bg=BG)
        root.geometry("980x720")
        root.minsize(860, 600)
        self._styles()
        self._build()
        self._poll_status()
        root.after(100, self._drain)

    # styles
    def _styles(self) -> None:
        s = ttk.Style()
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=TEXT, font=("Helvetica", 13))
        s.configure("Panel.TFrame", background=PANEL)
        s.configure("TLabel", background=BG, foreground=TEXT)
        s.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        s.configure("Muted.TLabel", background=PANEL, foreground=MUTED, font=("Helvetica", 11))
        s.configure("Title.TLabel", font=("Helvetica", 22, "bold"))
        s.configure("Sub.TLabel", foreground=MUTED, font=("Helvetica", 12))
        s.configure(
            "Head.TLabel", background=PANEL, foreground=MUTED, font=("Helvetica", 11, "bold")
        )
        for name, color, hover in (
            ("TButton", "#2a303a", "#353c48"),
            ("Primary.TButton", "#238636", "#2ea043"),
            ("Danger.TButton", "#8b2c2c", "#a83636"),
            ("Accent.TButton", "#1f4fa8", "#2a62c9"),
        ):
            s.configure(
                name,
                background=color,
                foreground="#ffffff",
                borderwidth=0,
                focusthickness=0,
                padding=(12, 7),
                font=("Helvetica", 12),
            )
            s.map(
                name,
                background=[("disabled", "#2a2e35"), ("active", hover)],
                foreground=[("disabled", "#6b7280")],
            )
        s.configure("Big.Primary.TButton", padding=(18, 12), font=("Helvetica", 14, "bold"))
        s.configure("Big.Danger.TButton", padding=(18, 12), font=("Helvetica", 14, "bold"))
        s.configure("Big.Accent.TButton", padding=(18, 12), font=("Helvetica", 14, "bold"))

    def _button(self, parent, text, cmd, style="TButton", guarded=True) -> ttk.Button:
        b = ttk.Button(parent, text=text, command=cmd, style=style, cursor="hand2")
        if guarded:
            self.buttons.append(b)
        return b

    # layout
    def _build(self) -> None:
        top = ttk.Frame(self.root, padding=(20, 16, 20, 8))
        top.pack(fill="x")
        ttk.Label(top, text="ComplianceWatch", style="Title.TLabel").pack(side="left")
        self.summary = ttk.Label(top, text="checking…", style="Sub.TLabel")
        self.summary.pack(side="left", padx=16, pady=(6, 0))

        big = ttk.Frame(self.root, padding=(20, 4, 20, 12))
        big.pack(fill="x")
        self._button(big, "▶  Start everything", self.start_all, "Big.Primary.TButton").pack(
            side="left"
        )
        self._button(big, "■  Stop everything", self.stop_all, "Big.Danger.TButton").pack(
            side="left", padx=10
        )
        self._button(
            big,
            "Open web app  ↗",
            lambda: webbrowser.open(WEB_URL),
            "Big.Accent.TButton",
            guarded=False,
        ).pack(side="left")

        body = ttk.Frame(self.root, padding=(20, 0, 20, 0))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=0, minsize=330)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # status column
        st = ttk.Frame(body, style="Panel.TFrame", padding=14)
        st.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        ttk.Label(st, text="STATUS", style="Head.TLabel").pack(anchor="w", pady=(0, 6))
        self.dots: dict[str, tuple[tk.Label, ttk.Label]] = {}
        self._status_row(st, "docker", "Docker (Colima)")
        self._status_row(st, "infra", "Databases & queues")
        self._status_row(st, "web", "Web app  :3000", link=WEB_URL)
        ttk.Label(st, text="SERVICES", style="Head.TLabel").pack(anchor="w", pady=(12, 6))
        for name, port in SERVICES:
            self._status_row(
                st,
                name,
                f"{name}  :{port}",
                link=f"http://localhost:{port}/docs",
                log=STACK_DIR / f"{name}.log",
            )

        # actions + log column
        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        acts = ttk.Frame(right, style="Panel.TFrame", padding=14)
        acts.grid(row=0, column=0, sticky="ew")
        groups = [
            ("Docker", [("Start", self.docker_start), ("Stop", self.docker_stop)]),
            (
                "Databases",
                [
                    ("Start", lambda: self.run([("make dev", "make dev")])),
                    ("Stop", lambda: self.run([("make dev-down", "make dev-down")])),
                ],
            ),
            (
                "Services",
                [
                    ("Start", self.services_start),
                    ("Stop", lambda: self.run([("make web-stack-down", "make web-stack-down")])),
                    ("Restart", self.services_restart),
                ],
            ),
            (
                "Web app",
                [
                    ("Start", lambda: self.run([("start web app", start_web)])),
                    ("Stop", lambda: self.run([("stop web app", stop_web)])),
                ],
            ),
            (
                "Data",
                [
                    ("Migrate DB", lambda: self.run([("make migrate", "make migrate")])),
                    ("Load demo data", self.seed),
                    ("Reset DB", self.reset_db),
                ],
            ),
            (
                "Tools",
                [
                    ("Run demo", lambda: self.run([("make demo", "make demo")])),
                    ("Run tests", lambda: self.run([("make test", "make test")])),
                    ("Temporal UI ↗", lambda: webbrowser.open(TEMPORAL_UI)),
                    ("Logs folder", lambda: subprocess.run(["open", str(STACK_DIR)])),
                ],
            ),
        ]
        acts.columnconfigure(1, weight=1)
        for r, (label, items) in enumerate(groups):
            ttk.Label(acts, text=label, style="Panel.TLabel", width=11).grid(
                row=r, column=0, sticky="w", pady=4
            )
            row = ttk.Frame(acts, style="Panel.TFrame")
            row.grid(row=r, column=1, sticky="w", pady=4)
            for text, cmd in items:
                guarded = not text.endswith("↗") and text != "Logs folder"
                self._button(row, text, cmd, guarded=guarded).pack(side="left", padx=(0, 6))

        logf = ttk.Frame(right, style="Panel.TFrame", padding=(14, 10, 14, 14))
        logf.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        hdr = ttk.Frame(logf, style="Panel.TFrame")
        hdr.pack(fill="x")
        ttk.Label(hdr, text="OUTPUT", style="Head.TLabel").pack(side="left")
        self.busy_label = ttk.Label(hdr, text="", style="Muted.TLabel")
        self.busy_label.pack(side="left", padx=10)
        self._button(hdr, "Clear", lambda: self.out.delete("1.0", "end"), guarded=False).pack(
            side="right"
        )
        self.out = tk.Text(
            logf,
            bg="#0d1015",
            fg="#c9d1d9",
            insertbackground=TEXT,
            relief="flat",
            font=("Menlo", 11),
            wrap="word",
            highlightthickness=0,
            padx=8,
            pady=6,
        )
        sb = ttk.Scrollbar(logf, command=self.out.yview)
        self.out.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", pady=(8, 0))
        self.out.pack(fill="both", expand=True, pady=(8, 0))
        self.out.tag_configure("step", foreground=ACCENT, font=("Menlo", 11, "bold"))
        self.out.tag_configure("err", foreground=RED)
        self.out.tag_configure("ok", foreground=GREEN)

        foot = ttk.Label(
            self.root,
            text="Closing this window leaves everything running. Use Stop everything to shut down.",
            style="Sub.TLabel",
            padding=(20, 8),
        )
        foot.pack(fill="x")

    def _status_row(self, parent, key, text, link=None, log=None) -> None:
        row = ttk.Frame(parent, style="Panel.TFrame")
        row.pack(fill="x", pady=2)
        dot = tk.Label(row, text="●", fg=MUTED, bg=PANEL, font=("Helvetica", 14))
        dot.pack(side="left")
        lbl = ttk.Label(row, text=text, style="Panel.TLabel")
        lbl.pack(side="left", padx=6)
        detail = ttk.Label(row, text="", style="Muted.TLabel")
        detail.pack(side="left")
        if log:
            lg = ttk.Label(row, text="log", style="Muted.TLabel", cursor="hand2")
            lg.pack(side="right", padx=(6, 0))
            lg.bind("<Button-1>", lambda _e: subprocess.run(["open", "-a", "Console", str(log)]))
        if link:
            a = ttk.Label(row, text="open", style="Muted.TLabel", cursor="hand2")
            a.pack(side="right")
            a.bind("<Button-1>", lambda _e: webbrowser.open(link))
        self.dots[key] = (dot, detail)

    # status polling
    def _poll_status(self) -> None:
        def work():
            self.events.put(("status", probe()))

        threading.Thread(target=work, daemon=True).start()
        self.root.after(4000, self._poll_status)

    def _show_status(self, s: dict) -> None:
        self.status = s

        def set_(key, up, detail="", partial=False):
            dot, d = self.dots[key]
            dot.configure(fg=GREEN if up else (AMBER if partial else RED))
            d.configure(text=detail)

        set_("docker", s["docker"], "running" if s["docker"] else "stopped")
        n = s["infra"]
        set_("infra", n == len(INFRA), f"{n}/{len(INFRA)} healthy", partial=0 < n < len(INFRA))
        set_("web", s["web"])
        for name, up in s["services"].items():
            set_(name, up)
        up = sum(s["services"].values())
        all_up = s["docker"] and n == len(INFRA) and up == len(SERVICES) and s["web"]
        if all_up:
            text = "Everything is running"
        elif not s["docker"]:
            text = "Stopped — click Start everything"
        else:
            text = f"{up}/{len(SERVICES)} services up · web app {'up' if s['web'] else 'down'}"
        self.summary.configure(text=text, foreground=GREEN if all_up else MUTED)

    # output plumbing
    def log(self, text: str, tag: str | None = None) -> None:
        self.events.put(("log", text, tag))

    def _drain(self) -> None:
        try:
            while True:
                ev = self.events.get_nowait()
                if ev[0] == "log":
                    self.out.insert("end", ev[1] + "\n", ev[2] or ())
                    self.out.see("end")
                elif ev[0] == "status":
                    self._show_status(ev[1])
                elif ev[0] == "busy":
                    self._set_busy(ev[1])
        except queue.Empty:
            pass
        self.root.after(100, self._drain)

    def _set_busy(self, label: str | None) -> None:
        self.busy = label is not None
        for b in self.buttons:
            b.state(["disabled"] if self.busy else ["!disabled"])
        self.busy_label.configure(text=f"working: {label}…" if label else "")

    # running steps
    def run(self, steps: list[tuple[str, object]], title: str | None = None) -> None:
        """Run steps in order; a step is a shell command string or a callable(log) -> bool."""
        if self.busy:
            return
        title = title or steps[0][0]
        self.events.put(("busy", title))

        def work():
            ok = True
            for name, step in steps:
                self.log(f"\n▸ {name}", "step")
                ok = bool(step(self.log)) if callable(step) else self._shell(step)
                if not ok:
                    self.log(f"✗ {name} failed — stopped here.", "err")
                    break
            if ok:
                self.log(f"✓ {title} done", "ok")
            self.events.put(("busy", None))
            self.events.put(("status", probe()))

        threading.Thread(target=work, daemon=True).start()

    def _shell(self, cmd: str) -> bool:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            cwd=REPO,
            env=ENV,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                self.log(line, "err" if "error" in line.lower() else None)
        return proc.wait() == 0

    # actions
    def _docker_up(self, log) -> bool:
        if _ok(["docker", "info"])[0]:
            log("Docker is already running")
            return True
        return self._shell(COLIMA_START)

    def docker_start(self) -> None:
        self.run([("start Docker", self._docker_up)])

    def docker_stop(self) -> None:
        self.run([("stop Docker", "colima stop")])

    def services_start(self) -> None:
        self.run(
            [
                ("make web-stack", "make web-stack STORE=postgres"),
                ("wait for services", "make web-stack-wait"),
            ]
        )

    def services_restart(self) -> None:
        self.run(
            [
                ("stop services", "make web-stack-down"),
                ("make web-stack", "make web-stack STORE=postgres"),
                ("wait for services", "make web-stack-wait"),
            ],
            title="restart services",
        )

    def seed(self) -> None:
        self.run(
            [
                ("seed rulebook", "make seed SERVICE=rulebook"),
                ("seed demo tenant", "make web-seed"),
            ],
            title="load demo data",
        )

    def reset_db(self) -> None:
        from tkinter import messagebox

        if not messagebox.askyesno(
            "Reset database", "Delete all local data and start with an empty database?"
        ):
            return
        self.run(
            [
                ("stop services", "make web-stack-down"),
                ("make dev-reset", "make dev-reset"),
                ("make dev", "make dev"),
                ("make migrate", "make migrate"),
                ("seed rulebook", "make seed SERVICE=rulebook"),
            ],
            title="reset database",
        )

    def start_all(self) -> None:
        self.run(
            [
                ("start Docker", self._docker_up),
                ("start databases and queues", "make dev"),
                ("migrate databases", "make migrate"),
                ("start services", "make web-stack STORE=postgres"),
                ("wait for services", "make web-stack-wait"),
                ("start web app", start_web),
                ("open browser", lambda log: webbrowser.open(WEB_URL) or True),
            ],
            title="start everything",
        )

    def stop_all(self) -> None:
        def docker_down(log):
            if not _ok(["docker", "info"])[0]:
                log("Docker is already stopped")
                return True
            return self._shell("make dev-down") and self._shell("colima stop")

        self.run(
            [
                ("stop web app", stop_web),
                ("stop services", "make web-stack-down"),
                ("stop databases and Docker", docker_down),
            ],
            title="stop everything",
        )


def main() -> None:
    root = tk.Tk()
    Panel(root)
    root.lift()
    root.attributes("-topmost", True)
    root.after(300, lambda: root.attributes("-topmost", False))
    root.mainloop()


if __name__ == "__main__":
    main()
