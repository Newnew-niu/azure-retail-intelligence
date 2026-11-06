"""The data catalog: which datasets exist, and what they mean.

The catalog is also the allow-list for run_query, so a dataset cannot be queried unless it
is documented. See scripts/build_serving_catalog.py for how the file is generated.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from serving.core.errors import DatasetNotFound


@dataclass(frozen=True)
class Catalog:
    content: dict

    @classmethod
    def load(cls, path: Path) -> "Catalog":
        return cls(yaml.safe_load(path.read_text(encoding="utf-8")))

    @property
    def datasets(self) -> dict[str, dict]:
        return self.content["datasets"]

    @property
    def allowed_tables(self) -> frozenset[str]:
        return frozenset(self.datasets)

    def dataset(self, name: str) -> dict:
        key = name.lower()
        if key not in self.datasets:
            raise DatasetNotFound(f"Unknown dataset '{name}'. Call list_datasets to see what exists.")
        return {"name": key, **self.datasets[key]}
