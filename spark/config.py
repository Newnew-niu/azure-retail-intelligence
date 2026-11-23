"""Where the lakehouse lives: one base path, local folder or Fabric OneLake.

    LAKEHOUSE_BASE_PATH=lakehouse/full                                   # local folder
    LAKEHOUSE_BASE_PATH=abfss://<workspace>@onelake.dfs.fabric.microsoft.com/<lakehouse>.Lakehouse/Tables

Every Delta table is stored at <base path>/<layer>_<entity>, for example bronze_orders or
gold_fact_orders. Flat names (no sub-folders) are what a Fabric Lakehouse shows as tables
when the folder is its Tables/ area. The code only ever builds paths from this setting, so
the same functions run on a laptop, in CI and in a Fabric notebook.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASE_PATH = "lakehouse/full"
SOURCE_SCHEMA = Path(__file__).resolve().parents[1] / "config" / "source_schema.yml"


@dataclass(frozen=True)
class LakehouseConfig:
    base_path: str

    @classmethod
    def from_env(cls, base_path: str | None = None) -> "LakehouseConfig":
        return cls.create(base_path or os.environ.get("LAKEHOUSE_BASE_PATH", DEFAULT_BASE_PATH))

    @classmethod
    def create(cls, base_path: str) -> "LakehouseConfig":
        # A local folder is made absolute so Spark does not resolve it against its own
        # working directory; a URL such as abfss://... is used exactly as given.
        if "://" not in base_path:
            base_path = Path(base_path).resolve().as_posix()
        return cls(base_path.rstrip("/"))

    def table(self, layer: str, entity: str) -> str:
        return f"{self.base_path}/{layer}_{entity}"
