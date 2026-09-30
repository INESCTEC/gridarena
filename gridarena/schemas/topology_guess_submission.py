from typing import List, Tuple

from pydantic import BaseModel, Field

# Well above any realistic grid's edge count -- just bounds pathological
# payloads from driving unbounded per-guess DB work.
_MAX_GUESSES = 5000


class TopologyGuessSubmission(BaseModel):
    guess_id: str
    grid_id: str
    guesses: List[Tuple[int, int]] = Field(max_length=_MAX_GUESSES)