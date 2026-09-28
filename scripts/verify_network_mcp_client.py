"""Run inside an isolated Docker client to probe a remote member MCP endpoint."""

from __future__ import annotations

import asyncio
import json
import os
import ssl
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main() -> None:
    assert not Path("/workspace/.git").exists(), "Client must not mount the Git repository"
    assert not Path("/run/secrets/backbone-http-tokens.json").exists(), (
        "Client must not mount the server's credential file"
    )
    token = os.environ["BACKBONE_TEST_TOKEN"]
    intent_id = os.environ["BACKBONE_TEST_INTENT_ID"]
    context = ssl.create_default_context(cafile="/certs/server.crt")
    async with httpx.AsyncClient(
        verify=context,
        trust_env=False,
        headers={"Authorization": f"Bearer {token}"},
    ) as http_client:
        async with streamable_http_client(
            "https://conductor:8000/mcp", http_client=http_client
        ) as (read, write, _session_id):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = {tool.name for tool in (await session.list_tools()).tools}
                assert tools == {
                    "get_my_task",
                    "submit_artifact",
                    "check_backbone_sync",
                    "create_intent",
                    "log_decision",
                    "start_task",
                    "rebase_task",
                }
                result = await session.call_tool(
                    "create_intent",
                    {
                        "intent_data": {
                            "id": intent_id,
                            "problem": "Verify isolated network member access",
                            "proposed_outcome": "Persist through trusted TLS and bearer auth",
                        }
                    },
                )
                assert not result.isError, result
                created = json.loads(result.content[0].text)
                assert created["id"] == intent_id and created["author"] == "alice", created


if __name__ == "__main__":
    asyncio.run(main())
    print("Isolated Docker member client completed HTTPS MCP call")
