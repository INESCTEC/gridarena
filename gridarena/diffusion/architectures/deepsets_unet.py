"""
Architecture 1 — Deep Sets permutation-invariant U-Net.

Node-mixing via the classic rho(x_i, sum_j phi(x_j)) pattern:
  phi : per-node MLP
  sum : mean + max pooling across H (permutation-invariant)
  rho : per-node MLP that takes [x_i || global] as input

Cost: O(H) — cheapest of the three options.
Limitation: each node only sees global summary statistics, not pairwise structure.
"""

import torch
import torch.nn as nn

from .temporal_blocks import (
    TimestepEmbedding,
    TemporalResBlock1D,
    TemporalDownsample,
    TemporalUpsample,
    InputProj,
    OutputProj,
)


class NodeSetBlock(nn.Module):
    """
    Deep-Sets node mixing: permutation-equivariant over the H axis.

    x : (B, H, C, W)  ->  (B, H, C, W)
    """
    def __init__(self, channels: int):
        super().__init__()
        self.phi = nn.Sequential(
            nn.Linear(channels, channels),
            nn.SiLU(),
            nn.Linear(channels, channels),
        )
        # global aggregation produces 2*C (mean and max concatenated)
        self.rho = nn.Sequential(
            nn.Linear(3 * channels, channels),
            nn.SiLU(),
            nn.Linear(channels, channels),
        )
        self.norm = nn.LayerNorm(channels)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, H, C, W = x.shape
        # operate independently per (B, W) slice
        h = x.permute(0, 3, 1, 2)          # (B, W, H, C)
        h = self.norm(h)

        phi_h = self.phi(h)                 # (B, W, H, C)
        g_mean = phi_h.mean(dim=2, keepdim=True).expand_as(phi_h)
        g_max = phi_h.max(dim=2, keepdim=True).values.expand_as(phi_h)

        combined = torch.cat([h, g_mean, g_max], dim=-1)  # (B, W, H, 3C)
        out = self.rho(combined)            # (B, W, H, C)

        return x + out.permute(0, 2, 3, 1)  # residual, back to (B, H, C, W)


class DeepSetsDiffusionUNet(nn.Module):
    """
    U-Net that uses Deep-Sets node mixing.

    forward(x, t) -> noise prediction, same shape as x.
      x : (B, 1, H, W)
      t : (B,)  diffusion timestep indices
    """
    def __init__(
        self,
        in_channels: int = 1,
        base_channels: int = 64,
        channel_mults: tuple = (1, 2, 4),
        layers_per_block: int = 2,
        t_dim: int = 128,
    ):
        super().__init__()
        self.t_embed = TimestepEmbedding(t_dim, t_dim)
        self.in_proj = InputProj(in_channels, base_channels)
        self.out_proj = OutputProj(base_channels, in_channels)

        channels = [base_channels * m for m in channel_mults]

        # channel transition convolutions between levels
        def make_chan_conv(c_in, c_out):
            return nn.Conv1d(c_in, c_out, kernel_size=1)

        self.down_blocks = nn.ModuleList()
        self.down_chan_convs = nn.ModuleList()
        self.down_samples = nn.ModuleList()
        self.down_node_mix = nn.ModuleList()

        c_in = base_channels
        skip_channels = []
        for c_out in channels:
            self.down_chan_convs.append(make_chan_conv(c_in, c_out))
            level_blocks = nn.ModuleList()
            for _ in range(layers_per_block):
                level_blocks.append(TemporalResBlock1D(c_out, t_dim))
            self.down_blocks.append(level_blocks)
            self.down_node_mix.append(NodeSetBlock(c_out))
            self.down_samples.append(TemporalDownsample(c_out))
            skip_channels.append(c_out)
            c_in = c_out

        c_mid = channels[-1]
        self.mid_block1 = TemporalResBlock1D(c_mid, t_dim)
        self.mid_node_mix = NodeSetBlock(c_mid)
        self.mid_block2 = TemporalResBlock1D(c_mid, t_dim)

        self.up_blocks = nn.ModuleList()
        self.up_chan_convs = nn.ModuleList()
        self.up_samples = nn.ModuleList()
        self.up_node_mix = nn.ModuleList()

        for c_skip in reversed(channels):
            self.up_samples.append(TemporalUpsample(c_in))
            self.up_chan_convs.append(make_chan_conv(c_in + c_skip, c_skip))
            level_blocks = nn.ModuleList()
            for _ in range(layers_per_block):
                level_blocks.append(TemporalResBlock1D(c_skip, t_dim))
            self.up_blocks.append(level_blocks)
            self.up_node_mix.append(NodeSetBlock(c_skip))
            c_in = c_skip

    def _apply_chan_conv(self, conv: nn.Conv1d, x: torch.Tensor) -> torch.Tensor:
        B, H, C, W = x.shape
        h = x.reshape(B * H, C, W)
        h = conv(h)
        return h.reshape(B, H, h.shape[1], W)

    def forward(self, x: torch.Tensor, t: torch.Tensor) -> torch.Tensor:
        t_emb = self.t_embed(t)
        h = self.in_proj(x)

        skips = []
        for chan_conv, level_blocks, node_mix, down in zip(
            self.down_chan_convs, self.down_blocks, self.down_node_mix, self.down_samples
        ):
            h = self._apply_chan_conv(chan_conv, h)
            for blk in level_blocks:
                h = blk(h, t_emb)
            h = node_mix(h)
            skips.append(h)
            h = down(h)

        h = self.mid_block1(h, t_emb)
        h = self.mid_node_mix(h)
        h = self.mid_block2(h, t_emb)

        for up, chan_conv, level_blocks, node_mix in zip(
            self.up_samples, self.up_chan_convs, self.up_blocks, self.up_node_mix
        ):
            h = up(h)
            skip = skips.pop()
            # align W if off-by-one from odd sizes
            if h.shape[-1] != skip.shape[-1]:
                h = h[..., : skip.shape[-1]]
            h = torch.cat([h, skip], dim=2)
            h = self._apply_chan_conv(chan_conv, h)
            for blk in level_blocks:
                h = blk(h, t_emb)
            h = node_mix(h)

        return self.out_proj(h)
