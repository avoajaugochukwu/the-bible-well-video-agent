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
    def test_anonymize_names_scrubs_every_cast_name(self):
        scrubbed = compositor._anonymize_names(
            "Sharon reassures Ellen at a table", CHARACTERS
        )
        self.assertNotIn("Ellen", scrubbed)
        self.assertNotIn("Sharon", scrubbed)

    def test_fallback_is_name_free_and_independent_of_authored_scene(self):
        fallback = compositor.build_fallback_prompt(
            scene("Ellen handles a literal story prop"),
            CHARACTERS,
        )
        self.assertNotIn("Ellen", fallback)
        self.assertNotIn("literal story prop", fallback)
        self.assertIn("movie moment", fallback)


if __name__ == "__main__":
    unittest.main()
