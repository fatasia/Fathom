from __future__ import annotations

import argparse
import json
import urllib.request


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310
        return json.loads(response.read())


def post_json(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return json.loads(response.read())


def main() -> None:
    parser = argparse.ArgumentParser(description="Dify-to-FATHOM contract smoke test")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    schema = get_json(f"{base}/openapi.json")
    expected_paths = {
        "/api/v1/query/ask",
        "/api/v1/semantics/overview",
        "/api/v1/semantics/assets",
    }
    missing = sorted(expected_paths - set(schema.get("paths", {})))
    if missing:
        raise SystemExit(f"OpenAPI missing Dify tool paths: {missing}")

    result = post_json(
        f"{base}/api/v1/query/ask",
        {
            "question": "为什么一号线昨天订单达成率下降？",
            "scope": {"plant": "east_plant", "line": "line_01"},
        },
    )
    checks = {
        "status": result.get("status") == "completed",
        "answer": bool(result.get("answer")),
        "abc": [stage.get("code") for stage in result["plan"]["abc"]] == ["A", "B", "C"],
        "evidence": len(result.get("evidence", [])) >= 3,
        "trace": bool(result.get("trace_id")),
    }
    if not all(checks.values()):
        raise SystemExit(f"Dify contract failed: {checks}")
    print(json.dumps({"status": "passed", "checks": checks}, ensure_ascii=False))


if __name__ == "__main__":
    main()
