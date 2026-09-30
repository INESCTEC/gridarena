"""Top-level training functions executed in subprocesses via ProcessPoolExecutor."""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import DummyVecEnv

from gridarena.rl.envs.multi_agent import MultiGridStabilityEnv, PettingZooVecEnvWrapper
from gridarena.rl.envs.single_agent import GridStabilityEnv
from gridarena.rl.schemas import GridConfig, WrapperConfig
from gridarena.rl.wrappers import apply_wrappers

logger = logging.getLogger(__name__)


class TrainingLogger(BaseCallback):
    def __init__(self, verbose=0):
        super().__init__(verbose)
        self.episode_rewards = []
        self.episode_violations = []
        self._current_ep_reward = 0.0

    def _on_step(self) -> bool:
        self._current_ep_reward += self.locals["rewards"][0]
        if self.locals["dones"][0]:
            self.episode_rewards.append(self._current_ep_reward)
            env_raw = self.training_env.envs[0].unwrapped
            v_pu = np.abs(env_raw.v_state) / env_raw.volt_ref
            num_violations = int(np.sum(np.abs(v_pu - 1.0) > env_raw.violation_threshold))
            self.episode_violations.append(num_violations)
            self._current_ep_reward = 0.0
        return True


class MultiAgentTrainingLogger(BaseCallback):
    def __init__(self, verbose=0):
        super().__init__(verbose)
        self.episode_rewards = []
        self.episode_violations = []
        self._current_ep_reward = 0.0

    def _on_step(self) -> bool:
        self._current_ep_reward += self.locals["rewards"][0]
        if self.locals["dones"][0]:
            self.episode_rewards.append(self._current_ep_reward)
            env_raw = self.training_env.unwrapped
            v_pu = np.abs(env_raw.v_state) / env_raw.volt_ref
            num_violations = int(np.sum(np.abs(v_pu - 1.0) > env_raw.violation_threshold))
            self.episode_violations.append(num_violations)
            self._current_ep_reward = 0.0
        return True


def _update_run_config(run_dir: str, updates: dict):
    config_path = Path(run_dir) / "run_config.json"
    with open(config_path) as f:
        data = json.load(f)
    data.update(updates)
    with open(config_path, "w") as f:
        json.dump(data, f, indent=2)


def run_training(run_dir: str) -> dict:
    """Top-level picklable function for subprocess execution.

    Reads config from run_dir/run_config.json, trains the model,
    saves artifacts, and updates the config with results.
    """
    import matplotlib
    matplotlib.use("Agg")

    config_path = Path(run_dir) / "run_config.json"
    with open(config_path) as f:
        run_data = json.load(f)

    _update_run_config(run_dir, {"status": "running"})

    try:
        grid_config = GridConfig.from_dict(run_data["grid_config"])
        agent_type = run_data["agent_type"]
        timesteps = run_data["timesteps"]
        active_wrappers = run_data.get("active_wrappers", [])
        wrapper_config = WrapperConfig(**run_data.get("wrapper_config", {}))
        device = run_data.get("device", "cpu")

        if agent_type == "single":
            model_name = "ppo_grid"
            rewards_name = "rewards.npy"
            violations_name = "violations.npy"

            def make_env():
                env = GridStabilityEnv(grid_config)
                env = apply_wrappers(env, active_wrappers, wrapper_config)
                env = Monitor(env)
                return env

            vec_env = DummyVecEnv([make_env])
            model = PPO(policy="MultiInputPolicy", env=vec_env, verbose=0, device=device)
            cb = TrainingLogger()
            model.learn(total_timesteps=timesteps, callback=cb, progress_bar=False)

        else:
            model_name = "ppo_multiagent"
            rewards_name = "marl_rewards.npy"
            violations_name = "marl_violations.npy"

            raw_env = MultiGridStabilityEnv(grid_config)
            vec_env = PettingZooVecEnvWrapper(raw_env)
            model = PPO(policy="MultiInputPolicy", env=vec_env, verbose=0, device=device)
            cb = MultiAgentTrainingLogger()
            total = timesteps * grid_config.n_nodes
            model.learn(total_timesteps=total, callback=cb, progress_bar=False)

        model.save(os.path.join(run_dir, model_name))
        np.save(os.path.join(run_dir, rewards_name), np.array(cb.episode_rewards))
        np.save(os.path.join(run_dir, violations_name), np.array(cb.episode_violations))

        metrics = {
            "total_episodes": len(cb.episode_rewards),
            "mean_reward": float(np.mean(cb.episode_rewards[-100:])) if cb.episode_rewards else 0.0,
            "mean_violations": float(np.mean(cb.episode_violations[-100:])) if cb.episode_violations else 0.0,
        }

        _update_run_config(run_dir, {
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "metrics": metrics,
        })

        return {"status": "completed", "metrics": metrics}

    except Exception as e:
        logger.error("Training failed: %s", e, exc_info=True)
        _update_run_config(run_dir, {
            "status": "failed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
        })
        return {"status": "failed", "error": str(e)}
