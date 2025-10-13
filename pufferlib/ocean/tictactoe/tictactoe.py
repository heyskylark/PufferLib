import numpy as np
import gymnasium as gym
from pettingzoo import AECEnv
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
        'is_parallelizable': True
    }

    def __init__(self, seed: int | None = None, flip_perspective: bool = True) -> None:
        super().__init__()
        self.possible_agents = ['X', 'O']
        self.flip_perspective = flip_perspective
        self._pending_terminal = False

        # C binding arrays
        self._obs = np.zeros(9, dtype=np.float32)
        self._actions = np.zeros(1, dtype=np.int32)
        self._rewards = np.zeros(1, dtype=np.float32)
        self._terminals = np.zeros(1, dtype=np.bool_)
        self._truncations = np.zeros(1, dtype=np.bool_)

        self._handle = binding.env_init(
            self._obs,
            self._actions,
            self._rewards,
            self._terminals,
            self._truncations,
            int(seed or 0)
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
        binding.env_close(self._handle)

    def render(self):
        binding.env_render(self._handle)

    def reset(self, seed=None, options=None):
        """
        Reset the game. Starting player is randomized in C code for balanced self-play.
        """
        binding.env_reset(self._handle, int(seed or 0))

        # Get starting player from C environment
        info = binding.env_get(self._handle) or {}
        cp_idx = int(info.get('current_player', 0))
        self._agent_selection = self.possible_agents[cp_idx]

        self.agents = self.possible_agents[:]
        self.rewards = {agent: 0.0 for agent in self.possible_agents}
        self._cumulative_rewards = {agent: 0.0 for agent in self.possible_agents}
        self.terminations = {agent: False for agent in self.possible_agents}
        self.truncations = {agent: False for agent in self.possible_agents}
        self.infos = {agent: {} for agent in self.possible_agents}
        self._pending_terminal = False

        self._update_infos()

    def step(self, action):
        """
        Execute one agent's action. Only the current agent (agent_selection) acts.
        After a move, agent_selection switches to the other player (or game ends).
        """
        if self._pending_terminal:
            # Terminate the other agent after the game-ending move
            self.terminations[self._agent_selection] = True
            self.truncations[self._agent_selection] = False
            if self._agent_selection in self.agents:
                self.agents.remove(self._agent_selection)
            self._pending_terminal = False
            self._update_infos()
            return

        if self.terminations.get(self._agent_selection, False):
            # Game already over, shouldn't be stepping
            return

        # Pass action to C environment
        self._actions[0] = int(action)
        binding.env_step(self._handle)

        # Check if game is over
        done = bool(self._terminals[0])
        r = float(self._rewards[0])  # r is always from X's perspective

        # Clear previous step rewards
        self.rewards = {agent: 0.0 for agent in self.possible_agents}

        if done:
            # Terminate current agent who made the game-ending move
            self.terminations[self._agent_selection] = True
            if self._agent_selection in self.agents:
                self.agents.remove(self._agent_selection)

            # Set rewards immediately
            self.rewards['X'] = r
            self.rewards['O'] = -r
            self._cumulative_rewards['X'] += r
            self._cumulative_rewards['O'] += -r

            # Mark pending so other agent terminates on their step
            self._pending_terminal = True

            # Switch to other agent
            self._agent_selection = self.possible_agents[1 if self._agent_selection == 'X' else 0]
        else:
            # Game continues - switch to next player
            info = binding.env_get(self._handle) or {}
            cp_idx = int(info.get('current_player', self._infer_current_from_board()))
            self._agent_selection = self.possible_agents[cp_idx]

        self._update_infos()

    def _infer_current_from_board(self) -> int:
        """
        Fallback to infer current player from board state.
        Even number of pieces => X's turn (0), odd => O's turn (1).
        """
        filled = (self._obs != 0.0).sum()
        return int(filled % 2)

    def _update_infos(self):
        """
        Update action masks for all agents.

        Key improvement for self-play training:
        - Current player gets action mask with legal moves
        - Waiting player gets all-zero mask (signals "don't act")
        """
        legal = (self._obs == 0.0)
        legal_mask = legal.astype(np.int8)
        zero_mask = np.zeros(9, dtype=np.int8)

        for agent in self.possible_agents:
            if agent == self._agent_selection and agent in self.agents:
                # Current player: provide legal moves
                self.infos[agent] = {
                    'action_mask': legal_mask,
                }
            else:
                # Waiting player: zero mask signals no action needed
                self.infos[agent] = {}

def make_tictactoe(buf=None, **kwargs):
    from pettingzoo.utils.conversions import aec_to_parallel
    env = TicTacToe(seed=42, flip_perspective=True)
    env = aec_to_parallel(env)
    env = pufferlib.MultiagentEpisodeStats(env)
    return pufferlib.emulation.PettingZooPufferEnv(env=env, buf=buf)