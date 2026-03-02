from __future__ import annotations

import sqlite3
from pathlib import Path


class OwnershipDB:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ownership (
                resource TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self._conn.commit()

    def owner_of(self, resource: str) -> str | None:
        row = self._conn.execute(
            "SELECT owner FROM ownership WHERE resource = ?", (resource,)
        ).fetchone()
        if row is None:
            return None
        return str(row[0])

    def acquire(self, resource: str, owner: str) -> bool:
        current = self.owner_of(resource)
        if current is None:
            self._conn.execute(
                "INSERT INTO ownership(resource, owner) VALUES(?, ?)", (resource, owner)
            )
            self._conn.commit()
            return True
        if current == owner:
            return True
        return False

    def release(self, resource: str, owner: str) -> bool:
        current = self.owner_of(resource)
        if current != owner:
            return False
        self._conn.execute("DELETE FROM ownership WHERE resource = ?", (resource,))
        self._conn.commit()
        return True

    def release_all_by_owner(self, owner: str) -> int:
        cur = self._conn.execute("DELETE FROM ownership WHERE owner = ?", (owner,))
        self._conn.commit()
        return int(cur.rowcount)

    def close(self) -> None:
        self._conn.close()
