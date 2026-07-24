"""Unit tests for the durable outbox queue."""

import json
import os
import shutil
import sys
import tempfile
import unittest

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)

from acl_core.outbox import Outbox


class TestOutbox(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.box = Outbox(self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_lap_roundtrip_and_staging(self):
        rec = {"user": "James", "time_ms": 81200,
               "telemetry": "telemetry/spa__james__81200.json"}
        self.box.add_lap(rec, '{"fake":1}')
        self.assertEqual(self.box.count(), 1)
        self.assertEqual(self.box.lap_count(), 1)
        snap = self.box.snapshot()
        self.assertEqual(snap[0]["record"]["user"], "James")
        staged = self.box.staged_path(rec["telemetry"])
        self.assertTrue(os.path.isfile(staged))
        with open(staged) as f:
            self.assertEqual(json.load(f), {"fake": 1})

    def test_records_are_copied_not_referenced(self):
        rec = {"user": "James", "time_ms": 1}
        self.box.add_lap(rec)
        rec["user"] = "MUTATED"
        self.assertEqual(self.box.snapshot()[0]["record"]["user"], "James")

    def test_persistence_across_instances(self):
        self.box.add_user("Dad")
        self.box.add_lap({"user": "Dad", "time_ms": 5}, None)
        again = Outbox(self.dir)
        self.assertEqual(again.count(), 2)
        self.assertEqual(again.lap_count(), 1)
        kinds = sorted(e["type"] for e in again.snapshot())
        self.assertEqual(kinds, ["lap", "user"])

    def test_remove_clears_entries_and_stage(self):
        rec = {"user": "J", "time_ms": 2, "telemetry": "telemetry/a.json"}
        i1 = self.box.add_lap(rec, "x")
        i2 = self.box.add_user("Dad")
        staged = self.box.staged_path("telemetry/a.json")
        self.assertTrue(os.path.isfile(staged))
        self.box.remove([i1, i2])
        self.assertEqual(self.box.count(), 0)
        self.assertFalse(os.path.isfile(staged))

    def test_remove_keeps_stage_shared_with_pending_entry(self):
        rec = {"user": "J", "time_ms": 3, "telemetry": "telemetry/b.json"}
        i1 = self.box.add_lap(rec, "one")
        self.box.add_lap(rec, "two")     # same rel staged again, still pending
        self.box.remove([i1])
        self.assertTrue(os.path.isfile(self.box.staged_path("telemetry/b.json")))

    def test_asset_replaces_pending_same_rel(self):
        src = os.path.join(self.dir, "src.bin")
        with open(src, "w") as f:
            f.write("v1")
        self.box.add_asset("trackmaps/x.png", src)
        with open(src, "w") as f:
            f.write("v2")
        self.box.add_asset("trackmaps/x.png", src)
        assets = [e for e in self.box.snapshot() if e["type"] == "asset"]
        self.assertEqual(len(assets), 1)
        with open(self.box.staged_path("trackmaps/x.png")) as f:
            self.assertEqual(f.read(), "v2")

    def test_ids_monotonic_after_reload(self):
        i1 = self.box.add_user("A")
        again = Outbox(self.dir)
        i2 = again.add_user("B")
        self.assertGreater(i2, i1)


if __name__ == "__main__":
    unittest.main()
