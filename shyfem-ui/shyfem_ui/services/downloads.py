"""Serve a download to the browser over HTTP, not over the websocket.

A download used to be read into memory, base64-encoded on the event loop and
sent to the browser as a ``data:`` URI, as one websocket frame (F-06, F-07):
a 500 MB file froze every session in the worker while it was encoded, and
the frame was a third larger than the file. Instead, a page offers the file
here and sends the browser a link to a session route; the browser fetches
the link with an ordinary GET, which Starlette streams in chunks from a
thread.

Each offer is a random token that expires after ``TTL_SECONDS``. The page
decides who may download what (its access check runs before the offer), and
the route serves only what it was offered, so a user who edits the link gets
a 404, not someone else's file.

A file is served at the size it had when the browser asked for it: a job's
output that is still growing is cut there, not failed for sending more than
its declared length.
"""

from __future__ import annotations

import secrets
import time
from collections import OrderedDict
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

from starlette.responses import PlainTextResponse, StreamingResponse

# Offers the browser never fetched (a closed tab, a blocked download) are
# dropped oldest first past this many, so they cannot pile up in a session.
# A buffer (an export ZIP, up to the export cap) is held at most once: a new
# one replaces the last.
MAX_PENDING = 16
TTL_SECONDS = 300

_CHUNK = 1024 * 1024


def _headers(filename: str, size: int) -> dict[str, str]:
    return {
        # filename*= survives any file name (quotes, CR/LF, non-ASCII).
        "Content-Disposition": f"attachment; filename*=utf-8''{quote(filename)}",
        "Content-Length": str(size),
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }


def _read_file(path: Path, size: int):
    """Yield the first ``size`` bytes of ``path``, in chunks."""
    with open(path, "rb") as fh:
        left = size
        while left > 0:
            chunk = fh.read(min(_CHUNK, left))
            if not chunk:
                return
            left -= len(chunk)
            yield chunk


def _read_buffer(buf: BytesIO, size: int):
    view = buf.getbuffer()
    try:
        for start in range(0, size, _CHUNK):
            yield bytes(view[start : start + _CHUNK])
    finally:
        view.release()


class SessionDownloads:
    """One session route serving the files and buffers a page offers."""

    def __init__(self, session, route_name: str = "download"):
        self._pending: OrderedDict[str, tuple] = OrderedDict()
        self._url = session.dynamic_route(route_name, self.handle)

    def _offer(self, entry: tuple) -> str:
        now = time.monotonic()
        for token, (_, _, _, _, expires) in list(self._pending.items()):
            if expires < now:
                del self._pending[token]
        if entry[0] == "buffer":
            for token in [t for t, e in self._pending.items() if e[0] == "buffer"]:
                del self._pending[token]
        token = secrets.token_urlsafe(16)
        self._pending[token] = (*entry, now + TTL_SECONDS)
        while len(self._pending) > MAX_PENDING:
            self._pending.popitem(last=False)
        return f"{self._url}&t={token}"

    def offer_file(self, path: Path, filename: str) -> str:
        """Return a link that downloads ``path`` as ``filename``."""
        return self._offer(("file", Path(path), filename, "application/octet-stream"))

    def offer_buffer(self, buf: BytesIO, filename: str, media_type: str) -> str:
        """Return a link that downloads the contents of ``buf``."""
        return self._offer(("buffer", buf, filename, media_type))

    def handle(self, request):
        entry = self._pending.get(request.query_params.get("t", ""))
        if entry is None or entry[4] < time.monotonic():
            return PlainTextResponse("This download link has expired.", status_code=404)
        kind, source, filename, media_type, _ = entry
        if kind == "file":
            try:
                size = source.stat().st_size
            except OSError:
                size = -1
            if size < 0 or not source.is_file():
                return PlainTextResponse("File not found.", status_code=404)
            body = _read_file(source, size)
        else:
            size = source.getbuffer().nbytes
            body = _read_buffer(source, size)
        # A sync iterator: Starlette reads it in a thread, off the event loop.
        return StreamingResponse(body, media_type=media_type, headers=_headers(filename, size))
