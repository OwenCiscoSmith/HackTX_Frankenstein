from pydantic import BaseModel, Field, ConfigDict, model_validator, ValidationError
import os
from pathlib import Path
from typing import Optional
from enum import Enum
import json
import random
import re
import sys
from dotenv import load_dotenv

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent
# Importing the schema must work without a key or a network connection. Construct
# the API client only when classify() is actually called.
DEFAULT_MODEL = "gemini-3.5-flash-lite"


def get_api_key():
    """Follow Google's key precedence when both supported variables are set."""
    return os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")


def get_model():
    return os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_MODEL


def get_client():
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
    key = get_api_key()
    if not key:
        raise ValueError(
            "Set GEMINI_API_KEY (or GOOGLE_API_KEY) in the project's "
            ".env file. To test without an API call, use --request-json."
        )
    from google import genai

    # AI Studio uses the Gemini Developer API, independent of any Vertex AI
    # configuration inherited from the hosting machine.
    return genai.Client(
        api_key=key,
        vertexai=False,
        http_options={"timeout": 60_000},
    )


animals = json.loads((BASE_DIR / "Animal_PNGS" / "animals.json").read_text(encoding="utf-8"))
allowed_tags = sorted({tag for a in animals.values() for tag in a["tags"]})
animal_reference = "\n".join(
    f"- {name}: {', '.join(info['tags'])}" for name, info in animals.items()
)


class BodySlot(str, Enum):
    TORSO = "torso"
    HEAD = "head"
    TAIL = "tail"
    FRONT_LEGS = "front_legs"
    BACK_LEGS = "back_legs"
    WINGS = "wings"
    HORN = "horn"
    EYES = "eyes"
    EARS = "ears"


class PartVariant(str, Enum):
    """Alternate forms for slots that can change type."""
    LEGS = "legs"
    ARMS = "arms"
    WINGS = "wings"
    FINS = "fins"


# Which variants are valid for which slots (slots not listed take no variant)
VALID_VARIANTS: dict[BodySlot, set[PartVariant]] = {
    BodySlot.FRONT_LEGS: {PartVariant.LEGS, PartVariant.ARMS},
    BodySlot.WINGS: {PartVariant.WINGS, PartVariant.FINS},
}


class Animal(str, Enum):
    MONKEY = "monkey"
    FISH = "fish"
    LION = "lion"
    ELEPHANT = "elephant"
    NARWHAL = "narwhal"
    BEAR = "bear"
    DOG = "dog"
    PEACOCK = "peacock"
    LIZARD = "lizard"
    ALLIGATOR = "alligator"

allowed_animals = [a.value for a in Animal]

class PartRequest(BaseModel):
    """One body part the creature needs."""
    model_config = ConfigDict(extra="forbid")

    slot: BodySlot = Field(description="Which body part this request is for")
    animal: Animal = Field(
        description="The animal this part is taken from. Required for every part, never null"
    )
    variant: Optional[PartVariant] = Field(
        default=None,
        description="Use 'arms' for front_legs or 'fins' for wings only when the "
                    "description calls for it; otherwise leave null",
    )
    count: int = Field(
        default=1, ge=1, le=8,
        description="How many of this part (e.g. 'two tails' -> 2, 'four eyes' -> 4)",
    )
    must: list[str] = Field(default_factory=list, description="Tags this part must have")
    prefer: list[str] = Field(default_factory=list, description="Tags that are preferred")
    avoid: list[str] = Field(default_factory=list, description="Tags to avoid")

    @model_validator(mode="after")
    def check_variant(self) -> "PartRequest":
        allowed = VALID_VARIANTS.get(self.slot, set())
        if self.variant is not None and self.variant not in allowed:
            raise ValueError(
                f"variant '{self.variant.value}' is not valid for slot '{self.slot.value}'"
            )
        if self.slot in {BodySlot.TORSO, BodySlot.HEAD} and self.count != 1:
            raise ValueError("the renderer supports exactly one torso and one head")
        return self


MIN_LEGS = 2
MIN_ANIMALS = 2
MAX_ANIMALS = 3

class MonsterRequest(BaseModel):
    """The user's description, classified into the parts needed to build it."""
    model_config = ConfigDict(extra="forbid")

    parts: list[PartRequest] = Field(
        description="Only the parts the creature needs; omit parts it doesn't have"
    )
    pose: Optional[str] = Field(
        default=None, description="Pose implied by the description, e.g. 'flying'"
    )

    @model_validator(mode="after")
    def check_parts(self) -> "MonsterRequest":
        slots = [p.slot for p in self.parts]
        if BodySlot.TORSO not in slots:
            raise ValueError("every creature needs a torso")
        if len(slots) != len(set(slots)):
            raise ValueError("each slot may appear only once; use 'count' for multiples")

        animals_used = {p.animal for p in self.parts}
        if not MIN_ANIMALS <= len(animals_used) <= MAX_ANIMALS:
            raise ValueError(
                f"a creature must use between {MIN_ANIMALS} and {MAX_ANIMALS} "
                f"different animals, got {len(animals_used)}: "
                f"{sorted(a.value for a in animals_used)}"
            )

        host = next(p.animal for p in self.parts if p.slot == BodySlot.TORSO)
        if host != Animal.FISH and any(
            p.animal == Animal.FISH
            and p.slot in {BodySlot.FRONT_LEGS, BodySlot.BACK_LEGS}
            for p in self.parts
        ):
            raise ValueError("fish legs are only allowed on a fish torso")

        # Count individual legs. front_legs with variant 'arms' are arms, not legs.
        leg_count = sum(
            p.count
            for p in self.parts
            if p.slot == BodySlot.BACK_LEGS
            or (p.slot == BodySlot.FRONT_LEGS and p.variant != PartVariant.ARMS)
        )
        if leg_count < MIN_LEGS:
            raise ValueError(
                f"creature needs at least {MIN_LEGS} legs (front or back), got {leg_count}"
            )
        return self

TWIST_SLOTS = ["tail", "ears", "horn", "wings", "eyes", "front_legs", "back_legs"]


def pick_silly_twists(animal_names: list[str], n: int = 2) -> list[str]:
    pool = random.sample(animal_names, 2)  # twists draw from only 2 animals
    twists = []
    for slot in random.sample(TWIST_SLOTS, n):
        animal = random.choice(pool)
        if animal == "fish" and slot in ("front_legs", "back_legs"):
            animal = next(a for a in pool if a != "fish")  # rule 14
        twists.append(f"{slot} from {animal}")
    return twists

rules = f"""\
You are a classifier for a monster image generator. The user describes a monster in everyday language. Your only job is to decide which body parts the creature needs and which tags each part should have, so the right parts can be picked from a fixed catalog. Do not describe the monster, explain your choices, or chat.

## Body slots (use exactly these values)
torso, head, tail, front_legs, back_legs, wings, horn, eyes, ears

## Variants
- front_legs: set variant to "arms" only if the creature uses humanoid or grasping arms. Otherwise leave variant null (normal legs).
- wings: set variant to "fins" only if the creature is aquatic or the user mentions fins. Otherwise leave variant null (normal wings).
- No other slot takes a variant. Never set one.

## Allowed tags
{", ".join(allowed_tags)}

{", ".join(allowed_animals)}

## Animal reference
Use this to translate animal comparisons into tags.
{animal_reference}

## Rules
1. Always include exactly one torso and one head. Use the torso's animal for the head unless the user names a different head donor. Include eyes from the head's animal unless the user explicitly excludes eyes or names a different eye donor.
2. Include a slot only if the creature has that part. If the description implies it is missing (e.g. "snake-like", "no legs", "no tail"), leave that slot out.
3. If the user doesn't mention a part but it is typical for the creature (e.g. a dog-like creature has ears, a tail and four legs), include it. Do not add horn, wings, extra eyes or other unusual parts unless the user asks or strongly implies them.
4. Each slot appears at most once. Use "count" for multiples ("two tails" -> count 2, "four eyes" -> count 4). Default count is 1.
5. Map the user's descriptive words onto the allowed tags by meaning, not just wording (e.g. "creepy" or "terrifying" -> "scary"). Never invent a tag. If nothing in the list fits, leave it out.
6. Sort tags by how strongly the user expressed them:
   - "must": explicit requirements ("definitely scary", "large wings").
   - "prefer": soft wishes or vibes ("kind of spooky", "maybe furry").
   - "avoid": negations or dislikes ("not scaly", "nothing slimy").
7. Handle negation carefully. "Not scary" puts "scary" in "avoid", never in "must" or "prefer".
8. If a tag applies to a specific part ("big wings"), put it on that part only. If it describes the whole creature ("a scary monster"), put it on the torso and any other parts it clearly applies to.
9. Set "pose" only if the user states or implies an action or pose (e.g. flying, swimming, running, sitting, standing). Otherwise set it to null. Only poses with socket transforms can change the rendered image.
10. If the input is vague, choose the fewest tags that fit rather than guessing many. Use an appropriate non-null animal for every part.
11. For each part, set "animal" to a non-null animal from the Allowed animals. Never return null or invent an animal. Map tiger to lion, wolf to dog, crocodile to alligator. Then pick one of two modes:
   a) The user names or compares to a specific animal ("lion-like", "a giant bear"). That is the main animal. It must be the torso's animal and the animal of MORE THAN HALF of the part entries (count each slot once, including head and eyes). If the user assigns a part to another animal ("a peacock's tail"), use that animal for that part. Every other part, including the minimum-legs fallback, takes the main animal. If the user names several animals, the first one named is the main animal. A comparison applies to the animal's ordinary parts, not to unrequested extras.
   b) The user names no specific animal. Use 2 or 3 different animals across the parts, never just 1 and never more than 3. Choose animals whose reference tags best fit the traits the user asked for, and spread them across the slots so no single animal covers every part. If no tags fit, choose any animals, such as dog, lion and peacock. Rule 14 still applies. When Silly twists are present, the twist animals count as part of the mix: build the creature from the twist animals plus at most one more animal, so the total never exceeds 3 different animals.
12. The app requires at least two legs (front_legs with variant arms do not count). For vague input, include torso, head, eyes and back_legs with count 2, and choose animals using rule 11b. Do not silently replace an explicit no-legs request with legs: that request is unsupported and validation will reject it.
13. The user message ends with "Silly twists", a list of random "slot from animal" pairs. Use them only when the description is vague, meaning it names no animal, or names an animal but gives almost nothing else (no extra parts or traits). When it is vague, apply every twist: set that slot's "animal" to the twist's animal, even if it clashes with the rest of the creature. Twist animals count toward the 3-animal limit, and when rule 11a applies the main animal must keep its majority. Never apply a twist if the description is specific, if it overrides something the user said, if it conflicts with a negation ("no horns"), or if it would break the 3-animal limit or the majority. Ignoring the twists when they don't apply is correct. Twists are animals, not tags, so tag limits don't apply to them.
14. Never set "animal" to "fish" on front_legs or back_legs unless the torso's animal is also "fish". This applies to silly twists and the minimum-legs fallback. If a twist would give fish legs to a non-fish torso, skip it. Use the torso's animal instead. Narwhals have no leg PNGs; use another allowed non-fish animal for requested legs on a narwhal torso.
15. A creature uses at most 3 different animals across all its parts, including the head and eyes. If the user names more than 3, keep the first 3 named, and give the parts of the others to the main animal (the torso's animal).
## Output
Return only the structured result matching the schema, with no extra text."""

examples = """\
## Examples

Input: "A bear with a peacock tail"
Output:
{
  "parts": [
    {
      "slot": "torso",
      "animal": "bear"
    },
    {
      "slot": "head",
      "animal": "bear"
    },
    {
      "slot": "tail",
      "animal": "peacock"
    },
    {
      "slot": "front_legs",
      "animal": "bear",
      "count": 2
    },
    {
      "slot": "back_legs",
      "animal": "bear",
      "count": 2
    },
    {
      "slot": "eyes",
      "animal": "bear"
    }
  ],
  "pose": null
}

Input: "A dog body with a lion head and a peacock tail, no wings"
Output:
{
  "parts": [
    {
      "slot": "torso",
      "animal": "dog"
    },
    {
      "slot": "head",
      "animal": "lion"
    },
    {
      "slot": "tail",
      "animal": "peacock"
    },
    {
      "slot": "front_legs",
      "animal": "dog",
      "count": 2
    },
    {
      "slot": "back_legs",
      "animal": "dog",
      "count": 2
    },
    {
      "slot": "eyes",
      "animal": "lion"
    }
  ],
  "pose": null
}

Input: "A flying lion with two peacock wings, two narwhal horns, and four lion eyes"
Output:
{
  "parts": [
    {
      "slot": "torso",
      "animal": "lion"
    },
    {
      "slot": "head",
      "animal": "lion"
    },
    {
      "slot": "front_legs",
      "animal": "lion",
      "count": 2
    },
    {
      "slot": "back_legs",
      "animal": "lion",
      "count": 2
    },
    {
      "slot": "eyes",
      "animal": "lion",
      "count": 4
    },
    {
      "slot": "horn",
      "animal": "narwhal",
      "count": 2
    },
    {
      "slot": "wings",
      "animal": "peacock",
      "count": 2
    }
  ],
  "pose": "flying"
}

Input: "A friendly monkey with huge arms and two back legs"
Output:
{
  "parts": [
    {
      "slot": "torso",
      "animal": "monkey",
      "must": [
        "friendly"
      ]
    },
    {
      "slot": "head",
      "animal": "monkey"
    },
    {
      "slot": "front_legs",
      "animal": "monkey",
      "variant": "arms",
      "count": 2,
      "must": [
        "large",
        "powerful"
      ]
    },
    {
      "slot": "back_legs",
      "animal": "monkey",
      "count": 2
    },
    {
      "slot": "eyes",
      "animal": "monkey"
    }
  ],
  "pose": null
}


Input: "A cute, colorful creature that can fly"
Output:
{
  "parts": [
    {"slot": "torso", "animal": "monkey", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "tail", "animal": "peacock", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "wings", "animal": "peacock", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "front_legs", "animal": "monkey", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []},
    {"slot": "back_legs", "animal": "dog", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []}
  ],
  "pose": "flying"
}

Input: "A furry creature that is kind of spooky but definitely not cute"
Output:
{
  "parts": [
    {"slot": "torso", "animal": "bear", "variant": null, "count": 1, "must": [], "prefer": ["scary"], "avoid": ["cute"]},
    {"slot": "front_legs", "animal": "bear", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": ["cute"]},
    {"slot": "back_legs", "animal": "lion", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": ["cute"]},
    {"slot": "ears", "animal": "dog", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": ["cute"]}
  ],
  "pose": null
}


Input: "A narwhal with big tusks that runs on land"
Silly twists: ears from elephant; wings from peacock
Output:
{
  "parts": [
    {"slot": "torso", "animal": "narwhal", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "head", "animal": "narwhal", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "eyes", "animal": "narwhal", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []},
    {"slot": "horn", "animal": "narwhal", "variant": null, "count": 1, "must": ["tusked", "large"], "prefer": [], "avoid": []},
    {"slot": "tail", "animal": "narwhal", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "front_legs", "animal": "dog", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []},
    {"slot": "back_legs", "animal": "dog", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []}
  ],
  "pose": "running"
}

Input: "A tough, armored swamp creature"
Silly twists: ears from dog; wings from peacock
Output:
{
  "parts": [
    {"slot": "torso", "animal": "alligator", "variant": null, "count": 1, "must": [], "prefer": ["armored", "powerful"], "avoid": []},
    {"slot": "head", "animal": "alligator", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "eyes", "animal": "alligator", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []},
    {"slot": "tail", "animal": "alligator", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "ears", "animal": "dog", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "wings", "animal": "peacock", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "front_legs", "animal": "alligator", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []},
    {"slot": "back_legs", "animal": "alligator", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []}
  ],
  "pose": null
}

Input: "A bear"
Silly twists: tail from peacock; ears from elephant
Output:
{
  "parts": [
    {"slot": "torso", "animal": "bear", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "head", "animal": "bear", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "eyes", "animal": "bear", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []},
    {"slot": "tail", "animal": "peacock", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "ears", "animal": "elephant", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "front_legs", "animal": "bear", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []},
    {"slot": "back_legs", "animal": "bear", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []}
  ],
  "pose": null
}

Input: "A lion with a peacock's tail and a bear's front legs"
Silly twists: ears from elephant; horn from narwhal
Output:
{
  "parts": [
    {"slot": "torso", "animal": "lion", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "head", "animal": "lion", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "eyes", "animal": "lion", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []},
    {"slot": "tail", "animal": "peacock", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "ears", "animal": "lion", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "front_legs", "animal": "bear", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []},
    {"slot": "back_legs", "animal": "lion", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []}
  ],
  "pose": null
}

Input: "A fish with strong legs that crawls on land"
Silly twists: tail from lion; horn from narwhal
Output:
{
  "parts": [
    {"slot": "torso", "animal": "fish", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "head", "animal": "fish", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "eyes", "animal": "fish", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []},
    {"slot": "tail", "animal": "fish", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "wings", "animal": "fish", "variant": "fins", "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "front_legs", "animal": "fish", "variant": null, "count": 2, "must": ["powerful"], "prefer": [], "avoid": []},
    {"slot": "back_legs", "animal": "fish", "variant": null, "count": 2, "must": ["powerful"], "prefer": [], "avoid": []}
  ],
  "pose": null
}

Input: "A monkey with huge arms that stands upright"
Silly twists: tail from peacock; ears from elephant
Output:
{
  "parts": [
    {"slot": "torso", "animal": "monkey", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "head", "animal": "monkey", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "eyes", "animal": "monkey", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []},
    {"slot": "tail", "animal": "monkey", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "front_legs", "animal": "monkey", "variant": "arms", "count": 2, "must": ["large"], "prefer": [], "avoid": []},
    {"slot": "back_legs", "animal": "monkey", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []}
  ],
  "pose": "standing"
}

Input: "A dog with three tails and six eyes"
Silly twists: wings from lizard; horn from elephant
Output:
{
  "parts": [
    {"slot": "torso", "animal": "dog", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "head", "animal": "dog", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "eyes", "animal": "dog", "variant": null, "count": 6, "must": [], "prefer": [], "avoid": []},
    {"slot": "tail", "animal": "dog", "variant": null, "count": 3, "must": [], "prefer": [], "avoid": []},
    {"slot": "ears", "animal": "dog", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "front_legs", "animal": "dog", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []},
    {"slot": "back_legs", "animal": "dog", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []}
  ],
  "pose": null
}

Input: "Something majestic and elegant"
Silly twists: tail from lion; ears from dog
Output:
{
  "parts": [
    {"slot": "torso", "animal": "peacock", "variant": null, "count": 1, "must": [], "prefer": ["elegant"], "avoid": []},
    {"slot": "head", "animal": "peacock", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "eyes", "animal": "peacock", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []},
    {"slot": "tail", "animal": "lion", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "ears", "animal": "dog", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "wings", "animal": "peacock", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "back_legs", "animal": "peacock", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []}
  ],
  "pose": null
}

Input: "A gentle creature with horns, nothing furry"
Silly twists: tail from lizard; ears from dog
Output:
{
  "parts": [
    {"slot": "torso", "animal": "elephant", "variant": null, "count": 1, "must": [], "prefer": ["gentle"], "avoid": ["furry"]},
    {"slot": "head", "animal": "elephant", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "eyes", "animal": "elephant", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []},
    {"slot": "tail", "animal": "lizard", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": ["furry"]},
    {"slot": "ears", "animal": "elephant", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": ["furry"]},
    {"slot": "horn", "animal": "narwhal", "variant": null, "count": 1, "must": ["horned"], "prefer": [], "avoid": []},
    {"slot": "front_legs", "animal": "elephant", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": ["furry"]},
    {"slot": "back_legs", "animal": "elephant", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": ["furry"]}
  ],
  "pose": null
}

"""


MAX_ATTEMPTS = 3


def classify(monster: str) -> MonsterRequest:
    """Use Gemini's structured output to return a validated MonsterRequest."""
    if not isinstance(monster, str) or not monster.strip():
        raise ValueError("Enter a non-empty creature description.")
    client = get_client()
    feedback = ""
    last_problems = ""
    try:
        for _ in range(MAX_ATTEMPTS):
            named_animals = [name for name in animals
                             if re.search(r'\b' + re.escape(name) + r's?\b', monster, re.I)]
            twists = [] if len(named_animals) >= 2 else pick_silly_twists(list(animals))
            try:
                response = client.interactions.create(
                    model=get_model(),
                    system_instruction=f"{rules}\n\n{examples}",
                    input=(
                        "Classify the creature description below into body parts.\n\n"
                        f"Description: {monster.strip()}\n"
                        "Interpret unnumbered plural hands/arms as a pair: front_legs, "
                        "variant arms, count 2. When both hands and legs are requested, "
                        "legs means back_legs, count 2 unless the user specifies a different count.\n"
                        f"Silly twists: {'; '.join(twists)}"
                        f"{feedback}"
                    ),
                    response_format={
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": MonsterRequest.model_json_schema(),
                    },
                    store=False,
                )
            except Exception as exc:
                # Provider errors are not retried: they will fail the same way again.
                raise RuntimeError(
                    f"Gemini classification failed ({type(exc).__name__}). Check the "
                    "Google API key, GEMINI_MODEL, API access/quota, and network."
                ) from exc

            if getattr(response, "status", None) not in {None, "completed"}:
                raise RuntimeError("Gemini did not complete the classification. Try another description.")
            text = response.output_text
            if not isinstance(text, str) or not text.strip():
                raise RuntimeError("Gemini returned no classification text. Try another description.")

            try:
                data = json.loads(text)
                # The model sometimes emits count=1 for unnumbered plural limbs.
                # Repair only this unambiguous wording before applying all rules.
                paired_hands = re.search(r'\b(hands|arms)\b', monster, re.I)
                paired_legs = re.search(r'\blegs\b', monster, re.I)
                explicit_count = re.search(r'\b(\d+|one|two|three|four|five|six|single)\b', monster, re.I)
                if paired_hands and paired_legs and not explicit_count and isinstance(data, dict):
                    for part in data.get('parts', []):
                        if isinstance(part, dict) and part.get('slot') in {'front_legs', 'back_legs'} and part.get('count', 1) == 1:
                            part['count'] = 2
                return MonsterRequest.model_validate(data)
            except json.JSONDecodeError:
                last_problems = 'Response must be valid JSON.'
                feedback = '\nReturn a valid JSON object matching the schema.'
            except ValidationError as exc:
                last_problems = "; ".join(
                    e["msg"].removeprefix("Value error, ") for e in exc.errors()
                )
                feedback = (
                    f"\n\nYour previous answer was rejected: {last_problems}. "
                    "Answer again and follow every rule. Use 2 or 3 different "
                    "animals, never just 1 and never more than 3."
                )

        raise RuntimeError(
            f"Gemini's classification still broke the creature rules after "
            f"{MAX_ATTEMPTS} attempts ({last_problems}). Try a more specific description."
        )
    finally:
        client.close()


if __name__ == "__main__":
    # Pass the description on the command line, or type it when prompted
    monster = " ".join(sys.argv[1:]) or input("Enter a monster that you want to create (give characteristics): ")
    result = classify(monster)
    print(result.model_dump_json(indent=2))

