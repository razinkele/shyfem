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


class CacheHeaderMiddleware:
    """ASGI middleware that adds Cache-Control headers to static asset responses."""

    def __init__(self, app, max_age: int = 86400):
        self.app = app
        self.max_age = max_age

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or self.max_age <= 0:
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        dot = path.rfind(".")
        ext = path[dot:].lower() if dot != -1 else ""

        if ext not in _STATIC_EXTENSIONS:
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
