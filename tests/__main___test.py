# noqa: CPY001

import functools
import io
import re
import textwrap

from dbrownell_Common.Streams.DoneManager import DoneManager
from typer.testing import CliRunner

from RepoRemedy import __version__
from RepoRemedy.__main__ import app


# ----------------------------------------------------------------------
def _Invoke(*args: str):
    result = CliRunner().invoke(app, list(args))
    assert result.exit_code == 0, result.output

    return result


# ----------------------------------------------------------------------
def test_Version():
    assert _Invoke("--version").output == f"RepoRemedy v{__version__}\n"


# ----------------------------------------------------------------------
def test_EntryPoint(monkeypatch):
    # DoneManager binds sys.stdout as a default argument at import time, bypassing CliRunner's capture
    sink = io.StringIO()
    monkeypatch.setattr(
        DoneManager, "CreateCommandLine", functools.partial(DoneManager.CreateCommandLine, stream=sink)
    )

    _Invoke("--verbose")

    # Elapsed time varies per run
    output = re.sub(r"\(0, [\d:.]+\)", "(0, <time>)", sink.getvalue())

    assert output == textwrap.dedent(
        """\
        Hello, world!

        Results: DONE! (0, <time>)

        """,
    )
