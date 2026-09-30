from dataclasses import dataclass, field
from typing import List, Literal, Optional

import numpy as np
from pydantic import BaseModel, Field


@dataclass
class GridConfig:
    """Pure-numpy grid configuration for the RL environment. No DB dependency."""

    grid_topology: np.ndarray
    admittances: np.ndarray
    n_nodes: int
    volt_ref: float = 230.0
    p_min_kw: float = -20.0
    p_max_kw: float = 30.0
    violation_threshold: float = 0.1
    reward_scale: float = 100.0

    def to_dict(self) -> dict:
        return {
            "grid_topology": self.grid_topology.tolist(),
            "admittances_real": np.real(self.admittances).tolist(),
            "admittances_imag": np.imag(self.admittances).tolist(),
            "n_nodes": self.n_nodes,
            "volt_ref": self.volt_ref,
            "p_min_kw": self.p_min_kw,
            "p_max_kw": self.p_max_kw,
            "violation_threshold": self.violation_threshold,
            "reward_scale": self.reward_scale,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GridConfig":
        admittances = np.array(d["admittances_real"]) + 1j * np.array(d["admittances_imag"])
        return cls(
            grid_topology=np.array(d["grid_topology"]),
            admittances=admittances,
            n_nodes=d["n_nodes"],
            volt_ref=d.get("volt_ref", 230.0),
            p_min_kw=d.get("p_min_kw", -20.0),
            p_max_kw=d.get("p_max_kw", 30.0),
            violation_threshold=d.get("violation_threshold", 0.1),
            reward_scale=d.get("reward_scale", 100.0),
        )


class WrapperConfig(BaseModel):
    action_penalty_weight: float = 0.5
    l1_penalty_weight: float = 10.0
    noise_level: float = 0.005
    power_balance_weight: float = 2.0
    unnecessary_act_weight: float = 1.0


class TrainRequest(BaseModel):
    grid_id: str
    agent_type: Literal["single", "multi"] = "single"
    timesteps: int = Field(default=5000, ge=1000, le=10_000_000)
    violation_threshold: float = Field(default=0.1, gt=0.0, le=0.5)
    reward_scale: float = Field(default=100.0, gt=0.0)
    p_min_kw: float = Field(default=-20.0)
    p_max_kw: float = Field(default=30.0)
    volt_ref: float = Field(default=230.0, gt=0.0)
    admittance_scale: float = Field(default=1.0, gt=0.0)
    active_wrappers: List[Literal[
        "ActionPenalty", "L1ActionPenalty", "ObservationNoise",
        "PowerBalance", "StablePenalty",
    ]] = ["ActionPenalty", "ObservationNoise"]
    wrapper_config: WrapperConfig = WrapperConfig()
    device: Literal["cpu", "cuda"] = "cpu"


class TrainResponse(BaseModel):
    run_id: str
    status: str
    message: str


class RunStatus(BaseModel):
    run_id: str
    grid_id: str
    agent_type: str
    status: Literal["queued", "running", "completed", "failed"]
    created_at: str
    completed_at: Optional[str] = None
    timesteps: int = 0
    error: Optional[str] = None
    metrics: Optional[dict] = None


class EvaluateRequest(BaseModel):
    loads: Optional[List[float]] = None
