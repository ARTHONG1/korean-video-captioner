from dataclasses import dataclass

@dataclass(frozen=True)
class Cue:
    id: int
    start_ms: int
    end_ms: int
    text: str
