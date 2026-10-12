import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "opz_slot_map_edit",
    ROOT / "tools" / "opz-slot-map-edit.py",
)
assert SPEC and SPEC.loader
SLOT_MAP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SLOT_MAP)


class SlotMapEditTests(unittest.TestCase):
    def test_replaces_one_slot_and_sorts_packs(self):
        document = {
            "tracks": [
                {
                    "index": 5,
                    "packs": [
                        {"id": 31, "slot": 10},
                        {"id": 65, "slot": 1},
                    ],
                }
            ]
        }

        prior = SLOT_MAP.edit_slot(document, 5, 10, 60005)

        self.assertEqual(prior, 31)
        self.assertEqual(
            document["tracks"][0]["packs"],
            [{"id": 65, "slot": 1}, {"id": 60005, "slot": 10}],
        )

    def test_adds_an_unassigned_slot(self):
        document = {"tracks": [{"index": 4, "packs": []}]}

        prior = SLOT_MAP.edit_slot(document, 4, 3, 60001)

        self.assertIsNone(prior)
        self.assertEqual(
            document["tracks"][0]["packs"],
            [{"id": 60001, "slot": 3}],
        )

    def test_rejects_missing_track(self):
        with self.assertRaisesRegex(ValueError, "no track 8"):
            SLOT_MAP.edit_slot({"tracks": []}, 8, 1, 10)


if __name__ == "__main__":
    unittest.main()
