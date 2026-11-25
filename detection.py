"""Moduł pose: wykrywanie punktów ciała (MediaPipe Tasks API, tryb IMAGE)."""

from pathlib import Path
from typing import NamedTuple

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

import config

# Indeksy w 33-elementowej liście MediaPipe Pose.
# L/P = lewa/prawa strona OSOBY, nie obrazu (na zdjęciu en face są odwrócone).
NOS = 0
UCHO_L, UCHO_P = 7, 8
BARK_L, BARK_P = 11, 12
BIODRO_L, BIODRO_P = 23, 24

KEY_POINTS: dict[str, int] = {
    "nos": NOS,
    "ucho_L": UCHO_L,
    "ucho_P": UCHO_P,
    "bark_L": BARK_L,
    "bark_P": BARK_P,
    "biodro_L": BIODRO_L,
    "biodro_P": BIODRO_P,
}


class Point(NamedTuple):
    x: float           # względem szerokości obrazu; zwykle 0-1, poza kadrem może wyjść poza zakres
    y: float           # względem wysokości obrazu (0 = góra)
    visibility: float  # 0-1, pewność, że punkt jest widoczny
    # z (głębia) celowo pomijamy - to szum przy jednej kamerze


def create_landmarker(model_path: Path | None = None) -> vision.PoseLandmarker:
    """Tworzy landmarker. Wywołuj RAZ, przed pętlą - ładowanie modelu jest droższe niż inferencja."""
    # None + rozwiązanie w środku: domyślny argument `= config.MODEL_PATH` liczyłby się raz, przy definicji
    model_path = model_path or config.MODEL_PATH
    options = vision.PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(model_path)),
        running_mode=vision.RunningMode.IMAGE,  # każda klatka niezależna
        num_poses=1,
    )
    return vision.PoseLandmarker.create_from_options(options)


def load_rgb_from_file(path: Path) -> np.ndarray:
    bgr = cv2.imread(str(path))
    if bgr is None:  # imread nie rzuca wyjątku przy błędzie, tylko zwraca None
        raise FileNotFoundError(f"Nie można wczytać obrazu: {path}")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def load_rgb_from_bytes(data: bytes) -> np.ndarray:
    """Dla bajtów z HTTP (np. upload JPEG z kamery)."""
    buf = np.frombuffer(data, dtype=np.uint8)
    bgr = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("Bajty nie są poprawnym obrazem (JPEG/PNG).")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def detect_landmarks(landmarker: vision.PoseLandmarker, rgb: np.ndarray) -> list | None:
    """Zwraca 33 punkty pierwszej osoby albo None, gdy nie wykryto osoby (osobny stan, nie błąd)."""
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    result = landmarker.detect(mp_image)

    if not result.pose_landmarks:
        return None
    return result.pose_landmarks[0]  # pierwsza (jedyna) osoba


def detect_keypoints(landmarker: vision.PoseLandmarker, rgb: np.ndarray) -> dict[str, Point] | None:
    """Tylko 7 kluczowych punktów - do podglądu w main()."""
    landmarks = detect_landmarks(landmarker, rgb)
    if landmarks is None:
        return None
    return {
        name: Point(landmarks[i].x, landmarks[i].y, landmarks[i].visibility)
        for name, i in KEY_POINTS.items()
    }


def main() -> None:
    photos = [config.BASE_DIR / "surowka" / "prosto.jpg", config.BASE_DIR / "surowka" / "garb.jpg"]

    with create_landmarker() as landmarker:  # model ładowany raz dla wszystkich zdjęć
        for photo in photos:
            rgb = load_rgb_from_file(photo)
            points = detect_keypoints(landmarker, rgb)

            print(f"\n=== {photo.name} ({rgb.shape[1]}x{rgb.shape[0]} px) ===")
            if points is None:
                print("Nie wykryto osoby.")
                continue

            print(f"{'punkt':<10}{'x':>8}{'y':>8}{'vis':>8}")
            for name, p in points.items():
                print(f"{name:<10}{p.x:>8.3f}{p.y:>8.3f}{p.visibility:>8.3f}")


if __name__ == "__main__":
    main()
