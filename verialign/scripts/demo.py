"""Run an offline demo of verified, warned, and blocked chat completions."""

import argparse
import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx

DOC = "VeriAlign is a verification support proxy for LLM outputs."


async def run(db_path: Path) -> None:
    from verialign.proxy import config

    with patch.dict(os.environ, {}, clear=True):
        settings = config.Settings(_env_file=None, db_path=str(db_path), use_nli=False)
        with patch.object(config, "get_settings", new=lambda: settings):
            from verialign.proxy import main as proxy

            with (
                patch.object(proxy, "get_settings", new=lambda: settings),
                patch.object(proxy, "configure_logging", new=lambda: None),
            ):
                async with proxy.app.router.lifespan_context(proxy.app):
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=proxy.app), base_url="http://demo"
                    ) as client:
                        await run_cases(client)


async def run_cases(client: httpx.AsyncClient) -> None:
    cases = [
        ("With evidence", [{"id": "doc-1", "text": DOC}], "pass-through", 200),
        ("Low trust warning", [], "warn", 200),
        ("Low trust block", [], "block", 422),
    ]
    for name, context, action, expected_status in cases:
        response = await client.post(
            "/v1/chat/completions",
            headers={"X-VeriAlign-Policy": action},
            json={
                "model": "demo",
                "messages": [{"role": "user", "content": "Summarize the project."}],
                "metadata": {"context": context},
            },
        )
        overlay = response.json()["verification"]
        if response.status_code != expected_status or overlay["policy_action"] != action:
            raise RuntimeError(f"Unexpected result for {name}")
        print(
            f"{name} | HTTP {response.status_code} | trust {overlay['trust_score']:.2f} | {action}"
        )
        for claim in overlay["claims"]:
            print(f"  {claim['label']}: {claim['text']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, help="Append the demo traces to a SQLite file")
    args = parser.parse_args()
    if args.db:
        asyncio.run(run(args.db))
        print(f"Trace console: verialign tui --db {str(args.db)!r}")
    else:
        with TemporaryDirectory(prefix="verialign-demo-") as tmp:
            asyncio.run(run(Path(tmp) / "traces.sqlite3"))


if __name__ == "__main__":
    main()
