"""Unit tests for the pure-Python core (run on any machine, no AC needed).

    python3 -m pytest tests/            # if pytest is installed
    python3 tests/test_core.py          # plain-stdlib fallback runner
"""

import os
import shutil
import sys
import tempfile
import unittest

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)

from acl_core import config, storage
from acl_core.timefmt import format_ms, parse_time
from acl_core.leaderboard import leaderboard_for


class TimeFmtTests(unittest.TestCase):
    def test_format_ms(self):
        self.assertEqual(format_ms(83456), "1:23.456")
        self.assertEqual(format_ms(59999), "0:59.999")
        self.assertEqual(format_ms(0), "0:00.000")
        self.assertEqual(format_ms(3661001), "61:01.001")
        self.assertEqual(format_ms(None), "--:--.---")
        self.assertEqual(format_ms(-5), "--:--.---")

    def test_parse_basic(self):
        self.assertEqual(parse_time("1:23.456"), 83456)
        self.assertEqual(parse_time("1:23"), 83000)
        self.assertEqual(parse_time("1:23.4"), 83400)
        self.assertEqual(parse_time("  1:23.456  "), 83456)

    def test_parse_seconds_only(self):
        self.assertEqual(parse_time("83.456"), 83456)
        self.assertEqual(parse_time("83"), 83000)
        self.assertEqual(parse_time("59.999"), 59999)

    def test_parse_comma_decimal(self):
        self.assertEqual(parse_time("1:23,456"), 83456)

    def test_parse_invalid(self):
        for bad in ["", "   ", "abc", "1:2:3", "1:99.0", ":.", "-1:00.0", "0", "0:00.000"]:
            self.assertIsNone(parse_time(bad), bad)

    def test_roundtrip(self):
        for ms in [83456, 59999, 120000, 1, 3599999]:
            self.assertEqual(parse_time(format_ms(ms)), ms)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="acltest_")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_upsert_and_persist(self):
        st = storage.Store(self.dir).load()
        r1 = storage.make_record("spa", "", "ferrari_488_gt3", "James", 130000)
        self.assertEqual(st.upsert_record(r1), "new")
        # Slower time is ignored.
        r2 = storage.make_record("spa", "", "ferrari_488_gt3", "James", 131000)
        self.assertEqual(st.upsert_record(r2), "ignored")
        # Faster time improves.
        r3 = storage.make_record("spa", "", "ferrari_488_gt3", "James", 128500)
        self.assertEqual(st.upsert_record(r3), "improved")
        self.assertEqual(len(st.records), 1)
        self.assertEqual(st.records[0]["time_ms"], 128500)

        st.save()
        st2 = storage.Store(self.dir).load()
        self.assertEqual(len(st2.records), 1)
        self.assertEqual(st2.records[0]["time_ms"], 128500)

    def test_case_insensitive_combo(self):
        st = storage.Store(self.dir).load()
        st.upsert_record(storage.make_record("Spa", "", "Ferrari_488_GT3", "James", 130000))
        # Same combo, different case -> updates the same record.
        res = st.upsert_record(storage.make_record("spa", "", "ferrari_488_gt3", "james", 129000))
        self.assertEqual(res, "improved")
        self.assertEqual(len(st.records), 1)

    def test_users_union_and_create(self):
        st = storage.Store(self.dir).load()
        self.assertTrue(st.add_user("Alex"))
        self.assertFalse(st.add_user("alex"))  # duplicate, case-insensitive
        st.upsert_record(storage.make_record("monza", "", "bmw_m3_e30", "James", 120000))
        users = st.all_users()
        self.assertIn("Alex", users)
        self.assertIn("James", users)
        # Created-but-timeless user still shows.
        self.assertTrue(st.add_user("Ghost"))
        self.assertIn("Ghost", st.all_users())


class LeaderboardTests(unittest.TestCase):
    def _records(self):
        return [
            storage.make_record("spa", "", "ferrari_488_gt3", "James", 130000),
            storage.make_record("spa", "", "ferrari_488_gt3", "Alex", 128000),
            storage.make_record("spa", "", "ferrari_488_gt3", "Sam", 131500),
            storage.make_record("spa", "", "bmw_m3_e30", "James", 140000),  # other car
            storage.make_record("monza", "", "ferrari_488_gt3", "James", 110000),  # other track
        ]

    def test_ranking_and_gaps(self):
        rows = leaderboard_for(self._records(), "spa", "", "ferrari_488_gt3")
        self.assertEqual([r["user"] for r in rows], ["Alex", "James", "Sam"])
        self.assertEqual(rows[0]["rank"], 1)
        self.assertEqual(rows[0]["gap_str"], "")
        self.assertEqual(rows[1]["gap_ms"], 2000)
        self.assertEqual(rows[1]["gap_str"], "+2.000")
        self.assertEqual(rows[2]["gap_str"], "+3.500")

    def test_combo_isolation(self):
        rows = leaderboard_for(self._records(), "spa", "", "bmw_m3_e30")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["user"], "James")


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="aclcfg_")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_creates_default_and_auto_repo(self):
        cfg = config.load(self.dir)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "config.json")))
        # No repo_path set -> auto-detects to the app dir (the clone root).
        self.assertEqual(cfg.repo_path, self.dir)
        self.assertEqual(cfg.data_dir,
                         os.path.normpath(os.path.join(self.dir, "docs/data")))
        # Not a git work tree (no .git here) -> not push-able.
        self.assertFalse(cfg.repo_configured())

    def test_repo_configured_with_git(self):
        os.mkdir(os.path.join(self.dir, ".git"))
        cfg = config.load(self.dir)
        self.assertTrue(cfg.repo_configured())

    def test_explicit_repo_path_overrides(self):
        cfg = config.load(self.dir)
        other = tempfile.mkdtemp(prefix="aclrepo_")
        try:
            cfg.values["repo_path"] = other
            self.assertEqual(cfg.data_dir,
                             os.path.normpath(os.path.join(other, "docs/data")))
        finally:
            shutil.rmtree(other, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
