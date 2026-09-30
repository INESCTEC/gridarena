"""Request/response schemas for the MV power-flow training-data generation pipeline."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class TopologyPerturbationConfig(BaseModel):
    type: Literal["none", "n_minus_k", "random"] = "none"
    k: int = Field(
        default=1, ge=1,
        description="Max simultaneous branch outages. No fixed upper bound here -- "
                    "for type == 'n_minus_k' the enumeration itself is capped by "
                    "perturbation.MAX_N_MINUS_K_COMBOS, which raises a clear error "
                    "if the requested k/branch-count combination is infeasible.",
    )
    n_variants: int = Field(default=10, ge=1, le=2000, description="Used only when type == 'random'.")


class AdmittancePerturbationConfig(BaseModel):
    enabled: bool = False
    sigma: float = Field(default=0.2, gt=0, lt=1, description="Relative R/X perturbation, e.g. 0.2 = +/-20%.")


class PFDataGenRequest(BaseModel):
    historical_database_id: str = Field(
        description="Historical database (see gridarena/routers/historical.py) to source P/Q injections from. "
                    "Its series must all share one grid_level (MV, LV, or Feeder) -- that determines how "
                    "injections are assigned to MV connection points.",
    )
    reassignment_period_timesteps: int = Field(
        default=100, ge=1,
        description="How many consecutive scenarios (in timestamp order) share one random "
                    "series-to-point assignment before it's redrawn, e.g. 100 = reassign every "
                    "100 scenarios.",
    )
    scenario_count: int = Field(default=1000, ge=1, le=200000, description="Total timesteps to use as scenarios.")
    load_noise_sigma: float = Field(default=0.0, ge=0, lt=1, description="Optional per-bus multiplicative noise, 0 = off.")
    topology_perturbation: TopologyPerturbationConfig = TopologyPerturbationConfig()
    admittance_perturbation: AdmittancePerturbationConfig = AdmittancePerturbationConfig()
    chunk_commit_size: int = Field(default=100, ge=1, le=5000)
    seed: Optional[int] = Field(default=None, description="Base RNG seed. Omit for a fresh random seed (logged).")


class PFDataGenStartResponse(BaseModel):
    run_id: str
    status: str
    message: str


class PFDataGenRunStatus(BaseModel):
    run_id: str
    mv_grid_id: str
    status: Literal["queued", "running", "completed", "failed"]
    created_at: str
    completed_at: Optional[str] = None
    error: Optional[str] = None
    config: Optional[dict] = None
    total_scenarios: int = 0
    completed_scenarios: int = 0
    failed_scenarios: int = 0
    n_topology_variants: int = 1
    seed_used: Optional[int] = None
    metrics: Optional[dict] = None
