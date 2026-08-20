from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="fathom", description="渊渟 FATHOM runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve", help="Start the FATHOM Web server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8000, type=int)
    subparsers.add_parser("init", help="Create the local data directory")
    token = subparsers.add_parser("token-hash", help="Hash an API token for configuration")
    token.add_argument("token")
    args = parser.parse_args()

    if args.command == "init":
        Path("data").mkdir(exist_ok=True)
        print("FATHOM Lite initialized: data/")
        return

    if args.command == "token-hash":
        from fathom.application.security import token_hash

        print(token_hash(args.token))
        return

    import uvicorn

    uvicorn.run("fathom.main:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
