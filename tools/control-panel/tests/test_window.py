"""What keeps the window responsive, tested without a display: when a wrapped label re-wraps
(and when it refuses to, because its width has started to depend on its own wrap), one probe of
each kind at a time, and the watch that logs a stalled event loop.

The flip below is the one that froze the panel after "Stop everything": on the Product tab,
never opened, a note's width went 612, 432, 612, 432… for ever, each wrap asking for the width
of the other.
"""

import sys
import tempfile
import threading
from pathlib import Path
from types import FrameType

import panel_core as core


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_a_label_re_wraps_only_when_its_width_moves_by_eight_pixels() -> None:
    assert core.rewrap_width(None, 600) == 592
    assert core.rewrap_width(592, 607) is None
    assert core.rewrap_width(592, 608) == 600
    # a narrowing under eight pixels keeps the wrap, which still fits: 592 < 593
    assert core.rewrap_width(592, 593) is None
    assert core.rewrap_width(592, 584) == 576
    assert core.rewrap_width(592, 1) is None  # not placed yet
    assert core.rewrap_width(None, 100) == core.WRAP_MINIMUM


def test_the_flip_that_froze_the_panel_settles_on_the_narrower_wrap() -> None:
    clock = Clock()
    state = core.WrapState(clock=clock)
    assert state.decide(612) == 604
    clock.now = 0.01
    assert state.decide(432) == 424
    clock.now = 0.02
    assert state.decide(612) is None  # back to the wrap of two re-wraps ago: a flip
    assert state.current == 424
    for step in range(50):
        clock.now = 0.03 + step / 100
        assert not state.wants(612)
        assert state.decide(612) is None
        assert state.decide(432) is None
    clock.now = 3.0
    assert state.decide(900) == 892  # a width somewhere new is followed again


def test_a_flip_back_to_the_narrower_wrap_is_taken_and_the_wider_refused() -> None:
    clock = Clock()
    state = core.WrapState(clock=clock)
    assert state.decide(600) == 592
    clock.now = 0.1
    assert state.decide(700) == 692
    clock.now = 0.2
    assert state.decide(600) == 592
    clock.now = 0.3
    assert state.decide(700) is None
    assert state.current == 592


def test_a_slow_resize_back_and_forth_is_followed() -> None:
    clock = Clock()
    state = core.WrapState(clock=clock)
    widths = (600, 700, 600, 700)
    for second, width in enumerate(widths):
        clock.now = second * (core.WRAP_FLIP_SECONDS + 1)
        assert state.decide(width) == width - core.WRAP_MARGIN


def test_one_probe_of_each_kind_at_a_time() -> None:
    flights = core.SingleFlight()
    assert flights.begin("status")
    assert not flights.begin("status")
    assert flights.begin("git")
    assert flights.running() == {"status", "git"}
    flights.end("status")
    assert flights.begin("status")
    flights.end("status")
    flights.end("git")
    wins: list[bool] = []
    start = threading.Barrier(16)

    def race() -> None:
        start.wait()
        wins.append(flights.begin("processes"))

    threads = [threading.Thread(target=race) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert wins.count(True) == 1


def watch_at(directory: Path, clock: Clock) -> core.HangWatch:
    main = threading.get_ident()
    frame = sys._getframe(1)  # the test's own frame stands in for the main thread's
    return core.HangWatch(
        directory,
        main,
        clock=clock,
        wall=lambda: 1_790_000_000.0,
        frames=lambda: {main: frame},
        context=lambda: "Panel build: test build",
    )


def test_a_stalled_event_loop_is_logged_once_with_its_stack_and_pending_list(
    tmp_path: Path,
) -> None:
    clock = Clock()
    directory = tmp_path / "var" / "control-panel"
    watch = watch_at(directory, clock)
    watch.beat("  after#7: timer 4542048384_drain")
    clock.now = core.HANG_SECONDS - 0.1
    assert watch.check() is None
    clock.now = 6.0
    path = watch.check()
    assert path is not None
    assert path.parent == directory
    assert path.name.startswith("hang-")
    assert path.suffix == ".log"
    text = path.read_text()
    assert "had not run for 6.0 s" in text
    assert "test_a_stalled_event_loop_is_logged_once_with_its_stack_and_pending_list" in text
    assert "after#7: timer 4542048384_drain" in text
    assert "Panel build: test build" in text
    clock.now = 9.0
    assert watch.check() is None  # once per stall
    assert watch.recovered() is None  # still stalled
    clock.now = 10.0
    watch.beat()
    assert watch.recovered() == (path, 10.0)
    assert watch.recovered() is None
    clock.now = 12.0
    assert watch.check() is None  # running again
    assert list(directory.iterdir()) == [path]


def test_a_hang_log_goes_to_a_temporary_folder_when_var_cannot_be_written(
    tmp_path: Path,
) -> None:
    blocked = tmp_path / "var"
    blocked.write_text("a file where the folder should be")
    clock = Clock()
    watch = watch_at(blocked / "control-panel", clock)
    clock.now = 6.0
    path = watch.check()
    assert path is not None
    try:
        assert path.parent == Path(tempfile.gettempdir()) / "compliancewatch-control-panel"
        assert "had not run for 6.0 s" in path.read_text()
    finally:
        path.unlink(missing_ok=True)


def mainloop() -> FrameType:
    """Stands for tkinter's Misc.mainloop, the frame the main thread waits for events in."""
    return sys._getframe()


def test_a_late_beat_while_the_loop_only_waits_is_not_a_hang(tmp_path: Path) -> None:
    clock, used = Clock(), Clock()
    main = threading.get_ident()
    waiting = mainloop()
    watch = core.HangWatch(tmp_path, main, clock=clock, frames=lambda: {main: waiting}, cpu=used)
    watch.beat()
    clock.now = 8.0
    used.now = 0.2  # macOS's App Nap held the timers back; the process slept
    assert watch.check() is None
    assert not list(tmp_path.iterdir())
    clock.now = 9.0
    used.now = 6.0  # Tcl spinning on its own, the freeze of "Stop everything"
    path = watch.check()
    assert path is not None
    assert "in mainloop" in path.read_text()
