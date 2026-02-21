"""Tests for SHYFEM tool wrappers."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from shyfem_ui.services.shyfem_wrapper import CommandResult, ShyfemWrapper


class TestShyfemWrapper:
    """Tests for ShyfemWrapper class."""

    @pytest.fixture
    def wrapper(self, tmp_path):
        """Create a wrapper with temporary SHYFEM directory."""
        shyfem_dir = tmp_path / "shyfem"
        shyfem_dir.mkdir()
        (shyfem_dir / "bin").mkdir()
        return ShyfemWrapper(shyfem_dir)

    def test_init(self, wrapper, tmp_path):
        """Test wrapper initialization."""
        assert wrapper.shyfem_dir == tmp_path / "shyfem"
        assert wrapper.bin_dir == tmp_path / "shyfem" / "bin"

    def test_get_executable_exists(self, wrapper):
        """Test getting executable that exists."""
        # Create a fake executable
        exe = wrapper.bin_dir / "shypre"
        exe.touch()

        result = wrapper.get_executable("shypre")
        assert result == exe

    def test_get_executable_not_found(self, wrapper):
        """Test getting executable that doesn't exist."""
        with pytest.raises(FileNotFoundError):
            wrapper.get_executable("nonexistent")

    def test_check_available_true(self, wrapper):
        """Test checking tool availability when available."""
        exe = wrapper.bin_dir / "shypre"
        exe.touch()

        assert wrapper.check_available("shypre") is True

    def test_check_available_false(self, wrapper):
        """Test checking tool availability when not available."""
        assert wrapper.check_available("nonexistent") is False

    @pytest.mark.asyncio
    async def test_run_command_success(self, wrapper, tmp_path):
        """Test running a command successfully."""
        # Create a fake executable (shell script)
        exe = wrapper.bin_dir / "test_tool"
        exe.write_text("#!/bin/bash\necho 'Hello World'")
        exe.chmod(0o755)

        result = await wrapper.run_command(
            "test_tool",
            [],
            tmp_path,
        )

        assert result.success is True
        assert result.return_code == 0
        assert "Hello World" in result.stdout

    @pytest.mark.asyncio
    async def test_run_command_failure(self, wrapper, tmp_path):
        """Test running a command that fails."""
        # Create a fake executable that fails
        exe = wrapper.bin_dir / "fail_tool"
        exe.write_text("#!/bin/bash\nexit 1")
        exe.chmod(0o755)

        result = await wrapper.run_command(
            "fail_tool",
            [],
            tmp_path,
        )

        assert result.success is False
        assert result.return_code == 1

    @pytest.mark.asyncio
    async def test_run_command_with_callback(self, wrapper, tmp_path):
        """Test running a command with output callback."""
        exe = wrapper.bin_dir / "test_tool"
        exe.write_text("#!/bin/bash\necho 'line1'\necho 'line2'")
        exe.chmod(0o755)

        output_lines = []

        def callback(line):
            output_lines.append(line)

        await wrapper.run_command(
            "test_tool",
            [],
            tmp_path,
            output_callback=callback,
        )

        assert len(output_lines) >= 2
        assert "line1" in output_lines
        assert "line2" in output_lines

    @pytest.mark.asyncio
    async def test_run_command_with_args(self, wrapper, tmp_path):
        """Test running a command with arguments."""
        exe = wrapper.bin_dir / "echo_tool"
        exe.write_text('#!/bin/bash\necho "$@"')
        exe.chmod(0o755)

        result = await wrapper.run_command(
            "echo_tool",
            ["arg1", "arg2"],
            tmp_path,
        )

        assert "arg1" in result.stdout
        assert "arg2" in result.stdout

    def test_parse_progress_shyfem(self, wrapper):
        """Test parsing progress from shyfem output."""
        line = "time = 1000.0 of 10000.0"
        progress = wrapper._parse_progress("shyfem", line)

        assert progress == pytest.approx(0.1)

    def test_parse_progress_shyelab(self, wrapper):
        """Test parsing progress from shyelab output."""
        line = "processing record 50 of 100"
        progress = wrapper._parse_progress("shyelab", line)

        assert progress == pytest.approx(0.5)

    def test_parse_progress_no_match(self, wrapper):
        """Test parsing progress with no match."""
        line = "some other output"
        progress = wrapper._parse_progress("shyfem", line)

        assert progress is None

    def test_check_solver_available_sparskit(self, wrapper):
        """SPARSKIT available when bin/shyfem exists."""
        (wrapper.bin_dir / "shyfem").touch()
        assert wrapper.check_solver_available("sparskit") is True

    def test_check_solver_available_petsc_missing(self, wrapper):
        """PETSc unavailable when bin/shyfem-petsc doesn't exist."""
        assert wrapper.check_solver_available("petsc") is False

    def test_check_solver_available_petsc_present(self, wrapper):
        """PETSc available when bin/shyfem-petsc exists."""
        (wrapper.bin_dir / "shyfem-petsc").touch()
        assert wrapper.check_solver_available("petsc") is True

    def test_check_solver_available_unknown(self, wrapper):
        """Unknown solver returns False."""
        assert wrapper.check_solver_available("unknown") is False

    def test_find_output_files(self, wrapper, tmp_path):
        """Test finding output files."""
        # Create some output files
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        (work_dir / "test.bas").touch()
        (work_dir / "other.txt").touch()

        files = wrapper._find_output_files("shypre", work_dir)

        assert len(files) == 1
        assert any("test.bas" in f for f in files)


class TestCommandResult:
    """Tests for CommandResult dataclass."""

    def test_create_result(self):
        """Test creating a command result."""
        result = CommandResult(
            success=True,
            return_code=0,
            stdout="output",
            stderr="",
            command="test cmd",
            working_dir="/tmp",
            duration=1.5,
            output_files=["/tmp/out.bas"],
        )

        assert result.success is True
        assert result.return_code == 0
        assert result.stdout == "output"
        assert result.duration == pytest.approx(1.5)
        assert len(result.output_files) == 1

    def test_create_failed_result(self):
        """Test creating a failed command result."""
        result = CommandResult(
            success=False,
            return_code=1,
            stdout="",
            stderr="error message",
            command="test cmd",
            working_dir="/tmp",
        )

        assert result.success is False
        assert result.return_code == 1
        assert result.stderr == "error message"

    def test_result_default_fields(self):
        """Test CommandResult default field values."""
        result = CommandResult(
            success=True,
            return_code=0,
            stdout="",
            stderr="",
            command="test",
            working_dir="/tmp",
        )
        assert result.duration == 0.0
        assert result.output_files == []


class TestShyfemWrapperExtended:
    """Extended tests for MPI, timeout, and error cases."""

    @pytest.fixture
    def wrapper(self, tmp_path):
        """Create a wrapper with temporary SHYFEM directory."""
        shyfem_dir = tmp_path / "shyfem"
        shyfem_dir.mkdir()
        (shyfem_dir / "bin").mkdir()
        return ShyfemWrapper(shyfem_dir)

    def test_find_output_files_multiple_extensions(self, wrapper, tmp_path):
        """Test finding output files for shyfem (multiple extension types)."""
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        (work_dir / "out.shy").touch()
        (work_dir / "out.ext").touch()
        (work_dir / "out.flx").touch()
        (work_dir / "unrelated.txt").touch()

        files = wrapper._find_output_files("shyfem", work_dir)
        found_names = [Path(f).name for f in files]

        assert "out.shy" in found_names
        assert "out.ext" in found_names
        assert "out.flx" in found_names
        assert "unrelated.txt" not in found_names

    def test_find_output_files_shyelab(self, wrapper, tmp_path):
        """Test finding output files for shyelab."""
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        (work_dir / "out.nc").touch()
        (work_dir / "out.txt").touch()

        files = wrapper._find_output_files("shyelab", work_dir)
        found_names = [Path(f).name for f in files]
        assert "out.nc" in found_names
        assert "out.txt" in found_names

    def test_find_output_files_empty_dir(self, wrapper, tmp_path):
        """Test finding output files in empty directory."""
        work_dir = tmp_path / "empty"
        work_dir.mkdir()

        files = wrapper._find_output_files("shypre", work_dir)
        assert files == []

    def test_find_output_files_unknown_tool(self, wrapper, tmp_path):
        """Test finding output files for unknown tool returns empty."""
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        (work_dir / "file.xyz").touch()

        files = wrapper._find_output_files("unknown_tool", work_dir)
        assert files == []

    def test_parse_progress_shyfem_various_formats(self, wrapper):
        """Test shyfem progress parsing with different output formats."""
        # Standard format
        assert wrapper._parse_progress("shyfem", "time = 5000.0 of 10000.0") == pytest.approx(0.5)
        # Full progress
        assert wrapper._parse_progress("shyfem", "time = 10000.0 of 10000.0") == pytest.approx(1.0)
        # Start
        assert wrapper._parse_progress("shyfem", "time = 0.0 of 10000.0") == pytest.approx(0.0)

    def test_parse_progress_shyelab_various(self, wrapper):
        """Test shyelab progress with various record counts."""
        assert wrapper._parse_progress("shyelab", "processing record 1 of 100") == pytest.approx(0.01)
        assert wrapper._parse_progress("shyelab", "processing record 100 of 100") == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_run_command_with_stderr(self, wrapper, tmp_path):
        """Test running a command that produces stderr."""
        exe = wrapper.bin_dir / "stderr_tool"
        exe.write_text("#!/bin/bash\necho 'error output' >&2\nexit 0")
        exe.chmod(0o755)

        result = await wrapper.run_command("stderr_tool", [], tmp_path)
        assert result.success is True
        assert "error output" in result.stderr

    @pytest.mark.asyncio
    async def test_run_command_nonexistent_tool(self, wrapper, tmp_path):
        """Test running a tool that doesn't exist raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            await wrapper.run_command("nonexistent_tool", [], tmp_path)

    @pytest.mark.asyncio
    async def test_run_command_measures_duration(self, wrapper, tmp_path):
        """Test that command duration is measured."""
        exe = wrapper.bin_dir / "slow_tool"
        exe.write_text("#!/bin/bash\nsleep 0.1\necho done")
        exe.chmod(0o755)

        result = await wrapper.run_command("slow_tool", [], tmp_path)
        assert result.duration >= 0.05

    def test_output_extensions_mapping(self, wrapper):
        """Test that OUTPUT_EXTENSIONS covers expected tools."""
        assert "shypre" in ShyfemWrapper.OUTPUT_EXTENSIONS
        assert "shyfem" in ShyfemWrapper.OUTPUT_EXTENSIONS
        assert "shyelab" in ShyfemWrapper.OUTPUT_EXTENSIONS
        assert ".bas" in ShyfemWrapper.OUTPUT_EXTENSIONS["shypre"]

    def test_check_available_multiple_tools(self, wrapper):
        """Test checking availability for multiple tools."""
        (wrapper.bin_dir / "shypre").touch()
        (wrapper.bin_dir / "shyfem").touch()

        assert wrapper.check_available("shypre") is True
        assert wrapper.check_available("shyfem") is True
        assert wrapper.check_available("shyplot") is False


class TestRunShyfemSolver:
    """Tests for solver selection in run_shyfem."""

    @pytest.fixture
    def wrapper(self, tmp_path):
        shyfem_dir = tmp_path / "shyfem"
        shyfem_dir.mkdir()
        (shyfem_dir / "bin").mkdir()
        # Create both solver binaries as shell scripts
        for name in ("shyfem", "shyfem-petsc"):
            exe = shyfem_dir / "bin" / name
            exe.write_text("#!/bin/bash\necho 'solver=$0'")
            exe.chmod(0o755)
        return ShyfemWrapper(shyfem_dir)

    @pytest.mark.asyncio
    async def test_default_solver_uses_shyfem(self, wrapper, tmp_path):
        """No solver arg uses bin/shyfem."""
        result = await wrapper.run_shyfem("test.str", tmp_path)
        assert "shyfem" in result.command
        assert "shyfem-petsc" not in result.command

    @pytest.mark.asyncio
    async def test_petsc_solver_uses_shyfem_petsc(self, wrapper, tmp_path):
        """solver='petsc' uses bin/shyfem-petsc."""
        result = await wrapper.run_shyfem("test.str", tmp_path, solver="petsc")
        assert "shyfem-petsc" in result.command

    @pytest.mark.asyncio
    async def test_sparskit_solver_uses_shyfem(self, wrapper, tmp_path):
        """solver='sparskit' uses bin/shyfem."""
        result = await wrapper.run_shyfem("test.str", tmp_path, solver="sparskit")
        assert "shyfem" in result.command
        assert "shyfem-petsc" not in result.command

    @pytest.mark.asyncio
    async def test_petsc_solver_not_found_raises(self, wrapper, tmp_path):
        """solver='petsc' raises FileNotFoundError if binary missing."""
        # Remove petsc binary
        (wrapper.bin_dir / "shyfem-petsc").unlink()
        with pytest.raises(FileNotFoundError):
            await wrapper.run_shyfem("test.str", tmp_path, solver="petsc")
