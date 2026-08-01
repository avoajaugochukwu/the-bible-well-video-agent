"""A duplicate /ingest used to queue a SECOND full prepare for the same row.

Nothing is cached any more, so that re-pays for the entire pipeline — dossier,
director, every scene image. One worker thread means the two runs go back to
back rather than racing, so there's no error to notice: it just bills twice and
reads as one slow job. Same shape on the render side.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import ingest_server


class EnqueueDedupe(unittest.TestCase):
    def setUp(self):
        ingest_server._ingest_queue_ids.clear()
        ingest_server._render_queue_ids.clear()
        while not ingest_server._ingest_queue.empty():
            ingest_server._ingest_queue.get()
        while not ingest_server._render_queue.empty():
            ingest_server._render_queue.get()
        ingest_server._current_ingest_row_id = None
        ingest_server._current_render_row_id = None

    def test_second_enqueue_while_waiting_is_refused(self):
        self.assertTrue(ingest_server._enqueue_ingest("2158"))
        self.assertFalse(ingest_server._enqueue_ingest("2158"))
        self.assertEqual(ingest_server._ingest_queue.qsize(), 1)

    def test_enqueue_while_already_running_is_refused(self):
        # Already dequeued, so it's gone from _ingest_queue_ids — the id set alone
        # can't catch this, which is exactly how the duplicate used to get through.
        ingest_server._current_ingest_row_id = "2158"
        self.assertFalse(ingest_server._enqueue_ingest("2158"))
        self.assertEqual(ingest_server._ingest_queue.qsize(), 0)

    def test_a_different_row_still_enqueues(self):
        self.assertTrue(ingest_server._enqueue_ingest("2158"))
        self.assertTrue(ingest_server._enqueue_ingest("2159"))
        self.assertEqual(ingest_server._ingest_queue.qsize(), 2)

    def test_render_queue_dedupes_the_same_way(self):
        self.assertTrue(ingest_server._enqueue_render("2158"))
        self.assertFalse(ingest_server._enqueue_render("2158"))
        ingest_server._render_queue_ids.discard("2158")
        ingest_server._current_render_row_id = "2158"
        self.assertFalse(ingest_server._enqueue_render("2158"))
        self.assertEqual(ingest_server._render_queue.qsize(), 1)


if __name__ == "__main__":
    unittest.main()
