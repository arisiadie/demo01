from __future__ import annotations

import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings
from app.rag.store import KnowledgeStore


def main() -> None:
    if settings.resolved_chroma_path.exists():
        shutil.rmtree(settings.resolved_chroma_path)
    store = KnowledgeStore()
    print(store.quality_metrics())
    print(store.evaluate_recall())


if __name__ == "__main__":
    main()

