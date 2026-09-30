"""
Architecture 2 — Factorized temporal-conv + cross-node attention U-Net.

Node-mixing via torch.nn.MultiheadAttention with NO positional encoding,
applied across the H (node) dimension.  This makes the operation genuinely
permutation-equivariant: shuffling rows of the input shuffles rows of the
output identically.

The factorization mirrors "spatial conv + temporal attention" used in video
diffusion models, with the two axes swapped for this domain.

Cost: O(H^2 * W) per node-mixing step.  Recommended default: needs no topology
and captures pairwise node structure via attention.
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


class NodeAttentionBlock(nn.Module):
    """
    Permutation-equivariant self-attention across the node axis H.

    x : (B, H, C, W)  ->  (B, H, C, W)

    Reshape to (B*W, H, C), apply MHA (no positional encoding), reshape back.
    """
    def __init__(self, channels: int, num_heads: int = 4):
        super().__init__()
        self.norm = nn.LayerNorm(channels)
        self.attn = nn.MultiheadAttention(
            embed_dim=channels,
            num_heads=num_heads,
            batch_first=True,
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, H, C, W = x.shape
        # treat each (batch, time) pair independently over nodes
        h = x.permute(0, 3, 1, 2).reshape(B * W, H, C)   # (B*W, H, C)
        h = self.norm(h)
        attn_out, _ = self.attn(h, h, h)
        attn_out = attn_out.reshape(B, W, H, C).permute(0, 2, 3, 1)  # (B,H,C,W)
        return x + attn_out


class AxialDiffusionUNet(nn.Module):
    """
    U-Net with factorized temporal conv (per-node, circular) + cross-node
    permutation-equivariant attention.

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
        num_heads: int = 4,
        t_dim: int = 128,
    ):
        super().__init__()
        self.t_embed = TimestepEmbedding(t_dim, t_dim)
        self.in_proj = InputProj(in_channels, base_channels)
        self.out_proj = OutputProj(base_channels, in_channels)

        channels = [base_channels * m for m in channel_mults]

        def make_chan_conv(c_in, c_out):
            return nn.Conv1d(c_in, c_out, kernel_size=1)

        self.down_blocks = nn.ModuleList()
        self.down_chan_convs = nn.ModuleList()
        self.down_samples = nn.ModuleList()
        self.down_node_mix = nn.ModuleList()

        c_in = base_channels
        skips_c = []
        for c_out in channels:
            self.down_chan_convs.append(make_chan_conv(c_in, c_out))
            level_blocks = nn.ModuleList()
            for _ in range(layers_per_block):
                level_blocks.append(TemporalResBlock1D(c_out, t_dim))
            self.down_blocks.append(level_blocks)
            self.down_node_mix.append(NodeAttentionBlock(c_out, num_heads))
            self.down_samples.append(TemporalDownsample(c_out))
            skips_c.append(c_out)
            c_in = c_out

        c_mid = channels[-1]
        self.mid_block1 = TemporalResBlock1D(c_mid, t_dim)
        self.mid_node_mix = NodeAttentionBlock(c_mid, num_heads)
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
            self.up_node_mix.append(NodeAttentionBlock(c_skip, num_heads))
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
            if h.shape[-1] != skip.shape[-1]:
                h = h[..., : skip.shape[-1]]
            h = torch.cat([h, skip], dim=2)
            h = self._apply_chan_conv(chan_conv, h)
            for blk in level_blocks:
                h = blk(h, t_emb)
            h = node_mix(h)

        return self.out_proj(h)
