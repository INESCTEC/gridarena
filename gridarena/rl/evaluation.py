"""Model evaluation — loads a trained model and runs a single inference step."""

import json
import os
from pathlib import Path

import numpy as np
from stable_baselines3 import PPO

from gridarena.rl.envs.single_agent import GridStabilityEnv
from gridarena.rl.envs.multi_agent import MultiGridStabilityEnv
from gridarena.rl.schemas import GridConfig


def evaluate_model(run_dir: str, loads: list[float] = None) -> dict:
    """Load model from run_dir, run one evaluation step, return before/after comparison."""
    config_path = Path(run_dir) / "run_config.json"
    with open(config_path) as f:
        run_data = json.load(f)

    grid_config = GridConfig.from_dict(run_data["grid_config"])
    agent_type = run_data["agent_type"]

    if agent_type == "single":
        model_path = os.path.join(run_dir, "ppo_grid")
        model = PPO.load(model_path)
        env = GridStabilityEnv(grid_config)
    else:
        model_path = os.path.join(run_dir, "ppo_multiagent")
        model = PPO.load(model_path)
        env = GridStabilityEnv(grid_config)

    obs, _ = env.reset()

    if loads is not None:
        load_array = np.array(loads, dtype=np.float32)
        if len(load_array) != grid_config.n_nodes:
            raise ValueError(f"Expected {grid_config.n_nodes} loads, got {len(load_array)}")
        load_array[0] = 0.0
        env.p_kw_state = load_array
        env._run_power_flow()
        obs = env._get_obs()

    v_init = np.abs(env.v_state) / env.volt_ref
    p_init = env.p_kw_state.copy()
    violations_init = int(np.sum(np.abs(v_init - 1.0) > grid_config.violation_threshold))

    if agent_type == "multi":
        actions = np.zeros(grid_config.n_nodes, dtype=np.float32)
        for i in range(grid_config.n_nodes):
            node_obs = {
                "voltages_pu": obs["voltages_pu"][i:i+1],
                "p_normalized": obs["p_normalized"][i:i+1],
            }
            act, _ = model.predict(np.expand_dims(
                np.concatenate([node_obs["voltages_pu"], node_obs["p_normalized"]]),
                axis=0,
            ) if False else node_obs, deterministic=True)
            actions[i] = act[0] if isinstance(act, np.ndarray) else act
        action = actions
    else:
        action, _ = model.predict(obs, deterministic=True)

    obs_after, reward, _, _, info = env.step(action)

    v_final = np.abs(env.v_state) / env.volt_ref
    p_final = env.p_kw_state.copy()
    violations_final = int(np.sum(np.abs(v_final - 1.0) > grid_config.violation_threshold))

    return {
        "n_nodes": grid_config.n_nodes,
        "violations_before": violations_init,
        "violations_after": violations_final,
        "reward": float(reward),
        "nodes": [
            {
                "index": i,
                "v_init_pu": round(float(v_init[i]), 4),
                "v_final_pu": round(float(v_final[i]), 4),
                "p_init_kw": round(float(p_init[i]), 2),
                "p_final_kw": round(float(p_final[i]), 2),
            }
            for i in range(grid_config.n_nodes)
        ],
    }
