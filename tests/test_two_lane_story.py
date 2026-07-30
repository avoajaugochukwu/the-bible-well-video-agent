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

    def test_break_into_scenes_requires_matching_beat_and_snippet_counts(self):
        # Beats and snippets must correspond 1:1 by position — no distribution
        # logic reconciles a mismatch anymore (agents/visual_director scores every
        # real snippet directly, so a mismatch means something upstream is broken,
        # not something to silently paper over).
        snippets = ["First.", "Second.", "Third."]
        visual_story = {
            "story_beats": [
                {"beat_number": 1, "location_id": "x", "character_ids": []},
                {"beat_number": 2, "location_id": "x", "character_ids": []},
            ]
        }
        with self.assertRaises(ValueError):
            scene_engine.break_into_scenes(snippets, [], visual_story)

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

if __name__ == "__main__":
    unittest.main()
