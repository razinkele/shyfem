"""Wrapper for SHYFEM Fortran CLI tools."""

import asyncio
import logging
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    """Result of a SHYFEM command execution."""

    success: bool
    return_code: int
    stdout: str
    stderr: str
    command: str
    working_dir: str
    duration: float = 0.0
    output_files: list[str] = field(default_factory=list)


class ShyfemWrapper:
    """Wrapper for SHYFEM command-line tools.

    Provides async execution with output streaming and progress tracking.
    """

    ALLOWED_TOOLS = frozenset(
        {
            "shyfem",
            "shyfem-petsc",
            "shypre",
            "shybas",
            "shyparts",
            "shyelab",
            "shyplot",
            "exgrd",
            "shyadj",
            "rstinf",
            "lgrelab",
        }
    )

    # Map tool names to expected output file extensions
    OUTPUT_EXTENSIONS = {
        "shypre": [".bas"],
        "shybas": [".grd", ".xyz", ".png"],
        "shyparts": [".par"],
        "shyfem": [".shy", ".ext", ".flx", ".ts"],
        "shyelab": [".nc", ".txt", ".dat"],
        "shyplot": [".png", ".pdf", ".eps"],
    }

    # Progress patterns for different tools
    PROGRESS_PATTERNS = {
        "shyfem": re.compile(r"time\s*=\s*([\d.]+).*(?:of|to)\s*([\d.]+)", re.IGNORECASE),
        "shyelab": re.compile(r"processing\s+record\s+(\d+)\s+of\s+(\d+)", re.IGNORECASE),
    }

    def __init__(self, shyfem_dir: Path | str):
        """Initialize wrapper with SHYFEM installation directory."""
        self.shyfem_dir = Path(shyfem_dir)
        self.bin_dir = self.shyfem_dir / "bin"

    def get_executable(self, tool_name: str) -> Path:
        """Get full path to a SHYFEM executable."""
        if tool_name not in self.ALLOWED_TOOLS:
            raise ValueError(
                f"{tool_name!r} is not an allowed SHYFEM tool. "
                f"Allowed: {sorted(self.ALLOWED_TOOLS)}"
            )
        exe = self.bin_dir / tool_name
        if exe.exists():
            return exe
        # Try without bin/ directory
        alt = self.shyfem_dir / tool_name
        if alt.exists():
            return alt
        # Check system PATH
        which = shutil.which(tool_name)
        if which:
            return Path(which)
        raise FileNotFoundError(f"Executable not found: {tool_name}")

    def check_available(self, tool_name: str) -> bool:
        """Check if a SHYFEM tool is available."""
        try:
            self.get_executable(tool_name)
            return True
        except FileNotFoundError:
            return False

    # Map solver names to executable names
    SOLVER_EXECUTABLES = {
        "sparskit": "shyfem",
        "petsc": "shyfem-petsc",
    }

    def check_solver_available(self, solver: str) -> bool:
        """Check if a solver variant is available."""
        exe_name = self.SOLVER_EXECUTABLES.get(solver)
        if exe_name is None:
            return False
        return self.check_available(exe_name)

    async def run_command(
        self,
        tool_name: str,
        args: list[str],
        working_dir: Path | str,
        progress_callback: Callable[[float, str], None] | None = None,
        output_callback: Callable[[str], None] | None = None,
        env: dict[str, str] | None = None,
        command_prefix: list[str] | None = None,
    ) -> CommandResult:
        """Run a SHYFEM command asynchronously.

        Args:
            tool_name: Name of the SHYFEM tool (shypre, shybas, etc.)
            args: Command arguments
            working_dir: Working directory for execution
            progress_callback: Called with (progress_fraction, message)
            output_callback: Called with each line of output
            env: Additional environment variables
            command_prefix: Optional prefix for the command (e.g. ["mpirun", "-np", "4"])

        Returns:
            CommandResult with execution details
        """
        exe = self.get_executable(tool_name)
        working_dir = Path(working_dir)
        working_dir.mkdir(parents=True, exist_ok=True)

        # Build environment
        run_env = os.environ.copy()
        run_env["SHYFEMDIR"] = str(self.shyfem_dir)
        if env:
            run_env.update(env)

        # Build command
        if command_prefix:
            cmd = command_prefix + [str(exe)] + args
        else:
            cmd = [str(exe)] + args
        cmd_str = " ".join(cmd)

        start_time = datetime.now()
        stdout_lines = []
        stderr_lines = []

        # Optional wall-clock timeout (None = disabled; preserves long sims).
        from shyfem_ui.config import get_config

        timeout = get_config().command_timeout_seconds

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
                env=run_env,
            )

            # Read output streams concurrently
            async def read_stream(stream, lines_list, is_stderr=False):
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    decoded = line.decode("utf-8", errors="replace").rstrip()
                    lines_list.append(decoded)

                    if output_callback:
                        output_callback(decoded)

                    # Check for progress
                    if progress_callback and not is_stderr:
                        progress = self._parse_progress(tool_name, decoded)
                        if progress is not None:
                            progress_callback(progress, decoded)

            async def _drain_and_wait():
                await asyncio.gather(
                    read_stream(proc.stdout, stdout_lines),
                    read_stream(proc.stderr, stderr_lines, is_stderr=True),
                )
                await proc.wait()

            if timeout:
                await asyncio.wait_for(_drain_and_wait(), timeout=timeout)
            else:
                await _drain_and_wait()
            return_code = proc.returncode

        except asyncio.TimeoutError:
            # A hung tool would otherwise wedge the job (and queue) forever.
            logger.warning("Command %r exceeded %ss timeout; terminating", cmd_str, timeout)
            proc.kill()
            try:
                await proc.wait()
            except Exception:
                logger.debug("Error awaiting killed process", exc_info=True)
            return CommandResult(
                success=False,
                return_code=-1,
                stdout="\n".join(stdout_lines),
                stderr=f"Command timed out after {timeout}s and was terminated",
                command=cmd_str,
                working_dir=str(working_dir),
            )
        except Exception as e:
            return CommandResult(
                success=False,
                return_code=-1,
                stdout="",
                stderr=str(e),
                command=cmd_str,
                working_dir=str(working_dir),
            )

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        # Find output files
        output_files = self._find_output_files(tool_name, working_dir)

        return CommandResult(
            success=return_code == 0,
            return_code=return_code,
            stdout="\n".join(stdout_lines),
            stderr="\n".join(stderr_lines),
            command=cmd_str,
            working_dir=str(working_dir),
            duration=duration,
            output_files=output_files,
        )

    def _parse_progress(self, tool_name: str, line: str) -> float | None:
        """Parse progress from output line."""
        pattern = self.PROGRESS_PATTERNS.get(tool_name)
        if not pattern:
            return None

        match = pattern.search(line)
        if match:
            try:
                current = float(match.group(1))
                total = float(match.group(2))
                if total > 0:
                    return min(1.0, current / total)
            except (ValueError, IndexError):
                pass
        return None

    def _find_output_files(self, tool_name: str, working_dir: Path) -> list[str]:
        """Find output files created by a tool."""
        extensions = self.OUTPUT_EXTENSIONS.get(tool_name, [])
        output_files = []
        for ext in extensions:
            for f in working_dir.glob(f"*{ext}"):
                output_files.append(str(f))
        return output_files

    # Convenience methods for specific tools

    async def run_shypre(
        self,
        grd_file: Path | str,
        working_dir: Path | str,
        options: list[str] | None = None,
        progress_callback: Callable[[float, str], None] | None = None,
        output_callback: Callable[[str], None] | None = None,
    ) -> CommandResult:
        """Run shypre to convert .grd to .bas file.

        Args:
            grd_file: Path to input .grd file
            working_dir: Working directory
            options: Additional options like ["-opti", "-renumber"]
        """
        args = list(options) if options else []   # copy: never mutate caller's list
        args.append(str(grd_file))
        return await self.run_command(
            "shypre", args, working_dir, progress_callback, output_callback
        )

    async def run_shybas(
        self,
        bas_file: Path | str,
        working_dir: Path | str,
        options: list[str] | None = None,
        progress_callback: Callable[[float, str], None] | None = None,
        output_callback: Callable[[str], None] | None = None,
    ) -> CommandResult:
        """Run shybas to analyze basin file.

        Args:
            bas_file: Path to input .bas file
            working_dir: Working directory
            options: Additional options like ["-quality", "-grd", "-xyz"]
        """
        args = list(options) if options else []   # copy: never mutate caller's list
        args.append(str(bas_file))
        return await self.run_command(
            "shybas", args, working_dir, progress_callback, output_callback
        )

    async def run_shyparts(
        self,
        bas_file: Path | str,
        working_dir: Path | str,
        np: int = 4,
        options: list[str] | None = None,
        progress_callback: Callable[[float, str], None] | None = None,
        output_callback: Callable[[str], None] | None = None,
    ) -> CommandResult:
        """Run shyparts to partition mesh for MPI.

        Args:
            bas_file: Path to input .bas file
            working_dir: Working directory
            np: Number of partitions
            options: Additional options
        """
        args = list(options) if options else []   # copy: never mutate caller's list
        args.extend(["-np", str(np)])
        args.append(str(bas_file))
        return await self.run_command(
            "shyparts", args, working_dir, progress_callback, output_callback
        )

    async def run_shyfem(
        self,
        str_file: Path | str,
        working_dir: Path | str,
        mpi_enabled: bool = False,
        mpi_np: int = 1,
        mpirun_path: str = "mpirun",
        options: list[str] | None = None,
        solver: str = "sparskit",
        progress_callback: Callable[[float, str], None] | None = None,
        output_callback: Callable[[str], None] | None = None,
    ) -> CommandResult:
        """Run shyfem simulation.

        Args:
            str_file: Path to input .str file
            working_dir: Working directory
            mpi_enabled: Whether to use MPI
            mpi_np: Number of MPI processes
            mpirun_path: Path to mpirun executable
            options: Additional options
            solver: Solver variant ('sparskit' or 'petsc')
        """
        tool_name = self.SOLVER_EXECUTABLES.get(solver, "shyfem")
        args_list = options or []
        args_list.append(str(str_file))

        prefix = None
        if mpi_enabled and mpi_np > 1:
            prefix = [mpirun_path, "-np", str(mpi_np)]

        return await self.run_command(
            tool_name,
            args_list,
            working_dir,
            progress_callback,
            output_callback,
            command_prefix=prefix,
        )

    async def run_shyelab(
        self,
        shy_file: Path | str,
        working_dir: Path | str,
        options: list[str] | None = None,
        progress_callback: Callable[[float, str], None] | None = None,
        output_callback: Callable[[str], None] | None = None,
    ) -> CommandResult:
        """Run shyelab to post-process output.

        Args:
            shy_file: Path to input .shy file
            working_dir: Working directory
            options: Additional options like ["-split", "-tmin", "0", "-tmax", "100"]
        """
        args = list(options) if options else []   # copy: never mutate caller's list
        args.append(str(shy_file))
        return await self.run_command(
            "shyelab", args, working_dir, progress_callback, output_callback
        )
