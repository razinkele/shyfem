"""Box-model "Setup" tab services (spec §8, PR 3): a tolerant STR reader,
open-boundary extraction, the SHYFEM time-series (forcing) reader and the
section-interface geometry from the cache ``meta.json``.

Pure: no reactive state, nothing from ``shyfem_ui.components`` or
``shyfem_ui.pages``. Paths are never rendered -- ``StrSetup.path_name`` and
every error message carry the basename only (spec §4).

**Why a second STR reader.** ``shyfem_ui.parser_str`` is the *editor's*
parser and models the subset of the grammar the editor can round-trip:
``SECTION_START = ^\\s*\\$(\\w+)\\s*$`` rejects ``&para``, any ``$boundN``
header with trailing text, and truncates a multi-line ``kbound``. On the real
Curonian STR only ``title, waves, name, extra`` parse. The reader here is
*defined by that file* (see ``tests/test_boxmodel_setup.py::CURONIAN_EXCERPT``)
and follows SHYFEM's own ``nls.f90`` semantics where they matter:

* a section is opened by ``$name`` or ``&name`` (case-insensitive; anything
  after the name is the section's *title*) and closed by ``$end``/``&end``;
* everything outside a section is ignored -- prose, banners, ``key = value``
  lines, and the Curonian idiom of a *bare-word block* (``seaice … end``)
  that disables a section by dropping its marker;
* inside a section, ``key = value`` pairs may share a line; a bare integer
  list may continue on following numbers-only lines; ``!`` starts a comment.

Assignments outside any section that nevertheless *look* like parameters
(``nsigma = 12`` after ``&end``) are collected as ``orphans`` so the Setup tab
can warn: SHYFEM silently ignores them.
"""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from shyfem_ui.boxmodel_common import no_symlink_components

__all__ = [
    "Boundary",
    "StrSection",
    "StrSetup",
    "StrSetupError",
    "boundaries",
    "kind",
    "period_from_summary",
    "read_forcing_series",
    "read_str_tolerant",
    "resolve_forcing_file",
    "section_interfaces",
    "str_summary",
]


class StrSetupError(ValueError):
    """User-facing problem with an STR or forcing file; names the basename only."""


# -- STR reader ----------------------------------------------------------------

_HEADER_RE = re.compile(r"^\s*[$&]([A-Za-z_]\w*)(.*)$")
_END_RE = re.compile(r"^\s*[$&]end\s*$", re.IGNORECASE)
_BARE_WORD_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*$")
_BARE_END_RE = re.compile(r"^\s*end\s*$", re.IGNORECASE)
_KEY_EQ_RE = re.compile(r"([A-Za-z_]\w*)\s*=\s*")
_INT_RE = re.compile(r"^[+-]?\d+$")
_NUM_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eEdD][+-]?\d+)?$")
_INT_LINE_RE = re.compile(r"^\s*(?:[+-]?\d+\s*)+$")
_BOUND_RE = re.compile(r"^bound(\d+)$")

_OTHER_FILE_KEYS = ("saltn", "tempn", "conzn", "vel3dn", "bio2dn", "sed2dn")
_SUMMARY_KEYS = (
    "itanf",
    "itend",
    "idt",
    "idtbox",
    "idtflx",
    "idtext",
    "date",
    "time",
    "ireib",
    "czdef",
    "ibarcl",
    "iheat",
    "ievap",
    "iturb",
    "isalt",
    "itemp",
    "nomp",
)


@dataclass
class StrSection:
    """One ``$name … $end`` block.

    ``params`` keeps values as written with the quotes stripped (strings), or
    as ``list[int]`` for a bare integer list of two or more numbers (possibly
    continued over several lines). ``lines`` is every raw line between the
    header and the end marker, so ``$title``/``$extra`` (which contain no
    ``=``) are still available verbatim. ``duplicates`` maps a key that was
    assigned more than once to its *earlier* values (the last one wins in
    ``params``, as in SHYFEM).
    """

    name: str
    title: str
    params: dict[str, str | list[int]] = field(default_factory=dict)
    lines: list[str] = field(default_factory=list)
    duplicates: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class StrSetup:
    """The sections of one STR file, in file order, plus the orphan assignments."""

    sections: list[StrSection]
    orphans: list[tuple[int, str, str]]
    path_name: str

    def get(self, name: str) -> StrSection | None:
        """First section called ``name`` (case-insensitive), or None."""
        want = name.lower()
        for s in self.sections:
            if s.name == want:
                return s
        return None

    def bounds(self) -> list[StrSection]:
        """The ``$bound<k>`` sections sorted by ``k``."""
        found = []
        for s in self.sections:
            m = _BOUND_RE.match(s.name)
            if m:
                found.append((int(m.group(1)), s))
        found.sort(key=lambda t: t[0])
        return [s for _, s in found]


def _strip_comment(line: str) -> str:
    """Drop a trailing ``!`` comment, but not a ``!`` inside quotes."""
    quote: str | None = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "!":
            return line[:i]
    return line


def _parse_pairs(text: str) -> tuple[list[tuple[str, str | list[int]]], bool]:
    """Parse ``key = value`` pairs from one comment-stripped line.

    Returns ``(pairs, clean)``. A value is a quoted string, a single bare
    token, or a run of bare numeric tokens (all integers -> ``list[int]``,
    otherwise the tokens joined with one space). ``clean`` is False when the
    line carried anything else (text before the first key, a non-numeric
    token after a value, an empty or unterminated value): inside a section
    the pairs are still taken; outside one such a line is prose, not an
    orphan.
    """
    pairs: list[tuple[str, str | list[int]]] = []
    m = _KEY_EQ_RE.search(text)
    if m is None:
        return pairs, False
    clean = not text[: m.start()].strip()
    n = len(text)
    while m is not None:
        key = m.group(1).lower()
        pos = m.end()
        if pos < n and text[pos] in "'\"":
            close = text.find(text[pos], pos + 1)
            if close == -1:  # unterminated quote: take the rest of the line
                pairs.append((key, text[pos + 1 :].rstrip()))
                return pairs, False
            pairs.append((key, text[pos + 1 : close]))
            m = _KEY_EQ_RE.search(text, close + 1)
            if text[close + 1 : m.start() if m else n].strip():
                clean = False
            continue
        m = _KEY_EQ_RE.search(text, pos)
        tokens = text[pos : m.start() if m else n].split()
        if not tokens:
            clean = False
            pairs.append((key, ""))
        elif len(tokens) == 1:
            pairs.append((key, tokens[0]))
        elif all(_INT_RE.match(t) for t in tokens):
            pairs.append((key, [int(t) for t in tokens]))
        else:
            run: list[str] = []
            for t in tokens:
                if not _NUM_RE.match(t):
                    break
                run.append(t)
            if len(run) < len(tokens):  # a non-numeric token follows: prose
                clean = False
            pairs.append((key, " ".join(run) if run else tokens[0]))
    return pairs, clean


def _as_text(value: str | list[int]) -> str:
    return " ".join(str(v) for v in value) if isinstance(value, list) else value


def _read_lines(path: Path, max_bytes: int, max_line: int) -> list[str]:
    name = path.name
    try:
        with open(path, "rb") as fh:
            data = fh.read(max_bytes + 1)
    except OSError as exc:
        raise StrSetupError(f"{name}: cannot be read ({exc.strerror or 'error'})") from None
    if len(data) > max_bytes:
        raise StrSetupError(f"{name}: larger than {max_bytes:,} bytes")
    raw_lines = data.split(b"\n")
    if raw_lines and raw_lines[-1] == b"":
        raw_lines.pop()
    out: list[str] = []
    for i, raw in enumerate(raw_lines, start=1):
        if len(raw) > max_line:
            raise StrSetupError(f"{name}: line {i} is longer than {max_line} bytes")
        out.append(raw.decode("utf-8", errors="replace").rstrip("\r"))
    return out


def read_str_tolerant(path: Path, *, max_bytes: int = 1_000_000, max_line: int = 4096) -> StrSetup:
    """Read an STR file the way SHYFEM's ``nls`` does, without ever raising on content.

    Raises ``StrSetupError`` (naming the basename) only for a file over
    ``max_bytes`` or a line over ``max_line`` bytes, or an unreadable file.
    """
    path = Path(path)
    lines = _read_lines(path, max_bytes, max_line)

    sections: list[StrSection] = []
    orphans: list[tuple[int, str, str]] = []
    current: StrSection | None = None
    cont_key: str | None = None  # key whose bare int list may continue
    in_bare_block = False  # `seaice … end` idiom outside sections

    def _assign(sec: StrSection, key: str, value: str | list[int]) -> None:
        if key in sec.params:
            sec.duplicates.setdefault(key, []).append(_as_text(sec.params[key]))
        sec.params[key] = value

    for line_no, line in enumerate(lines, start=1):
        if _END_RE.match(line) or _END_RE.match(_strip_comment(line)):
            current = None
            cont_key = None
            continue
        hm = _HEADER_RE.match(line)
        if hm:
            rest = _strip_comment(hm.group(2))
            title = re.sub(r"^[\s\-]+|[\s\-]+$", "", rest)
            current = StrSection(name=hm.group(1).lower(), title=title)
            sections.append(current)
            cont_key = None
            in_bare_block = False
            continue

        if current is None:
            # Outside any section: SHYFEM ignores everything. Only report
            # assignments that look like parameters (a line made of pairs
            # only) and are not inside a disabled bare-word block.
            stripped = line.strip()
            if not stripped or stripped[0] in "!#":
                continue
            if in_bare_block:
                if _BARE_END_RE.match(line):
                    in_bare_block = False
                continue
            if _BARE_WORD_RE.match(line) and not _BARE_END_RE.match(line):
                in_bare_block = True
                continue
            body = _strip_comment(line)
            if "=" in body:
                pairs, clean = _parse_pairs(body)
                if clean:
                    orphans.extend((line_no, k, _as_text(v)) for k, v in pairs)
            continue

        # Inside a section.
        current.lines.append(line)
        stripped = line.strip()
        if not stripped:
            continue  # a blank line neither breaks nor extends anything
        if stripped[0] in "!#":
            continue
        body = _strip_comment(line)
        if not body.strip():
            continue
        if "=" in body:
            pairs, _clean = _parse_pairs(body)
            for k, v in pairs:
                _assign(current, k, v)
            last = pairs[-1] if pairs else None
            cont_key = last[0] if last and isinstance(last[1], list) else None
            continue
        if cont_key is not None and _INT_LINE_RE.match(body):
            existing = current.params.get(cont_key)
            if isinstance(existing, list):
                existing.extend(int(t) for t in body.split())
                continue
        cont_key = None

    return StrSetup(sections=sections, orphans=orphans, path_name=path.name)


# -- boundaries ------------------------------------------------------------------


@dataclass
class Boundary:
    """One ``$bound<k>`` section reduced to what the Setup tab shows."""

    number: int
    title: str
    ibtyp: int | None
    zfact: float
    kbound: list[int]
    boundn: str | None
    other_files: dict[str, str] = field(default_factory=dict)


def _int_or_none(value) -> int | None:
    if isinstance(value, list):
        return value[0] if len(value) == 1 else None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _kbound_list(value) -> list[int]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    out: list[int] = []
    for tok in str(value).split():
        try:
            out.append(int(tok))
        except ValueError:
            return out
    return out


def boundaries(setup: StrSetup) -> list[Boundary]:
    """The ``$bound<k>`` sections as ``Boundary`` rows, sorted by ``k``.

    Raises ``StrSetupError`` for a ``zfact`` that is not a number (showing
    1.0 for it would misreport the scaling); a missing ``zfact`` is 1.0.
    """
    out: list[Boundary] = []
    for sec in setup.bounds():
        number = int(_BOUND_RE.match(sec.name).group(1))
        p = sec.params
        zraw = p.get("zfact")
        if zraw is None:
            zfact = 1.0
        else:
            try:
                zfact = float(_as_text(zraw).lower().replace("d", "e"))
            except ValueError:
                raise StrSetupError(
                    f"{setup.path_name}: bound{number}: zfact {_as_text(zraw)!r} is not a number"
                ) from None
        boundn = p.get("boundn")
        out.append(
            Boundary(
                number=number,
                title=sec.title,
                ibtyp=_int_or_none(p["ibtyp"]) if "ibtyp" in p else None,
                zfact=zfact,
                kbound=_kbound_list(p.get("kbound")),
                boundn=_as_text(boundn) if boundn is not None else None,
                other_files={k: _as_text(p[k]) for k in _OTHER_FILE_KEYS if k in p},
            )
        )
    return out


def kind(b: Boundary) -> str:
    """``"level"`` (ibtyp 1), ``"discharge"`` (ibtyp 2 or 3) or ``"unknown"``."""
    if b.ibtyp == 1:
        return "level"
    if b.ibtyp in (2, 3):
        return "discharge"
    return "unknown"


# -- summary / period ------------------------------------------------------------


def str_summary(setup: StrSetup) -> dict[str, str]:
    """The ``&para`` keys the Setup tab shows, plus ``title`` and ``orphans`` when any."""
    out: dict[str, str] = {}
    title = setup.get("title")
    if title is not None:
        for ln in title.lines:
            if ln.strip():
                out["title"] = ln.strip()
                break
    para = setup.get("para")
    if para is not None:
        for key in _SUMMARY_KEYS:
            if key in para.params:
                out[key] = _as_text(para.params[key])
    if setup.orphans:
        out["orphans"] = ", ".join(f"{k} = {v} (line {ln})" for ln, k, v in setup.orphans)
    return out


_ISO_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:::(\d{2}:\d{2})(?::(\d{2}))?)?$")


def _iso_stamp(value: str) -> pd.Timestamp | None:
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    text = m.group(1)
    if m.group(2):
        text += " " + m.group(2) + (":" + m.group(3) if m.group(3) else ":00")
    try:
        return pd.Timestamp(text)
    except (ValueError, TypeError):
        return None


def period_from_summary(summary: dict[str, str]) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """``(itanf, itend)`` when both are ISO dates (``'2016-12-31'``, ``'2013-12-31::06:00'``)."""
    a = summary.get("itanf")
    b = summary.get("itend")
    if not a or not b:
        return None
    start = _iso_stamp(a)
    end = _iso_stamp(b)
    if start is None or end is None:
        return None
    return start, end


# -- forcing files ---------------------------------------------------------------


def resolve_forcing_file(
    boundn: str, forcing_dir: Path | None, config, user
) -> tuple[Path | None, str | None]:
    """Locate the forcing file an STR ``boundn`` names, by basename, under ``forcing_dir``.

    Returns ``(path, None)`` for a readable, confined, regular ``.txt`` file,
    else ``(None, note)`` with a short user-facing note. The path is confined
    through ``config.confine_path(..., must_exist=True)`` on every call, so
    callers re-resolve at each open (spec §9).
    """
    name = Path(str(boundn).replace("\\", "/")).name
    if not name or name in (".", ".."):
        return None, "not found"
    if not name.lower().endswith(".txt"):
        suffix = Path(name).suffix or "no suffix"
        return None, f"not read ({suffix})"
    if forcing_dir is None:
        return None, "forcing dir not configured"
    candidate = Path(forcing_dir) / name
    # A name the STR reader preserved verbatim can still be one pathlib
    # refuses to stat (an embedded NUL byte is valid UTF-8 and survives the
    # reader's "never raise on content" contract). Treat it as absent rather
    # than letting ValueError escape into a render.
    try:
        if not candidate.exists() and not candidate.is_symlink():
            return None, "not found"
        if not no_symlink_components(candidate):
            return None, "symlink refused"
        if not candidate.is_file():
            return None, "not a regular file"
    except ValueError:
        return None, "not found"
    try:
        confined = config.confine_path(candidate, user, must_exist=True)
    except ValueError:
        return None, "outside the allowed roots"
    except FileNotFoundError:
        return None, "not found"
    return Path(confined), None


def read_forcing_series(
    path: Path, *, max_bytes: int = 50_000_000, max_rows: int = 2_000_000
) -> pd.Series:
    """Read a SHYFEM time-series file (``YYYY-MM-DD::HH:MM:SS  v1 [v2 …]``).

    Returns a float64 series of the first value column indexed by timestamp
    (``datetime64[ns]``). Blank lines and lines starting with ``#`` are
    skipped. A malformed line, the size caps, or a symlink leaf raise
    ``StrSetupError`` naming the basename and the 1-based line number.
    """
    path = Path(path)
    name = path.name
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise StrSetupError(f"{name}: cannot be opened ({exc.strerror or 'error'})") from None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise StrSetupError(f"{name}: not a regular file")
        if st.st_size > max_bytes:
            raise StrSetupError(f"{name}: larger than {max_bytes:,} bytes")
        with os.fdopen(fd, "rb") as fh:
            fd = -1
            data = fh.read(max_bytes + 1)
    finally:
        if fd != -1:
            os.close(fd)
    if len(data) > max_bytes:
        raise StrSetupError(f"{name}: larger than {max_bytes:,} bytes")

    stamps: list[str] = []
    values: list[float] = []
    line_nos: list[int] = []
    for line_no, raw in enumerate(data.split(b"\n"), start=1):
        text = raw.decode("utf-8", errors="replace").strip()
        if not text or text.startswith("#"):
            continue
        parts = text.split()
        if len(parts) < 2:
            raise StrSetupError(f"{name}: line {line_no}: expected a time stamp and a value")
        m = _ISO_RE.match(parts[0])
        if not m:
            raise StrSetupError(f"{name}: line {line_no}: bad time stamp {parts[0]!r}")
        try:
            value = float(parts[1].lower().replace("d", "e"))
        except ValueError:
            raise StrSetupError(f"{name}: line {line_no}: bad value {parts[1]!r}") from None
        # Normalise to one shape so a single explicit format parses the lot.
        stamp = f"{m.group(1)} {m.group(2) or '00:00'}:{m.group(3) or '00'}"
        stamps.append(stamp)
        values.append(value)
        line_nos.append(line_no)
        if len(values) > max_rows:
            raise StrSetupError(f"{name}: more than {max_rows} rows")

    index = pd.to_datetime(stamps, format="%Y-%m-%d %H:%M:%S", errors="coerce")
    if len(index) and index.isna().any():
        # The regex accepted the shape; the calendar did not (e.g. 02-30).
        pos = int(index.isna().argmax())
        raise StrSetupError(f"{name}: line {line_nos[pos]}: bad date {stamps[pos].split(' ')[0]!r}")
    index = pd.DatetimeIndex(index).as_unit("ns")
    return pd.Series(values, index=index, dtype="float64", name="value")


# -- section interfaces ----------------------------------------------------------


def section_interfaces(meta: dict) -> list[dict]:
    """Section lines from a cache ``meta.json``.

    Each entry is ``{"section", "from_box", "to_box", "open_boundary", "path"}``
    where ``path`` is ``[[lon, lat], …]`` from ``meta["section_nodes"]`` and
    ``open_boundary`` is ``k`` for an open-boundary section (SHYFEM writes
    ``from_box = -k`` for ``$bound<k>``; a negative ``to_box`` is tolerated
    the same way). Sections without coordinates are omitted.
    """
    sections = meta.get("sections") if isinstance(meta, dict) else None
    nodes = meta.get("section_nodes") if isinstance(meta, dict) else None
    if not isinstance(sections, list) or not isinstance(nodes, dict):
        return []
    out: list[dict] = []
    for rec in sections:
        if not isinstance(rec, dict):
            continue
        try:
            sec = int(rec["section"])
            from_box = int(rec["from_box"])
            to_box = int(rec["to_box"])
        except (KeyError, TypeError, ValueError):
            continue
        pts = nodes.get(str(sec))
        if not isinstance(pts, list) or not pts:
            continue
        try:
            path = [[float(p[0]), float(p[1])] for p in pts]
        except (TypeError, ValueError, IndexError):
            continue
        if from_box < 0:
            open_boundary: int | None = -from_box
        elif to_box < 0:
            open_boundary = -to_box
        else:
            open_boundary = None
        out.append(
            {
                "section": sec,
                "from_box": from_box,
                "to_box": to_box,
                "open_boundary": open_boundary,
                "path": path,
            }
        )
    return out
