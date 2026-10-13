import tempfile
import unittest
from pathlib import Path

from detector.core import compare, content_hash, normalize
from detector.store import Store


class ComparisonTests(unittest.TestCase):
    def test_whitespace_and_unicode(self):
        self.assertEqual(normalize("  Cafe\u0301  \r\n\n Price  100 "), "Café\nPrice 100")

    def test_hash_is_normalized(self):
        self.assertEqual(content_hash("Cost  100"), content_hash("Cost 100"))
        self.assertNotEqual(content_hash("Cost 100"), content_hash("Cost 101"))

    def test_first_capture_is_not_alert(self):
        result = compare(None, "Hello")
        self.assertTrue(result.new_version)
        self.assertFalse(result.meaningful)

    def test_add_remove_modify(self):
        for old, new in [("a", "a b"), ("a b", "a"), ("Cost 100", "Cost 99")]:
            with self.subTest(old=old, new=new):
                self.assertTrue(compare(old, new).meaningful)

    def test_unchanged(self):
        self.assertFalse(compare("a b", "a  b").new_version)

    def test_small_change_still_has_version(self):
        result = compare("one two three four", "one two three five", threshold=0.5)
        self.assertTrue(result.new_version)
        self.assertFalse(result.meaningful)

    def test_cumulative_changes_use_significant_baseline(self):
        result = compare("a b c x", "a b y x", significant_baseline="a b c d", threshold=0.4)
        self.assertTrue(result.meaningful)

    def test_invalid_thresholds(self):
        for value in [-1, 2, float("nan")]:
            with self.assertRaises(ValueError):
                compare("a", "b", threshold=value)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name) / "test.sqlite")
        self.store = Store(self.path)
        self.monitor = self.store.add_monitor("Example")

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def capture(self, text, time="2026-10-12T17:00:00Z"):
        # Explicit fixture bytes; this test does not claim real browser capture.
        return self.store.record(self.monitor, checked_at=time, status="ok",
                                 text=text, screenshot=b"fixture-image")

    def test_deduplicates_consecutive_versions_but_records_every_check(self):
        self.assertIsNotNone(self.capture("a"))
        self.assertIsNone(self.capture("a"))
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM snapshots").fetchone()[0], 1)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM checks").fetchone()[0], 2)

    def test_reversion_is_a_new_version(self):
        self.capture("a")
        self.capture("b")
        self.assertIsNotNone(self.capture("a"))

    def test_failure_and_block_preserve_baseline(self):
        self.capture("a")
        for status in ["error", "blocked"]:
            self.store.record(self.monitor, checked_at="2026-10-12T17:01:00Z", status=status)
            row = self.store.db.execute("SELECT * FROM monitors").fetchone()
            self.assertEqual(row["significant_text"], "a")
            self.assertIsNone(row["last_changed"])
            self.assertEqual(row["status"], status)
        self.assertIsNone(self.capture("a"))

    def test_change_updates_last_changed(self):
        self.capture("a")
        self.capture("b", time="2026-10-12T17:02:00Z")
        row = self.store.db.execute("SELECT * FROM monitors").fetchone()
        self.assertEqual(row["last_changed"], "2026-10-12T17:02:00Z")

    def test_persists_after_reopen(self):
        self.capture("a")
        self.store.close()
        self.store = Store(self.path)
        self.assertIsNone(self.capture("a"))

    def test_missing_screenshot_rejected_without_partial_write(self):
        with self.assertRaises(ValueError):
            self.store.record(self.monitor, checked_at="now", status="ok", text="a")
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM checks").fetchone()[0], 0)

    def test_unknown_monitor_rejected(self):
        with self.assertRaises(ValueError):
            self.store.record(999, checked_at="now", status="error")


if __name__ == "__main__":
    unittest.main()
