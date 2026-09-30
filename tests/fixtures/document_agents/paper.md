# Noise Robustness in Grid State Estimation

## Introduction

This paper studies how measurement noise affects the accuracy of state estimation
in low voltage grids.

## Method

### Noise model

We model sensor noise as additive Gaussian noise with a standard deviation of 1%
of the nominal voltage.

### Estimation procedure

Estimates are computed with a weighted least squares solver applied to a
radial feeder topology.

## Results

Across 500 trials, the estimator's mean absolute error stayed below 0.5% for
noise levels up to 2% of nominal voltage.
