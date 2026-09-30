"""Power Flow Routine"""

import numpy as np


def backwards_pass(grid, nodal_curr):
    """
    Performs the backward sweep of the backward/forward power flow algorithm,
    calculating the branch currents flowing through each edge of the network.

    This function propagates the current demands from the leaves of the network
    (terminal nodes) back to the root, summing all downstream nodal and branch
    currents to obtain the total current in each line segment.

    Parameters
    ----------
    grid : np.ndarray
        Array of shape (n_edges, 2), where each row [i, j] defines a directed edge
        from node `i` to node `j`. The order is assumed to correspond to a valid
        traversal of a radial (tree-structured) network.

    nodal_curr : np.ndarray
        Complex current injections at each node (in A), shape (n_nodes,).
        Typically obtained via I = conj(S / V), where S is complex power and V is voltage.

    Returns
    -------
    jotas : np.ndarray
        Complex line currents (in A) for each edge, ordered according to the input `grid`.
        Represents the total current flowing through each line, accounting for all
        downstream loads.
    """

    jotas = np.zeros(len(grid), dtype=complex)
    n_edges = len(grid)

    for i, edge in enumerate(grid[::-1]):
        node_j = edge[1]
        jotas[n_edges - 1 - i] += nodal_curr[node_j]

        for j, edge in enumerate(grid):
            if edge[0] == node_j:
                jotas[n_edges - 1 - i] += jotas[j]

    return jotas


def forward_pass(volts, grid, jotas, impedances):
    """
    Performs the forward sweep of the backward/forward power flow algorithm,
    updating the voltages at each downstream node based on upstream voltages
    and branch impedances.

    This function traverses the network in the forward direction (from root to leaves),
    applying Ohm’s Law: V_j = V_i + Z_ij * I_ij, where V_j is the voltage at the child node,
    V_i is the voltage at the parent node, Z_ij is the line impedance, and I_ij is the branch current.

    Parameters
    ----------
    volts : np.ndarray
        Complex voltage values at each node (in V or p.u.), updated in-place.

    grid : np.ndarray
        Array of shape (n_edges, 2), where each row [i, j] represents a connection
        from node `i` to node `j` (typically in a radial tree structure).

    jotas : np.ndarray
        Complex line currents (in A) for each edge, corresponding in order to `grid`.

    impedances : np.ndarray
        Complex line impedances (Z) for each edge, same order as `grid`.

    Returns
    -------
    volts : np.ndarray
        Updated complex voltage values at each node after the forward pass.
    """

    for i, edge in enumerate(grid):
        node_i = edge[0]
        node_j = edge[1]

        volts[node_j] = volts[node_i] + impedances[i] * jotas[i]

    return volts


def full_pf(power_measurements, grid, admitances, volt_pt, tol_lim=1e-10, return_diagnostics=False):
    """
    Performs a full power flow (PF) computation using a backward/forward sweep algorithm
    for a radial low-voltage distribution grid.

    This iterative method solves the nonlinear system of power flow equations by:
    - Calculating nodal currents from the given power injections and voltage estimates.
    - Performing a backward pass to compute branch currents.
    - Executing a forward pass to update node voltages.
    The process repeats until the voltage solution converges within a defined tolerance.

    Parameters
    ----------
    power_measurements : np.ndarray
        Complex power draw at each node (in VA), shape (n_nodes,), S = P + jQ.
        Load convention: positive P = consumption (pulls voltage down), negative
        P = generation/injection e.g. solar PV (pushes voltage up) -- matching
        how power_active/power_reactive are stored (see llm/docs/measurements.md).

    grid : np.ndarray
        Array defining the grid connectivity. Each row or pair in `grid` indicates
        a connection between nodes, typically in the form of edges (from_node, to_node).

    admitances : np.ndarray
        Array of complex admittance values (1/Z) for each line segment,
        corresponding in order to the connections in `grid`.

    volt_pt : complex or float
        Initial voltage magnitude or complex value used to initialise all node voltages.
        Usually the nominal voltage, e.g., 1.0 (p.u.) or 230 (V).

    tol_lim : float, optional
        Tolerance limit for convergence in both real and imaginary parts of voltages.
        Default is 1e-10.

    return_diagnostics : bool, optional
        If True, also return whether the solve converged within the iteration budget
        and how many iterations it took. Default is False, preserving the original
        single-return signature for existing callers.

    Returns
    -------
    volt_values : np.ndarray
        Complex voltage at each node after convergence (or after exhausting the
        iteration budget), shape (n_nodes,). Represents the steady-state voltage
        profile across the network.

    converged, n_iter : bool, int
        Only returned when `return_diagnostics=True`. `converged` is False if the
        tolerance was never met within the iteration budget (the returned voltages
        are then the last computed values, not a valid solution).
    """

    n_nodes = len(np.unique(grid))
    volt_values = volt_pt * np.ones(n_nodes, dtype=complex)

    converged = False
    n_iter = 0

    for _iter in range(8192):
        n_iter = _iter + 1

        old_v = np.copy(volt_values)
        # Negated: power_measurements uses load convention (positive = consumption),
        # but nodal_curr must be the current *injected into* the node from the
        # network for the backward/forward sweep below to produce a voltage drop
        # under load (and a rise under generation) -- i.e. injection convention.
        nodal_curr = -np.conj(power_measurements / volt_values)

        cable_currents = backwards_pass(grid, nodal_curr)
        volt_values = forward_pass(volt_values, grid, cable_currents, admitances**-1)

        tol_r = np.max(np.abs(np.real(old_v - volt_values)))
        tol_i = np.max(np.abs(np.imag(old_v - volt_values)))

        if (tol_r < tol_lim) and (tol_i < tol_lim):
            converged = True
            break

    if return_diagnostics:
        return volt_values, converged, n_iter
    return volt_values
