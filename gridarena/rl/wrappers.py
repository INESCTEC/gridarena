"""Reward-shaping wrappers for the grid stability environment."""

import gymnasium as gym
import numpy as np


class ActionPenaltyWrapper(gym.Wrapper):
    def __init__(self, env, penalty_weight=0.5):
        super().__init__(env)
        self.penalty_weight = penalty_weight

    def step(self, action):
        obs, reward, terminated, truncated, info = self.env.step(action)
        applied_action = info.get("applied_action", action)
        penalty = self.penalty_weight * np.sum(np.square(applied_action))
        return obs, reward - penalty, terminated, truncated, info


class ObservationNoiseWrapper(gym.ObservationWrapper):
    def __init__(self, env, noise_level=0.005):
        super().__init__(env)
        self.noise_level = noise_level

    def observation(self, obs):
        noise = np.random.normal(0, self.noise_level, size=obs["voltages_pu"].shape)
        low = self.env.observation_space["voltages_pu"].low
        high = self.env.observation_space["voltages_pu"].high
        obs["voltages_pu"] = np.clip(obs["voltages_pu"] + noise, low, high)
        return obs


class PowerBalanceWrapper(gym.Wrapper):
    def __init__(self, env, penalty_weight=2.0):
        super().__init__(env)
        self.penalty_weight = penalty_weight

    def step(self, action):
        p_init_sum = np.sum(self.env.unwrapped.p_kw_state)
        obs, reward, terminated, truncated, info = self.env.step(action)
        p_final_sum = np.sum(self.env.unwrapped.p_kw_state)
        penalty = self.penalty_weight * abs(p_final_sum - p_init_sum)
        return obs, reward - penalty, terminated, truncated, info


class L1ActionPenaltyWrapper(gym.Wrapper):
    def __init__(self, env, penalty_weight=10.0):
        super().__init__(env)
        self.penalty_weight = penalty_weight

    def step(self, action):
        obs, reward, terminated, truncated, info = self.env.step(action)
        applied_action = info.get("applied_action", action)
        penalty = self.penalty_weight * np.linalg.norm(applied_action, ord=1)
        info["penalty_l1"] = penalty
        return obs, reward - penalty, terminated, truncated, info


class StablePenalty(gym.Wrapper):
    def __init__(self, env, penalty_weight=0.5, unnecessary_act_weight=1.0):
        super().__init__(env)
        self.penalty_weight = penalty_weight
        self.unnecessary_act_weight = unnecessary_act_weight

    def step(self, action):
        v_pu_before = self.env.unwrapped._get_obs()["voltages_pu"]
        is_stable = np.all(np.abs(v_pu_before - 1.0) <= self.env.unwrapped.violation_threshold)

        obs, reward, terminated, truncated, info = self.env.step(action)

        applied_action = info.get("applied_action", action)
        penalty = self.penalty_weight * np.sum(np.square(applied_action))

        unnecessary = 0.0
        if is_stable:
            mag = np.sum(np.square(applied_action))
            if mag > 1e-4:
                unnecessary = self.unnecessary_act_weight * mag

        info["unnecessary_penalty"] = unnecessary
        return obs, reward - penalty - unnecessary, terminated, truncated, info


WRAPPER_MAP = {
    "ActionPenalty": ActionPenaltyWrapper,
    "L1ActionPenalty": L1ActionPenaltyWrapper,
    "ObservationNoise": ObservationNoiseWrapper,
    "PowerBalance": PowerBalanceWrapper,
    "StablePenalty": StablePenalty,
}

WRAPPER_PARAM_MAP = {
    "ActionPenalty": lambda cfg: {"penalty_weight": cfg.action_penalty_weight},
    "L1ActionPenalty": lambda cfg: {"penalty_weight": cfg.l1_penalty_weight},
    "ObservationNoise": lambda cfg: {"noise_level": cfg.noise_level},
    "PowerBalance": lambda cfg: {"penalty_weight": cfg.power_balance_weight},
    "StablePenalty": lambda cfg: {"penalty_weight": cfg.action_penalty_weight, "unnecessary_act_weight": cfg.unnecessary_act_weight},
}


def apply_wrappers(env, active_wrappers, wrapper_config):
    for name in active_wrappers:
        cls = WRAPPER_MAP.get(name)
        if cls:
            params = WRAPPER_PARAM_MAP[name](wrapper_config)
            env = cls(env, **params)
    return env
