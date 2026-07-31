import json
import unittest
from unittest.mock import patch

from agents.character_ledger import client as character_ledger
from agents.visual_director import client as visual_director


class AgentContractTests(unittest.TestCase):
    @staticmethod
    def _visual_profile(**overrides):
        profile = {
            "age": 54,
            "gender": "woman",
            "ethnicity": "Latina",
            "height": "5 feet 10 inches",
            "build": "medium sturdy build",
            "skin_tone": "warm medium-olive skin",
            "face_shape": "long oval",
            "cheek_structure": "defined cheekbones",
            "eye_description": "dark-brown almond-shaped eyes",
            "nose_description": "straight nose",
            "lip_description": "medium lips",
            "age_markers": "faint smile lines",
            "eyewear": "thin rectangular dark-brown glasses",
            "hair_color": "deep-brown",
            "hair_texture": "straight",
            "hair_length": "jaw-length",
            "haircut": "blunt pageboy cut",
            "hair_part": "precise left-side part",
            "hair_end_shape": "smooth inward-curved ends",
            "hair_position": "both sides tucked behind ears",
            "hair_accessory": "no hair accessory",
            "inner_top": "white round-neck cotton T-shirt",
            "outer_layer": "dusty-teal knitted cardigan",
            "outer_layer_closure": "fully unbuttoned",
            "bottom": "straight black trousers",
            "footwear": "plain black leather loafers",
            "jewelry": "no jewelry",
            "accessories": "no accessories",
        }
        profile.update(overrides)
        return profile

    def test_visual_profile_compiles_to_one_locked_prompt_fragment(self):
        profile = self._visual_profile()

        appearance = character_ledger.compile_visual_profile(profile)

        for value in profile.values():
            self.assertIn(str(value), appearance)
        self.assertIn("dusty-teal knitted cardigan fully unbuttoned", appearance)
        self.assertIn("blunt pageboy cut", appearance)

    def test_director_handoff_excludes_source_audit_details(self):
        dossier = {
            "source_facts": {"protagonist": [{"fact": "source-only detail"}]},
            "whole_script_vibe": {
                "social_class_and_lifestyle": "modest and independent",
                "wardrobe_vibe": "source-event costume",
            },
            "cinematic_inference": {"protagonist_occupation": "architect"},
            "director_profile": {"professional_vibe": "precise"},
        }

        handoff = visual_director._profile_for_director(dossier)

        self.assertNotIn("source_facts", handoff)
        self.assertEqual(
            handoff["whole_script_vibe"],
            {"social_class_and_lifestyle": "modest and independent"},
        )
        self.assertNotIn("wardrobe_vibe", json.dumps(handoff))

    def test_director_score_carries_bridge_cues_without_narration(self):
        spine = {
            "core_transformation": {
                "from_state": "withdrawal",
                "to_state": "purposeful_action",
            },
            "emotional_beats": [{
                "beat_number": 1,
                "narration_anchor": "verbatim source phrase",
                "story_pressure": "unease",
                "emotional_valence": "negative",
                "agency": 2,
                "social_openness": 1,
                "tempo": "measured",
                "camera_distance": "close",
                "bridge_cues": [
                    {
                        "cue": "silver tweezers",
                        "cue_type": "tool",
                        "evidence": "with silver tweezers",
                    },
                    {
                        "cue": "tightening a small screw",
                        "cue_type": "physical_gesture",
                        "evidence": "tightening the screw",
                    },
                ],
            }],
        }

        score = visual_director._score_for_director(spine)

        self.assertIn("silver tweezers", score)
        self.assertIn("tightening a small screw", score)
        self.assertNotIn("verbatim source phrase", score)

    def test_director_cannot_invent_bridge_cues(self):
        emotional_beats = [{
            "beat_number": 1,
            "bridge_cues": [{
                "cue": "silver tweezers",
                "cue_type": "tool",
                "evidence": "with silver tweezers",
            }],
        }]
        plan = {
            "story_beats": [{
                "beat_number": 1,
                "bridge_cue": "gold pocket watch",
            }]
        }

        problems = visual_director._validate_bridge_cues(plan["story_beats"], emotional_beats)

        self.assertTrue(any("unapproved bridge_cue" in p for p in problems))

    def test_character_retry_includes_previous_json(self):
        generation_messages = []
        generation_count = 0

        def fake_call(messages, _schema, **_kwargs):
            nonlocal generation_count
            generation_messages.append([dict(message) for message in messages])
            generation_count += 1
            if generation_count == 1:
                return {
                    "characters": [{
                        "id": "protagonist",
                        "name": "Ellen",
                        "role": "protagonist",
                        "visual_profile": self._visual_profile(hair_position=""),
                        "casting_basis": "whole-story casting",
                    }]
                }
            return {
                "characters": [{
                    "id": "protagonist",
                    "name": "Ellen",
                    "role": "protagonist",
                    "visual_profile": self._visual_profile(),
                    "casting_basis": "whole-story casting",
                }]
            }

        with patch.object(character_ledger, "call_llm_json", side_effect=fake_call):
            result = character_ledger.build(
                "Ellen considered her future.",
                {},
                story_dossier={},
            )

        self.assertEqual(result["characters"][0]["id"], "protagonist")
        retry = generation_messages[1]
        assistant_messages = [
            message["content"]
            for message in retry
            if message["role"] == "assistant"
        ]
        self.assertTrue(assistant_messages)
        self.assertIn('"visual_profile"', assistant_messages[-1])
        self.assertIn('"hair_position": ""', assistant_messages[-1])
        self.assertNotIn('"appearance"', assistant_messages[-1])


if __name__ == "__main__":
    unittest.main()
