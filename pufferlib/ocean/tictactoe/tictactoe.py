import numpy as np
import gymnasium as gym
from pettingzoo import AECEnv
from pettingzoo.utils.conversions import turn_based_aec_to_parallel
import pufferlib

from pufferlib.ocean.tictactoe import binding

class TicTacToe(AECEnv):
    """
    TicTacToe environment using PettingZoo's AEC (Agent Environment Cycle) API.
    This is the natural fit for turn-based games where agents act sequentially.

    For self-play training with a single policy, both agents see equivalent observations
    when flip_perspective=True (default).
    """
    metadata = {
        'render_modes': ['human'],
        'name': 'tictactoe_v0',
    }

    def __init__(
        self,
        seed: int | None = None,
        flip_perspective: bool = True,
        random_open_prob: float = 0.0,
        random_open_depth: int = 0,
    ) -> None:
        super().__init__()
        self.possible_agents = ['X', 'O']
        self.flip_perspective = flip_perspective
        self._pending_terminal = False
        self.random_open_prob = float(random_open_prob)
        self.random_open_prob = max(0.0, min(1.0, self.random_open_prob))
        self.random_open_depth = max(0, int(random_open_depth))

        # C binding arrays
        self._obs = np.zeros(9, dtype=np.float32)
        self._actions = np.zeros(1, dtype=np.int32)
        self._rewards = np.zeros(1, dtype=np.float32)
        self._terminals = np.zeros(1, dtype=np.bool_)
        self._truncations = np.zeros(1, dtype=np.bool_)

        self.c_envs = binding.env_init(
            self._obs,
            self._actions,
            self._rewards,
            self._terminals,
            self._truncations,
            int(seed or 0),
            random_open_prob=self.random_open_prob,
            random_open_depth=self.random_open_depth,
        )

        # AEC state
        self.agents = []
        self._agent_selection = None
        self.rewards = {}
        self._cumulative_rewards = {}
        self.terminations = {}
        self.truncations = {}
        self.infos = {}

    def observation_space(self, agent):
        return gym.spaces.Box(low=-1, high=1, shape=(9,), dtype=np.float32)

    def action_space(self, agent):
        return gym.spaces.Discrete(9)

    @property
    def agent_selection(self):
        """Current agent whose turn it is to act."""
        return self._agent_selection

    def observe(self, agent):
        """
        Get observation for a specific agent.

        When flip_perspective=True (default for self-play):
        - X sees board as-is (X=+1, O=-1, empty=0)
        - O sees negated board (O=+1, X=-1, empty=0)

        This ensures both agents learn the same policy regardless of role.
        """
        obs = self._obs.copy()
        if agent == 'O' and self.flip_perspective:
            obs = -obs
        return obs

    def close(self):
        binding.env_close(self.c_envs)

    def render(self):
        binding.env_render(self.c_envs)

    def reset(self, seed=None, options=None):
        """
        Reset the game. Starting player is randomized in C code for balanced self-play.
        """
        binding.env_reset(self.c_envs, int(seed or 0))

        # Get starting player from C environment and rotate active order so parallel wrapper stays in sync
        info = binding.env_get(self.c_envs) 
        cp_idx = int(info['current_player'])
        starting_agent = self.possible_agents[cp_idx]
        other_agent = self.possible_agents[1 - cp_idx]
        self._agent_selection = starting_agent

        self.agents = [starting_agent, other_agent]
        self.rewards = {agent: 0.0 for agent in self.agents}
        self._cumulative_rewards = {agent: 0.0 for agent in self.agents}
        self.terminations = {agent: False for agent in self.agents}
        self.truncations = {agent: False for agent in self.agents}
        self.infos = {agent: {} for agent in self.agents}
        self._pending_terminal = False

    def step(self, action):
        """
        Execute one agent's action. Only the current agent (agent_selection) acts.
        After a move, agent_selection switches to the other player (or game ends).
        """
        if self._pending_terminal:
            # Terminate the other agent after the game-ending move
            self.terminations[self._agent_selection] = True
            if self._agent_selection in self.agents:
                self.agents.remove(self._agent_selection)
            self._pending_terminal = False
            return

        if self.terminations.get(self._agent_selection, False):
            # Game already over, shouldn't be stepping
            raise ValueError(f"Game already over for agent {self._agent_selection}")

        # Pass action to C environment
        self._actions[0] = int(action)
        binding.env_step(self.c_envs)

        # Check if game is over
        done = bool(self._terminals[0])
        r = float(self._rewards[0]) 

        if done:
            # Terminate current agent who made the game-ending move
            acting_agent = self._agent_selection
            opponent_idx = 1 if acting_agent == 'X' else 0
            opponent_agent = self.possible_agents[opponent_idx]
            self.terminations[acting_agent] = True
            if acting_agent in self.agents:
                self.agents.remove(acting_agent)

            # Rewards are from the acting agent's perspective; propagate symmetrically
            self.rewards[acting_agent] = r
            self.rewards[opponent_agent] = -r
            self._cumulative_rewards[acting_agent] += r
            self._cumulative_rewards[opponent_agent] += -r

            s = self.rewards['X'] + self.rewards['O']
            assert abs(s) < 1e-6, (
                f"Non-zero-sum terminal: X+O={s}, rX={self.rewards['X']}, rO={self.rewards['O']}"
            )

            # Mark pending so other agent terminates on their step
            self._pending_terminal = True

            # Switch to other agent
            self._agent_selection = opponent_agent
        else:
            # Game continues - switch to next player
            info = binding.env_get(self.c_envs) 
            cp_idx = int(info['current_player'])
            self._agent_selection = self.possible_agents[cp_idx]

def make_tictactoe(buf=None, **kwargs):
    kwargs = dict(kwargs)
    seed = kwargs.pop('seed', 42)
    flip = kwargs.pop('flip_perspective', True)
    kwargs.pop('num_envs', None)
    env = TicTacToe(seed=seed, flip_perspective=flip, **kwargs)
    env = turn_based_aec_to_parallel(env)
    env = pufferlib.MultiagentEpisodeStats(env)
    return pufferlib.emulation.PettingZooPufferEnv(env=env, buf=buf)
