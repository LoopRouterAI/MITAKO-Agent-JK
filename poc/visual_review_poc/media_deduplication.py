from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def deduplicate_media(paths: Iterable[Path]) -> Tuple[List[Path], Dict[str, Any]]:
    unique: List[Path] = []
    first_by_digest: Dict[str, Path] = {}
    duplicates: List[Dict[str, str]] = []
    submitted = list(paths)
    for path in submitted:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        fingerprint = digest.hexdigest()
        kept = first_by_digest.get(fingerprint)
        if kept is None:
            first_by_digest[fingerprint] = path
            unique.append(path)
        else:
            duplicates.append({"kept": kept.name, "ignored": path.name, "sha256": fingerprint})
    return unique, {
        "submitted_count": len(submitted),
        "unique_count": len(unique),
        "duplicate_count": len(duplicates),
        "duplicates": duplicates,
    }
