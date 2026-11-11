import asyncio
from pathlib import Path

from mayfly_publish.server import create_server
from mayfly_publish.settings import Settings
from mayfly_publish.storage import Storage


def test_only_transport_tools(tmp_path: Path) -> None:
    config = Settings(
        tmp_path,
        "https://example.invalid",
        "us-east-1",
        "bucket",
        "fake",
        "fake",
        "mayfly-staging/",
        "path",
        7200,
        1000,
        25,
        "INFO",
    )
    server = create_server(config, Storage(config))

    async def check() -> None:
        tools = await server.list_tools()
        assert {tool.name for tool in tools} == {"temp_publish", "revoke_object"}
        annotations = {tool.name: tool.annotations for tool in tools}
        assert annotations["temp_publish"] is not None
        assert annotations["temp_publish"].readOnlyHint is False
        assert annotations["temp_publish"].destructiveHint is False
        assert annotations["revoke_object"] is not None
        assert annotations["revoke_object"].readOnlyHint is False
        assert annotations["revoke_object"].destructiveHint is True
        assert "Never use this tool's output for captions" in next(
            tool.description for tool in tools if tool.name == "temp_publish"
        )
        result = await server.call_tool("temp_publish", {"relative_path": "../secret.jpg"})
        assert "invalid_input" in str(result)
        assert str(tmp_path) not in str(result)

    asyncio.run(check())
