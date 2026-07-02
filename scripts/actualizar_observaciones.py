from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

import requests

from smn_common import (
    ApiError,
    api_headers,
    as_int,
    error_record,
    get_token,
    load_json,
    request_with_retries,
    response_json,
    sha256_file,
    utc_now,
    write_json_atomic,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "config/estaciones.json"
CACHE_FILE = ROOT / "data/cache/estaciones.json"
DOCS_DIR = ROOT / "docs"
WEATHER_URL = "https://ws1.smn.gob.ar/v1/weather/location/{location_id}"


def fetch_station(session: requests.Session, token: str, target: dict[str, Any]) -> dict[str, Any]:
    station_number = int(target["station_number"])
    representative_id = int(target["representative_locality_id"])
    response = session.get(
        WEATHER_URL.format(location_id=representative_id),
        headers=api_headers(token),
        timeout=30,
    )
    payload = response_json(response, f"la estación {station_number}")
    if not isinstance(payload, dict):
        raise ApiError("El tiempo actual no es un objeto JSON.")
    location = payload.get("location")
    if not isinstance(location, dict) or as_int(location.get("id")) != representative_id:
        raise ApiError("La observación devolvió una localidad representante distinta.")
    if as_int(payload.get("station_id")) != station_number:
        raise ApiError(
            f"La observación devolvió station_id {payload.get('station_id')!r}; "
            f"se esperaba {station_number}."
        )
    if payload.get("temperature") is None and not payload.get("weather"):
        raise ApiError("La observación está vacía.")
    return payload


def slim_record(record: dict[str, Any]) -> dict[str, Any]:
    result = {
        "status": record.get("status"),
        "fresh": record.get("status") == "success",
        "historical": False,
        "data_source": record.get("data_source"),
        "fetched_at": record.get("fetched_at"),
        "payload": record.get("payload"),
    }
    if record.get("last_refresh_attempt_at") is not None:
        result["last_refresh_attempt_at"] = record["last_refresh_attempt_at"]
    if record.get("last_refresh_error") is not None:
        result["last_refresh_error"] = record["last_refresh_error"]
    return result


def publish(cache: dict[str, Any], expected: int, run: dict[str, Any]) -> None:
    records = cache.get("records", {})
    if len(records) != expected:
        raise RuntimeError(f"Se encontraron {len(records)} estaciones; se esperaban {expected}.")
    generated_at = utc_now()
    published = {key: slim_record(records[key]) for key in sorted(records, key=int)}
    fresh = sum(1 for record in published.values() if record["status"] == "success")
    stale = sum(1 for record in published.values() if record["status"] == "stale")
    errors = sum(1 for record in published.values() if record["status"] == "error")
    stations_path = DOCS_DIR / "estaciones.min.json"
    write_json_atomic(
        stations_path,
        {"schema_version": 1, "generated_at": generated_at, "count": len(published), "records": published},
        minified=True,
    )
    manifest = {
        "schema_version": 1,
        "generated_at": generated_at,
        "counts": {"stations": len(published), "fresh": fresh, "stale": stale, "errors": errors},
        "files": {
            "stations": {
                "path": "estaciones.min.json",
                "bytes": stations_path.stat().st_size,
                "sha256": sha256_file(stations_path),
            }
        },
        "validation": {"expected": expected, "available": fresh + stale, "errors": errors},
    }
    write_json_atomic(DOCS_DIR / "manifiesto.json", manifest, minified=True)
    write_json_atomic(DOCS_DIR / "estado.json", {"schema_version": 1, "generated_at": generated_at, **run}, minified=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Actualiza las 121 observaciones operativas del SMN.")
    parser.add_argument("--sleep-seconds", type=float, default=1.5)
    parser.add_argument("--http-attempts", type=int, default=4)
    parser.add_argument("--retry-base-seconds", type=float, default=2.0)
    args = parser.parse_args()
    if args.sleep_seconds < 1.0:
        raise ValueError("--sleep-seconds no puede ser menor que 1.0.")

    config = load_json(CONFIG_FILE)
    stations = config.get("stations")
    if not isinstance(stations, list) or len(stations) != 121:
        raise RuntimeError("La configuración no contiene las 121 estaciones esperadas.")
    cache = load_json(CACHE_FILE) if CACHE_FILE.exists() else {"schema_version": 1, "records": {}}
    records = cache.setdefault("records", {})
    session = requests.Session()
    token = get_token(session)
    successes = failures = stale = 0

    for index, target in enumerate(stations, start=1):
        station_number = str(target["station_number"])
        previous = records.get(station_number) if isinstance(records.get(station_number), dict) else None
        print(f"[{index}/{len(stations)}] estación {station_number}")
        try:
            payload, token, http_attempts = request_with_retries(
                session,
                token,
                fetch_station,
                target,
                max_http_attempts=args.http_attempts,
                retry_base_seconds=args.retry_base_seconds,
            )
            records[station_number] = {
                **target,
                "status": "success",
                "data_source": "smn_modern_weather",
                "fetched_at": utc_now(),
                "http_attempts_last_run": http_attempts,
                "payload": payload,
            }
            successes += 1
            print("  OK")
        except Exception as error:
            failures += 1
            if previous and previous.get("payload") is not None:
                records[station_number] = {
                    **target,
                    "status": "stale",
                    "data_source": previous.get("data_source", "smn_modern_weather"),
                    "fetched_at": previous.get("fetched_at"),
                    "last_refresh_attempt_at": utc_now(),
                    "last_refresh_error": error_record(error),
                    "payload": previous.get("payload"),
                }
                stale += 1
                print(f"  TEMPORAL: se conserva el último dato válido ({error})")
            else:
                records[station_number] = {
                    **target,
                    "status": "error",
                    "last_refresh_attempt_at": utc_now(),
                    "last_refresh_error": error_record(error),
                }
                print(f"  ERROR: {error}")
        cache["generated_at"] = utc_now()
        write_json_atomic(CACHE_FILE, cache)
        if index < len(stations):
            time.sleep(args.sleep_seconds)

    run = {
        "status": "ok" if failures == 0 else "partial",
        "expected": len(stations),
        "successful_queries": successes,
        "failed_queries": failures,
        "preserved_as_stale": stale,
    }
    publish(cache, len(stations), run)
    print(f"Observaciones terminadas: {successes} correctas, {failures} fallidas.")


if __name__ == "__main__":
    main()
