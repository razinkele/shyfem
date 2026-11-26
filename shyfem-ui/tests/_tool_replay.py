"""Replay the real captured output of a SHYFEM tool run (``tests/fixtures/tool_stdout``).

A fake tool that prints a capture's stdout and stderr and exits with its
status, so a test drives the real ``ShyfemWrapper`` with real tool output.
"""

import shlex
from pathlib import Path

from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper

FIX = Path(__file__).parent / "fixtures" / "tool_stdout"


def case(name: str) -> tuple[int, str, str]:
    """(exit status, stdout, stderr) of a capture."""
    code = int((FIX / f"{name}.exit").read_text())
    return code, (FIX / f"{name}.stdout").read_text(), (FIX / f"{name}.stderr").read_text()


def replay(wrapper: ShyfemWrapper, tool: str, name: str) -> None:
    """Install ``tool`` in the wrapper's bin folder as a replay of capture ``name``."""
    code = int((FIX / f"{name}.exit").read_text())
    exe = wrapper.bin_dir / tool
    exe.write_text(
        "#!/bin/bash\n"
        f"cat {shlex.quote(str(FIX / (name + '.stdout')))}\n"
        f"cat {shlex.quote(str(FIX / (name + '.stderr')))} >&2\n"
        f"exit {code}\n"
    )
    exe.chmod(0o755)


def make_wrapper(tmp_path: Path) -> ShyfemWrapper:
    d = tmp_path / "shyfem"
    (d / "bin").mkdir(parents=True, exist_ok=True)
    return ShyfemWrapper(d)
