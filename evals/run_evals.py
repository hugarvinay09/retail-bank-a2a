import argparse
import asyncio
import json
from pathlib import Path

import httpx


async def run(base_url: str) -> int:
    failures = 0
    headers = {
        "X-Customer-ID": "cust-001",
        "X-Accounts": "acct-001",
        "X-Scopes": "assistant:use accounts:read payments:create payments:approve",
    }
    contents = await asyncio.to_thread(Path("evals/cases.jsonl").read_text)
    cases = [json.loads(line) for line in contents.splitlines()]
    async with httpx.AsyncClient(base_url=base_url, timeout=60) as client:
        for case in cases:
            response = await client.post(
                "/v1/chat", json={"message": case["message"]}, headers=headers
            )
            response.raise_for_status()
            result = response.json()
            checks = [result["intent"] == case["expected_intent"]]
            if case.get("requires_citation"):
                checks.append(bool(result["citations"]))
            if case.get("requires_approval"):
                checks.append(result["requires_human_approval"] is True)
            if case.get("expected_warning"):
                checks.append(case["expected_warning"] in result["warnings"])
            answer = result["answer"].lower()
            checks.extend(value.lower() in answer for value in case.get("must_contain", []))
            checks.extend(value.lower() not in answer for value in case.get("must_not_contain", []))
            passed = all(checks)
            print(json.dumps({"case": case["id"], "passed": passed}))
            failures += 0 if passed else 1
    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8080")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.base_url)))
