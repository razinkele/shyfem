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
from typing import Any


@dataclass
class StrSection:
    """A section in a .str file."""

    name: str
    parameters: dict[str, Any] = field(default_factory=dict)
    raw_lines: list[str] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)
    # Track which parameters were modified after parsing (for smart regeneration)
    _modified_params: set = field(default_factory=set)
    # The opening and closing lines exactly as they were read, so a parsed
    # section round-trips byte-exact. SHYFEM's reader takes '&' or '$' for
    # both (nls.f90::nls_is_section) and reads any text after the name as a
    # documented "extra information" field, so "$bound1   ---- Baltic ----"
    # and "&para" are ordinary headers -- but neither survives being
    # regenerated from the name alone. None for a section built in memory,
    # which is emitted as "$name" / "$end" as before.
    header_line: str | None = None
    end_line: str | None = None
    #: The text after the section name on the header line ("---- Baltic ----").
    header_extra: str = ""
    # raw_lines index -> the parameter key a numeric continuation line belongs
    # to, so an edit to a multi-line list can drop its continuations.
    _continuation_owner: dict[int, str] = field(default_factory=dict)


@dataclass
class StrFile:
    """Parsed representation of a .str file."""

    # One entry per section NAME, holding the first occurrence. A file may
    # legitimately repeat a section — the core reads them in a dispatch
    # loop (shyplot/subnsa.f90 nrdsec) — and every later block is held by
    # _structure, which is what generate() walks. Keeping repeats out of
    # this dict deliberately: its keys are treated as real section names
    # all over the app (input ids, COMMON_PARAMS lookups, emitted headers),
    # so a synthetic key for a repeat would leak into all of them.
    sections: dict[str, StrSection] = field(default_factory=dict)
    header_comments: list[str] = field(default_factory=list)
    # Preserves the order of top-level elements for round-trip fidelity:
    # each entry is ("section", StrSection) or ("inter", [lines]). Holding
    # the section itself rather than its name is what lets a repeated
    # section survive: by name, every occurrence resolved to the same
    # entry and generate() emitted it once per occurrence, overwriting the
    # earlier blocks' content.
    _structure: list[tuple[str, Any]] = field(default_factory=list)
    file_path: Path | None = None

    def get_param(self, section: str, key: str, default: Any = None) -> Any:
        """Get a parameter value from a section.

        A repeated section resolves to its first occurrence.
        """
        if section in self.sections:
            return self.sections[section].parameters.get(key, default)
        return default

    def set_param(self, section: str, key: str, value: Any) -> None:
        """Set a parameter value in a section.

        A repeated section resolves to its first occurrence; later blocks
        keep their own values and round-trip untouched.
        """
        if section not in self.sections:
            self.sections[section] = StrSection(name=section)
        self.sections[section].parameters[key] = value
        self.sections[section]._modified_params.add(key)

    def get_section_names(self) -> list[str]:
        """Get all section names."""
        return list(self.sections.keys())

    def remove_sections(self, name: str) -> bool:
        """Drop every section called *name*; True if any was removed.

        Deletion is the one operation that cannot settle for the first
        occurrence: a surviving later block is still read by the core.
        """
        found = self.sections.pop(name, None) is not None
        kept = [
            entry
            for entry in self._structure
            if not (entry[0] == "section" and entry[1].name == name)
        ]
        if len(kept) != len(self._structure):
            found = True
            self._structure[:] = kept
        return found


# Values that are not character data to the Fortran reader and must stay
# unquoted: numbers (incl. d-exponent forms) and logicals.
_BARE_STR_VALUE = re.compile(
    r"[+-]?(\d+\.?\d*|\.\d+)([ed][+-]?\d+)?|\.(true|false)\.", re.IGNORECASE
)


def _is_numeric(value: Any) -> bool:
    """A number, or a non-empty list of numbers (never a bool)."""
    items = value if isinstance(value, list) else [value]
    return bool(items) and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in items
    )


class StrParser:
    """Parser for SHYFEM .str parameter files."""

    # Regex patterns
    # '&' as well as '$' (nls.f90:543 takes either), and any text after the
    # section name -- the Fortran reader returns it as `extra`. Group 2 is
    # that text. SECTION_END is matched first (see parse()), so the "end"
    # that \w+ would also accept here never reaches this pattern.
    SECTION_START = re.compile(r"^\s*[$&](\w+)(?:\s+(\S.*?))?\s*$", re.IGNORECASE)
    # A closing marker may carry a trailing comment ("$end  ! done"). \b keeps
    # a section legitimately named "endX" from matching.
    SECTION_END = re.compile(r"^\s*[$&]end\b.*$", re.IGNORECASE)
    COMMENT = re.compile(r"^\s*[#!]")
    # Parameter patterns: key = value or key = 'string'
    # The bare branch consumes a RUN of tokens ("kbound = 1855 1856 1882 1883"
    # is one four-element value, not 1855 with three ignored tokens), stopping
    # before a token that opens the next pair ("czdef =") thanks to the
    # negative lookahead. Quoted branches are unaffected, so a quoted value
    # containing spaces stays one string.
    PARAM_PATTERN = re.compile(
        r"(\w+)\s*=\s*(?:'([^']*)'|\"([^\"]*)\"|(\S+(?:\s+(?!\S+\s*=)\S+)*))"
    )
    # Standalone value (like in $extra section): number 'description'
    STANDALONE_PATTERN = re.compile(r"^\s*(\d+)\s+'([^']+)'")

    @classmethod
    def parse(cls, content: str) -> StrFile:
        """Parse .str file content into structured data."""
        result = StrFile()
        current_section: StrSection | None = None
        # The key of the most recent parameter whose bare value is numeric; a
        # following numbers-only line continues it ("kbound = 1547 1548" or
        # "kbound = 1547", then "        1554 1555"). Reset at every section boundary so a
        # continuation can never attach across one.
        last_list_key: str | None = None
        in_header = True
        inter_section_lines: list[str] = []

        for line in content.splitlines():
            stripped = line.strip()

            # Check for section end BEFORE section start: SECTION_START's
            # \$(\w+) also matches a bare "$end" line ("end" is a valid
            # \w+ word), so checking it first mis-parses every legitimate
            # closing marker as a new section literally named "end". That
            # phantom section then round-trips through generate() as an
            # extra, ownerless "$end" pair sitting between real sections --
            # which SHYFEM's own Fortran STR reader (iostr.f90 nlsh2d) is
            # NOT tolerant of: encountering "$end" where it expects a new
            # section header is a hard `stop 'error stop : nlsh2d'`. Since
            # SECTION_END only ever matches the literal word "end", checking
            # it first is strictly more specific and cannot shadow any real
            # section name (title, para, name, bound1, ...).
            if cls.SECTION_END.match(stripped):
                last_list_key = None
                if current_section is None:
                    # Ownerless: the opening header was decorated
                    # ("$nduge  ! legacy"), which SECTION_START does not
                    # match, so the whole block is inter-section text.
                    # Dropping this line would emit an unterminated block.
                    inter_section_lines.append(line)
                else:
                    current_section.end_line = line
                    current_section = None
                continue

            # Check for section start
            section_match = cls.SECTION_START.match(stripped)
            if section_match:
                # Save any accumulated inter-section content
                if inter_section_lines:
                    if in_header:
                        result.header_comments = inter_section_lines[:]
                    else:
                        result._structure.append(("inter", inter_section_lines[:]))
                    inter_section_lines = []

                in_header = False
                section_name = section_match.group(1).lower()
                last_list_key = None
                current_section = StrSection(
                    name=section_name,
                    header_line=line,
                    header_extra=(section_match.group(2) or "").strip(),
                )
                # First occurrence is the one addressable by name; every
                # occurrence is recorded in _structure so none is lost.
                result.sections.setdefault(section_name, current_section)
                result._structure.append(("section", current_section))
                continue

            # Handle content outside sections
            if current_section is None:
                inter_section_lines.append(line)
                continue

            # Store raw line
            current_section.raw_lines.append(line)

            # Skip empty lines and comments
            if not stripped or cls.COMMENT.match(stripped):
                if cls.COMMENT.match(stripped):
                    current_section.comments.append(stripped)
                continue

            # $title is three lines of text (title, run name, basin; the core
            # reads them as text), so "restart (nkn=6 > nel=4)" is not two
            # parameters. Its lines stay raw and round-trip untouched.
            if current_section.name == "title":
                continue

            # Try to parse parameters
            code = cls._split_comment(stripped)[0]

            # Handle standalone values (like in $extra section)
            standalone_match = cls.STANDALONE_PATTERN.match(code)
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
            matched_any = False
            for match in cls.PARAM_PATTERN.finditer(code):
                matched_any = True
                key = match.group(1).lower()
                # Value is in group 2 (single quoted), 3 (double quoted), or 4 (unquoted)
                if match.group(4) is not None:
                    # Bare: possibly a run of tokens forming one list value.
                    value = cls._convert_bare_value(match.group(4))
                else:
                    # "is not None", not "or": an empty quoted value
                    # ("wind = ''") is group 2 == "", and "or" fell through
                    # to group 3 (None). The form then showed "None" and an
                    # Apply with no edit wrote wind = 'None'.
                    quoted = match.group(2) if match.group(2) is not None else match.group(3)
                    value = cls._convert_value(quoted)
                current_section.parameters[key] = value
                # A bare number or run of numbers can go on over the next
                # lines, a one-token "kbound = 1547" too (S-11); a quoted
                # value cannot.
                last_list_key = key if match.group(4) is not None and _is_numeric(value) else None

            if not matched_any and last_list_key is not None:
                # A numbers-only line continues the list above it. SHYFEM reads
                # a section's values as one stream, so "kbound = 1547 1548" over
                # several lines is one list; parsing only the first line left
                # boundaries short of most of their nodes.
                extra = cls._numeric_tokens(code)
                if extra is not None:
                    head = current_section.parameters[last_list_key]
                    head = list(head) if isinstance(head, list) else [head]
                    current_section.parameters[last_list_key] = head + extra
                    current_section._continuation_owner[len(current_section.raw_lines) - 1] = (
                        last_list_key
                    )

        # Save trailing inter-section content
        if inter_section_lines:
            if in_header:
                result.header_comments = inter_section_lines[:]
            else:
                result._structure.append(("inter", inter_section_lines[:]))

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
    def _split_comment(line: str) -> tuple[str, str]:
        """Split a line into its code part and its trailing comment.

        The core stops reading at the first ``!``/``#`` that is not inside
        a quoted value (nls.f90 nls_skip_whitespace_on_line), so anything
        past it is text, not parameters.

        An unterminated quote leaves the scan with no comment boundary, so
        the whole line reads as code. That only arises for input the core
        rejects outright — nls_read_text stops the run when istos finds no
        closing delimiter — so it is not a case to preserve, just one that
        must not corrupt anything on the way to that error.
        """
        quote = ""
        for i, char in enumerate(line):
            if quote:
                if char == quote:
                    quote = ""
            elif char in "'\"":
                quote = char
            elif char in "!#":
                return line[:i], line[i:]
        return line, ""

    @classmethod
    def _numeric_tokens(cls, text: str) -> list[Any] | None:
        """Every token of ``text`` converted, or None if any is not a number.

        Used for continuation lines, where even a single token extends the list
        above ("kbound = 1547 1548" then a line holding just "1554"); that
        differs from a value, where one token is a scalar.
        """
        tokens = text.split()
        if not tokens:
            return None
        converted = [cls._convert_value(t) for t in tokens]
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in converted):
            return converted
        return None

    @classmethod
    def _convert_bare_value(cls, value: str) -> Any:
        """Convert an unquoted value, which may be a whitespace-separated run.

        Returns ``list[int]``/``list[float]`` when every token converts and
        there is more than one, else the scalar conversion of the whole text.
        A mixed or non-numeric run (which SHYFEM would not read as a list
        either) stays a single string.
        """
        tokens = value.split()
        if len(tokens) > 1:
            converted = [cls._convert_value(t) for t in tokens]
            if all(isinstance(v, int) and not isinstance(v, bool) for v in converted):
                return converted
            if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in converted):
                return [float(v) for v in converted]
            return value
        return cls._convert_value(value)

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
        """Generate .str file content from structured data.

        Preserves original formatting via raw_lines where possible, overlaying
        any parameter modifications. Inter-section comments and blank lines
        are preserved using the recorded _structure order.
        """
        lines = []

        # Header comments
        for comment in str_file.header_comments:
            lines.append(comment)

        # No separator is added here: the blank line before the first section is
        # itself one of the header lines, so appending another inserted one on
        # every save.

        # Use recorded structure if available, otherwise fall back to section dict order
        if str_file._structure:
            for entry_type, entry_value in str_file._structure:
                if entry_type == "inter":
                    lines.extend(entry_value)
                elif entry_type == "section":
                    cls._generate_section(lines, entry_value)

            # Emit any new sections not in the original structure. Compared
            # by identity, not name: a repeated section contributes several
            # structure entries that share one name.
            structured = [v for t, v in str_file._structure if t == "section"]
            for section in str_file.sections.values():
                if not any(section is known for known in structured):
                    cls._generate_section(lines, section)
        else:
            for section in str_file.sections.values():
                cls._generate_section(lines, section)

        # ``splitlines`` dropped the newline that ended each line, so joining
        # puts one back between lines and this adds the one that ended the last
        # line. That makes the transform the exact inverse of the split for any
        # file ending in a newline (a file not ending in one gains it, which is
        # what the previous implementation did too).
        return "\n".join(lines) + "\n" if lines else ""

    @classmethod
    def _generate_section(cls, lines: list[str], section: StrSection) -> None:
        """Generate a single section, overlaying modifications on raw_lines."""
        # The header exactly as it was read, so "&para" and
        # "$bound1   ---- Baltic ----" survive; f"${name}" only for a section
        # built in memory.
        lines.append(section.header_line if section.header_line is not None else f"${section.name}")

        if section.raw_lines and section._modified_params:
            # Overlay modified params onto raw lines
            emitted_modified = set()
            for index, raw_line in enumerate(section.raw_lines):
                owner = section._continuation_owner.get(index)
                if owner is not None and owner in section._modified_params:
                    # A continuation of a list that has been edited. The
                    # overlay rewrites a parameter within one line, so the new
                    # value is emitted whole on the line that opened it and the
                    # continuations go; the result is valid, not byte-identical.
                    continue
                stripped = raw_line.strip()
                # Skip comments and blanks — emit as-is
                if stripped and not cls.COMMENT.match(stripped):
                    # Rebuild the line by match span rather than substring
                    # replace: a substring replace can land inside the wrong
                    # param when an earlier key+value on the same
                    # multi-assign line textually contains a later param's
                    # "key = value" (e.g. "vcorlength = 2000.  corlength =
                    # 2000." — modifying corlength must not clobber
                    # vcorlength). PARAM_PATTERN has no anchors, so matching
                    # the unstripped code part keeps spans aligned with it.
                    # The trailing comment is excluded and re-attached
                    # verbatim: a "key = value" inside it is text to the
                    # core, so rewriting it there would both corrupt the
                    # comment and mark the param emitted, dropping the
                    # user's real edit.
                    code, comment = cls._split_comment(raw_line)
                    parts = []
                    pos = 0
                    for match in cls.PARAM_PATTERN.finditer(code):
                        key = match.group(1).lower()
                        parts.append(code[pos : match.start()])
                        if key in section._modified_params:
                            new_val = cls._format_value(section.parameters[key])
                            parts.append(f"{key} = {new_val}")
                            emitted_modified.add(key)
                        else:
                            parts.append(match.group(0))
                        pos = match.end()
                    parts.append(code[pos:])
                    parts.append(comment)
                    new_line = "".join(parts)
                else:
                    new_line = raw_line
                lines.append(new_line)
            # Append any new params not found in raw_lines
            for key in section._modified_params - emitted_modified:
                if key != "_standalone":
                    formatted_value = cls._format_value(section.parameters[key])
                    lines.append(f"        {key} = {formatted_value}")
        elif section.raw_lines:
            # No modifications — emit raw lines as-is (perfect round-trip)
            for raw_line in section.raw_lines:
                lines.append(raw_line)
        else:
            # No raw lines — generate from parameters
            for key, value in section.parameters.items():
                if key == "_standalone":
                    for item in value:
                        lines.append(f"        {item['id']}     '{item['description']}'")
                elif key.startswith("_"):
                    continue
                else:
                    formatted_value = cls._format_value(value)
                    lines.append(f"        {key} = {formatted_value}")

        lines.append(section.end_line if section.end_line is not None else "$end")
        # A parsed file already carries whatever separated its sections (as an
        # inter-section entry), so adding one here inserted a blank line into
        # the user's file on every save. Only a section built in memory needs
        # the separator.
        if section.header_line is None:
            lines.append("")

    @staticmethod
    def _format_value(value: Any) -> str:
        """Format a Python value for .str file."""
        if isinstance(value, bool):
            return ".true." if value else ".false."
        if isinstance(value, (list, tuple)):
            # A list is a run of values in the STR ("kbound = 1855 1856"). The
            # core's reader hard-stops on "[1855, 1856]" ('no value found'),
            # so this branch is the difference between a valid file and a
            # fatal one.
            return " ".join(StrParser._format_value(v) for v in value)
        if isinstance(value, str):
            # Already quoted (e.g. from apply_quick_settings) — emit as-is
            # so we never double-wrap into ''value''.
            if len(value) >= 2 and value[0] in "'\"" and value[-1] == value[0]:
                return value
            # Fortran logicals and numeric-looking strings (incl. d-exponents)
            # are not character values — leave bare.
            if _BARE_STR_VALUE.fullmatch(value):
                return value
            # Everything else is a character value: the core's reader
            # hard-stops on an unquoted one (nls.f90: 'no value found'),
            # so `wind = INPUT/wind.txt` would make the STR fatal.
            # nls.f90's reader is delimiter-matched with no escape
            # mechanism, so a value holding BOTH quote characters has no
            # valid emission — either wrapper closes early and ships a
            # fatal STR line.
            if "'" in value and '"' in value:
                raise ValueError(
                    f"value cannot be written to a .str file: {value!r} contains both "
                    "a single and a double quote, and the SHYFEM reader has no escape "
                    "mechanism for either delimiter"
                )
            # nls.f90 accepts '..' and ".." — switch delimiter when the
            # value itself contains an apostrophe.
            if "'" in value:
                return f'"{value}"'
            return f"'{value}'"
        if isinstance(value, float):
            # repr() is the shortest form float() reads back exactly; a
            # fixed-precision one (%.2e) silently rewrote e.g.
            # tau = 1234567. as 1.23e+06.
            return repr(value)
        return str(value)

    @classmethod
    def save(cls, str_file: StrFile, file_path: Path | str) -> None:
        """Save .str file to disk."""
        file_path = Path(file_path)
        content = cls.generate(str_file)
        file_path.write_text(content, encoding="utf-8")


def format_param_display(value: Any) -> str:
    """Render a parsed parameter value the way the .str file spells it.

    The counterpart of ``StrParser._format_value`` for a UI text field: same
    spelling for a value run, but no quoting, because a field shows the value
    itself and the user edits it in place.

    ``str()`` is not a substitute. A parameter whose .str value is a run of
    numbers (``kbound = 1855 1856 1882 1883``, an ``int_list`` in
    ``COMMON_PARAMS``) parses to a list, and ``str()`` on one yields
    ``"[1855, 1856, 1882, 1883]"``. That text is not just ugly in the field:
    it is what a save reads back out of it, and ``[..]`` in an .str makes the
    core hard-stop (``nls.f90``: 'no value found').

    ``None`` -- an absent parameter -- renders empty, so the field is blank
    rather than showing the word "None".
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return ".true." if value else ".false."
    if isinstance(value, (list, tuple)):
        return " ".join(format_param_display(v) for v in value)
    return str(value)


def _display_token(text: str) -> Any:
    """One field token as int, float, or the text itself."""
    try:
        if "." in text or "e" in text.lower():
            return float(text)
        return int(text)
    except ValueError:
        return text


def parse_param_display(text: str) -> Any:
    """Convert a UI field's text back to the value to store in the STR.

    The inverse of :func:`format_param_display`, and the same rule the parser
    applies when reading a file: a whitespace-separated run of numbers is a
    value run (``kbound = 1855 1856 1882 1883``), not a string. Leaving it a
    string would make ``_format_value`` quote it -- ``kbound = '1855 1856'``,
    a character value the core hard-stops on.

    The pair must stay an inverse for every value the app can show. A form
    reads a field back on save and rewrites the parameter when the value
    differs from the parsed one, so a non-inverse silently corrupts a field
    the user never touched: that is how the STR editor's Form view turned
    ``sedgrs = 0.1 0.2 0.3`` into ``sedgrs = '[0.1, 0.2, 0.3]'``.

    A run whose tokens are not all numeric (a per-area array like
    ``0.3, 0.25, 0.1``, or a path containing a space) stays one string, which
    is what the parser does with it too.
    """
    tokens = text.split()
    if len(tokens) > 1:
        converted = [_display_token(t) for t in tokens]
        if all(isinstance(v, int) and not isinstance(v, bool) for v in converted):
            return converted
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in converted):
            return [float(v) for v in converted]
        return text
    return _display_token(text)


# Section descriptions for UI
COMMON_SECTIONS = {
    "title": "Simulation title and grid reference",
    "para": "Main simulation parameters (time, physics, output)",
    "extra": "Extra output nodes for time series (.ext files)",
    "name": "Input/output file paths",
    "bound": "Boundary conditions (water level, velocity, discharge)",
    "bound1": "Boundary condition #1",
    "bound2": "Boundary condition #2",
    "bound3": "Boundary condition #3",
    "flux": "Flux section definitions for discharge calculation",
    "volume": "Volume monitoring polylines",
    "levels": "Vertical layer depths (one value per line, meters)",
    "waves": "Wave parameters",
    "sedtr": "Sediment transport parameters",
    "lagrg": "Lagrangian particle tracking (IBM, oil spill, connectivity)",
    "connec": "Particle connectivity analysis (source-destination tracking)",
    "bfmsc": "BFM biogeochemical flux model",
    "wrt": "Custom write sections",
    "nonhyd": "Non-hydrostatic mode parameters",
}

# Parameter metadata: (description, type_str, default, units, valid_range_or_options)
# type_str: "int", "float", "string", "bool_int" (0/1)
# valid_range_or_options: None, "0-5", [0,1], ">0", etc. (for display only)
ParamInfo = tuple  # (description, type_str, default, units, options)


def _p(
    desc: str, ptype: str = "float", default: Any = None, units: str = "", options: str = ""
) -> ParamInfo:
    return (desc, ptype, default, units, options)


COMMON_PARAMS: dict[str, dict[str, ParamInfo]] = {
    "para": {
        # --- Timing (required) ---
        "itanf": _p("Start time of simulation", "string", "0", "", "date string or seconds"),
        "itend": _p("End time of simulation", "string", None, "", "date string or seconds"),
        "idt": _p("Time step of integration", "string", None, "s", ">0"),
        "date": _p("Reference date for time 0", "int", -1, "", "YYYYMMDD"),
        "time": _p("Reference time for time 0", "int", 0, "", "HHMMSS"),
        "tz": _p("Time zone", "int", 0, "", "0=GMT, 1=MET, 2=MEST"),
        # --- Output intervals ---
        "idtout": _p("Hydrodynamic output interval", "string", "0", "s", ""),
        "idtext": _p("Extra point time series interval", "string", "0", "s", ""),
        "idtrst": _p("Restart file interval", "string", "0", "s", "-1=last step only"),
        "idtres": _p("Residual data interval", "string", "0", "s", ""),
        "idtrms": _p("RMS velocity output interval", "string", "0", "s", ""),
        "idtflx": _p("Flux/discharge output interval", "string", "0", "s", ""),
        "idtcon": _p("Scalar/concentration output interval", "string", "0", "s", ""),
        "idtvol": _p("Volume monitoring interval", "string", "0", "s", ""),
        "idtmet": _p("Meteo variable output interval", "string", "0", "s", ""),
        "idtstb": _p("Stability index interval", "string", "0", "s", ""),
        "netcdf": _p("Output file format", "int", 0, "", "0=Fortran, 1=NetCDF"),
        "ishyff": _p("SHYFEM file format version", "int", 1, "", "0=old, 1=new, 2=both"),
        # --- Model physics: advection ---
        "ilin": _p("Advective (nonlinear) terms", "int", 1, "", "0=linear, 1=nonlinear"),
        "itlin": _p("Advection scheme", "int", 0, "", "0=FE, 1=semi-Lagrangian"),
        "iclin": _p("Linearize continuity equation", "int", 0, "", "0=nonlinear, 1=linear"),
        # --- Variable time stepping ---
        "itsplt": _p("Time step mode", "int", 0, "", "0=constant, 1-2=splitting, 3=fractional"),
        "coumax": _p("Maximum Courant number", "float", 1.0, "", ">0"),
        "idtsyn": _p("Synchronization interval for itsplt=2", "int", 0, "s", ">=0"),
        # --- Semi-implicit weighting ---
        "azpar": _p("Transport term weighting", "float", 0.5, "", "[0,1]"),
        "ampar": _p("Pressure term weighting", "float", 0.5, "", "[0,1]"),
        "afpar": _p("Coriolis term weighting", "float", 0.5, "", "[0,1]"),
        "atpar": _p("Vertical viscosity weighting", "float", 1.0, "", "[0,1]"),
        "adpar": _p("Vertical diffusion weighting", "float", 1.0, "", "[0,1]"),
        "aapar": _p("Vertical advection weighting", "float", 1.0, "", "[0,1]"),
        # --- Coriolis ---
        "icor": _p("Coriolis force", "int", 0, "", "0=off, 1=beta-plane, 2=f-plane"),
        "dlat": _p("Latitude for Coriolis parameter", "float", 100.0, "deg N", ""),
        "isphe": _p("Coordinate system", "int", -1, "", "-1=auto, 0=Cartesian, 1=spherical"),
        # --- Depth ---
        "href": _p("Reference depth correction", "float", 0.0, "m", ""),
        "hzmin": _p("Minimum water depth (drying)", "float", 0.01, "m", ">0"),
        "hzoff": _p("Depth threshold for drying", "float", 0.05, "m", ">hzmin"),
        "hzon": _p("Depth threshold for rewetting", "float", 0.10, "m", ">hzoff"),
        "hmin": _p("Minimum basin depth", "float", -99999, "m", ""),
        "hmax": _p("Maximum basin depth", "float", 99999, "m", ""),
        "rlin": _p("Non-linear term strength", "float", 1.0, "", "0=off, 1=full"),
        # --- Bottom friction ---
        "ireib": _p(
            "Bottom friction type",
            "int",
            0,
            "",
            "0=none, 1=Chezy law, 2=Strickler, 3=Chezy coeff, 4=linear, "
            "5=quadratic drag, 6=roughness z0, 7=Strickler+drag, "
            "8=sediment z0, 9=fluid mud, 10=hybrid quad-linear",
        ),
        "czdef": _p("Friction coefficient", "float", 0.0, "", "depends on ireib"),
        "iczv": _p("Friction coefficient type flag", "int", 1, "", "0/1"),
        # --- Wind ---
        "iwtype": _p("Wind input type", "int", 1, "", "1-5"),
        "itdrag": _p("Drag calculation type", "int", 0, "", "0/1"),
        "dragco": _p("Wind drag coefficient", "float", 2.5e-3, "", ">0"),
        "wsmax": _p("Maximum wind speed", "float", 50.0, "m/s", ">0"),
        "rfact": _p("Wind stress scaling factor", "float", 1.0, "", ">0"),
        # --- Heat flux ---
        "iheat": _p(
            "Heat flux algorithm",
            "int",
            1,
            "",
            "0=off, 1=AREG, 2=POM bulk, 3=Gill, 4=Dejak, 5=GOTM, "
            "6=COARE 3.0, 7=read from file, 8=MFS bulk",
        ),
        "imetout": _p(
            "Meteo output streams (bitmask)",
            "int",
            0,
            "",
            "digits: 1s=wind,10s=heat,100s=rain,1000s=ice,10000s=heat-fluxes",
        ),
        "ihtype": _p("Water vapor input type", "int", 1, "", "1=RH%, 2=Tw, 3=Td, 4=q"),
        "hdecay": _p("Radiation penetration depth", "float", 0.0, "m", "0=no penetration"),
        "albedo": _p("Surface albedo", "float", 0.06, "", "[0,1]"),
        "ievap": _p("Compute evaporation mass flux", "int", 0, "", "0/1"),
        "irain": _p("Compute precipitation mass flux", "int", 1, "", "0/1"),
        # --- Physical constants ---
        "rowass": _p("Water density", "float", 1025.0, "kg/m3", ">0"),
        "roluft": _p("Air density", "float", 1.225, "kg/m3", ">0"),
        "grav": _p("Gravitational acceleration", "float", 9.81, "m/s2", ">0"),
        # --- 3D layers ---
        "dzreg": _p("Regular vertical layer spacing", "float", 0.0, "m", "0=use $levels"),
        "ilytyp": _p(
            "Bottom layer treatment", "int", 3, "", "0=none,1=delete,2=delete if thin,3=merge"
        ),
        "hlvmin": _p("Minimum bottom layer thickness fraction", "float", 0.25, "", "[0,1]"),
        "nzadapt": _p("Moving surface layers (z-star)", "int", 0, "", "0=z-layers only"),
        "nsigma": _p("Number of sigma layers", "int", 0, "", "0=use $levels"),
        "hsigma": _p("Depth for sigma-zeta transition", "float", 10000.0, "m", ">0"),
        # --- Vertical mixing ---
        "difmol": _p("Molecular vertical diffusivity", "float", 1.0e-6, "m2/s", ">0"),
        "diftur": _p("Turbulent vertical diffusivity", "float", 0.0, "m2/s", ">=0"),
        "vismol": _p("Molecular vertical viscosity", "float", 1.0e-6, "m2/s", ">0"),
        "vistur": _p("Turbulent vertical viscosity", "float", 0.0, "m2/s", ">=0"),
        "iturb": _p(
            "Turbulence closure model", "int", 0, "", "0=none,1=GOTM,2=k-e,3=Munk-Anderson"
        ),
        # --- Horizontal mixing ---
        "idhtyp": _p(
            "Horizontal diffusion type", "int", 0, "", "0=constant,1=area-weighted,2=Smagorinsky"
        ),
        "ahpar": _p("Horizontal viscosity coefficient", "float", 0.0, "m2/s", ">=0"),
        "dhpar": _p("Horizontal diffusion coefficient", "float", 0.0, "m2/s", ">=0"),
        "noslip": _p("Boundary condition", "int", 0, "", "0=free-slip, 1=no-slip"),
        # --- Scalar transport ---
        "itvd": _p("Horizontal advection scheme for scalars", "int", 0, "", "0=upwind, 1-2=TVD"),
        "itvdv": _p("Vertical advection scheme for scalars", "int", 0, "", "0=upwind, 1=TVD"),
        # --- Temperature / Salinity ---
        "ibarcl": _p(
            "Baroclinic mode",
            "int",
            0,
            "",
            "0=off, 1=diagnostic, 2=T/S diagnostic, 3=prognostic, 4=nudging, 5=assimilation",
        ),
        "itemp": _p("Compute temperature", "int", 1, "", "0/1"),
        "isalt": _p("Compute salinity", "int", 1, "", "0/1"),
        "temref": _p("Initial reference temperature", "float", 0.0, "C", ""),
        "salref": _p("Initial reference salinity", "float", 0.0, "PSU", ""),
        "thpar": _p("Temperature horizontal diffusion", "float", -1.0, "", "-1=use dhpar"),
        "shpar": _p("Salinity horizontal diffusion", "float", -1.0, "", "-1=use dhpar"),
        # --- Concentration / Tracers ---
        "iconz": _p("Number of concentrations/tracers", "int", 0, "", "0=off"),
        "idecay": _p("Tracer decay type", "int", 0, "", "0=none,1=exponential,2=Chapra"),
        "ibeach": _p(
            "Tracer beaching/burial mode", "int", 0, "", "0=off,1=Curonian,2=Danube,3=STR rates"
        ),
        "beachrate": _p(
            "Beaching rate (surface loss/step)", "float", 0.0, "", "used when ibeach=3"
        ),
        "burryrate": _p("Burial rate (bottom loss/step)", "float", 0.0, "", "used when ibeach=3"),
        "iage": _p("Water age tracer mode", "int", 0, "", "0/1"),
        "conref": _p("Initial reference concentration", "float", 0.0, "", ""),
        "chpar": _p("Concentration horizontal diffusion", "float", -1.0, "", "-1=use dhpar"),
        "wsettl": _p("Settling velocity", "float", 0.0, "m/s", "downward positive"),
        # --- Output averaging ---
        "iout_av": _p("Hydro output averaging", "int", 0, "", "0=instantaneous, 1=time-averaged"),
        "icon_av": _p(
            "Scalar output averaging", "int", 0, "", "0=instant,1=time-avg,2=vert+time-avg"
        ),
        # --- Module activation ---
        "ihydro": _p("Compute hydrodynamics", "int", 1, "", "0/1 (0 for debug)"),
        "ibio": _p("Biological module", "int", 0, "", "0/1"),
        "issedi": _p("Sediment module", "int", 0, "", "0/1"),
        "rtide": _p("Tidal forcing", "int", 0, "", "0/1"),
        "icemod": _p("Ice model", "int", 0, "", "0/1"),
        # --- Waves ---
        "iwave": _p(
            "Wave coupling mode",
            "int",
            0,
            "",
            "0=off, 1=constant file, 2=WWMIII rad+SHYFEM wind, 3=WWMIII vort+SHYFEM wind, "
            "4=WWMIII rad+WWM wind, 5=WWMIII vort+WWM wind",
        ),
        "dtwave": _p("Wave-current coupling time step", "float", 0.0, "s", ">0 when iwave>0"),
        # --- Mercury ---
        "imerc": _p("Mercury contamination model", "int", 0, "", "0=off, 1=on"),
        # --- Restart ---
        "itrst": _p("Restart file write interval", "string", "0", "s", "-1=last step only"),
        "itmrst": _p("Restart output start time", "string", "-1", "", "date or seconds"),
        "ityrst": _p(
            "Restart mode",
            "int",
            0,
            "",
            "0=strict match, 1=cold-start if missing, 2=closest time",
        ),
        # --- Offline mode ---
        "idtoff": _p(
            "Offline mode",
            "int",
            0,
            "",
            "0=off, >0=write hydro, -1=read hydro, -2=read T/S, -4=read turb, -3/-7=combos",
        ),
        "itmoff": _p("Offline start time", "string", "-1", "", "date or seconds"),
        # --- Grid/partition ---
        "ibasin": _p("Grid optimization", "int", -1, "", "-1=none,0=renumber,1=optimize"),
        "pqual": _p("Max partition quality index (MPI)", "float", 2.5, "", ">0"),
    },
    "name": {
        # Forcing files
        "wind": _p("Wind forcing time series file", "string", "", "", ""),
        "rain": _p("Precipitation forcing file", "string", "", "", ""),
        "qflux": _p("Heat flux data file", "string", "", "", ""),
        "ice": _p("Ice forcing file", "string", "", "", ""),
        # Initial conditions
        "zinit": _p("Initial water level file", "string", "", "", ""),
        "tempin": _p("Initial temperature file", "string", "", "", ""),
        "saltin": _p("Initial salinity file", "string", "", "", ""),
        "conzin": _p("Initial concentration file", "string", "", "", ""),
        # Restart
        "restrt": _p("Restart file for continuation", "string", "", "", ""),
        # Observations
        "tempobs": _p("Temperature observations file", "string", "", "", ""),
        "saltobs": _p("Salinity observations file", "string", "", "", ""),
        # Turbulence
        "gotmpa": _p("GOTM turbulence parameters file", "string", "", "", ""),
        # System
        "basnam": _p("Grid/basin file name", "string", "", "", ""),
        # Ecology
        "bioin": _p("Initial pelagic ecology state file", "string", "", "", ""),
        "biosin": _p("Initial sediment ecology state file", "string", "", "", ""),
        "biocon": _p("Biogeochemical constants file", "string", "", "", ""),
        "biolight": _p("Light extinction data file", "string", "", "", ""),
        "mercin": _p("Initial mercury concentrations file", "string", "", "", ""),
        "bfmini": _p("Initial BFM state file", "string", "", "", ""),
        # Sediment
        "sedp": _p("Spatially varying sediment distribution file", "string", "", "", ""),
        "sedt": _p("Spatially varying critical erosion stress file", "string", "", "", ""),
        "sedcon": _p("Sediment model constants file", "string", "", "", ""),
        # Lagrangian / Nudging
        "lgrlin": _p("Lagrangian release area lines file", "string", "", "", ""),
        "lgrtrj": _p("Drifter trajectory file", "string", "", "", ""),
        "statcnn": _p("Connectivity station coordinates file", "string", "", "", ""),
        "surfvel": _p("Surface velocity nudging file", "string", "", "", ""),
        # Scalar boundary files
        "saltn": _p("Boundary salinity time series file", "string", "", "", ""),
        "tempn": _p("Boundary temperature time series file", "string", "", "", ""),
        "conzn": _p("Boundary concentration time series file", "string", "", "", ""),
    },
    "bound": {
        "kbound": _p("Boundary node/element numbers", "int_list", None, "", ""),
        "ibtyp": _p(
            "Boundary type",
            "int",
            1,
            "",
            "-1=closed, 0=off, 1=water level, 2=discharge, 3=volume inlet, "
            "4=momentum, 5=fixed scalar, 31=radiation/zero-gradient",
        ),
        "boundn": _p("Boundary time series file", "string", "", "", ""),
        "intpol": _p(
            "Interpolation method",
            "int",
            0,
            "",
            "0=auto (2, or 4 for water level), 1=stepwise, 2=linear, 4=cubic",
        ),
        "zfact": _p("Scaling factor for boundary values", "float", 1.0, "", ""),
        "ztilt": _p("Tilt for water level gradient", "float", 0.0, "m", ""),
    },
    "sedtr": {
        "isedi": _p("Enable full sediment transport", "int", 0, "", "0=off, 1=on"),
        "sedgrs": _p("Grain sizes (space-separated, fine to coarse)", "string", "", "mm", ""),
        "percin": _p("Initial grain size fractions (must sum to 1.0)", "string", "", "", ""),
        "tauin": _p("Critical erosion stress per grain class", "string", "", "Pa", ""),
        "irocks": _p("Element type excluded from erosion", "int", -1, "", "-1=none"),
        "sedref": _p("Initial reference sediment concentration", "float", 0.0, "kg/m3", ">=0"),
        "sedhpar": _p("Sediment horizontal diffusion", "float", 0.0, "m2/s", ">=0"),
        "adjtime": _p("Morphology equilibration time", "float", -1.0, "s", "-1=off"),
        "idtsed": _p("Sediment output interval", "int", 0, "s", ""),
        "itmsed": _p("Sediment output start time", "int", -1, "s", ""),
    },
    "lagrg": {
        "ilagr": _p("Lagrangian mode", "int", 0, "", "0=off, 1=surface, 2=2D, 3=3D"),
        "nbdy": _p("Particles per release event", "int", 0, "", ">=0"),
        "nbdymax": _p("Max particles in domain", "int", -1, "", "-1=unlimited"),
        "rwhpar": _p("Horizontal diffusion for particles", "float", 0.0, "m2/s", "-1=local"),
        "idtl": _p("Particle release interval", "int", 0, "s", ">0"),
        "ipvert": _p("Vertical distribution", "int", 0, "", "0=surface, >0=regular, <0=random"),
        "lbeach": _p("Beaching probability", "float", 0.0, "", "[0-1]"),
        "ldecay": _p("Particle decay time", "float", 0.0, "s", "0=no decay"),
        "ioil": _p("Oil spill simulation", "int", 0, "", "0=off, 1=on"),
        "ilarv": _p("Larval behavior module", "int", 0, "", "0=off, 1=on"),
        "stkpar": _p("Stokes drift calibration", "float", 0.0, "", ""),
        "dripar": _p("Drifter inertia multiplier", "float", 1.0, "", ">0"),
        "itlanf": _p("Lagrangian start time", "int", -1, "", "-1=use itanf"),
        "itlend": _p("Lagrangian end time", "int", -1, "", "-1=use itend"),
        "idtlgr": _p("Lagrangian output interval", "int", 0, "s", ">0"),
    },
    "connec": {
        "icnn": _p("Number of connectivity stations", "int", 0, "", ">=0"),
        "radcnn": _p("Release area radius", "float", 0.0, "m", ">0"),
        "ppscnn": _p("Particles per second per station", "float", 0.0, "1/s", ">0"),
        "pldcnn": _p("Pelagic larval duration", "float", 0.0, "days", ">0"),
        "idtcnn": _p("Connectivity output interval", "int", 0, "s", ">0"),
    },
    "bfmsc": {
        "ibfm": _p("Enable BFM biogeochemical model", "int", 0, "", "0=off, 1=on"),
        "ibtanf": _p("BFM start time", "int", 0, "", ""),
        "ibtend": _p("BFM end time", "int", 0, "", ""),
        "itmbfm": _p("BFM output start time", "int", -1, "", ""),
        "idtbfm": _p("BFM output interval", "int", 0, "s", ">0"),
    },
    "wrt": {
        "idtwrt": _p("Reset interval", "int", -1, "s", "-1=off, 0=no reset"),
        "c0": _p("Initial tracer concentration", "float", 1.0, "", ""),
        "iaout": _p("Outside area code", "int", -1, "", "-1=none"),
        "percmin": _p("Completion percentage threshold", "float", 0.0, "%", "0-100"),
        "iret": _p("Return flow flag", "int", 1, "", "0=explicit zero, 1=return"),
    },
    "nonhyd": {
        "inohyd": _p("Non-hydrostatic mode", "int", 0, "", "0=hydrostatic, 1=non-hydrostatic"),
        "aqpar": _p("Implicit parameter", "float", 0.5, "", "[0,1]"),
        "islope": _p("Poisson grid type", "int", 0, "", ""),
        "ivwadv": _p("Vertical advection of vertical momentum", "int", 0, "", "0=off, 1=on"),
    },
}
