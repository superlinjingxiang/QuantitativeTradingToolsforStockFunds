"""Run the FastAPI backend with uvicorn."""

from __future__ import annotations

import argparse

import uvicorn


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the China Quant FastAPI backend.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    print(f"CHINA_QUANT_BACKEND_READY http://{args.host}:{args.port}", flush=True)
    uvicorn.run(
        "china_quant_platform.api.app:app",
        host=args.host,
        port=args.port,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
