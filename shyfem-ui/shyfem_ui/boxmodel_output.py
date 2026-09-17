"""Streaming readers for SHYFEM box-model (``idtbox``) output.

Formats verified on real 8.4 output (spec §5). Everything streams line by
line; nothing here imports ``shyfem_ui.services`` or ``shyfem_ui.db`` -- the
cache-builder child process imports this module and must stay light.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

STATE_VARS = ("temp", "salt", "cur_speed", "act_eta", "aver_eta", "bstress", "volume")
METEO_VARS = ("srad", "tair", "rhum", "wspeed", "cc", "rain", "evap", "ice")
FILE_TYPE_STATE, FILE_TYPE_METEO, FILE_TYPE_STATS, FILE_TYPE_GEOM = 2, 1, 8, 7
MAX_BOXES = 10_000
MAX_SECTIONS = 100_000
MAX_LINE_LENGTH = 1024
_STAMP = "%Y-%m-%d::%H:%M:%S"


class BoxOutputError(ValueError):
    """Malformed or out-of-policy box output; the message names file and record."""


@dataclass(frozen=True)
class Preamble:
    idbox: int
    file_type: int
    nvers: int


@dataclass
class StateRecord:
    seconds: float
    stamp: datetime
    box_ids: np.ndarray
    values: np.ndarray  # (nbox, 7) in STATE_VARS order
    sections: np.ndarray  # (nsec, 6): section, from, to, total, positive, negative


@dataclass
class MeteoRecord:
    seconds: float
    stamp: datetime
    box_ids: np.ndarray
    values: np.ndarray  # (nbox, 8) in METEO_VARS order


@dataclass
class BoxStats:
    date0: int
    time0: int
    idtbox_seconds: int
    start: datetime
    end: datetime
    boxes: pd.DataFrame
    sections: pd.DataFrame
    section_nodes: dict[int, list[tuple[float, float]]] = field(default_factory=dict)


@dataclass
class RunLogFacts:
    simulation_start_wall: str | None = None
    simulation_end_wall: str | None = None
    simulation_runtime: str | None = None
    cpu_total_seconds: float | None = None
    program_stop_time: str | None = None
    forcing: list[dict] = field(default_factory=list)


def _lines(path: Path) -> Iterator[tuple[int, str]]:
    """Yield (line_number, stripped line) enforcing the line-length cap."""
    with open(path, encoding="ascii", errors="replace") as fh:
        for n, raw in enumerate(fh, start=1):
            if len(raw) > MAX_LINE_LENGTH:
                raise BoxOutputError(f"{path.name}: line {n} exceeds {MAX_LINE_LENGTH} bytes")
            yield n, raw.rstrip("\n")


def read_preamble(path: Path) -> Preamble:
    it = _lines(path)
    try:
        _, l1 = next(it)
        _, l2 = next(it)
    except StopIteration as e:
        raise BoxOutputError(f"{path.name}: truncated preamble") from e
    if not l1.lstrip().startswith("#") or "idbox" not in l1:
        raise BoxOutputError(f"{path.name}: missing idbox preamble")
    g = l2.split()
    if len(g) != 4 or g[0] != "#":
        raise BoxOutputError(f"{path.name}: malformed preamble line 2")
    return Preamble(int(g[1]), int(g[2]), int(g[3]))


def _expect_preamble(path: Path, file_type: int) -> None:
    pre = read_preamble(path)
    if pre.file_type != file_type:
        raise BoxOutputError(f"{path.name}: file_type {pre.file_type}, expected {file_type}")


def _parse_stamp(g: list[str], path: Path, rec: int) -> tuple[float, datetime]:
    if len(g) != 2:
        raise BoxOutputError(f"{path.name}: record {rec}: bad time line")
    try:
        return float(g[0]), datetime.strptime(g[1], _STAMP)
    except ValueError as e:
        raise BoxOutputError(f"{path.name}: record {rec}: bad time stamp") from e


def _read_block(it, path: Path, rec: int, count: int, ncols: int, label: str) -> np.ndarray:
    """Read `count` numeric lines of `ncols` fields; duplicate first-column ids abort."""
    out = np.empty((count, ncols), dtype=float)
    seen: set[int] = set()
    for i in range(count):
        try:
            n, line = next(it)
        except StopIteration as e:
            raise BoxOutputError(f"{path.name}: record {rec}: truncated {label} block") from e
        g = line.split()
        if len(g) != ncols:
            raise BoxOutputError(f"{path.name}: record {rec}: malformed {label} line {n}")
        try:
            row = [float(x) for x in g]
        except ValueError as e:
            raise BoxOutputError(f"{path.name}: record {rec}: malformed {label} line {n}") from e
        key = int(row[0])
        if key in seen:
            raise BoxOutputError(f"{path.name}: record {rec}: duplicate {label} id {key}")
        seen.add(key)
        out[i] = row
    return out


def _iter_records(path: Path, file_type: int, nvars: int, with_sections: bool):
    _expect_preamble(path, file_type)
    it = _lines(path)
    next(it)
    next(it)  # preamble
    rec = 0
    for n, line in it:
        if line.strip() != "# time record":
            if line.strip() == "":
                continue
            raise BoxOutputError(
                f"{path.name}: record {rec + 1}: expected '# time record' at line {n}"
            )
        rec += 1
        _, tl = next(it)
        seconds, stamp = _parse_stamp(tl.split(), path, rec)
        _, hdr = next(it)
        if "boxes" not in hdr:
            raise BoxOutputError(f"{path.name}: record {rec}: expected boxes header")
        _, cnt = next(it)
        g = cnt.split()
        if len(g) != 2 or int(g[1]) != nvars:
            raise BoxOutputError(
                f"{path.name}: record {rec}: expected nvars={nvars}, got {cnt.strip()!r}"
            )
        nbox = int(g[0])
        if nbox <= 0 or nbox > MAX_BOXES:
            raise BoxOutputError(f"{path.name}: record {rec}: boxes={nbox} outside 1..{MAX_BOXES}")
        next(it)  # '# box ...' column header
        block = _read_block(it, path, rec, nbox, nvars + 1, "box")
        box_ids = block[:, 0].astype(int)
        values = block[:, 1:]
        sections = np.empty((0, 6))
        if with_sections:
            _, sh = next(it)
            if "sections" not in sh:
                raise BoxOutputError(f"{path.name}: record {rec}: expected sections header")
            _, sc = next(it)
            nsec = int(sc.split()[0])
            if nsec < 0 or nsec > MAX_SECTIONS:
                raise BoxOutputError(
                    f"{path.name}: record {rec}: sections={nsec} outside 0..{MAX_SECTIONS}"
                )
            next(it)  # '# section from to ...'
            sections = _read_block(it, path, rec, nsec, 6, "section")
        yield seconds, stamp, box_ids, values, sections


def iter_state_records(path: Path) -> Iterator[StateRecord]:
    for seconds, stamp, ids, values, sections in _iter_records(path, FILE_TYPE_STATE, 7, True):
        yield StateRecord(seconds, stamp, ids, values, sections)


def iter_meteo_records(path: Path) -> Iterator[MeteoRecord]:
    for seconds, stamp, ids, values, _ in _iter_records(path, FILE_TYPE_METEO, 8, False):
        yield MeteoRecord(seconds, stamp, ids, values)


def read_stats(path: Path) -> BoxStats:
    _expect_preamble(path, FILE_TYPE_STATS)
    lines = [ln for _, ln in _lines(path)][2:]
    i = 0

    def take():
        nonlocal i
        i += 1
        return lines[i - 1]

    if "information on simulation" not in take():
        raise BoxOutputError(f"{path.name}: expected simulation information block")
    d0 = take().split()
    date0, time0 = int(d0[0]), int(d0[1])
    idtbox = int(float(take().split()[0]))
    start = datetime.strptime(take().split("=")[1].strip(), _STAMP)
    end = datetime.strptime(take().split("=")[1].strip(), _STAMP)
    take()  # '#      boxes       nvars'
    g = take().split()
    if len(g) != 2:
        raise BoxOutputError(f"{path.name}: malformed boxes/nvars line")
    n = int(g[1])
    if n != 4:
        raise BoxOutputError(f"{path.name}: expected nvars=4 in stats header, got {n}")
    nbox = int(g[0])
    if nbox <= 0 or nbox > MAX_BOXES:
        raise BoxOutputError(f"{path.name}: boxes={nbox} outside 1..{MAX_BOXES}")
    take()  # column header
    rows = [take().split() for _ in range(nbox)]
    boxes = pd.DataFrame(rows, columns=["box", "layers", "area", "volume", "depth"]).astype(
        {"box": int, "layers": int, "area": float, "volume": float, "depth": float}
    )
    if (boxes["layers"] > 1).any():
        raise BoxOutputError(f"{path.name}: layers > 1 (3-D box output is not supported)")
    take()  # '#   sections'
    nsec = int(take().split()[0])
    if nsec < 0 or nsec > MAX_SECTIONS:
        raise BoxOutputError(f"{path.name}: sections={nsec} outside 0..{MAX_SECTIONS}")
    take()
    srows = [take().split() for _ in range(nsec)]
    sections = pd.DataFrame(
        srows, columns=["section", "from_box", "to_box", "nls", "nlb1", "nlb2"]
    ).astype(int)
    section_nodes: dict[int, list[tuple[float, float]]] = {}
    if i < len(lines) and "section details" in lines[i]:
        take()
        take()  # header + count
        for _ in range(nsec):
            take()  # '#    section nodes from-box to-box layers'
            g = take().split()
            sec, nn = int(g[0]), int(g[1])
            take()  # '#       node node-number x y'
            pts = []
            for _ in range(nn):
                h = take().split()
                pts.append((float(h[2]), float(h[3])))
            section_nodes[sec] = pts
    return BoxStats(date0, time0, idtbox, start, end, boxes, sections, section_nodes)


def read_geom(path: Path) -> pd.DataFrame:
    _expect_preamble(path, FILE_TYPE_GEOM)
    lines = [ln for _, ln in _lines(path)][2:]
    if "elements" not in lines[0]:
        raise BoxOutputError(f"{path.name}: expected elements header")
    g = lines[1].split()
    if len(g) != 2:
        raise BoxOutputError(f"{path.name}: malformed elements/nvars line")
    n = int(g[1])
    if n != 3:
        raise BoxOutputError(f"{path.name}: expected nvars=3 in geom header, got {n}")
    nel = int(g[0])
    rows = [ln.split() for ln in lines[3 : 3 + nel]]
    if len(rows) != nel or any(len(r) != 4 for r in rows):
        raise BoxOutputError(f"{path.name}: malformed element table")
    return pd.DataFrame(rows, columns=["element", "box", "area", "depth"]).astype(
        {"element": int, "box": int, "area": float, "depth": float}
    )


_IFF_ROW = re.compile(r"^\s*(\d+)\s+(\d+)\s+(-?\d+)\s+(\d+)\s+(-?\d+)\s+(-?\d+)\s+(.*)$")


def read_run_log(
    path: Path, *, head_bytes: int = 4_000_000, tail_bytes: int = 1_000_000
) -> RunLogFacts:
    """Read the head (forcing table, wall-clock start) and the tail (stop, cpu) of a
    possibly huge log without loading it."""
    facts = RunLogFacts()
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        head = fh.read(head_bytes).decode("ascii", errors="replace")
        if size > head_bytes:
            fh.seek(max(size - tail_bytes, head_bytes))
            tail = fh.read().decode("ascii", errors="replace")
        else:
            tail = ""
    in_iff = False
    for line in head.splitlines():
        s = line.strip()
        if s.startswith("simulation start:"):
            facts.simulation_start_wall = s.split(":", 1)[1].strip()
        elif s.startswith("iff_print_info"):
            in_iff = True
            continue
        elif in_iff:
            if s.startswith("id ") or s.startswith("id\t"):
                continue
            m = _IFF_ROW.match(line)
            if not m:
                in_iff = False
                continue
            rest = m.group(7).rstrip()
            parts = rest.split()
            file_ = parts[-1] if parts and ("/" in parts[-1] or "." in parts[-1]) else ""
            descript = rest[: len(rest) - len(file_)].strip() if file_ else rest.strip()
            facts.forcing.append(
                {
                    "id": int(m.group(1)),
                    "ibc": int(m.group(2)),
                    "unit": int(m.group(3)),
                    "nvar": int(m.group(4)),
                    "intp": int(m.group(5)),
                    "form": int(m.group(6)),
                    "descript": descript,
                    "file": file_,
                }
            )
    for line in (tail or head).splitlines():
        s = line.strip()
        if s.startswith("program stop at time"):
            facts.program_stop_time = s.split("=", 1)[1].strip()
        elif s.startswith("cpu time (total)"):
            facts.cpu_total_seconds = float(s.split(":", 1)[1])
        elif s.startswith("simulation end:"):
            facts.simulation_end_wall = s.split(":", 1)[1].strip()
        elif s.startswith("simulation runtime:"):
            facts.simulation_runtime = s.split(":", 1)[1].strip()
    return facts
