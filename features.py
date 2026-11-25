"""Moduł cech: z 33 punktów MediaPipe liczy kąty szyi i tułowia od pionu.

Kontrakt: wejście = 33 punkty + szerokość i wysokość obrazu w px, wyjście = słownik wartości.
"""

import math
from collections.abc import Sequence
from typing import Protocol

from detection import BARK_L, BARK_P, BIODRO_L, BIODRO_P, NOS, UCHO_L, UCHO_P

MIN_VIS = 0.6           # próg wiarygodności pojedynczego punktu
SIDE_TIE_MARGIN = 0.05  # różnica sum visibility poniżej tego = remis, rozstrzyga z

# (ucho, bark, biodro) dla każdej strony OSOBY
SIDES: dict[str, tuple[int, int, int]] = {
    "left": (UCHO_L, BARK_L, BIODRO_L),
    "right": (UCHO_P, BARK_P, BIODRO_P),
}


class Landmark(Protocol):
    x: float
    y: float
    z: float
    visibility: float


def to_px(lm: Landmark, width: int, height: int) -> tuple[float, float]:
    """Denormalizacja. x jest względem szerokości, y względem wysokości - kąty liczymy dopiero w px."""
    return lm.x * width, lm.y * height


def choose_side(landmarks: Sequence[Landmark]) -> str:
    """Strona bliższa kamerze.

    Kryterium główne: suma visibility ucha i barku. Z profilu MediaPipe daje jednak obu stronom
    ~0.98 (zasłonięta strona jest dopowiadana), więc przy remisie rozstrzyga z barków:
    bezwzględna głębia to szum, ale znak różnicy L-P jest stabilny. Mniejsze z = bliżej kamery.
    """
    vis_left = landmarks[UCHO_L].visibility + landmarks[BARK_L].visibility
    vis_right = landmarks[UCHO_P].visibility + landmarks[BARK_P].visibility

    if abs(vis_left - vis_right) >= SIDE_TIE_MARGIN:
        return "left" if vis_left > vis_right else "right"
    return "left" if landmarks[BARK_L].z < landmarks[BARK_P].z else "right"


def _angle_from_vertical(bottom: tuple[float, float], top: tuple[float, float], facing: int) -> float:
    """Kąt odcinka bottom->top od pionu w stopniach. 0 = top idealnie nad bottom, + = do przodu."""
    dx = (top[0] - bottom[0]) * facing
    dy = top[1] - bottom[1]
    return math.degrees(math.atan2(dx, -dy))  # oś Y obrazu rośnie w dół, więc "góra" to -dy


def compute_features(landmarks: Sequence[Landmark], width: int, height: int) -> dict:
    side = choose_side(landmarks)
    ear_i, shoulder_i, hip_i = SIDES[side]
    ear, shoulder, hip = landmarks[ear_i], landmarks[shoulder_i], landmarks[hip_i]

    ear_px = to_px(ear, width, height)
    shoulder_px = to_px(shoulder, width, height)
    hip_px = to_px(hip, width, height)

    # Nos na prawo od ucha = patrzy w prawo, wtedy dodatnie dx to "do przodu". Inaczej odwracamy znak.
    facing = 1 if landmarks[NOS].x > ear.x else -1

    neck_ok = ear.visibility >= MIN_VIS and shoulder.visibility >= MIN_VIS
    torso_ok = shoulder.visibility >= MIN_VIS and hip.visibility >= MIN_VIS

    return {
        "status": "ok" if neck_ok else "low_visibility",
        "side": side,
        # None, nie 0 - zero to fałszywa informacja "idealnie prosto"
        "neck_angle": _angle_from_vertical(shoulder_px, ear_px, facing) if neck_ok else None,
        "torso_angle": _angle_from_vertical(hip_px, shoulder_px, facing) if torso_ok else None,
        "vis_ear": ear.visibility,
        "vis_shoulder": shoulder.visibility,
        "vis_hip": hip.visibility,
    }
