"""Topology and admittance perturbation for the MV PF data-generation pipeline.

MV (and LV) grids in this codebase are strictly radial trees -- the
backward/forward-sweep solver (powerflow/powerflow_algorithm.py::full_pf)
requires it, and nothing in the schema models mesh/tie-switch redundancy.
That means every branch is a cut-edge: disabling any single connection
always islands the subtree below it. Rather than reject nearly every
candidate (the reference pipeline's "keep only if still a single connected
component, otherwise discard" rule, written for meshed transmission-style
test cases), a topology variant here is always accepted: the
substation-connected remainder is what gets solved, and the islanded nodes
are simply excluded from that variant's output. This mirrors what a real
N-1 fault on a radial feeder actually does.

Because nothing is ever discarded, there is no rejection-sampling loop --
`random` mode draws each variant directly.
"""

import itertools
from dataclasses import dataclass, field
from math import comb
from typing import Dict, List, Set, Tuple

import numpy as np

from gridarena.pf_datagen.grid_loader import MVBranch, substation_connected_component
from gridarena.pf_datagen.schemas import TopologyPerturbationConfig

MAX_N_MINUS_K_COMBOS = 5000


@dataclass
class TopologyVariant:
    variant_idx: int
    disabled_connection_ids: Set[str] = field(default_factory=set)
    energised_node_ids: Set[str] = field(default_factory=set)


def build_variants(
    config: TopologyPerturbationConfig, branches: List[MVBranch], node_ids: List[str],
    substation_node_id: str, rng: np.random.Generator,
) -> List[TopologyVariant]:
    if config.type == "none":
        return [TopologyVariant(0, set(), set(node_ids))]
    if config.type == "n_minus_k":
        return _build_n_minus_k_variants(branches, node_ids, substation_node_id, config.k)
    if config.type == "random":
        return _build_random_variants(branches, node_ids, substation_node_id, config.k, config.n_variants, rng)
    raise Exception(f"Unknown topology_perturbation.type '{config.type}'.")


def _build_n_minus_k_variants(
    branches: List[MVBranch], node_ids: List[str], substation_node_id: str, k: int,
) -> List[TopologyVariant]:
    connection_ids = [b.connection_id for b in branches]
    all_active = set(connection_ids)

    n_combos = sum(comb(len(connection_ids), j) for j in range(0, k + 1))
    if n_combos > MAX_N_MINUS_K_COMBOS:
        raise Exception(
            f"n_minus_k with k={k} over {len(connection_ids)} connections would enumerate "
            f"{n_combos} variants (limit {MAX_N_MINUS_K_COMBOS}). Lower k or use 'random' instead."
        )

    variants = []
    idx = 0
    for j in range(0, k + 1):
        for combo in itertools.combinations(connection_ids, j):
            disabled = set(combo)
            active = all_active - disabled
            energised = substation_connected_component(node_ids, branches, active, substation_node_id)
            variants.append(TopologyVariant(idx, disabled, energised))
            idx += 1
    return variants


def _build_random_variants(
    branches: List[MVBranch], node_ids: List[str], substation_node_id: str,
    k: int, n_variants: int, rng: np.random.Generator,
) -> List[TopologyVariant]:
    connection_ids = np.array([b.connection_id for b in branches])
    all_active = set(connection_ids.tolist())

    variants = []
    for idx in range(n_variants):
        r = min(int(rng.integers(1, k + 1)), len(connection_ids))
        disabled = set(rng.choice(connection_ids, size=r, replace=False).tolist())
        active = all_active - disabled
        energised = substation_connected_component(node_ids, branches, active, substation_node_id)
        variants.append(TopologyVariant(idx, disabled, energised))
    return variants


def perturb_admittances(
    branches: List[MVBranch], sigma: float, rng: np.random.Generator,
) -> Dict[str, Tuple[float, float]]:
    """Redraw each branch's R/X uniformly in [(1-sigma)*orig, (1+sigma)*orig],
    relative to the branch's original per-km impedance (spec section 5).
    Returns {connection_id: (r_ohm_per_km, x_ohm_per_km)}. Drawn once per
    topology variant (not per scenario) -- a cable's physical impedance is a
    property of the branch itself, not of a specific timestamp."""
    lower = max(0.0, 1 - sigma)
    upper = 1 + sigma
    out = {}
    for b in branches:
        r = rng.uniform(lower * b.r_ohm_per_km, upper * b.r_ohm_per_km)
        x = rng.uniform(lower * b.x_ohm_per_km, upper * b.x_ohm_per_km)
        out[b.connection_id] = (r, x)
    return out
