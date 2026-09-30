"""
Shared temporal building blocks used by all three custom diffusion backbones.

All blocks operate on tensors shaped (B, H, C, W) where:
  H = grid nodes  (never downsampled — no real spatial hierarchy among nodes)
  W = time steps  (downsampled 2x per U-Net level)

Temporal convolutions are 1D along W, applied identically to every node
(weight-sharing across H via a reshape trick).  Circular padding is used by
default so convolutions respect the cyclic day boundary (sample 47 wraps to 0).

Ported from the standalone diffusion_p_analysis project (no Flyte / S3 deps).
"""

import math

import torch
import torch.nn as nn
import torch.nn.functional as F


# ---------------------------------------------------------------------------
# Timestep embedding (sinusoidal + MLP), shared across all architectures
# ---------------------------------------------------------------------------

class SinusoidalEmbedding(nn.Module):
    def __init__(self, dim: int):
        super().__init__()
        self.dim = dim

    def forward(self, timesteps: torch.Tensor) -> torch.Tensor:
        half = self.dim // 2
        freqs = torch.exp(
            -math.log(10000) * torch.arange(half, device=timesteps.device) / (half - 1)
        )
        args = timesteps.float()[:, None] * freqs[None]
        return torch.cat([args.cos(), args.sin()], dim=-1)


class TimestepEmbedding(nn.Module):
    """Sinusoidal embedding followed by a two-layer MLP."""
    def __init__(self, in_dim: int, out_dim: int):
        super().__init__()
        self.sin_embed = SinusoidalEmbedding(in_dim)
        self.mlp = nn.Sequential(
            nn.Linear(in_dim, out_dim),
            nn.SiLU(),
            nn.Linear(out_dim, out_dim),
        )

    def forward(self, t: torch.Tensor) -> torch.Tensor:
        return self.mlp(self.sin_embed(t))


# ---------------------------------------------------------------------------
# FiLM conditioning: scale + shift from a timestep embedding vector
# ---------------------------------------------------------------------------

class FiLM(nn.Module):
    """Applies affine conditioning:  out = scale * x + shift."""
    def __init__(self, channels: int, t_dim: int):
        super().__init__()
        self.proj = nn.Linear(t_dim, 2 * channels)

    def forward(self, x: torch.Tensor, t_emb: torch.Tensor) -> torch.Tensor:
        # x: (B*H, C, W) or (B, C)  —  t_emb: (B, t_dim)
        params = self.proj(t_emb)           # (B, 2C)
        scale, shift = params.chunk(2, dim=-1)
        return x * (1 + scale[..., None]) + shift[..., None]


# ---------------------------------------------------------------------------
# Temporal residual block  (1D conv along W, circular pad, FiLM from t)
# ---------------------------------------------------------------------------

class TemporalResBlock1D(nn.Module):
    """
    ResNet block operating along the time axis W.

    Input/output shape: (B, H, C, W)
    Internally reshapes to (B*H, C, W) for Conv1d, then reshapes back.
    """
    def __init__(self, channels: int, t_dim: int, kernel_size: int = 3, groups: int = 8):
        super().__init__()
        pad = kernel_size // 2
        self.conv1 = nn.Conv1d(channels, channels, kernel_size, padding=pad, padding_mode="circular")
        self.conv2 = nn.Conv1d(channels, channels, kernel_size, padding=pad, padding_mode="circular")
        self.norm1 = nn.GroupNorm(groups, channels)
        self.norm2 = nn.GroupNorm(groups, channels)
        self.film = FiLM(channels, t_dim)
        self.act = nn.SiLU()

    def forward(self, x: torch.Tensor, t_emb: torch.Tensor) -> torch.Tensor:
        B, H, C, W = x.shape
        h = x.reshape(B * H, C, W)

        h = self.act(self.norm1(self.conv1(h)))
        # FiLM: broadcast t_emb over H nodes
        t_rep = t_emb.unsqueeze(1).expand(B, H, -1).reshape(B * H, -1)
        h = self.film(h, t_rep)
        h = self.act(self.norm2(self.conv2(h)))

        return x + h.reshape(B, H, C, W)


# ---------------------------------------------------------------------------
# Down / up sampling along W only
# ---------------------------------------------------------------------------

class TemporalDownsample(nn.Module):
    """Halves W via stride-2 Conv1d.  H is unchanged."""
    def __init__(self, channels: int):
        super().__init__()
        self.conv = nn.Conv1d(channels, channels, kernel_size=4, stride=2, padding=1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, H, C, W = x.shape
        h = x.reshape(B * H, C, W)
        h = self.conv(h)
        return h.reshape(B, H, C, h.shape[-1])


class TemporalUpsample(nn.Module):
    """Doubles W via nearest interpolation + Conv1d.  H is unchanged."""
    def __init__(self, channels: int):
        super().__init__()
        self.conv = nn.Conv1d(channels, channels, kernel_size=3, padding=1, padding_mode="circular")

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, H, C, W = x.shape
        h = x.reshape(B * H, C, W)
        h = F.interpolate(h, scale_factor=2, mode="nearest")
        h = self.conv(h)
        return h.reshape(B, H, C, h.shape[-1])


# ---------------------------------------------------------------------------
# Input / output projections  (1 channel <-> base_channels)
# ---------------------------------------------------------------------------

class InputProj(nn.Module):
    def __init__(self, in_channels: int, base_channels: int):
        super().__init__()
        self.conv = nn.Conv1d(in_channels, base_channels, kernel_size=1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, C_in, H, W = x.shape
        h = x.permute(0, 2, 1, 3).reshape(B * H, C_in, W)
        h = self.conv(h)
        C_out = h.shape[1]
        return h.reshape(B, H, C_out, W)


class OutputProj(nn.Module):
    def __init__(self, base_channels: int, out_channels: int):
        super().__init__()
        self.norm = nn.GroupNorm(8, base_channels)
        self.conv = nn.Conv1d(base_channels, out_channels, kernel_size=1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, H, C, W = x.shape
        h = x.reshape(B * H, C, W)
        h = self.conv(F.silu(self.norm(h)))
        C_out = h.shape[1]
        return h.reshape(B, H, C_out, W).permute(0, 2, 1, 3)
