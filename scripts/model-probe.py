from __future__ import annotations

import argparse
import getpass
import json
import urllib.error
import urllib.request


def request_json(url: str, api_key: str, payload: dict | None = None) -> tuple[int, dict]:
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, headers=headers, data=data)
    try:
        with urllib.request.urlopen(request, timeout=45) as response:  # noqa: S310
            return response.status, json.loads(response.read(2_000_000))
    except urllib.error.HTTPError as error:
        body = error.read(100_000).decode("utf-8", errors="replace")
        try:
            return error.code, json.loads(body)
        except json.JSONDecodeError:
            return error.code, {"error": body[:500]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely probe a FATHOM model provider")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--credential-name", default="fathom-probe")
    parser.add_argument("--store-key", action="store_true")
    args = parser.parse_args()
    api_key = getpass.getpass("API Key (input hidden): ")
    base_url = args.base_url.rstrip("/")

    results: dict[str, object] = {}
    status, models = request_json(f"{base_url}/models", api_key)
    model_ids = [item.get("id") for item in models.get("data", []) if item.get("id")]
    results["models"] = {
        "status": status,
        "count": len(model_ids),
        "target_available": args.model in model_ids,
    }

    status, chat = request_json(
        f"{base_url}/chat/completions",
        api_key,
        {
            "model": args.model,
            "messages": [{"role": "user", "content": "只回复 FATHOM_OK"}],
            "temperature": 0,
            "max_tokens": 32,
            "stream": False,
        },
    )
    chat_text = ((chat.get("choices") or [{}])[0].get("message") or {}).get("content")
    results["chat_completions"] = {"status": status, "text": chat_text}

    status, responses = request_json(
        f"{base_url}/responses",
        api_key,
        {"model": args.model, "input": "只回复 FATHOM_OK", "max_output_tokens": 32},
    )
    results["responses"] = {
        "status": status,
        "text": responses.get("output_text"),
        "has_output": bool(responses.get("output")),
    }

    if args.store_key:
        import keyring

        keyring.set_password("fathom-model-gateway", args.credential_name, api_key)
        results["credential"] = f"keyring://model/{args.credential_name}"

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
