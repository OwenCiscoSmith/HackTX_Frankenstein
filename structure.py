from pydantic import BaseModel, Field, ConfigDict
import openai
from langchain_openai import ChatOpenAI
import os
from pathlib import Path
from dotenv import load_dotenv
from typing import List, Optional


load_dotenv();


llm = ChatOpenAI(api_key=os.getenv('OPEN_AI'), model='gpt-4o-mini')

Coord = tuple[float, float]  # (x, y)



class PoseOverride(BaseModel):
    """Adjustments applied to a socket's attachment when a pose is active."""
    model_config = ConfigDict(extra="forbid")

    angle: float = Field(default=0.0, description="Change in angle (delta added to the socket angle)")
    scale: float = Field(default=1.0, gt=0, description="Scale multiplier")


class Socket(BaseModel):
    """A point on this part where a child part can attach."""
    model_config = ConfigDict(extra="forbid")

    at: Coord = Field(description="[x, y] position of the socket on this part")
    angle: float = Field(default=0.0, description="Rotation applied to the attached part")
    layer: int = Field(default=0, description="Draw order for the attached part")
    must: list[str] = Field(default_factory=list, description="Tags the child part must have")
    prefer: list[str] = Field(default_factory=list, description="Tags that make a child more likely to be picked")
    avoid: list[str] = Field(default_factory=list, description="Tags that make a child less likely to be picked")
    pose: dict[str, PoseOverride] = Field(
        default_factory=dict,
        description="Per-pose overrides keyed by pose name, e.g. 'flying'",
    )



class Part(BaseModel):
    """A single cut-out creature part taken from a real animal image."""
    model_config = ConfigDict(extra="forbid")

    file: Path = Field(description="Path to the part's image file")
    slot: str = Field(description="What kind of part this is, e.g. mouth, arms, legs, torso")
    plug: Optional[Coord] = Field(
        default=None,
        description="[x, y] where this part slots into its parent; None for root parts like the torso",
    )
    layer: int = Field(description="Draw order (z); lower layers are drawn first")
    recolor: bool = Field(default=False, description="Whether this part should be recolored")
    tags: list[str] = Field(default_factory=list, description="Descriptors used to filter parts")
    sockets: dict[str, list[Socket]] = Field(
        default_factory=dict,
        description="Named attachment points; each name maps to one or more socket placements (e.g. left/right)",
    )


class PartsCatalog(BaseModel):
    """Top-level structure: the full dictionary of parts."""
    model_config = ConfigDict(extra="forbid")

    parts: dict[str, Part]



