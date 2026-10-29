"""D-04: runtime imports the app needs must be declared in pyproject.toml.

``pip install -e .`` (the documented install, and what CI runs) installs only
what ``[project].dependencies`` lists. Without ``alembic`` the database cannot
be migrated, and without ``shiny-deckgl`` the map pages and their tests are
skipped.
"""

import re
from pathlib import Path

import pytest
import tomllib

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _declared() -> dict[str, str]:
    deps = tomllib.loads(_PYPROJECT.read_text())["project"]["dependencies"]
    out = {}
    for dep in deps:
        name = re.match(r"[A-Za-z0-9._-]+", dep).group(0)
        out[re.sub(r"[-_.]+", "-", name).lower()] = dep
    return out


@pytest.mark.parametrize("name", ["alembic", "shiny-deckgl"])
def test_runtime_dependency_is_declared(name):
    assert name in _declared(), f"{name} missing from [project].dependencies"


@pytest.mark.parametrize("name", ["alembic", "shiny-deckgl"])
def test_installed_version_satisfies_the_declared_constraint(name):
    from importlib.metadata import PackageNotFoundError, version

    from packaging.requirements import Requirement

    req = Requirement(_declared()[name])
    try:
        installed = version(name)
    except PackageNotFoundError:
        pytest.skip(f"{name} not installed")
    if req.url:
        # A git direct reference pins a tag: the installed version must be it.
        tag = re.search(r"@v(\d+(?:\.\d+)*)$", req.url)
        assert tag, f"{name}: direct reference must pin a vX.Y.Z tag: {req.url}"
        assert installed == tag.group(1), (name, installed, req.url)
    else:
        assert req.specifier.contains(installed, prereleases=True), (name, installed, str(req))
