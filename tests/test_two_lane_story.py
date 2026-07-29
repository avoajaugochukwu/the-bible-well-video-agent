import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import scene_engine


class TwoLaneStoryTests(unittest.TestCase):
    def test_agent_boundaries_are_anchored_to_verbatim_script(self):
        script = "The farmhouse sat quiet. Inside, a stove crackled. Outside, rain began."
        snippets = scene_engine.slice_by_snippets(
            script,
            [
                "The farmhouse sat quiet.",
                "a paraphrase the script does not contain",
                "Outside, rain began.",
            ],
        )
        self.assertIsNotNone(snippets)
        self.assertEqual("".join(snippets), script)
        self.assertEqual(len(snippets), 2)

    def test_snippets_map_chronologically_to_director_beats(self):
        script = (
            "She arrived early at the hall. People began to gather. "
            "The meeting became difficult. She listened before answering. "
            "The group returned to work. By sunset, the project was ready."
        )
        snippets = scene_engine.mechanical_split(script, sentences_per_scene=1)
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

    def test_scene_cap_is_lossless(self):
        script = " ".join(f"word{i}" for i in range(1, 76))
        snippets = scene_engine.cap_segments([script], max_words=30)
        self.assertEqual("".join(snippets), script)
        self.assertEqual([len(s.split()) for s in snippets], [30, 30, 15])

    def test_scene_cap_prefers_natural_boundaries(self):
        script = (
            "One two three four five six seven eight nine ten. "
            "Eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen "
            "nineteen twenty twenty-one twenty-two twenty-three twenty-four."
        )
        snippets = scene_engine.cap_segments([script], max_words=15)
        self.assertEqual("".join(snippets), script)
        self.assertEqual(len(snippets), 2)
        self.assertTrue(snippets[0].strip().endswith("ten."))

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
