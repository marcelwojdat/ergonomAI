"""Zapis wyników do CSV: jeden wiersz na każdą próbę, także nieudaną."""

import csv
import logging
import os
from datetime import datetime
from pathlib import Path

# Nowe kolumny dopisujemy NA KOŃCU - skrypty czytające po indeksie dalej działają
COLUMNS = [
    "timestamp", "status", "side", "neck_angle", "torso_angle",
    "vis_ear", "vis_shoulder", "vis_hip", "image_file",
    "smoothed_angle", "delta", "verdict",
]

logger = logging.getLogger("ergonomai")


def _read_header(path: Path) -> list[str] | None:
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return next(csv.reader(f), None)
    except (UnicodeDecodeError, csv.Error):  # np. plik zapisany przez Excel w innym kodowaniu
        return None


def _rotate_if_schema_changed(path: Path) -> None:
    """Inny nagłówek = inny schemat. Stary plik dostaje nazwę z datą i zostaje NIETKNIĘTY
    (rotacja zamiast migracji: nigdy nie przepisujemy istniejących danych)."""
    if not path.exists() or path.stat().st_size == 0:
        return
    if _read_header(path) == COLUMNS:
        return
    archived = path.with_name(f"{path.stem}_{datetime.now():%Y%m%d_%H%M%S}{path.suffix}")
    os.replace(path, archived)
    logger.warning("Zmieniony schemat CSV - stary plik przeniesiony do %s", archived.name)


def _fmt(value) -> str:
    if value is None:
        return ""  # pusta komórka = brak pomiaru (nie 0)
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


class CsvLogger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _rotate_if_schema_changed(self.path)

        # Pusty plik też traktujemy jak nowy (np. skrypt padł, zanim zapisał nagłówek)
        needs_header = not self.path.exists() or self.path.stat().st_size == 0

        # newline="" - wymóg modułu csv; bez tego na Windows po każdym wierszu jest pusta linia
        self._file = open(self.path, "a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=COLUMNS)
        if needs_header:
            self._writer.writeheader()
            self._sync()

    def write(self, row: dict) -> None:
        self._writer.writerow({col: _fmt(row.get(col)) for col in COLUMNS})
        self._sync()

    def _sync(self) -> None:
        self._file.flush()             # bufor Pythona -> system (chroni przed Ctrl+C / crashem)
        os.fsync(self._file.fileno())  # cache systemu -> dysk (chroni przed zanikiem prądu)

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> "CsvLogger":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
