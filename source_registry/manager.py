from __future__ import annotations

from pathlib import Path

from .registry_loader import (
    DEFAULT_REGISTRY_PATH,
    DEFAULT_SCHEMA_DIR,
    load_registry,
)
from .state_db import DEFAULT_STATE_DB, SyncSummary, sync_registry_state


class RegistryManager:
    def __init__(
        self,
        registry_path: str | Path = DEFAULT_REGISTRY_PATH,
        state_db_path: str | Path = DEFAULT_STATE_DB,
        schema_dir: str | Path = DEFAULT_SCHEMA_DIR,
    ) -> None:
        self._registry_path = Path(registry_path)
        self._state_db_path = Path(state_db_path)
        self._schema_dir = Path(schema_dir)

    def sync(self) -> SyncSummary:
        registry = load_registry(
            registry_path=self._registry_path,
            schema_dir=self._schema_dir,
        )
        return sync_registry_state(
            registry=registry,
            db_path=self._state_db_path,
        )
