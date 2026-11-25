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
