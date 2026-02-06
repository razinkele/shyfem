"""Parser for SHYFEM .str (parameter) files.

.str file format:
- Sections delimited by $section_name and $end
- Parameters can be: key = value, key = 'string', or just standalone values
- Comments start with # or !
- Multiple parameters per line allowed
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class StrSection:
    """A section in a .str file."""

    name: str
    parameters: dict[str, Any] = field(default_factory=dict)
    raw_lines: list[str] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)


@dataclass
class StrFile:
    """Parsed representation of a .str file."""

    sections: dict[str, StrSection] = field(default_factory=dict)
    header_comments: list[str] = field(default_factory=list)
    file_path: Optional[Path] = None

    def get_param(self, section: str, key: str, default: Any = None) -> Any:
        """Get a parameter value from a section."""
        if section in self.sections:
            return self.sections[section].parameters.get(key, default)
        return default

    def set_param(self, section: str, key: str, value: Any) -> None:
        """Set a parameter value in a section."""
        if section not in self.sections:
            self.sections[section] = StrSection(name=section)
        self.sections[section].parameters[key] = value

    def get_section_names(self) -> list[str]:
        """Get all section names."""
        return list(self.sections.keys())


class StrParser:
    """Parser for SHYFEM .str parameter files."""

    # Regex patterns
    SECTION_START = re.compile(r"^\s*\$(\w+)\s*$", re.IGNORECASE)
    SECTION_END = re.compile(r"^\s*\$end\s*$", re.IGNORECASE)
    COMMENT = re.compile(r"^\s*[#!]")
    # Parameter patterns: key = value or key = 'string'
    PARAM_PATTERN = re.compile(
        r"(\w+)\s*=\s*(?:'([^']*)'|\"([^\"]*)\"|(\S+))"
    )
    # Standalone value (like in $extra section): number 'description'
    STANDALONE_PATTERN = re.compile(r"^\s*(\d+)\s+'([^']+)'")

    @classmethod
    def parse(cls, content: str) -> StrFile:
        """Parse .str file content into structured data."""
        result = StrFile()
        current_section: Optional[StrSection] = None
        in_header = True

        for line in content.splitlines():
            stripped = line.strip()

            # Check for section start
            section_match = cls.SECTION_START.match(stripped)
            if section_match:
                in_header = False
                section_name = section_match.group(1).lower()
                current_section = StrSection(name=section_name)
                result.sections[section_name] = current_section
                continue

            # Check for section end
            if cls.SECTION_END.match(stripped):
                current_section = None
                continue

            # Handle content
            if current_section is None:
                # Before any section or between sections
                if in_header and (cls.COMMENT.match(stripped) or not stripped):
                    result.header_comments.append(line)
                continue

            # Store raw line
            current_section.raw_lines.append(line)

            # Skip empty lines and comments
            if not stripped or cls.COMMENT.match(stripped):
                if cls.COMMENT.match(stripped):
                    current_section.comments.append(stripped)
                continue

            # Try to parse parameters
            # Handle standalone values (like in $extra section)
            standalone_match = cls.STANDALONE_PATTERN.match(stripped)
            if standalone_match:
                node_id = int(standalone_match.group(1))
                description = standalone_match.group(2)
                if "_standalone" not in current_section.parameters:
                    current_section.parameters["_standalone"] = []
                current_section.parameters["_standalone"].append(
                    {"id": node_id, "description": description}
                )
                continue

            # Parse key=value parameters
            for match in cls.PARAM_PATTERN.finditer(stripped):
                key = match.group(1).lower()
                # Value is in group 2 (single quoted), 3 (double quoted), or 4 (unquoted)
                value = match.group(2) or match.group(3) or match.group(4)
                # Try to convert to appropriate type
                value = cls._convert_value(value)
                current_section.parameters[key] = value

        return result

    @classmethod
    def parse_file(cls, file_path: Path | str) -> StrFile:
        """Parse a .str file from disk."""
        file_path = Path(file_path)
        content = file_path.read_text(encoding="utf-8", errors="replace")
        result = cls.parse(content)
        result.file_path = file_path
        return result

    @staticmethod
    def _convert_value(value: str) -> Any:
        """Convert string value to appropriate Python type."""
        if value is None:
            return None

        # Check for boolean
        if value.lower() in ("true", ".true."):
            return True
        if value.lower() in ("false", ".false."):
            return False

        # Check for integer
        try:
            return int(value)
        except ValueError:
            pass

        # Check for float (including scientific notation)
        try:
            return float(value)
        except ValueError:
            pass

        # Return as string
        return value

    @classmethod
    def generate(cls, str_file: StrFile) -> str:
        """Generate .str file content from structured data."""
        lines = []

        # Header comments
        for comment in str_file.header_comments:
            lines.append(comment)

        if str_file.header_comments:
            lines.append("")

        # Sections
        for section_name, section in str_file.sections.items():
            lines.append(f"${section_name}")

            # If we have raw lines, use them (preserves formatting)
            if section.raw_lines:
                for raw_line in section.raw_lines:
                    lines.append(raw_line)
            else:
                # Generate from parameters
                for key, value in section.parameters.items():
                    if key == "_standalone":
                        for item in value:
                            lines.append(f"        {item['id']}     '{item['description']}'")
                    else:
                        formatted_value = cls._format_value(value)
                        lines.append(f"        {key} = {formatted_value}")

            lines.append("$end")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _format_value(value: Any) -> str:
        """Format a Python value for .str file."""
        if isinstance(value, bool):
            return ".true." if value else ".false."
        if isinstance(value, str):
            # Quote strings that contain spaces or are date-like
            if " " in value or value.startswith("'") or "-" in value:
                return f"'{value}'"
            return value
        if isinstance(value, float):
            # Use scientific notation for very small/large values
            if abs(value) < 1e-3 or abs(value) > 1e6:
                return f"{value:.2e}"
            return str(value)
        return str(value)

    @classmethod
    def save(cls, str_file: StrFile, file_path: Path | str) -> None:
        """Save .str file to disk."""
        file_path = Path(file_path)
        content = cls.generate(str_file)
        file_path.write_text(content, encoding="utf-8")


# Commonly used section and parameter names for UI hints
COMMON_SECTIONS = {
    "title": "Simulation title and grid reference",
    "para": "Main simulation parameters (time, physics)",
    "extra": "Extra output nodes",
    "name": "Input file paths",
    "bound": "Boundary conditions",
    "flux": "Flux boundaries",
    "waves": "Wave parameters",
    "sedtr": "Sediment transport",
    "wrt": "Custom write sections",
}

COMMON_PARAMS = {
    "para": {
        "itanf": ("Start time", "date/time string"),
        "itend": ("End time", "date/time string"),
        "idt": ("Time step", "seconds or string like '300s'"),
        "idtout": ("Output interval", "seconds or string like '3h'"),
        "idtext": ("External output interval", "seconds"),
        "date": ("Reference date", "YYYYMMDD"),
        "ilin": ("Linear interpolation", "0=no, 1=yes"),
        "iwtype": ("Wind stress type", "1-5"),
        "dragco": ("Drag coefficient", "float"),
        "ireib": ("Bottom friction type", "0-7"),
        "czdef": ("Default Chezy coefficient", "float"),
        "icoriol": ("Coriolis", "0=no, 1=yes"),
        "dlat": ("Latitude for Coriolis", "degrees"),
    },
}
