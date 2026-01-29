#!/usr/bin/env python3
"""Run the Lead Enrichment API server.

Usage:
    python run_api.py [--host HOST] [--port PORT]

Examples:
    python run_api.py                    # Default: 0.0.0.0:8000
    python run_api.py --port 3001        # Custom port
    python run_api.py --host 127.0.0.1   # Localhost only
"""

import argparse
import logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Lead Enrichment API server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    import uvicorn

    from lead_enrichment.api import app

    print(f"\n{'='*50}")
    print("Lead Enrichment API Server")
    print(f"{'='*50}")
    print(f"URL: http://{args.host}:{args.port}")
    print(f"Docs: http://{args.host}:{args.port}/docs")
    print(f"{'='*50}\n")

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
