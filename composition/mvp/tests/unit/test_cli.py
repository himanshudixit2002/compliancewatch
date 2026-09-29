"""``cw-mvp``: every command parses and runs what it names."""

import pytest

from cw_mvp import serve as serve_module
from cw_mvp.cli import main


def test_the_command_line_routes_serve(monkeypatch: pytest.MonkeyPatch) -> None:
    served: list[bool] = []
    monkeypatch.setattr(serve_module, "serve", lambda: served.append(True))
    assert main(["serve"]) == 0
    assert served == [True]
    with pytest.raises(SystemExit):
        main([])
