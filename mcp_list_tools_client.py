"""Minimal MCP client: connect and list available tools.

Run from the repository root (with the server already running):
    uv run --with mcp mcp-server-demo/mcp_list_tools_client.py
"""

import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main() -> None:
    url = "http://127.0.0.1:8000/mcp"

    async with streamable_http_client(url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()

    print("Tools:")
    for tool in tools.tools:
        print(f"- {tool.name}")


if __name__ == "__main__":
    asyncio.run(main())

