"""Lagrangian particle trajectory loader — wraps lgrelab -lgmean.

Usage::

    wrapper = ShyfemWrapper(config.shyfem_dir)
    svc = LgrService(wrapper)
    tracks = await svc.load(Path("output.lgr"))
    # tracks: list[ParticleTrack], one per particle type group

lgrelab -lgmean writes ``lagrange_mean_traj.N`` text files to CWD.
Each file has one line per timestep: date(20) lon(f14.5) lat(f14.5)
depth(f10.3) age(f10.3) size(f10.3) [custom...].
"""

import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper

logger = logging.getLogger(__name__)


@dataclass
class ParticleTrack:
    """Mean trajectory for one particle type group from lgrelab -lgmean."""

    type_id: int
    path: list[list[float]] = field(default_factory=list)  # [[lon, lat], ...]
    times: list[str] = field(default_factory=list)  # "YYYY-MM-DD HH:MM:SS"
    depths: list[float] = field(default_factory=list)
    ages: list[float] = field(default_factory=list)


class LgrService:
    """Loads .lgr Lagrangian particle files via lgrelab -lgmean."""

    def __init__(self, wrapper: ShyfemWrapper):
        self._wrapper = wrapper

    async def load(self, lgr_path: Path) -> list[ParticleTrack]:
        """Run lgrelab -lgmean on lgr_path and return parsed tracks.

        Args:
            lgr_path: Path to a .lgr file from a completed IBM simulation.

        Returns:
            List of ParticleTrack objects, one per particle type group.
            Returns an empty list if the file produced no trajectory output.

        Raises:
            FileNotFoundError: If lgr_path does not exist.
            RuntimeError: If lgrelab is not found or exits with a non-zero return code.
        """
        if not lgr_path.exists():
            raise FileNotFoundError(f"LGR file not found: {lgr_path}")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            try:
                result = await self._wrapper.run_command(
                    "lgrelab",
                    ["-lgmean", str(lgr_path.resolve())],
                    working_dir=tmp_path,
                )
            except FileNotFoundError as e:
                raise RuntimeError(
                    "lgrelab executable not found — ensure SHYFEM bin directory is configured"
                ) from e
            if not result.success:
                raise RuntimeError(f"lgrelab failed (code {result.return_code}): {result.stderr}")

            traj_files = sorted(tmp_path.glob("lagrange_mean_traj.*"))
            if not traj_files:
                logger.warning("lgrelab produced no lagrange_mean_traj.* files for %s", lgr_path)
                return []

            tracks = []
            for i, tfile in enumerate(traj_files, start=1):
                rows = _parse_traj_file(tfile)
                if rows:
                    tracks.append(
                        ParticleTrack(
                            type_id=i,
                            path=[[r["lon"], r["lat"]] for r in rows],
                            times=[r["date"] for r in rows],
                            depths=[r["depth"] for r in rows],
                            ages=[r["age"] for r in rows],
                        )
                    )
            return tracks


def _parse_traj_file(path: Path) -> list[dict]:
    """Parse a lagrange_mean_traj.N text file into a list of row dicts.

    Fortran format: (a20, 2f14.5, 3f10.3, nc*f10.3)
    The 20-char date field "YYYY-MM-DD HH:MM:SS" splits into two whitespace
    tokens, so floats start at index 2.

    Returns:
        List of dicts with keys: date, lon, lat, depth, age
    """
    rows = []
    with open(path) as f:
        for line in f:
            parts = line.split()
            if len(parts) < 6:
                continue
            # Verify parts[1] looks like HH:MM:SS (colon at index 2)
            if len(parts[1]) < 3 or parts[1][2] != ":":
                logger.debug("Skipping line with unexpected date format: %s", line.rstrip())
                continue
            try:
                date = f"{parts[0]} {parts[1]}"
                lon = float(parts[2])
                lat = float(parts[3])
                depth = float(parts[4])
                age = float(parts[5])
                rows.append({"date": date, "lon": lon, "lat": lat, "depth": depth, "age": age})
            except (ValueError, IndexError):
                logger.debug("Skipping malformed trajectory line: %s", line.rstrip())
    return rows


def filter_by_time(
    tracks: list[ParticleTrack],
    tmin: str | None,
    tmax: str | None,
) -> list[ParticleTrack]:
    """Filter track timesteps by time string range.

    Comparison is lexicographic on "YYYY-MM-DD HH:MM:SS" strings.
    Tracks with no remaining steps after filtering are dropped.

    Args:
        tracks: Input list of ParticleTrack objects.
        tmin: Earliest time to include (inclusive), or None for no lower bound.
        tmax: Latest time to include (inclusive), or None for no upper bound.

    Returns:
        New list of ParticleTrack objects with filtered timesteps.
    """
    tmin = tmin or None
    tmax = tmax or None
    if tmin is None and tmax is None:
        return tracks

    filtered = []
    for track in tracks:
        indices = [
            i
            for i, t in enumerate(track.times)
            if (tmin is None or t >= tmin) and (tmax is None or t <= tmax)
        ]
        if indices:
            filtered.append(
                ParticleTrack(
                    type_id=track.type_id,
                    path=[track.path[i] for i in indices],
                    times=[track.times[i] for i in indices],
                    depths=[track.depths[i] for i in indices],
                    ages=[track.ages[i] for i in indices],
                )
            )
    return filtered
