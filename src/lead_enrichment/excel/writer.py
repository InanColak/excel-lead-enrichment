"""Excel writer that adds enrichment columns to the original file."""

from __future__ import annotations

import logging
from pathlib import Path

import openpyxl

from ..db.repository import Repository

logger = logging.getLogger(__name__)

# Output column names in the order they will be appended
OUTPUT_COLUMNS = [
    "apollo_email",
    "apollo_handynummer",
    "apollo_festnetz_durchwahl",
    "lusha_email",
    "lusha_handynummer",
    "lusha_festnetz_durchwahl",
]


def write_enriched_excel(
    input_path: Path,
    output_path: Path,
    repo: Repository,
) -> Path:
    """Open the original Excel, append enrichment columns, save to output_path.

    Preserves all original data and formatting. Returns the output path.
    """
    wb = openpyxl.load_workbook(input_path)
    ws = wb.active
    if ws is None:
        raise ValueError(f"No active worksheet in {input_path}")

    last_col = ws.max_column

    # Write new column headers in row 1
    for offset, col_name in enumerate(OUTPUT_COLUMNS):
        ws.cell(row=1, column=last_col + 1 + offset, value=col_name)

    # Fetch all enriched rows from DB
    all_rows = repo.get_all_rows()

    for row in all_rows:
        excel_row = row.row_id + 1  # row_id is 1-indexed data row, Excel row 1 is headers
        base_col = last_col + 1

        ws.cell(row=excel_row, column=base_col + 0, value=row.apollo_email)
        ws.cell(row=excel_row, column=base_col + 1, value=row.apollo_mobile)
        ws.cell(row=excel_row, column=base_col + 2, value=row.apollo_direct)
        ws.cell(row=excel_row, column=base_col + 3, value=row.lusha_email)
        ws.cell(row=excel_row, column=base_col + 4, value=row.lusha_mobile)
        ws.cell(row=excel_row, column=base_col + 5, value=row.lusha_direct)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    wb.close()

    logger.info("Enriched Excel written to %s (%d rows)", output_path, len(all_rows))
    return output_path
