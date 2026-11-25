"""Klasyfikator postawy: kalibracja, wygładzanie medianą, histereza. Czysta logika - bez wątków i sieci.

Instancję posiada WYŁĄCZNIE wątek capture (jeden właściciel), więc klasa nie potrzebuje locka.
Inne wątki komunikują się z nim przez SharedState (np. żądanie kalibracji), nigdy bezpośrednio.
"""

import json
import logging
import os
import statistics
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import config

logger = logging.getLogger("ergonomai")


@dataclass(frozen=True)
class ClassifierResult:
    # ok / slouching / no_baseline / calibrating / no_person / no_frame / low_visibility / error
    verdict: str
    smoothed_angle: float | None  # None, gdy bieżący pomiar nieważny - nie przepisujemy starych danych
    delta: float | None           # smoothed_angle - baseline
    baseline: float | None
    calibrating: bool
    calib_collected: int
    calib_needed: int
    # Ustawione tylko w iteracji, w której kalibracja się zakończyła - sygnał "zapisz na dysk"
    new_baseline: float | None = None
    calibration_samples: tuple[float, ...] = ()


class PostureClassifier:
    def __init__(self, baseline: float | None, *, calib_needed: int, window: int,
                 enter_delta: float, exit_delta: float) -> None:
        if exit_delta >= enter_delta:
            raise ValueError("Histereza wymaga progu wyjścia niższego niż próg wejścia")
        self.baseline = baseline
        self._calib_needed = calib_needed
        self._enter = enter_delta
        self._exit = exit_delta
        self._recent: deque[float] = deque(maxlen=window)  # ostatnie WAŻNE kąty szyi
        self._slouching = False                             # stan histerezy
        self._calib: list[float] | None = None              # None = brak trwającej kalibracji

    @classmethod
    def from_config(cls, baseline: float | None) -> "PostureClassifier":
        return cls(baseline,
                   calib_needed=config.CALIBRATION_SAMPLES, window=config.SMOOTHING_WINDOW,
                   enter_delta=config.SLOUCH_ENTER_DELTA, exit_delta=config.SLOUCH_EXIT_DELTA)

    def start_calibration(self) -> None:
        """Kolejne N ważnych pomiarów posłuży jako baseline. Ponowne wywołanie zaczyna od zera."""
        self._calib = []

    def update(self, status: str, neck_angle: float | None) -> ClassifierResult:
        valid = status == "ok" and neck_angle is not None
        new_baseline = None
        samples: tuple[float, ...] = ()

        if valid:
            self._recent.append(neck_angle)
            if self._calib is not None:
                self._calib.append(neck_angle)
                if len(self._calib) >= self._calib_needed:
                    samples = tuple(self._calib)
                    new_baseline = statistics.median(samples)  # mediana: odporna na pojedyncze wychylenia
                    self.baseline = new_baseline
                    self._calib = None
                    self._slouching = False  # nowy punkt odniesienia - stary stan histerezy nic nie znaczy

        # median_low, nie median: przy niepełnym buforze (2 próbki po starcie) median uśrednia,
        # więc jeden skok [10, 50] dałby 30. median_low zwraca rzeczywistą próbkę (10).
        # Przy pełnym, nieparzystym oknie wynik jest identyczny jak median.
        smoothed = statistics.median_low(self._recent) if valid else None
        delta = smoothed - self.baseline if smoothed is not None and self.baseline is not None else None

        # Histereza zmienia stan tylko przy WAŻNYM pomiarze, znanym baseline i poza kalibracją.
        # Stany specjalne (no_person, no_frame, low_visibility, error) jej nie dotykają.
        if delta is not None and self._calib is None:
            if not self._slouching and delta > self._enter:
                self._slouching = True
            elif self._slouching and delta < self._exit:
                self._slouching = False

        return ClassifierResult(
            verdict=self._verdict(status, valid),
            smoothed_angle=smoothed,
            delta=delta,
            baseline=self.baseline,
            calibrating=self._calib is not None,
            calib_collected=len(self._calib) if self._calib is not None else 0,
            calib_needed=self._calib_needed,
            new_baseline=new_baseline,
            calibration_samples=samples,
        )

    def _verdict(self, status: str, valid: bool) -> str:
        if self._calib is not None:
            return "calibrating"
        if not valid:
            return status  # stan specjalny przechodzi wprost do werdyktu
        if self.baseline is None:
            return "no_baseline"
        return "slouching" if self._slouching else "ok"


def load_baseline(path: Path) -> float | None:
    """Baseline z pliku albo None (brak pliku / uszkodzony plik = start bez kalibracji)."""
    try:
        return float(json.loads(path.read_text(encoding="utf-8"))["neck_baseline"])
    except FileNotFoundError:
        return None
    except (ValueError, KeyError, TypeError) as exc:  # JSONDecodeError dziedziczy po ValueError
        logger.warning("Uszkodzony %s (%s) - start bez kalibracji", path.name, exc)
        return None


def save_baseline(path: Path, baseline: float, samples: tuple[float, ...]) -> None:
    """Zapis atomowy: plik tymczasowy + fsync + os.replace. Plik jest albo stary, albo nowy - nigdy ucięty."""
    payload = {
        "neck_baseline": round(baseline, 2),
        "samples": [round(s, 2) for s in samples],
        "calibrated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)  # atomowa podmiana; na Windows nadpisuje istniejący plik (os.rename by nie umiał)
