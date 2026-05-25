"""Async HTTP client for the uav_api server.

A single aiohttp.ClientSession is created at startup via `init(base_url)` and
closed at shutdown via `close()`. All MCP tools in `mcp_app.py` use `get` and
`post` to call uav_api endpoints.

Non-2xx responses raise `RuntimeError(<detail>)`, where `<detail>` is the
`detail` field from uav_api's FastAPI HTTPException response body.
"""

from typing import Any, Optional

import aiohttp

_session: Optional[aiohttp.ClientSession] = None
_base_url: Optional[str] = None


async def init(base_url: str) -> None:
    global _session, _base_url
    _base_url = base_url.rstrip("/")
    _session = aiohttp.ClientSession()


async def close() -> None:
    global _session
    if _session is not None:
        await _session.close()
        _session = None


def _url(path: str) -> str:
    if _base_url is None:
        raise RuntimeError("uav_api_client.init() has not been called")
    return f"{_base_url}{path}"


async def get(path: str, params: Optional[dict] = None) -> dict[str, Any]:
    async with _session.get(_url(path), params=params) as resp:
        body = await resp.json()
        if resp.status >= 400:
            raise RuntimeError(body.get("detail", str(body)) if isinstance(body, dict) else str(body))
        return body


async def post(path: str, json_body: dict) -> dict[str, Any]:
    async with _session.post(_url(path), json=json_body) as resp:
        body = await resp.json()
        if resp.status >= 400:
            raise RuntimeError(body.get("detail", str(body)) if isinstance(body, dict) else str(body))
        return body
