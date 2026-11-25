"""Współdzielony stan: wątek capture pisze, serwer WWW tylko czyta.

Copy-on-write: każdy zapis tworzy NOWY niezmienny Snapshot (dataclasses.replace).
Czytelnik dostaje referencję do obiektu, którego nikt już nigdy nie zmodyfikuje,
więc ma spójny widok bez kopiowania przy każdym odczycie.
"""

import threading
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Snapshot:
    # Ostatnia próba (także nieudana)
    status: str = "starting"         # ok / low_visibility / no_person / no_frame / error / starting
    timestamp: str | None = None     # ISO, czas ostatniej próby
    side: str | None = None
    neck_angle: float | None = None
    torso_angle: float | None = None
    vis_ear: float | None = None
    vis_shoulder: float | None = None
    vis_hip: float | None = None

    # Ostatnia UDANA klatka - zostaje, gdy kolejne próby to no_frame
    frame_jpeg: bytes | None = None        # z nakładką, jeśli wykryto osobę
    frame_timestamp: str | None = None     # ISO - do wyświetlenia
    frame_monotonic: float | None = None   # time.monotonic() - do liczenia wieku (odporne na NTP)

    # Klasyfikacja (pisze wątek capture)
    verdict: str = "starting"        # ok / slouching / no_baseline / calibrating / stany specjalne
    smoothed_angle: float | None = None
    delta: float | None = None
    baseline: float | None = None
    calibrating: bool = False
    calib_collected: int = 0
    calib_needed: int = 0

    # Okno kroczące (pisze wątek capture)
    win_samples: int = 0
    win_valid_pct: float | None = None    # % ważnych względem oczekiwanej liczby próbek
    win_slouch_pct: float | None = None   # % garbienia wśród ważnych; None = za mało danych
    win_enough_data: bool = False

    # Żądanie kalibracji: ustawia serwer WWW, przejmuje (kasuje) wątek capture
    calibration_requested: bool = False


class SharedState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snap = Snapshot()

    def update(self, **changes) -> None:
        """Odczyt-modyfikacja-zapis pod lockiem: dwóch piszących nie nadpisze sobie zmian."""
        with self._lock:
            self._snap = replace(self._snap, **changes)

    def snapshot(self) -> Snapshot:
        with self._lock:
            return self._snap

    def request_calibration(self) -> None:
        """Wywołuje serwer WWW. Nie dotyka klasyfikatora - tylko zostawia "bloczek z zamówieniem"."""
        self.update(calibration_requested=True)

    def consume_calibration_request(self) -> bool:
        """Wywołuje wątek capture. Sprawdź-i-skasuj pod JEDNYM lockiem: żądanie nie zginie
        ani nie wykona się dwa razy. W tym samym kroku oznaczamy start kalibracji,
        żeby UI nie zobaczył chwili "żądanie skasowane, a kalibracja jeszcze nie trwa"."""
        with self._lock:
            if not self._snap.calibration_requested:
                return False
            self._snap = replace(self._snap, calibration_requested=False,
                                 calibrating=True, calib_collected=0)
            return True
