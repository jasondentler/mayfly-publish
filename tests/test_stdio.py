import asyncio
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def test_stdio_launch_and_safe_error(isolated_mcp_launcher: tuple[Path, Path, dict[str, str]]) -> None:
    launcher, files, env = isolated_mcp_launcher
    (files / "payload").write_bytes(b"anything")
    params = StdioServerParameters(command=str(launcher), env=env, cwd=launcher.parents[1])

    async def check() -> None:
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {tool.name for tool in tools.tools} == {"temp_publish", "revoke_object"}
                result = await session.call_tool("temp_publish", {"relative_path": "../secret.jpg"})
                assert "invalid_input" in str(result)

    asyncio.run(asyncio.wait_for(check(), 15))
