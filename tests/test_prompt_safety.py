import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agents.scene_compositor import client as compositor


CHARACTERS = {
    "protagonist": {
        "id": "protagonist",
        "name": "Ellen",
        "role": "protagonist; woman who learns to stop waiting and begin living",
        "appearance": (
            "Full-figured woman in her early fifties, Caucasian, medium build with kind brown "
            "eyes and short wavy salt-and-pepper hair. Dresses modestly in modern comfortable "
            "clothing, soft sweaters, a plain gray knit top, tailored trousers, and simple "
            "walking shoes."
        ),
    },
    "sharon": {
        "id": "sharon",
        "name": "Sharon (sister-in-law)",
        "role": "sister-in-law; casual critic whose remarks push Ellen to honesty",
        "appearance": (
            "Full-figured woman in her early fifties, African American, medium-tall, with "
            "smooth dark skin, shoulder-length straightened hair, a floral blouse, smart "
            "cardigan, slacks, and understated jewelry."
        ),
    },
}


def scene(prompt, ids=("protagonist",)):
    return {
        "scene_number": 1,
        "image_prompt": prompt,
        "hero_subject": "the protagonist makes a difficult choice at a community meeting",
        "scene_type": "reflection",
        "character_ids": list(ids),
    }


class PromptSafetyTests(unittest.TestCase):
    def test_scrubs_every_cast_name_and_narrative_role_detail(self):
        prompt = compositor.build_scene_prompt(
            scene("Sharon reassures Ellen at a table", ("sharon", "protagonist")),
            CHARACTERS,
        )
        self.assertNotIn("Ellen", prompt)
        self.assertNotIn("Sharon", prompt)
        self.assertNotIn("woman who learns", prompt)
        self.assertNotIn("sister-in-law", prompt)
        self.assertIn("the recurring supporting character", prompt)
        self.assertIn("the protagonist", prompt)

    def test_constraints_are_positive_and_structural(self):
        constraints = compositor._build_constraints(scene("the protagonist walks outside"))
        self.assertIn("Preserve every stated character detail exactly", constraints)
        self.assertIn("entire horizontal 16:9 frame", constraints)
        self.assertIn("requested scene", constraints)
        self.assertNotIn("negative prompt", constraints.lower())

    def test_fallback_is_name_free_and_independent_of_authored_scene(self):
        fallback = compositor.build_fallback_prompt(
            scene("Ellen handles a literal story prop"),
            CHARACTERS,
        )
        self.assertNotIn("Ellen", fallback)
        self.assertNotIn("literal story prop", fallback)
        self.assertIn("movie moment", fallback)
        self.assertIn("the protagonist", fallback)


if __name__ == "__main__":
    unittest.main()
