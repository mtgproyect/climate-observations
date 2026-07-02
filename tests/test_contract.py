from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ObservationContractTests(unittest.TestCase):
    def test_station_config(self) -> None:
        config = json.loads((ROOT / "config/estaciones.json").read_text(encoding="utf-8"))
        self.assertEqual(config["count"], 121)
        self.assertEqual(len(config["stations"]), 121)
        numbers = [item["station_number"] for item in config["stations"]]
        self.assertEqual(len(numbers), len(set(numbers)))

    def test_publication(self) -> None:
        payload = json.loads((ROOT / "docs/estaciones.min.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["count"], 121)
        self.assertEqual(len(payload["records"]), 121)

    def test_manifest(self) -> None:
        manifest = json.loads((ROOT / "docs/manifiesto.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["counts"]["stations"], 121)
        self.assertEqual(manifest["files"]["stations"]["path"], "estaciones.min.json")


if __name__ == "__main__":
    unittest.main()
