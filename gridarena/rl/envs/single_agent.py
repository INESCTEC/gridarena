"""Single-agent Gymnasium environment for grid voltage stability."""

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from gridarena.powerflow.powerflow_algorithm import full_pf
from gridarena.rl.schemas import GridConfig


class GridStabilityEnv(gym.Env):
    """Gymnasium environment for voltage control on a radial LV grid.

    Takes a GridConfig with dynamic topology instead of reading from a hardcoded config file.
    """

    def __init__(self, grid_config: GridConfig):
        super().__init__()

        self.grid = grid_config.grid_topology
        self.admitances = grid_config.admittances
        self.n_nodes = grid_config.n_nodes
        self.volt_ref = grid_config.volt_ref
        self.p_min_kw = grid_config.p_min_kw
        self.p_max_kw = grid_config.p_max_kw
        self.violation_threshold = grid_config.violation_threshold
        self.reward_scale = grid_config.reward_scale

        self.observation_space = spaces.Dict({
            "voltages_pu": spaces.Box(low=0.5, high=1.5, shape=(self.n_nodes,), dtype=np.float32),
            "p_normalized": spaces.Box(low=-1.0, high=1.0, shape=(self.n_nodes,), dtype=np.float32),
        })

        self.action_space = spaces.Box(low=-1.0, high=1.0, shape=(self.n_nodes,), dtype=np.float32)

    def _get_obs(self):
        v_pu = (np.abs(self.v_state) / self.volt_ref).astype(np.float32)
        p_norm = np.interp(
            self.p_kw_state, (self.p_min_kw, self.p_max_kw), (-1.0, 1.0),
        ).astype(np.float32)
        return {
            "voltages_pu": np.clip(v_pu, 0.5, 1.5),
            "p_normalized": p_norm,
        }

    def _run_power_flow(self):
        self.v_state = full_pf(
            power_measurements=self.p_kw_state,
            grid=self.grid,
            admitances=self.admitances,
            volt_pt=self.volt_ref + 0j,
        )

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.p_kw_state = np.random.uniform(
            self.p_min_kw, self.p_max_kw, size=(self.n_nodes,),
        ).astype(np.float32)
        self.p_kw_state[0] = 0.0
        self._run_power_flow()
        return self._get_obs(), {}

    def step(self, action):
        constrained_action = np.copy(action)

        constrained_action = np.where(self.p_kw_state > 0, np.minimum(constrained_action, 0), constrained_action)
        constrained_action = np.where(self.p_kw_state < 0, np.maximum(constrained_action, 0), constrained_action)
        constrained_action[self.p_kw_state == 0] = 0

        delta = constrained_action * (self.p_max_kw - self.p_min_kw) / 2.0
        new_power = self.p_kw_state + delta

        new_power = np.where(self.p_kw_state > 0, np.maximum(new_power, 0.0), new_power)
        new_power = np.where(self.p_kw_state < 0, np.minimum(new_power, 0.0), new_power)

        self.p_kw_state = np.clip(new_power, self.p_min_kw, self.p_max_kw)
        self.p_kw_state[0] = 0.0

        self._run_power_flow()
        v_pu = np.abs(self.v_state) / self.volt_ref

        dist_from_nominal = np.abs(v_pu - 1.0)
        violations = np.where(dist_from_nominal > self.violation_threshold, dist_from_nominal**2, 0)
        reward = -float(np.sum(violations) * self.reward_scale)

        info = {"applied_action": constrained_action}
        return self._get_obs(), reward, True, False, info
