"""Extract source facts and infer a coherent cinematic world from the whole script."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "utils"))

from llm import call_llm_json


STORY_DOSSIER_CONTRACT_VERSION = 11
MAX_ATTEMPTS = 3

_FACT_SCHEMA = {
    "type": "object",
    "properties": {
        "fact": {"type": "string"},
        "evidence": {
            "type": "string",
            "description": "short verbatim source phrase supporting the fact",
        },
    },
    "required": ["fact", "evidence"],
    "additionalProperties": False,
}

DOSSIER_SCHEMA = {
    "name": "story_world_dossier",
    "schema": {
        "type": "object",
        "properties": {
            "source_facts": {
                "type": "object",
                "properties": {
                    "protagonist": {
                        "type": "array",
                        "minItems": 3,
                        "maxItems": 12,
                        "items": _FACT_SCHEMA,
                    },
                    "relationships": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 10,
                        "items": _FACT_SCHEMA,
                    },
                    "social_world": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 10,
                        "items": _FACT_SCHEMA,
                    },
                    "occupation": {
                        "type": "object",
                        "properties": {
                            "stated": {"type": "boolean"},
                            "value": {"type": "string"},
                            "evidence": {"type": "string"},
                        },
                        "required": ["stated", "value", "evidence"],
                        "additionalProperties": False,
                    },
                    "unstated_visual_traits": {
                        "type": "array",
                        "description": (
                            "names of appearance/casting attributes the source leaves "
                            "unstated, not props, locations, events, or inferred designs"
                        ),
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "protagonist",
                    "relationships",
                    "social_world",
                    "occupation",
                    "unstated_visual_traits",
                ],
                "additionalProperties": False,
            },
            "whole_script_vibe": {
                "type": "object",
                "properties": {
                    "social_class_and_lifestyle": {"type": "string"},
                    "professional_energy": {"type": "string"},
                    "primary_visual_vibe": {"type": "string"},
                    "wardrobe_vibe": {"type": "string"},
                    "credible_social_domains": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 6,
                        "items": {"type": "string"},
                    },
                    "credible_locations": {
                        "type": "array",
                        "minItems": 4,
                        "maxItems": 10,
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "social_class_and_lifestyle",
                    "professional_energy",
                    "primary_visual_vibe",
                    "wardrobe_vibe",
                    "credible_social_domains",
                    "credible_locations",
                ],
                "additionalProperties": False,
            },
            "abstract_casting_signals": {
                "type": "object",
                "properties": {
                    "age_range": {"type": "string"},
                    "gender": {"type": "string"},
                    "temperament": {
                        "type": "array",
                        "minItems": 3,
                        "maxItems": 7,
                        "items": {"type": "string"},
                    },
                    "economic_independence": {"type": "string"},
                    "work_style": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 6,
                        "items": {"type": "string"},
                    },
                    "interpersonal_style": {"type": "string"},
                    "wardrobe_formality": {"type": "string"},
                    "cultural_tone": {"type": "string"},
                },
                "required": [
                    "age_range",
                    "gender",
                    "temperament",
                    "economic_independence",
                    "work_style",
                    "interpersonal_style",
                    "wardrobe_formality",
                    "cultural_tone",
                ],
                "additionalProperties": False,
            },
            "cinematic_inference": {
                "type": "object",
                "properties": {
                    "protagonist_occupation": {"type": "string"},
                    "occupation_basis": {
                        "type": "string",
                        "enum": ["explicit", "strong_inference", "creative_inference"],
                    },
                    "body_design": {"type": "string"},
                    "ethnicity_design": {"type": "string"},
                    "hair_design": {"type": "string"},
                    "wardrobe_design": {"type": "string"},
                    "casting_rationale": {"type": "string"},
                },
                "required": [
                    "protagonist_occupation",
                    "occupation_basis",
                    "body_design",
                    "ethnicity_design",
                    "hair_design",
                    "wardrobe_design",
                    "casting_rationale",
                ],
                "additionalProperties": False,
            },
            "director_profile": {
                "type": "object",
                "properties": {
                    "stable_identity": {
                        "type": "array",
                        "minItems": 3,
                        "maxItems": 8,
                        "items": {"type": "string"},
                    },
                    "social_dynamics": {"type": "string"},
                    "professional_vibe": {"type": "string"},
                    "visual_vibe": {"type": "string"},
                    "credible_worlds": {
                        "type": "array",
                        "minItems": 3,
                        "maxItems": 8,
                        "items": {"type": "string"},
                    },
                    "parallel_story_rule": {"type": "string"},
                },
                "required": [
                    "stable_identity",
                    "social_dynamics",
                    "professional_vibe",
                    "visual_vibe",
                    "credible_worlds",
                    "parallel_story_rule",
                ],
                "additionalProperties": False,
            },
        },
        "required": [
            "source_facts",
            "whole_script_vibe",
            "abstract_casting_signals",
            "cinematic_inference",
            "director_profile",
        ],
        "additionalProperties": False,
    },
}

DOSSIER_REVIEW_SCHEMA = {
    "name": "story_dossier_review",
    "schema": {
        "type": "object",
        "properties": {
            "approved": {"type": "boolean"},
            "issues": {
                "type": "array",
                "maxItems": 8,
                "items": {"type": "string"},
            },
        },
        "required": ["approved", "issues"],
        "additionalProperties": False,
    },
}

CASTING_SCHEMA = {
    "name": "independent_cinematic_casting",
    "schema": {
        "type": "object",
        "properties": {
            "cinematic_inference": DOSSIER_SCHEMA["schema"]["properties"]["cinematic_inference"],
            "director_profile": DOSSIER_SCHEMA["schema"]["properties"]["director_profile"],
        },
        "required": ["cinematic_inference", "director_profile"],
        "additionalProperties": False,
    },
}

OCCUPATION_CANDIDATES_SCHEMA = {
    "name": "occupation_candidates",
    "schema": {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "minItems": 5,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "job_title": {"type": "string"},
                        "profile_fit": {"type": "string"},
                        "visual_world": {"type": "string"},
                    },
                    "required": ["job_title", "profile_fit", "visual_world"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["candidates"],
        "additionalProperties": False,
    },
}


def _occupation_selection_schema(job_titles: list[str]) -> dict:
    return {
        "name": "occupation_selection",
        "schema": {
            "type": "object",
            "properties": {
                "job_title": {"type": "string", "enum": job_titles},
                "rationale": {"type": "string"},
            },
            "required": ["job_title", "rationale"],
            "additionalProperties": False,
        },
    }


def _choose_occupation(abstract_profile: dict) -> dict:
    candidates = call_llm_json(
        [
            {
                "role": "system",
                "content": (
                    "Propose exactly five distinct, plausible occupations for an adult "
                    "character from an abstract profile. Create real range across work "
                    "settings, responsibilities, colleagues, and customers. Avoid obvious "
                    "one-trait stereotypes and do not repeat the same profession family. "
                    "Treat religion, family background, and cultural tone as personal context, "
                    "not evidence for choosing a religious or family institution as employer. "
                    "Each option must fit the stated economic independence and temperament "
                    "while offering a visually active daily world."
                ),
            },
            {"role": "user", "content": str(abstract_profile)},
        ],
        OCCUPATION_CANDIDATES_SCHEMA,
        max_completion_tokens=2048,
    )["candidates"]
    titles = [candidate["job_title"] for candidate in candidates]
    selection = call_llm_json(
        [
            {
                "role": "system",
                "content": (
                    "Choose one occupation for a parallel visual film. Balance credibility "
                    "with visual range and prefer the least obvious non-stereotyped casting "
                    "that still fits the abstract character. The work world should support "
                    "active scenes, varied relationships, and changing environments without "
                    "depending mainly on paperwork, approvals, or formal meetings. Do not "
                    "promote religious, family, or cultural affiliation into the employer; "
                    "those belong to personal identity unless occupation was explicitly known."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"ABSTRACT PROFILE:\n{abstract_profile}\n\n"
                    f"CANDIDATES:\n{candidates}"
                ),
            },
        ],
        _occupation_selection_schema(titles),
        max_completion_tokens=1024,
    )
    return selection


def _abstract_casting_input(dossier: dict) -> dict:
    return dossier.get("abstract_casting_signals") or {}


def _review_casting(
    abstract_profile: dict,
    source_facts: dict,
    casting: dict,
) -> list[str]:
    review = call_llm_json(
        [
            {
                "role": "system",
                "content": (
                    "Audit an independent cinematic casting against an abstract character "
                    "profile. Approve only if it chooses one concrete plausible occupation, "
                    "not alternatives or hedging; a combined title is acceptable when it clearly "
                    "describes one plausible role in a small organization, and title punctuation "
                    "or wording is outside this reviewer's scope. Approve only if it builds a "
                    "credible workplace, daily activity, "
                    "and relationship world distinct from private faith/family life; does not "
                    "turn a private religious or family institution into the employer when "
                    "the source did not state that job; infers "
                    "body, hair, ethnicity, and reusable wardrobe as deliberate casting choices "
                    "without stereotypes; each is one production-ready choice rather than open "
                    "casting, alternatives, ranges of identities, or decisions deferred to rehearsal; "
                    "specific height, shoulders, torso, hips, and build are desirable and must not "
                    "be flattened into a generic or automatically medium body. Reject body design "
                    "only when the proposal explicitly claims that its shape was caused by or inferred "
                    "from occupation, competence, age, faith, hobby, or emotional condition; and keep "
                    "the director profile plot-free. The casting "
                    "does not map one soft trait directly to a stereotyped caring/service job; "
                    "must create visual range without inventing status, wealth, or temperament "
                    "that conflicts with the abstract profile or evidence-backed source facts. "
                    "Use source facts only to catch contradictions in stable identity, status, "
                    "body, grooming, jewelry, or reusable wardrobe. Do not ask the casting to "
                    "include narrated objects, event costumes, relationships, faith practices, "
                    "locations, or plot actions. Report concise actionable issues."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"ABSTRACT PROFILE:\n{abstract_profile}\n\n"
                    f"EVIDENCE-BACKED SOURCE FACTS (contradiction audit only):\n"
                    f"{source_facts}\n\n"
                    f"PROPOSED CASTING:\n{casting}"
                ),
            },
        ],
        DOSSIER_REVIEW_SCHEMA,
        max_completion_tokens=2048,
    )
    if review.get("approved"):
        return []
    return review.get("issues") or ["casting reviewer rejected the design"]


def build(script: str) -> dict:
    messages = [
        {
            "role": "system",
            "content": (
                "Read the ENTIRE Christian story before classifying its protagonist or "
                "visual world. Build a production dossier with two clearly separated "
                "layers. SOURCE FACTS must be supported by short verbatim evidence; do "
                "not treat a comparison, hypothetical, or another character's life as "
                "the protagonist's fact. CINEMATIC INFERENCE fills unstated production "
                "details from the whole-script tone, age, lifestyle, agency, social "
                "world, and economic cues. Inference is required, but label its basis. "
                "When occupation is unstated, make a plausible cinematic choice from "
                "temperament, independence, resources, and social class. Choose exactly one "
                "occupation, not alternatives or an optional suggestion. Give it a credible "
                "workplace and daily relationship world distinct from the source's spiritual "
                "and family plot so the visual lane has somewhere independent to live. Do not turn a "
                "narrated object, faith practice, hobby, or later act of service into her "
                "job. whole_script_vibe and cinematic_inference remain reusable and "
                "plot-free: general social/professional texture and regular wardrobe, not "
                "event locations, key props, symbolic objects, or one-scene costumes. "
                "credible_locations are general environment types not copied from narrated "
                "events. Choose a coherent body, ethnicity, hair, and wardrobe design; "
                "never infer body size from 'full-body' or use body shape as shorthand for "
                "emotion, faith, or age. Clothing reflects the inferred professional and "
                "social vibe and excludes event-specific source costumes. Everyday America "
                "is texture, not a mandatory civic-volunteer "
                "plot. abstract_casting_signals is the only handoff to an independent "
                "casting call: it contains generalized age, gender, temperament, economic "
                "independence, work style, interpersonal style, wardrobe formality, and "
                "cultural tone. It must name no employer, institution, occupation, object, "
                "hobby, source event, relationship, or location. work_style contains generic "
                "behavioral modes such as methodical, collaborative, independent, precise, "
                "or adaptable, never occupation-coded skills such as teaching, mentoring, "
                "caregiving, sales, medicine, or management. "
                "The director_profile is a plot-free handoff containing only stable "
                "identity, social dynamics, professional and visual vibe, and credible "
                "worlds. It must not mention source plot events, objects, specific event "
                "locations, or retelling suggestions. Return only the dossier."
            ),
        },
        {"role": "user", "content": script},
    ]
    data = call_llm_json(messages, DOSSIER_SCHEMA, max_completion_tokens=6144)

    abstract_profile = _abstract_casting_input(data)
    occupation = _choose_occupation(abstract_profile)
    casting_messages = [
        {
            "role": "system",
            "content": (
                "You are a casting director and production designer. You do not receive "
                "the source story, its objects, actions, hobbies, or locations. From the "
                "abstract profile. The occupation has already been selected independently; "
                "use it exactly and build an "
                "independent daily work world with colleagues, clients, and credible places. "
                "A private religious or family institution cannot become the employer when "
                "the source did not state that job. Keep personal cultural texture in off-duty "
                "identity, not the profession or main plot. Avoid stereotypical one-to-one "
                "casting such as turning patience into a caring profession or organization "
                "into administration. Balance temperament with an independent, visually rich "
                "daily world. Choose body design independently for visual specificity; never "
                "use the selected job, competence, age, faith, or sadness to justify weight or "
                "build. Infer one concrete, production-ready body and ethnicity design rather "
                "than offering alternatives, open casting, or deferring the choice. Infer concrete "
                "hair, and reusable wardrobe. Describe physical design directly without explaining "
                "it as the result of work, hobbies, competence, age, faith, or emotion. "
                "design sensitively from the overall culture and production needs. Clothing "
                "must combine professional and off-duty life. The director_profile stays "
                "plot-free and gives a future director stable identity, social dynamics, "
                "professional/visual vibe, and several credible worlds. Be concise: occupation "
                "is one job title; rationale is two or three sentences; do not invent a list "
                "of duties or a future plot. Return only JSON."
            ),
        },
        {
            "role": "user",
            "content": (
                f"ABSTRACT PROFILE:\n{abstract_profile}\n\n"
                f"LOCKED OCCUPATION:\n{occupation}"
            ),
        },
    ]
    issues = []
    for _ in range(MAX_ATTEMPTS):
        if issues:
            casting_messages.append({
                "role": "user",
                "content": (
                    "Revise the complete casting to address this review:\n"
                    + "\n".join(f"- {issue}" for issue in issues)
                ),
            })
        casting = call_llm_json(
            casting_messages,
            CASTING_SCHEMA,
            max_completion_tokens=4096,
        )
        # Occupation is an upstream selection, not another free-form casting output.
        # Carry it forward structurally so harmless title paraphrases cannot break the
        # contract and so the reviewer audits the actual locked choice.
        casting["cinematic_inference"]["protagonist_occupation"] = occupation["job_title"]
        issues = _review_casting(
            abstract_profile,
            data.get("source_facts") or {},
            casting,
        )
        if not issues:
            occupation_stated = bool(
                data.get("source_facts", {}).get("occupation", {}).get("stated")
            )
            casting["cinematic_inference"]["occupation_basis"] = (
                "explicit" if occupation_stated else "creative_inference"
            )
            data.update(casting)
            data["occupation_selection"] = occupation
            data["story_dossier_contract_version"] = STORY_DOSSIER_CONTRACT_VERSION
            return data
        casting_messages.append({
            "role": "assistant",
            "content": json.dumps(casting, ensure_ascii=False),
        })
    raise RuntimeError(f"story_dossier.build() casting failed review: {issues}")


if __name__ == "__main__":
    print("ok  story_dossier schema loaded")
