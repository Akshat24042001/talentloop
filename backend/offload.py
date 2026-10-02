"""Run a request handler's blocking work off the server's event loop.

Most handlers are `async` only to read the JSON body, then do synchronous database work. On a remote Postgres
every query is a network round trip, and doing them on the event loop freezes every other request (other users,
live interview turns) until the handler is done. @offload reads the body on the event loop (where it has to be
read; Starlette caches it), then runs the handler in a worker thread on its own short-lived loop.

Only for handlers whose sole awaits are `req.json()` / `req.body()`: anything bound to the main loop (asyncio
locks, the shared async LLM client) must not run inside."""
import asyncio
import functools

from fastapi import Request


def offload(fn):
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        req = kwargs.get("req") or next((a for a in args if isinstance(a, Request)), None)
        if req is not None:
            await req.body()
        return await asyncio.to_thread(asyncio.run, fn(*args, **kwargs))
    return wrapper
