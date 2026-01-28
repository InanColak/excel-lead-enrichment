"""Entry point: python -m lead_enrichment"""

import asyncio
import logging
import sys
from pathlib import Path

from .config import Settings
from .orchestrator import EnrichmentService


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)

    if len(sys.argv) < 2:
        print("Usage: python -m lead_enrichment <command> [args]")
        print()
        print("Commands:")
        print("  enrich <input.xlsx> <output.xlsx>  Run full enrichment pipeline")
        print("  status                             Show enrichment progress")
        print("  export <input.xlsx> <output.xlsx>  Export current state to Excel")
        sys.exit(1)

    command = sys.argv[1]

    try:
        settings = Settings()  # type: ignore[call-arg]
    except Exception as exc:
        logger.error("Configuration error: %s", exc)
        logger.error("Make sure .env file exists with required keys. See .env.example")
        sys.exit(1)

    service = EnrichmentService(settings)

    try:
        if command == "enrich":
            if len(sys.argv) < 4:
                print("Usage: python -m lead_enrichment enrich <input.xlsx> <output.xlsx>")
                sys.exit(1)
            input_path = Path(sys.argv[2])
            output_path = Path(sys.argv[3])
            result = asyncio.run(service.run_full_pipeline(input_path, output_path))
            print(f"\nEnrichment complete. Output: {result.get('output_file')}")

        elif command == "status":
            summary = service.get_status()
            total = summary["total_rows"]
            print(f"Total rows: {total}")
            print(f"Lusha:  {summary['lusha']['complete']}/{total} complete, "
                  f"{summary['lusha']['error']} errors")
            print(f"Apollo: {summary['apollo']['complete']}/{total} complete, "
                  f"{summary['apollo']['awaiting_webhook']} awaiting webhook, "
                  f"{summary['apollo']['timeout']} timeout, "
                  f"{summary['apollo']['error']} errors")

        elif command == "export":
            if len(sys.argv) < 4:
                print("Usage: python -m lead_enrichment export <input.xlsx> <output.xlsx>")
                sys.exit(1)
            input_path = Path(sys.argv[2])
            output_path = Path(sys.argv[3])
            service.export_excel(input_path, output_path)
            print(f"Exported to {output_path}")

        else:
            print(f"Unknown command: {command}")
            sys.exit(1)

    finally:
        service.close()


if __name__ == "__main__":
    main()
