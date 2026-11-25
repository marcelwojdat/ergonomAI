"""Parametry aplikacji w jednym miejscu - zmieniasz tutaj, nie w kodzie.

Moduły czytają je jako `config.NAZWA` w chwili użycia (nie `from config import NAZWA`),
więc zmiana wartości w trakcie działania - np. w teście - jest widoczna wszędzie.
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# --- Kamera / capture ---
ESP32_URL = "http://192.168.0.11/capture"  # adres ESP32 z Serial Monitora po starcie płytki
CAPTURE_INTERVAL = 5.0                     # s między klatkami
REQUEST_TIMEOUT = 3.0                      # s, osobno na połączenie i odczyt HTTP; bez tego zawieszone WiFi = zamrożona pętla
OUT_DIR = BASE_DIR / "data"                # CSV i klatki (w .gitignore - to Twój obraz)
OVERLAY_EVERY = 10                         # zapis nakładki NA DYSK co N-tą udaną detekcję (licząc od pierwszej)
FRAME_JPEG_QUALITY = 80                    # jakość JPEG klatki z nakładką trzymanej w pamięci (dla WWW)

# --- Model i punkty ciała ---
MODEL_PATH = BASE_DIR / "pose_landmarker_lite.task"
MIN_VIS = 0.6            # próg wiarygodności punktu (visibility) - poniżej: kąt pusty, nie 0
SIDE_TIE_MARGIN = 0.05   # różnica sum visibility L/P poniżej tego = remis, rozstrzyga głębia z barków

# --- Serwer WWW ---
HOST = "127.0.0.1"  # tylko ten komputer; "0.0.0.0" wystawiłby obraz z kamery całej sieci
PORT = 8000
UI_REFRESH_S = 3.0  # s; jak często strona odpytuje /api/state

# --- Klasyfikacja postawy ---
CALIBRATION_SAMPLES = 6       # ważnych pomiarów do baseline (6 x 5 s = 30 s)
SMOOTHING_WINDOW = 3          # mediana z tylu ostatnich ważnych pomiarów kąta szyi
SLOUCH_ENTER_DELTA = 12.0     # ° ponad baseline: OK -> GARBIENIE
SLOUCH_EXIT_DELTA = 8.0       # ° ponad baseline: GARBIENIE -> OK (martwa strefa 8-12° tłumi szum)
BASELINE_FILE = BASE_DIR / "baseline.json"  # w .gitignore - Twoja osobista kalibracja

# --- Statystyki okna ---
WINDOW_S = 300.0         # s; okno kroczące statystyk (5 min)
WINDOW_MIN_VALID = 0.5   # poniżej tego odsetka ważnych próbek (względem oczekiwanej liczby) -> "za mało danych"

# --- Świeżość danych ---
FRAME_STALE_AFTER = 15.0  # s; starsza klatka = "Brak obrazu"
