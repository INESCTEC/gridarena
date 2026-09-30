"""Custom permutation-aware diffusion backbones for grid power data.

Three node-mixing strategies over a shared 1D temporal-conv U-Net backbone,
ported from the standalone diffusion_p_analysis project (Flyte/S3 removed):

  * deepsets — Deep Sets mean/max pooling (cheapest, global summary only)
  * axial    — cross-node self-attention (recommended default, pairwise)
  * gnn      — GCN message passing over an edge topology (fully-connected by
               default; accepts a real adjacency)

All operate on (B, 1, H, W) tensors where H = grid nodes (never downsampled)
and W = intra-day time steps (downsampled 2x per level). None require an even
node count, so — unlike the diffusers UNet2DModel — they work for any grid.
"""

from .axial_unet import AxialDiffusionUNet
from .deepsets_unet import DeepSetsDiffusionUNet
from .graph_unet import GraphDiffusionUNet

__all__ = ["DeepSetsDiffusionUNet", "AxialDiffusionUNet", "GraphDiffusionUNet"]
