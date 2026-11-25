"""Serwer WWW: serwuje dane wyłącznie ze stanu w pamięci. Z ESP32 łączy się tylko wątek capture.

Użycie:  python server.py [URL_ESP32]     (domyślny URL oraz host/port w config.py)
"""

import argparse
import logging
import time
from dataclasses import fields

from flask import Flask, Response, jsonify, render_template, request

import config
from monitor import start_capture, stop_capture
from state import SharedState, Snapshot

# Nie wysyłamy w JSON: bajtów obrazu (osobny endpoint) i surowego zegara monotonicznego
_HIDDEN_FIELDS = {"frame_jpeg", "frame_monotonic"}


def snapshot_to_json(snap: Snapshot) -> dict:
    data = {f.name: getattr(snap, f.name) for f in fields(snap) if f.name not in _HIDDEN_FIELDS}

    # Wiek klatki liczony przy KAŻDYM odczycie: zawieszony wątek capture nie zaktualizuje stanu,
    # więc nie może sam zgłosić, że jego dane są stare.
    age = None if snap.frame_monotonic is None else time.monotonic() - snap.frame_monotonic
    data["has_frame"] = snap.frame_jpeg is not None
    data["frame_age_s"] = None if age is None else round(age, 1)
    data["frame_stale"] = age is None or age > config.FRAME_STALE_AFTER

    # Werdykt efektywny - z tego samego powodu liczony przy odczycie, a nie przez wątek capture
    if data["has_frame"] and data["frame_stale"]:
        data["verdict"] = "no_frame"        # klatka za stara (np. zawieszony wątek / ESP32)
    elif snap.calibration_requested or snap.calibrating:
        data["verdict"] = "calibrating"     # od kliknięcia, nie dopiero od pierwszej próbki
    return data


def _window_label(seconds: float) -> str:
    """300 -> "5 min", 90 -> "90 s" (bez "1.5 min" czy "0.333333 min")."""
    return f"{seconds / 60:g} min" if seconds % 60 == 0 else f"{seconds:g} s"


def create_app(state: SharedState) -> Flask:
    app = Flask(__name__)

    @app.after_request
    def no_store(response: Response) -> Response:
        response.headers["Cache-Control"] = "no-store"  # dane na żywo - przeglądarka ma ich nie trzymać
        return response

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            refresh_ms=int(config.UI_REFRESH_S * 1000),
            calib_seconds=round(config.CALIBRATION_SAMPLES * config.CAPTURE_INTERVAL),
            window_label=_window_label(config.WINDOW_S),
        )

    @app.get("/api/state")
    def api_state():
        return jsonify(snapshot_to_json(state.snapshot()))

    @app.post("/api/calibrate")
    def api_calibrate():
        # Wymagamy JSON: obca strona otwarta w przeglądarce może wysłać "prosty" POST (formularz,
        # text/plain) na 127.0.0.1 bez pytania. application/json wymusza preflight CORS,
        # na który nie odpowiadamy zgodą - przeglądarka zablokuje takie żądanie (ochrona przed CSRF).
        if not request.is_json:
            return jsonify(error="Wymagany Content-Type: application/json"), 415
        state.request_calibration()  # tylko "bloczek z zamówieniem" - klasyfikatora dotyka wątek capture
        return jsonify(calibration_requested=True), 202  # przyjęte, wykona inny wątek

    @app.get("/frame.jpg")
    def frame():
        jpeg = state.snapshot().frame_jpeg
        if jpeg is None:  # jeszcze żadna klatka nie dotarła - "chwilowo niedostępne", nie "nie istnieje"
            return Response("Brak klatki", status=503, mimetype="text/plain")
        return Response(jpeg, mimetype="image/jpeg")

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor postawy z podglądem WWW.")
    parser.add_argument("url", nargs="?", default=config.ESP32_URL,
                        help=f"adres JPEG z ESP32 (domyślnie z config.py: {config.ESP32_URL})")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(threadName)s: %(message)s")
    logging.getLogger("werkzeug").setLevel(logging.WARNING)  # bez linii na każde zapytanie co 3 s

    state = SharedState()
    thread, stop = start_capture(args.url, config.CAPTURE_INTERVAL, config.OUT_DIR, state)
    try:
        print(f"Serwer: http://{config.HOST}:{config.PORT}/api/state  (Ctrl+C kończy)")
        # use_reloader=False: reloader uruchamia skrypt DRUGI raz w procesie potomnym ->
        # dwa wątki capture, dwa połączenia z ESP32, dwóch piszących do jednego CSV.
        create_app(state).run(host=config.HOST, port=config.PORT,
                              debug=False, use_reloader=False, threaded=True)
        # Werkzeug sam łapie KeyboardInterrupt i po prostu wraca z run()
    finally:
        stop_capture(thread, stop)


if __name__ == "__main__":
    main()
