from __future__ import annotations

import sqlite3


class ClosingSQLiteConnection(sqlite3.Connection):
    """SQLite connection whose transaction context also releases its FD."""

    def __exit__(self, exc_type, exc, traceback):
        try:
            return super().__exit__(exc_type, exc, traceback)
        finally:
            self.close()


SQLITE_CONNECTION_FACTORY = ClosingSQLiteConnection
