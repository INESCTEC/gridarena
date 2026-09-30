"""Multi-agent PettingZoo environment for grid voltage stability."""

import functools

import numpy as np
from gymnasium import spaces
from pettingzoo import ParallelEnv
from stable_baselines3.common.vec_env import VecEnv

from gridarena.powerflow.powerflow_algorithm import full_pf
from gridarena.rl.schemas import GridConfig


class MultiGridStabilityEnv(ParallelEnv):
    """PettingZoo ParallelEnv where each grid node is an agent.

    Takes a GridConfig with dynamic topology instead of reading from a hardcoded config file.
    """

    metadata = {"render_modes": [], "name": "multi_grid_stability_v0"}

    def __init__(self, grid_config: GridConfig):
        super().__init__()

        self.grid = grid_config.grid_topology
        self.admittances = grid_config.admittances
        self.n_nodes = grid_config.n_nodes
        self.volt_ref = grid_config.volt_ref
        self.p_min_kw = grid_config.p_min_kw
        self.p_max_kw = grid_config.p_max_kw
        self.violation_threshold = grid_config.violation_threshold
        self.reward_scale = grid_config.reward_scale

        self.possible_agents = [f"node_{i}" for i in range(self.n_nodes)]
        self.agents = self.possible_agents[:]

        self.observation_spaces = {
            agent: spaces.Dict({
                "voltages_pu": spaces.Box(low=0.5, high=1.5, shape=(1,), dtype=np.float32),
                "p_normalized": spaces.Box(low=-1.0, high=1.0, shape=(1,), dtype=np.float32),
            })
            for agent in self.possible_agents
        }

        self.action_spaces = {
            agent: spaces.Box(low=-1.0, high=1.0, shape=(1,), dtype=np.float32)
            for agent in self.possible_agents
        }

    @functools.lru_cache(maxsize=None)
    def observation_space(self, agent):
        return self.observation_spaces[agent]

    @functools.lru_cache(maxsize=None)
    def action_space(self, agent):
        return self.action_spaces[agent]

    def _get_obs(self):
        v_pu = (np.abs(self.v_state) / self.volt_ref).astype(np.float32)
        v_pu_clipped = np.clip(v_pu, 0.5, 1.5)
        p_norm = np.interp(self.p_kw_state, (self.p_min_kw, self.p_max_kw), (-1, 1)).astype(np.float32)

        return {
            agent: {
                "voltages_pu": np.array([v_pu_clipped[i]], dtype=np.float32),
                "p_normalized": np.array([p_norm[i]], dtype=np.float32),
            }
            for i, agent in enumerate(self.possible_agents)
            if agent in self.agents
        }

    def _run_power_flow(self):
        self.v_state = full_pf(
            power_measurements=self.p_kw_state,
            grid=self.grid,
            admitances=self.admittances,
            volt_pt=self.volt_ref + 0j,
        )

    def reset(self, seed=None, options=None):
        self.agents = self.possible_agents[:]
        if seed is not None:
            np.random.seed(seed)

        self.p_kw_state = np.random.uniform(
            self.p_min_kw, self.p_max_kw, size=(self.n_nodes,),
        ).astype(np.float32)
        self.p_kw_state[0] = 0.0
        self._run_power_flow()

        observations = self._get_obs()
        infos = {agent: {} for agent in self.agents}
        return observations, infos

    def step(self, actions):
        if not self.agents:
            return {}, {}, {}, {}, {}

        action_array = np.zeros(self.n_nodes, dtype=np.float32)
        for i, agent in enumerate(self.possible_agents):
            if agent in actions:
                val = actions[agent]
                action_array[i] = val[0] if isinstance(val, np.ndarray) else val

        constrained_action = np.copy(action_array)
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

        rewards = {agent: reward for agent in self.agents}
        observations = self._get_obs()
        terminations = {agent: True for agent in self.agents}
        truncations = {agent: False for agent in self.agents}
        infos = {agent: {"applied_action": float(constrained_action[i])} for i, agent in enumerate(self.agents)}

        if any(terminations.values()) or any(truncations.values()):
            self.agents = []

        return observations, rewards, terminations, truncations, infos


class PettingZooVecEnvWrapper(VecEnv):
    """Wraps a PettingZoo ParallelEnv as a Stable-Baselines3 VecEnv."""

    def __init__(self, env: MultiGridStabilityEnv):
        self.env = env
        self.possible_agents = env.possible_agents
        num_envs = len(self.possible_agents)

        first_agent = self.possible_agents[0]
        observation_space = env.observation_space(first_agent)
        action_space = env.action_space(first_agent)

        super().__init__(num_envs, observation_space, action_space)
        self.current_obs = None

    def reset(self):
        obs_dict, _ = self.env.reset()
        self.current_obs = obs_dict
        return self._convert_obs(obs_dict)

    def step_async(self, actions):
        self.pending_actions = actions

    def step_wait(self):
        actions_dict = {}
        for idx, agent in enumerate(self.possible_agents):
            if agent in self.env.agents:
                actions_dict[agent] = self.pending_actions[idx]

        obs_dict, rewards_dict, terminations_dict, truncations_dict, infos_dict = self.env.step(actions_dict)

        dones = np.zeros(self.num_envs, dtype=bool)
        rewards = np.zeros(self.num_envs, dtype=np.float32)
        infos = [{} for _ in range(self.num_envs)]

        for idx, agent in enumerate(self.possible_agents):
            rewards[idx] = rewards_dict.get(agent, 0.0)
            dones[idx] = terminations_dict.get(agent, False) or truncations_dict.get(agent, False)
            infos[idx] = infos_dict.get(agent, {})

        if any(dones):
            new_obs_dict, _ = self.env.reset()
            for idx, agent in enumerate(self.possible_agents):
                infos[idx]["terminal_observation"] = obs_dict.get(agent, self.observation_space.sample())
            obs_dict = new_obs_dict

        self.current_obs = obs_dict
        return self._convert_obs(obs_dict), rewards, dones, infos

    def _convert_obs(self, obs_dict):
        voltages, p_norms = [], []
        for agent in self.possible_agents:
            obs = obs_dict.get(agent, {
                "voltages_pu": np.array([1.0], dtype=np.float32),
                "p_normalized": np.array([0.0], dtype=np.float32),
            })
            voltages.append(obs["voltages_pu"])
            p_norms.append(obs["p_normalized"])
        return {
            "voltages_pu": np.array(voltages, dtype=np.float32),
            "p_normalized": np.array(p_norms, dtype=np.float32),
        }

    @property
    def unwrapped(self):
        return self.env

    def close(self):
        pass

    def get_attr(self, attr_name, indices=None):
        if hasattr(self, attr_name):
            return [getattr(self, attr_name)] * self.num_envs
        if hasattr(self.env, attr_name):
            return [getattr(self.env, attr_name)] * self.num_envs
        raise AttributeError(f"Attribute {attr_name} not found")

    def set_attr(self, attr_name, value, indices=None):
        setattr(self.env, attr_name, value)

    def env_method(self, method_name, *method_args, **method_kwargs):
        method = getattr(self.env, method_name)
        return [method(*method_args, **method_kwargs)] * self.num_envs

    def env_is_wrapped(self, wrapper_class, indices=None):
        return [False] * self.num_envs
