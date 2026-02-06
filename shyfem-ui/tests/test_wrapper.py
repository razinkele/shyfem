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
