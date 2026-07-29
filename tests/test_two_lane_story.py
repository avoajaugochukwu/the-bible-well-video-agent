import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import scene_engine


class TwoLaneStoryTests(unittest.TestCase):
    def test_narration_split_is_verbatim_and_merges_short_rhetorical_lines(self):
        script = (
            "Not today. Not tomorrow. She kept moving. "
            "The community hall filled slowly with neighbors carrying folding chairs. "
            "By evening, everyone had found a place at the table."
        )
        snippets = scene_engine.split_narration_scenes(
            script,
            target_words=12,
            max_words=20,
        )
        self.assertEqual("".join(snippets), script)
        self.assertLess(len(snippets), 5)
        self.assertTrue(snippets[0].startswith("Not today. Not tomorrow."))

    def test_snippets_map_chronologically_to_director_beats(self):
        script = (
            "She arrived early at the hall. People began to gather. "
            "The meeting became difficult. She listened before answering. "
            "The group returned to work. By sunset, the project was ready."
        )
        snippets = scene_engine.split_narration_scenes(
            script,
            target_words=6,
            max_words=12,
        )
        beats = [
            {"beat_number": 1, "narration_anchor": "She arrived early"},
            {"beat_number": 2, "narration_anchor": "The meeting became difficult"},
            {"beat_number": 3, "narration_anchor": "The group returned to work"},
        ]
        assigned = scene_engine._assign_snippets_to_beats(script, snippets, beats)
        flattened = [
            scene_number
            for beat_number in (1, 2, 3)
            for scene_number, _ in assigned[beat_number]
        ]
        self.assertEqual(flattened, list(range(1, len(snippets) + 1)))
        self.assertTrue(all(assigned[n] for n in (1, 2, 3)))
        counts = [len(assigned[n]) for n in (1, 2, 3)]
        self.assertLessEqual(max(counts) - min(counts), 1)

    def test_every_director_beat_gets_screen_time(self):
        snippets = [f"Scene {i}. " for i in range(1, 14)]
        beats = [
            {"beat_number": i, "narration_anchor": "unused"}
            for i in range(1, 6)
        ]
        assigned = scene_engine._assign_snippets_to_beats("", snippets, beats)
        self.assertTrue(all(assigned[i] for i in range(1, 6)))
        self.assertEqual(sum(map(len, assigned.values())), len(snippets))


if __name__ == "__main__":
    unittest.main()
