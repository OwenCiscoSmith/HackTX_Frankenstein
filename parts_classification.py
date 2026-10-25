from pydantic import BaseModel, Field, ConfigDict, model_validator
import openai
from langchain_openai import ChatOpenAI
import os
from pathlib import Path
from dotenv import load_dotenv
from typing import List, Optional, Literal
from enum import Enum
from langchain_core.messages import SystemMessage, HumanMessage

load_dotenv()

monster = input("Enter a monster that you want to create(give characteristics): ")
llm = ChatOpenAI(api_key=os.getenv('OPEN_AI'), model='gpt-4o-mini')


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


class PartRequest(BaseModel):
    """One body part the creature needs."""
    model_config = ConfigDict(extra="forbid")

    slot: BodySlot = Field(description="Which body part this request is for")
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


rules = """\
You are a classifier for a monster image generator. The user describes a monster in everyday language. Your only job is to decide which body parts the creature needs and which tags each part should have, so the right parts can be picked from a fixed catalog. Do not describe the monster, explain your choices, or chat.

## Body slots (use exactly these values)
torso, tail, front_legs, back_legs, wings, horn, eyes, ears

## Variants
- front_legs: set variant to "arms" only if the creature uses humanoid or grasping arms. Otherwise leave variant null (normal legs).
- wings: set variant to "fins" only if the creature is aquatic or the user mentions fins. Otherwise leave variant null (normal wings).
- No other slot takes a variant. Never set one.

## Allowed tags
{", ".join(allowed_tags)}

## Allowed poses
{", ".join(allowed_poses)}

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

## Output
Return only the structured result matching the schema, with no extra text."""

examples = """\
## Examples

Input: "A scary dragon with big wings and two horns that breathes fire"
Output:
{
  "parts": [
    {"slot": "torso", "must": ["scary"]},
    {"slot": "tail"},
    {"slot": "front_legs", "count": 2},
    {"slot": "back_legs", "count": 2},
    {"slot": "wings", "variant": "wings", "must": ["large"]},
    {"slot": "horn", "count": 2}
  ],
  "pose": null
}

Input: "A cute fish-like creature that swims, with four eyes"
Output:
{
  "parts": [
    {"slot": "torso", "prefer": ["cute"]},
    {"slot": "tail"},
    {"slot": "back_legs", "count": 2},
    {"slot": "wings", "variant": "fins"},
    {"slot": "eyes", "count": 4}
  ],
  "pose": "swimming"
}

Input: "A two-tailed fox monster, not scaly"
Output:
{
  "parts": [
    {"slot": "torso", "avoid": ["scaly"]},
    {"slot": "tail", "count": 2, "avoid": ["scaly"]},
    {"slot": "front_legs", "count": 2, "avoid": ["scaly"]},
    {"slot": "back_legs", "count": 2, "avoid": ["scaly"]},
    {"slot": "ears"}
  ],
  "pose": null
}

Input: "A hulking beast with huge arms that walks on two legs"
Output:
{
  "parts": [
    {"slot": "torso", "must": ["large"]},
    {"slot": "front_legs", "variant": "arms", "count": 2, "must": ["large"]},
    {"slot": "back_legs", "count": 2}
  ],
  "pose": "standing"
}
"""


messages = [
    SystemMessage(content= f"{rules} \n {examples}"),
    HumanMessage(content=(
            "Classify the creature description below into body parts.\n\n"
            f"Description: {monster.strip()}"
        ))
]

result = llm.invoke(messages)

print(result.content)

