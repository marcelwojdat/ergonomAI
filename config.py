"""Parametry aplikacji w jednym miejscu - zmieniasz tutaj, nie w kodzie."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# --- Kamera / capture ---
ESP32_URL = "http://192.168.0.11/capture"  # adres ESP32 z Serial Monitora po starcie płytki
CAPTURE_INTERVAL = 5.0                     # s między klatkami
OUT_DIR = BASE_DIR / "data"                # CSV i klatki (w .gitignore - to Twój obraz)

# --- Serwer WWW ---
HOST = "127.0.0.1"  # tylko ten komputer; "0.0.0.0" wystawiłby obraz z kamery całej sieci
PORT = 8000
UI_REFRESH_S = 3.0  # s; jak często strona odpytuje /api/state

# --- Świeżość danych ---
FRAME_STALE_AFTER = 15.0  # s; starsza klatka = "Brak obrazu"
