from pydantic import BaseModel, Field, ConfigDict, model_validator
import openai
from langchain_openai import ChatOpenAI
import os
from pathlib import Path
from dotenv import load_dotenv
from typing import List, Optional, Literal
from enum import Enum
from langchain_core.messages import SystemMessage, HumanMessage
import json
import random
import sys

load_dotenv()


llm = ChatOpenAI(api_key=os.getenv('OPEN_AI'), model='gpt-4o-mini')


animals = json.loads(Path("Animal_PNGS/animals.json").read_text()) 
allowed_tags = sorted({tag for a in animals.values() for tag in a["tags"]})
animal_reference = "\n".join(
    f"- {name}: {', '.join(info['tags'])}" for name, info in animals.items()
)


class BodySlot(str, Enum):
    TORSO = "torso"
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
        return self


MIN_LEGS = 2

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
        if len(animals_used) > MAX_ANIMALS:
            raise ValueError(
                f"a creature may use at most {MAX_ANIMALS} different animals, "
                f"got {len(animals_used)}: {sorted(a.value for a in animals_used)}"
            )

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
    """Random 'slot from animal' pairs, e.g. 'tail from peacock'."""
    return [
        f"{slot} from {random.choice(animal_names)}"
        for slot in random.sample(TWIST_SLOTS, n)
    ]
twists = pick_silly_twists(list(animals))

rules = f"""\
You are a classifier for a monster image generator. The user describes a monster in everyday language. Your only job is to decide which body parts the creature needs and which tags each part should have, so the right parts can be picked from a fixed catalog. Do not describe the monster, explain your choices, or chat.

## Body slots (use exactly these values)
torso, tail, front_legs, back_legs, wings, horn, eyes, ears

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
1. Always include a torso. Every creature has one.
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
9. Set "pose" only if the user states or implies an action or pose, using an allowed pose. Otherwise set it to null.
10. If the input is vague, choose the fewest tags that fit rather than guessing many. If the input isn't about a creature, still return a torso with empty tag lists.
11. For each part, set "animal" to the animal that part should be taken from, using only the Allowed animals. If the user compares the creature to an animal ("lion-like", "part bear") or names an animal for one part ("a peacock's tail"), set that animal on the matching parts. A comparison to one animal applies to the parts that animal normally has (torso, tail, legs, ears), but not to extras the user didn't ask for. If the user names an animal that isn't listed, use the closest listed animal (e.g. tiger -> lion, wolf -> dog, crocodile -> alligator), or null if none is close. If no animal is implied, set "animal" to null and rely on tags. Never invent an animal.
12. If the input is vague, choose the fewest tags that fit rather than guessing many. If the input isn't about a creature, still return a torso and back_legs with count 2, both from one animal of your choice, with empty tag lists.
13. The user message ends with "Silly twists", a list of random "slot from animal" pairs. Use them only when the description is vague, meaning it names no animal, or names an animal but gives almost nothing else (no extra parts or traits). When it is vague, apply every twist: set that slot's "animal" to the twist's animal, even if it clashes with the rest of the creature. Never apply a twist if the description is specific, if it overrides something the user said, or if it conflicts with a negation ("no horns"). Ignoring the twists when they don't apply is correct. Rule 12 still limits tags, but twists are animals, not tags, so they are not limited by it.
14. Never set "animal" to "fish" on front_legs or back_legs unless the torso's animal is also "fish". This applies to everything, including silly twists and the minimum-legs fallback. If a twist would give a fish's legs to a non-fish torso, skip that twist. If the legs need an animal and the creature has fish parts but a non-fish torso, use the torso's animal, or null if the torso has none. When the torso is a fish, fish legs are fine.
15. A creature uses at most 3 different animals across all its parts. If the user names more than 3, keep the 3 mentioned first or most prominently, and give the parts of the others the torso's animal.
## Output
Return only the structured result matching the schema, with no extra text."""

examples =  """\
## Examples

Input: "A lion-like creature with a scaly tail"
Output:
{
  "parts": [
    {"slot": "torso", "animal": "lion", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "tail", "animal": "lion", "variant": null, "count": 1, "must": ["scaly"], "prefer": [], "avoid": []},
    {"slot": "front_legs", "animal": "lion", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []},
    {"slot": "back_legs", "animal": "lion", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []}
  ],
  "pose": null
}

Input: "A bear with a peacock's tail"
Output:
{
  "parts": [
    {"slot": "torso", "animal": "bear", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "tail", "animal": "peacock", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "front_legs", "animal": "bear", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []},
    {"slot": "back_legs", "animal": "bear", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []},
    {"slot": "ears", "animal": "bear", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []}
  ],
  "pose": null
}

Input: "A narwhal-like sea monster that swims"
Output:
{
  "parts": [
    {"slot": "torso", "animal": "narwhal", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "tail", "animal": "narwhal", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "back_legs", "animal": "narwhal", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []},
    {"slot": "wings", "animal": "narwhal", "variant": "fins", "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "horn", "animal": "narwhal", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "eyes", "animal": "narwhal", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []}
  ],
  "pose": "swimming"
}

Input: "A tiger-like monster"
Output:
{
  "parts": [
    {"slot": "torso", "animal": "lion", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "tail", "animal": "lion", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "front_legs", "animal": "lion", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []},
    {"slot": "back_legs", "animal": "lion", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []},
    {"slot": "ears", "animal": "lion", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []}
  ],
  "pose": null
}

Input: "A friendly dog monster with floppy ears, not scary"
Output:
{
  "parts": [
    {"slot": "torso", "animal": "dog", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": ["scary"]},
    {"slot": "tail", "animal": "dog", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": ["scary"]},
    {"slot": "front_legs", "animal": "dog", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": ["scary"]},
    {"slot": "back_legs", "animal": "dog", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": ["scary"]},
    {"slot": "ears", "animal": "dog", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []}
  ],
  "pose": null
}

Input: "A hulking monkey-like beast with huge arms, standing on two legs"
Output:
{
  "parts": [
    {"slot": "torso", "animal": "monkey", "variant": null, "count": 1, "must": ["large", "heavy"], "prefer": [], "avoid": []},
    {"slot": "front_legs", "animal": "monkey", "variant": "arms", "count": 2, "must": ["large", "powerful"], "prefer": [], "avoid": []},
    {"slot": "back_legs", "animal": "monkey", "variant": null, "count": 2, "must": ["large"], "prefer": [], "avoid": []}
  ],
  "pose": "standing"
}

Input: "A slithering lizard monster with no legs and four eyes, maybe a little slimy"
Output:
{
  "parts": [
    {"slot": "torso", "animal": "lizard", "variant": null, "count": 1, "must": [], "prefer": ["slimy"], "avoid": []},
    {"slot": "tail", "animal": "lizard", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "back_legs", "animal": "lizard", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []},
    {"slot": "eyes", "animal": "lizard", "variant": null, "count": 4, "must": [], "prefer": [], "avoid": []}
  ],
  "pose": null
}

Input: "A creepy flying peacock-like monster, not cute"
Output:
{
  "parts": [
    {"slot": "torso", "animal": "peacock", "variant": null, "count": 1, "must": ["scary"], "prefer": [], "avoid": ["cute"]},
    {"slot": "tail", "animal": "peacock", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "back_legs", "animal": "peacock", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []},
    {"slot": "wings", "animal": "peacock", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "eyes", "animal": "peacock", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []}
  ],
  "pose": "flying"
}

Input: "A furry creature that is kind of spooky but definitely not cute"
Output:
{
  "parts": [
    {"slot": "torso", "animal": "bear", "variant": null, "count": 1, "must": ["furry"], "prefer": ["scary"], "avoid": ["cute"]},
    {"slot": "front_legs", "animal": "bear", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": ["cute"]},
    {"slot": "back_legs", "animal": "bear", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": ["cute"]},
    {"slot": "ears", "animal": "bear", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": ["cute"]}
  ],
  "pose": null
}

Input: "A lion, a bear, a dog and a monkey all mixed together"
Output:
{
  "parts": [
    {"slot": "torso", "animal": "lion", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "tail", "animal": "bear", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "front_legs", "animal": "bear", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []},
    {"slot": "back_legs", "animal": "dog", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []},
    {"slot": "ears", "animal": "dog", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []}
  ],
  "pose": null
}

Input: "A weird monster"
Silly twists: tail from peacock; ears from elephant
Output:
{
  "parts": [
    {"slot": "torso", "animal": "lizard", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "tail", "animal": "peacock", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "ears", "animal": "elephant", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "back_legs", "animal": "lizard", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []}
  ],
  "pose": null
}

Input: "A scary lion with huge wings and two horns"
Silly twists: tail from peacock; eyes from fish
Output:
{
  "parts": [
    {"slot": "torso", "animal": "lion", "variant": null, "count": 1, "must": ["scary"], "prefer": [], "avoid": []},
    {"slot": "tail", "animal": "lion", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "front_legs", "animal": "lion", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []},
    {"slot": "back_legs", "animal": "lion", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []},
    {"slot": "wings", "animal": "lion", "variant": null, "count": 1, "must": ["large"], "prefer": [], "avoid": []},
    {"slot": "horn", "animal": "lion", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []}
  ],
  "pose": null
}

Input: "A strange creature"
Silly twists: back_legs from fish; tail from peacock
Output:
{
  "parts": [
    {"slot": "torso", "animal": "monkey", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "tail", "animal": "peacock", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "back_legs", "animal": "monkey", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []}
  ],
  "pose": null
}

Input: "What's the weather like today?"
Output:
{
  "parts": [
    {"slot": "torso", "animal": "dog", "variant": null, "count": 1, "must": [], "prefer": [], "avoid": []},
    {"slot": "back_legs", "animal": "dog", "variant": null, "count": 2, "must": [], "prefer": [], "avoid": []}
  ],
  "pose": null
}
"""

def classify(monster: str) -> MonsterRequest:
    """Turn a free-text monster description into a validated MonsterRequest."""
    messages = [
        SystemMessage(content=f"{rules} \n {examples}"),
        HumanMessage(content=(
            "Classify the creature description below into body parts.\n\n"
            f"Description: {monster.strip()}\n"
            f"Silly twists: {'; '.join(twists)}"
        )),
    ]
    # with_structured_output makes the model return a MonsterRequest instead of plain text
    return llm.with_structured_output(MonsterRequest).invoke(messages)


if __name__ == "__main__":
    # Pass the description on the command line, or type it when prompted
    monster = " ".join(sys.argv[1:]) or input("Enter a monster that you want to create (give characteristics): ")
    result = classify(monster)
    print(result.model_dump_json(indent=2))

