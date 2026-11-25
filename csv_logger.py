"""Zapis wyników do CSV: jeden wiersz na każdą próbę, także nieudaną."""

import csv
import os
from pathlib import Path

COLUMNS = [
    "timestamp", "status", "side", "neck_angle", "torso_angle",
    "vis_ear", "vis_shoulder", "vis_hip", "image_file",
]


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
