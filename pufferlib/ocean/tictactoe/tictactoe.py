import gymnasium
import numpy as np

import pufferlib
from pufferlib.ocean.tictactoe import binding


class TicTacToe(pufferlib.PufferEnv):
    def __init__(self, num_envs=1, render_mode=None, report_interval=128, buf=None, seed=0):
        self.single_observation_space = gymnasium.spaces.Box(
            low=-1.0, high=1.0, shape=(9,), dtype=np.float32
        )
        self.single_action_space = gymnasium.spaces.Discrete(9)
        self.report_interval = report_interval
        self.render_mode = render_mode
        self.num_agents = num_envs

        super().__init__(buf=buf)
        self.c_envs = binding.vec_init(
            self.observations, self.actions, self.rewards,
            self.terminals, self.truncations, num_envs, seed
        )
        self.tick = 0

    def reset(self, seed=None):
        self.tick = 0
        binding.vec_reset(self.c_envs, 0 if seed is None else seed)
        return self.observations, []

    def step(self, actions):
        self.actions[:] = actions
        binding.vec_step(self.c_envs)
        self.tick += 1

        info = []
        if self.tick % self.report_interval == 0:
            log = binding.vec_log(self.c_envs)
            if log.get('episode_length', 0) > 0:
                info.append(log)

        return (self.observations, self.rewards, self.terminals, self.truncations, info)

    def render(self):
        binding.vec_render(self.c_envs, 0)

    def close(self):
        binding.vec_close(self.c_envs)
