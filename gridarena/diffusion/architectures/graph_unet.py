"""
Architecture 3 — Graph Neural Network U-Net over a fixed edge topology.

Node-mixing via GCN-style message passing along a fixed edge_index.
Implemented in plain torch (scatter via index_add_) — no torch_geometric
dependency.

The topology is resolved at construction time by architectures/topology.py.
By default it uses a fully-connected graph over the node axis (which has the
same expressive reach as the Axial model's attention). A real grid adjacency
can be supplied via GridConfig-derived edge lists — see topology.get_edge_index.
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
from .topology import get_edge_index


class NodeGraphConvBlock(nn.Module):
    """
    One round of GCN-style message passing along edge_index.

    Aggregation: mean over in-neighbors, then linear transform.
    Residual connection applied after.

    x          : (B, H, C, W)
    edge_index : (2, E)  — rows are [src, dst], both directions included
    ->           (B, H, C, W)
    """
    def __init__(self, channels: int, edge_index: torch.Tensor):
        super().__init__()
        self.register_buffer("edge_index", edge_index)
        self.linear_msg = nn.Linear(channels, channels)
        self.linear_self = nn.Linear(channels, channels)
        self.norm = nn.LayerNorm(channels)
        self.act = nn.SiLU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, H, C, W = x.shape
        src, dst = self.edge_index[0], self.edge_index[1]  # (E,)

        # Operate per (B, W) slice; flatten to (B*W, H, C)
        h = x.permute(0, 3, 1, 2).reshape(B * W, H, C)   # (B*W, H, C)
        h = self.norm(h)

        # gather source features
        msgs = self.linear_msg(h[:, src, :])               # (B*W, E, C)

        # mean-aggregate into destination nodes
        agg = torch.zeros_like(h)
        count = torch.zeros(H, device=x.device)
        count.index_add_(0, dst, torch.ones(len(dst), device=x.device))
        count = count.clamp(min=1)

        # scatter msgs into agg along the H dimension
        dst_exp = dst[None, :, None].expand(B * W, -1, C)  # (B*W, E, C)
        agg.scatter_add_(1, dst_exp, msgs)
        agg = agg / count[None, :, None]

        out = self.act(self.linear_self(h) + agg)           # (B*W, H, C)
        out = out.reshape(B, W, H, C).permute(0, 2, 3, 1)  # (B, H, C, W)

        return x + out


class GraphDiffusionUNet(nn.Module):
    """
    U-Net that uses GCN-style message passing for node mixing.

    Topology is fixed at construction time via topology.get_edge_index(num_nodes,
    edge_index).

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
        num_nodes: int = 55,
        edge_index=None,
    ):
        super().__init__()
        edge_index = get_edge_index(num_nodes, edge_index)

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
            self.down_node_mix.append(NodeGraphConvBlock(c_out, edge_index))
            self.down_samples.append(TemporalDownsample(c_out))
            skips_c.append(c_out)
            c_in = c_out

        c_mid = channels[-1]
        self.mid_block1 = TemporalResBlock1D(c_mid, t_dim)
        self.mid_node_mix = NodeGraphConvBlock(c_mid, edge_index)
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
            self.up_node_mix.append(NodeGraphConvBlock(c_skip, edge_index))
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
