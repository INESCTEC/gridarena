from typing import Dict

from pydantic import BaseModel, Field

from gridarena.schemas.types import Phase

# Well above any realistic grid's node count -- just bounds pathological
# payloads from driving unbounded per-guess DB work.
_MAX_GUESSES = 5000


class PhaseGuessSubmission(BaseModel):
    guess_id: str
    grid_id: str
    guesses: Dict[str, Phase] = Field(max_length=_MAX_GUESSES)
