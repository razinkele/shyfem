"""ASGI middleware for static-asset Cache-Control headers."""

_STATIC_EXTENSIONS = frozenset(
    {
        ".css",
        ".js",
        ".woff2",
        ".woff",
        ".ttf",
        ".png",
        ".svg",
        ".ico",
    }
)


def static_asset_ext(path: str) -> str:
    """Return the lower-cased static-asset extension of ``path``, or ``""``."""
    dot = path.rfind(".")
    ext = path[dot:].lower() if dot != -1 else ""
    return ext if ext in _STATIC_EXTENSIONS else ""


def is_static_asset_request(scope: dict) -> bool:
    """True for a GET/HEAD of a static file (script, stylesheet, font, image).

    Shiny's per-session routes (``/session/<id>/...``, e.g. downloads) are
    dynamic even when the name ends in an asset extension.
    """
    path = scope.get("path", "")
    return (
        scope.get("method", "GET") in ("GET", "HEAD")
        and "/session/" not in path
        and bool(static_asset_ext(path))
    )


class CacheHeaderMiddleware:
    """ASGI middleware that adds Cache-Control headers to static asset responses."""

    def __init__(self, app, max_age: int = 86400):
        self.app = app
        self.max_age = max_age

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or self.max_age <= 0:
            return await self.app(scope, receive, send)

        if not static_asset_ext(scope.get("path", "")):
            return await self.app(scope, receive, send)

        cache_value = f"public, max-age={self.max_age}".encode()

        async def send_with_cache(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append([b"cache-control", cache_value])
                message = {**message, "headers": headers}
            result = send(message)
            if result is not None:
                await result

        return await self.app(scope, receive, send_with_cache)
