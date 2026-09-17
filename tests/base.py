"""Baza comuna pentru teste: fiecare test porneste cu o baza de date SQLite proprie,
intr-un fisier temporar, ca testele sa nu se calce unele pe altele sau pe date reale."""

from __future__ import annotations

import os
import tempfile
import unittest

from tracker import db


class TrackerTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._prev_db = os.environ.get("TRACKER_DB")
        os.environ["TRACKER_DB"] = self._tmp.name
        db.reset_thread_state()
        db.init_db()

    def tearDown(self):
        db.reset_thread_state()
        if self._prev_db is None:
            os.environ.pop("TRACKER_DB", None)
        else:
            os.environ["TRACKER_DB"] = self._prev_db
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass
