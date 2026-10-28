"""Downloads go over HTTP from a one-shot session route (F-06, F-07).

The file page and the project export used to base64 the whole file on the
event loop and push it down the websocket as a ``data:`` URI. They now offer
it to ``SessionDownloads`` and send the browser a link to fetch.
"""

import ast
import pathlib
from io import BytesIO
from urllib.parse import parse_qs, urlsplit

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from shyfem_ui.services import downloads as dl
from shyfem_ui.services.downloads import SessionDownloads

SRC = pathlib.Path(__file__).resolve().parents[1] / "shyfem_ui"


class _FakeSession:
    def __init__(self):
        self.routes = {}

    def dynamic_route(self, name, handler):
        self.routes[name] = handler
        return f"session/abc/dynamic_route/{name}?nonce=0123"


@pytest.fixture
def served():
    """A SessionDownloads behind a real Starlette app, and a client for it."""
    session = _FakeSession()
    downloads = SessionDownloads(session, "download")
    app = Starlette(routes=[Route("/session/abc/dynamic_route/download", downloads.handle)])
    return downloads, TestClient(app)


def _get(client, href):
    return client.get("/" + href)


def test_offer_file_serves_the_file(served, tmp_path):
    downloads, client = served
    f = tmp_path / "out.shy"
    f.write_bytes(b"\x00\x01payload")
    href = downloads.offer_file(f, "out.shy")

    assert parse_qs(urlsplit(href).query)["nonce"] == ["0123"]
    r = _get(client, href)
    assert r.status_code == 200
    assert r.content == b"\x00\x01payload"
    assert "attachment" in r.headers["content-disposition"]
    assert "out.shy" in r.headers["content-disposition"]
    assert r.headers["cache-control"] == "no-store"
    # A retried or resumed download fetches the link again.
    assert _get(client, href).content == b"\x00\x01payload"


def test_a_link_expires(served, tmp_path, monkeypatch):
    downloads, client = served
    f = tmp_path / "out.shy"
    f.write_bytes(b"x")
    clock = [1000.0]
    monkeypatch.setattr(dl.time, "monotonic", lambda: clock[0])
    href = downloads.offer_file(f, "out.shy")
    clock[0] += dl.TTL_SECONDS - 1
    assert _get(client, href).status_code == 200
    clock[0] += 2
    assert _get(client, href).status_code == 404


def test_a_growing_file_is_served_at_its_size_when_fetched(served, tmp_path, monkeypatch):
    """A running job's output may grow while it is sent: cut, not failed."""
    downloads, client = served
    f = tmp_path / "run.inf"
    f.write_bytes(b"a" * 10)
    real_read_file = dl._read_file

    def grow_then_read(path, size):
        with open(path, "ab") as fh:
            fh.write(b"b" * 5000)
        yield from real_read_file(path, size)

    monkeypatch.setattr(dl, "_read_file", grow_then_read)
    r = _get(client, downloads.offer_file(f, "run.inf"))
    assert r.status_code == 200
    assert r.content == b"a" * 10
    assert r.headers["content-length"] == "10"


def test_a_new_export_replaces_the_unfetched_one(served):
    downloads, client = served
    first = downloads.offer_buffer(BytesIO(b"one"), "a.zip", "application/zip")
    second = downloads.offer_buffer(BytesIO(b"two"), "a.zip", "application/zip")
    assert _get(client, first).status_code == 404
    assert _get(client, second).content == b"two"


def test_offer_buffer_streams_and_names_the_zip(served):
    downloads, client = served
    data = bytes(range(256)) * 9000  # > one 1 MiB chunk
    buf = BytesIO(data)
    buf.read()  # a caller may hand over a buffer that is not rewound
    href = downloads.offer_buffer(buf, "Lagoon run ä.zip", "application/zip")

    r = _get(client, href)
    assert r.status_code == 200
    assert r.content == data
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["content-length"] == str(len(data))
    assert r.headers["content-disposition"] == (
        "attachment; filename*=utf-8''Lagoon%20run%20%C3%A4.zip"
    )


def test_a_guessed_or_edited_token_is_refused(served, tmp_path):
    downloads, client = served
    f = tmp_path / "secret.txt"
    f.write_text("x")
    href = downloads.offer_file(f, "secret.txt")
    assert _get(client, href.rsplit("&t=", 1)[0] + "&t=guess").status_code == 404
    assert _get(client, href.rsplit("&t=", 1)[0]).status_code == 404
    assert _get(client, href).status_code == 200


def test_a_file_deleted_after_the_offer_is_a_404(served, tmp_path):
    downloads, client = served
    f = tmp_path / "gone.txt"
    f.write_text("x")
    href = downloads.offer_file(f, "gone.txt")
    f.unlink()
    assert _get(client, href).status_code == 404


def test_unfetched_offers_are_capped(served, tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "MAX_PENDING", 3)
    downloads, client = served
    f = tmp_path / "a.txt"
    f.write_text("x")
    hrefs = [downloads.offer_file(f, "a.txt") for _ in range(5)]
    assert [_get(client, h).status_code for h in hrefs] == [404, 404, 200, 200, 200]


@pytest.mark.parametrize("page", ["pages/files.py", "pages/home.py"])
def test_pages_no_longer_base64_a_download(page):
    """No data: URI downloads, and the file page never reads the file itself."""
    text = (SRC / page).read_text()
    assert "base64" not in text
    assert "data:application" not in text
    calls = {
        n.func.attr
        for n in ast.walk(ast.parse(text))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    if page == "pages/files.py":
        assert "read_bytes" not in calls
