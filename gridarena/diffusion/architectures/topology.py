"""
Edge topology for the GNN diffusion backbone.

Unlike the standalone diffusion_p_analysis project (which hardcoded a 55-node
fully-connected fallback), gridarena grids vary in size and can be merged across
several grids, so the node count is only known at training time from the loaded
dataset. This module therefore builds the topology dynamically:

  * If an explicit ``edge_index`` (shape ``(2, E)``) is supplied, it is used
    verbatim after validating that every node index is in ``[0, num_nodes)``.
  * Otherwise a fully-connected graph over ``num_nodes`` nodes is generated,
    which gives the GCN the same reach as unconstrained attention while
    remaining topology-agnostic.

To feed the *real* grid adjacency, build an edge list from the grid's
``Connection`` rows (both directions per undirected edge, node ids mapped to
the diffusion node index order) and pass it through as ``edge_index``.
"""

from typing import Optional

import torch


def fully_connected_edge_index(n: int) -> torch.Tensor:
    """All-pairs directed edges (excluding self-loops) over ``n`` nodes."""
    if n < 1:
        raise ValueError(f"num_nodes must be >= 1, got {n}")
    if n == 1:
        # A single node has no edges; return an empty (2, 0) index.
        return torch.zeros((2, 0), dtype=torch.long)
    src = torch.arange(n).repeat_interleave(n)
    dst = torch.arange(n).repeat(n)
    mask = src != dst
    return torch.stack([src[mask], dst[mask]], dim=0)


def get_edge_index(num_nodes: int, edge_index: Optional[torch.Tensor] = None) -> torch.Tensor:
    """
    Return the edge_index for a grid of ``num_nodes`` nodes.

    If ``edge_index`` is provided it is validated and returned as a long tensor;
    otherwise a fully-connected graph is built. Raises ValueError if a supplied
    edge_index references node indices outside ``[0, num_nodes)`` or is not
    shaped ``(2, E)``.
    """
    if edge_index is None:
        return fully_connected_edge_index(num_nodes)

    ei = torch.as_tensor(edge_index, dtype=torch.long)
    if ei.ndim != 2 or ei.shape[0] != 2:
        raise ValueError(f"edge_index must have shape (2, E); got {tuple(ei.shape)}")
    if ei.numel() and (int(ei.max()) >= num_nodes or int(ei.min()) < 0):
        raise ValueError(
            f"edge_index references node indices outside [0, {num_nodes})."
        )
    return ei
