from __future__ import annotations

import json
from pathlib import Path

from yt_visuals.workflow.contracts import schema_documents


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    schema_dir = ROOT / "schemas"
    schema_dir.mkdir(parents=True, exist_ok=True)
    for filename, schema in schema_documents().items():
        schema["$id"] = f"https://yt-visuals.local/schemas/{filename}"
        path = schema_dir / filename
        path.write_text(
            json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
