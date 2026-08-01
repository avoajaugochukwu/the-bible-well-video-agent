"""add_scene_image() is a read-modify-write of one whole jsonb payload, called
from several threads at once (the compositor's progress writes, the production
UI's regenerate/pick routes). Without src/supabase_jobs.py's module lock the
last writer wins and images silently vanish — this pins that down without
touching Supabase.
"""
import copy
import os
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import supabase_jobs  # src/

SCENES = 8


class JobProgressTests(unittest.TestCase):
    def setUp(self):
        self.stored = supabase_jobs.build_job_payload(
            "row-test",
            {"title": "T", "clickup_url": "u"},
            [{"scene_number": n, "script_snippet": "s", "image_prompt": "p", "image_url": None}
             for n in range(1, SCENES + 1)],
        )["payload"]
        self.write_lock = threading.Lock()

    def _fake_get(self, row_id):
        # A real PostgREST read hands back a fresh parse of the row, and takes
        # long enough for another thread to get in between read and write —
        # that window is the whole bug.
        time.sleep(0.005)
        return copy.deepcopy(self.stored)

    def _fake_upsert(self, row):
        with self.write_lock:
            self.stored = row["payload"]
        return row

    def test_counters_start_at_zero_of_total(self):
        self.assertEqual(self.stored["total"], SCENES)
        self.assertEqual(self.stored["completed"], 0)

    def test_concurrent_image_writes_all_survive(self):
        with patch.object(supabase_jobs, "get_job", self._fake_get), \
                patch.object(supabase_jobs, "upsert_job", self._fake_upsert):
            with ThreadPoolExecutor(max_workers=SCENES) as ex:
                list(ex.map(
                    lambda n: supabase_jobs.add_scene_image(
                        "row-test", n, f"https://example.com/{n}.png", "gpt-image", prompt="p"),
                    range(1, SCENES + 1),
                ))

        urls = [s["asset"]["imageHistory"][0]["url"] if s["asset"]["imageHistory"] else None
                for s in self.stored["scenes"]]
        self.assertEqual(urls, [f"https://example.com/{n}.png" for n in range(1, SCENES + 1)])
        self.assertEqual(self.stored["completed"], SCENES)

    def test_regenerating_a_done_scene_does_not_overcount(self):
        with patch.object(supabase_jobs, "get_job", self._fake_get), \
                patch.object(supabase_jobs, "upsert_job", self._fake_upsert):
            supabase_jobs.add_scene_image("row-test", 1, "https://example.com/a.png", "gpt-image")
            supabase_jobs.add_scene_image("row-test", 1, "https://example.com/b.png", "gpt-image")
        self.assertEqual(self.stored["completed"], 1)
        self.assertEqual(len(self.stored["scenes"][0]["asset"]["imageHistory"]), 2)


if __name__ == "__main__":
    unittest.main()
