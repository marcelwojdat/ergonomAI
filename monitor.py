"""Pętla monitora: co N sekund klatka JPEG z ESP32 -> punkty -> kąty -> wiersz CSV + stan w pamięci.

Pętla capture działa w osobnym wątku; główny wątek tylko czeka na Ctrl+C.
Użycie:  python monitor.py http://192.168.1.50/capture [--interval 5] [--out data]
"""

import argparse
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import requests

from csv_logger import CsvLogger
from detection import BASE_DIR, create_landmarker, detect_landmarks, load_rgb_from_bytes
from features import SIDES, compute_features, to_px
from state import SharedState

REQUEST_TIMEOUT = 3        # s, osobno na połączenie i na odczyt; bez tego zawieszone WiFi = zamrożony skrypt
OVERLAY_EVERY = 10         # zapis nakładki NA DYSK co N-tą udaną detekcję (licząc od pierwszej)
FRAME_JPEG_QUALITY = 80    # jakość JPEG klatki z nakładką trzymanej w pamięci (dla WWW)

logger = logging.getLogger("ergonomai")


def fetch_frame(url: str) -> bytes | None:
    """Bajty JPEG albo None. Żaden błąd sieci nie może zatrzymać pętli."""
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
    except requests.RequestException:  # timeout, connection error, urwany transfer...
        return None
    if response.status_code != 200 or not response.content:
        return None
    return response.content


def _fmt_angle(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def draw_overlay(rgb: np.ndarray, landmarks, feats: dict) -> np.ndarray:
    """Linie ucho-bark-biodro i kąty na klatce. Zwraca obraz BGR; zapis robi wywołujący."""
    h, w = rgb.shape[:2]
    img = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    ear, shoulder, hip = (
        tuple(round(c) for c in to_px(landmarks[i], w, h)) for i in SIDES[feats["side"]]
    )
    cv2.line(img, shoulder, ear, (0, 255, 255), 2)
    cv2.line(img, hip, shoulder, (255, 0, 255), 2)
    for point in (ear, shoulder, hip):
        cv2.circle(img, point, 4, (0, 0, 255), -1)

    # Hershey to fonty ASCII - bez znaku stopnia i polskich liter
    text = f"neck {_fmt_angle(feats['neck_angle'])}  torso {_fmt_angle(feats['torso_angle'])} deg"
    font, scale = cv2.FONT_HERSHEY_SIMPLEX, 0.5
    (tw, th), baseline = cv2.getTextSize(text, font, scale, 1)
    cv2.rectangle(img, (0, 0), (tw + 10, th + baseline + 8), (0, 0, 0), -1)  # tło pod tekst
    cv2.putText(img, text, (5, th + 4), font, scale, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def _now_iso() -> tuple[datetime, str]:
    now = datetime.now().astimezone()  # czas ścienny ze strefą - do CSV i nazw plików
    return now, now.isoformat(timespec="seconds")


def sample(landmarker, url: str, out_dir: Path, overlay_due: bool) -> tuple[dict, bytes | None]:
    """Jedna próba = zawsze jeden wiersz CSV, także nieudana.

    Zwraca (wiersz, klatka JPEG do pokazania lub None). Klatka ma nakładkę, jeśli wykryto osobę.
    """
    now, now_iso = _now_iso()
    row: dict = {"timestamp": now_iso}

    data = fetch_frame(url)
    if data is None:
        row["status"] = "no_frame"
        return row, None
    try:
        rgb = load_rgb_from_bytes(data)
    except ValueError:  # 200 OK, ale w treści nie ma poprawnego JPEG
        row["status"] = "no_frame"
        return row, None

    frame_path = out_dir / "frames" / now.strftime("%Y-%m-%d") / now.strftime("%Y%m%d_%H%M%S.jpg")
    frame_path.parent.mkdir(parents=True, exist_ok=True)
    frame_path.write_bytes(data)  # oryginalne bajty - bez ponownej kompresji JPEG
    row["image_file"] = frame_path.relative_to(out_dir).as_posix()

    landmarks = detect_landmarks(landmarker, rgb)
    if landmarks is None:
        row["status"] = "no_person"
        return row, data  # bez osoby nie ma czego rysować - oryginalne bajty

    h, w = rgb.shape[:2]
    feats = compute_features(landmarks, w, h)
    row.update(feats)

    overlay = draw_overlay(rgb, landmarks, feats)  # w pamięci: KAŻDA klatka z osobą
    if overlay_due:                                 # na dysku: co N-tą, jak dotąd
        cv2.imwrite(str(frame_path.with_name(frame_path.stem + "_overlay.jpg")), overlay)
    ok, encoded = cv2.imencode(".jpg", overlay, [cv2.IMWRITE_JPEG_QUALITY, FRAME_JPEG_QUALITY])
    return row, encoded.tobytes() if ok else data


STATE_FIELDS = ("timestamp", "status", "side", "neck_angle", "torso_angle",
                "vis_ear", "vis_shoulder", "vis_hip")


def publish(state: SharedState, row: dict, frame: bytes | None) -> None:
    """Wiersz -> stan. Pola pomiaru zawsze nadpisujemy (brak = None); klatkę tylko, gdy jest nowa."""
    changes = {key: row.get(key) for key in STATE_FIELDS}
    if frame is not None:
        changes.update(frame_jpeg=frame, frame_timestamp=row["timestamp"],
                       frame_monotonic=time.monotonic())
    state.update(**changes)


def capture_loop(url: str, interval: float, out_dir: Path,
                 state: SharedState, stop: threading.Event) -> None:
    """Ciało wątku capture. Jedyne miejsce, które łączy się z ESP32. Kończy się po stop.set()."""
    detections = 0
    with create_landmarker() as landmarker, CsvLogger(out_dir / "posture_log.csv") as csv_log:
        print(f"Start: {url} co {interval} s -> {out_dir}  (Ctrl+C kończy)")
        next_tick = time.monotonic()  # zegar monotoniczny: nie skacze przy NTP / zmianie czasu

        while not stop.is_set():
            try:
                row, frame = sample(landmarker, url, out_dir,
                                    overlay_due=detections % OVERLAY_EVERY == 0)
            except Exception:  # błąd w jednej iteracji nie może zabić wątku
                logger.exception("Błąd w iteracji capture")
                row, frame = {"timestamp": _now_iso()[1], "status": "error"}, None

            try:
                csv_log.write(row)
            except OSError:  # np. pełny dysk - stan w pamięci i tak aktualizujemy
                logger.exception("Nie udało się zapisać wiersza CSV")
            publish(state, row, frame)

            if row["status"] in ("ok", "low_visibility"):
                detections += 1
            print(f"{row['timestamp'][11:19]}  {row['status']:<14} {row.get('side') or '':<6}"
                  f"neck={_fmt_angle(row.get('neck_angle')):>5}  torso={_fmt_angle(row.get('torso_angle')):>5}")

            # Harmonogram bezwzględny: takty liczone od startu, więc błąd się nie sumuje
            next_tick += interval
            delay = next_tick - time.monotonic()
            if delay > 0:
                stop.wait(delay)  # zamiast sleep: stop.set() budzi wątek natychmiast
            else:
                next_tick = time.monotonic()  # spóźnienie > interwał: nie nadrabiamy serią klatek
    # wyjście z `with` = CSV zamknięty, model zwolniony
    print("Wątek capture zakończony.")


def start_capture(url: str, interval: float, out_dir: Path,
                  state: SharedState) -> tuple[threading.Thread, threading.Event]:
    stop = threading.Event()
    thread = threading.Thread(
        target=capture_loop, args=(url, interval, out_dir, state, stop),
        name="capture",
        daemon=True,  # siatka bezpieczeństwa: gdyby wątek utknął, nie zablokuje wyjścia procesu
    )
    thread.start()
    return thread, stop


def stop_capture(thread: threading.Thread, stop: threading.Event) -> None:
    """Grzeczne zatrzymanie: sygnał + czekanie, aż wątek dokończy iterację i zamknie CSV."""
    stop.set()
    thread.join(timeout=2 * REQUEST_TIMEOUT + 5)  # najgorszy przypadek: trwające żądanie HTTP
    if thread.is_alive():
        logger.warning("Wątek capture nie zakończył się w czasie - wychodzę mimo to.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor postawy: klatka z ESP32 co N s -> CSV.")
    parser.add_argument("url", help="adres JPEG z kamery, np. http://192.168.1.50/capture")
    parser.add_argument("--interval", type=float, default=5.0, help="odstęp między klatkami [s]")
    parser.add_argument("--out", type=Path, default=BASE_DIR / "data", help="folder na CSV i klatki")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(threadName)s: %(message)s")
    state = SharedState()
    thread, stop = start_capture(args.url, args.interval, args.out, state)
    try:
        # KeyboardInterrupt trafia tylko do głównego wątku. join() bez timeoutu na Windows
        # nie jest przerywalny przez Ctrl+C, więc czekamy krótkimi odcinkami.
        while thread.is_alive():
            thread.join(0.5)
    except KeyboardInterrupt:
        print("\nZatrzymywanie...")
    finally:
        stop_capture(thread, stop)


if __name__ == "__main__":
    main()
