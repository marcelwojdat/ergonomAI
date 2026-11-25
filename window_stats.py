"""Statystyki kroczącego okna (domyślnie 5 min): % czasu w garbieniu i odsetek ważnych próbek.

Jak klasyfikator: instancję posiada tylko wątek capture, więc klasa nie potrzebuje locka.
Czas podaje wywołujący (time.monotonic()) - dzięki temu test może podać własne znaczniki.
"""

from collections import deque
from dataclasses import dataclass

VALID_VERDICTS = {"ok", "slouching"}  # próbki z oceną postawy (bez kalibracji, bez baseline, bez stanów specjalnych)


@dataclass(frozen=True)
class WindowStats:
    samples: int              # wszystkie próby w oknie, także nieudane
    valid: int                # z werdyktem ok / slouching
    slouching: int
    valid_pct: float          # valid / OCZEKIWANA liczba próbek w oknie
    slouch_pct: float | None  # slouching / valid; None = za mało danych
    enough_data: bool


class RollingWindow:
    def __init__(self, window_s: float, interval_s: float, min_valid_ratio: float) -> None:
        self._window_s = window_s
        self._expected = window_s / interval_s  # np. 300 s / 5 s = 60 próbek
        self._min_valid_ratio = min_valid_ratio
        self._entries: deque[tuple[float, str]] = deque()  # (czas monotoniczny, werdykt), od najstarszego

    def add(self, t: float, verdict: str) -> WindowStats:
        self._entries.append((t, verdict))
        return self.stats(t)

    def stats(self, now: float) -> WindowStats:
        # Wpisy są chronologiczne, więc wystarczy zdejmować z początku, dopóki wypadają poza okno
        while self._entries and self._entries[0][0] <= now - self._window_s:
            self._entries.popleft()

        valid = sum(1 for _, v in self._entries if v in VALID_VERDICTS)
        slouching = sum(1 for _, v in self._entries if v == "slouching")

        # Mianownik = oczekiwana liczba próbek (max z zebraną na wypadek drobnego jittera taktowania).
        # Zebrana liczba kłamałaby po starcie: 2 próbki to 3% okna, a nie "100% ważnych".
        valid_ratio = valid / max(self._expected, len(self._entries))
        enough = valid_ratio >= self._min_valid_ratio
        return WindowStats(
            samples=len(self._entries),
            valid=valid,
            slouching=slouching,
            valid_pct=100 * valid_ratio,
            slouch_pct=100 * slouching / valid if enough else None,
            enough_data=enough,
        )
