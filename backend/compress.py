"""Gzip for text responses (pages, scripts, styles, JSON). Scripts shrink about 4x, which is most of the first load.

Only complete, compressible bodies are compressed: recordings, images, PDFs, range requests and streamed responses
pass through untouched; text bodies over 8 MB too. Hashed /assets/ files are compressed once and kept in memory."""
import gzip

COMPRESSIBLE = ("text/", "application/json", "application/javascript", "application/xml", "image/svg+xml", "application/manifest+json")
MIN_SIZE = 1024
MAX_SIZE = 8 * 1024 * 1024
_cache: dict[tuple[str, int], bytes] = {}


class Gzip:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        hdrs = dict(scope.get("headers") or [])
        if b"gzip" not in hdrs.get(b"accept-encoding", b"") or b"range" in hdrs:
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        start: dict | None = None
        passthrough = False
        parts: list[bytes] = []
        size = [0]

        async def wrapped(msg):
            nonlocal start, passthrough
            if msg["type"] == "http.response.start":
                h = {k.lower(): v for k, v in msg.get("headers", [])}
                ctype = h.get(b"content-type", b"").decode("latin-1")
                if b"content-encoding" in h or not ctype.startswith(COMPRESSIBLE) or ctype.startswith("text/event-stream"):
                    passthrough = True
                    return await send(msg)
                start = msg
                return
            if msg["type"] != "http.response.body" or passthrough:
                return await send(msg)
            parts.append(msg.get("body", b""))
            size[0] += len(parts[-1])
            if size[0] > MAX_SIZE:                          # too big to buffer: send what we have, uncompressed
                await send(start)
                start, passthrough = None, True
                await send({"type": "http.response.body", "body": b"".join(parts), "more_body": msg.get("more_body", False)})
                return
            if msg.get("more_body"):
                return
            body = b"".join(parts)
            if len(body) < MIN_SIZE or start.get("status") not in (200, 404):
                await send(start)
                return await send({"type": "http.response.body", "body": body})
            key = (path, len(body))
            z = _cache.get(key) if path.startswith("/assets/") else None
            if z is None:
                z = gzip.compress(body, 6)
                if path.startswith("/assets/") and len(_cache) < 200:
                    _cache[key] = z
            headers = [(k, v) for k, v in start.get("headers", []) if k.lower() != b"content-length"]
            headers += [(b"content-encoding", b"gzip"), (b"content-length", str(len(z)).encode()), (b"vary", b"Accept-Encoding")]
            await send({**start, "headers": headers})
            await send({"type": "http.response.body", "body": z})

        await self.app(scope, receive, wrapped)
