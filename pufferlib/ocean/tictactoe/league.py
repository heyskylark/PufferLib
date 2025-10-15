from __future__ import annotations

import copy
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
import shutil

import numpy as np
import torch


@dataclass
class Snapshot:
    """Metadata for a frozen policy snapshot used as a league opponent."""

    identifier: int
    path: Path
    elo: float
    games: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    model: Optional[torch.nn.Module] = None

    def record(self, hero_score: float) -> None:
        """Update summary statistics after a match."""
        self.games += 1
        if hero_score > 0.5:
            self.losses += 1
        elif hero_score < 0.5:
            self.wins += 1
        else:
            self.draws += 1


class LeagueManager:
    """Single-policy league with ELO-managed opponent pool for TicTacToe."""

    def __init__(self, config, policy, vecenv, device, data_dir, env_name, run_id=None):
        self.config = config
        self.policy_template = policy
        self.hero_device = torch.device(device)
        opponent_device = config.get('opponent_device', 'cpu')
        self.opponent_device = torch.device(opponent_device)

        self.agents_per_env = vecenv.driver_env.num_agents
        if hasattr(vecenv, 'num_environments'):
            self.num_envs = vecenv.num_environments
        elif hasattr(vecenv, 'envs'):
            self.num_envs = len(vecenv.envs)
        else:
            self.num_envs = vecenv.num_agents // self.agents_per_env

        self.hero_elo = float(config.get('hero_start_elo', 1000.0))
        self.elo_k = float(config.get('elo_k', 32.0))
        self.pool_probability = float(config.get('pool_probability', 0.5))
        self.snapshot_interval = int(config.get('snapshot_interval', 10_000))
        self.snapshot_min_games = int(config.get('snapshot_min_games', 64))
        self.max_snapshots = int(config.get('max_snapshots', 16))
        self.random_state = random.Random(config.get('seed', None))

        self.total_games = 0
        self.games_since_snapshot = 0
        self.last_snapshot_step = 0

        base_dir = Path(data_dir) / 'league' / env_name
        if run_id is not None:
            self.league_dir = base_dir / str(run_id)
            if self.league_dir.exists():
                shutil.rmtree(self.league_dir, ignore_errors=True)
            self.league_dir.mkdir(parents=True, exist_ok=True)
        else:
            self.league_dir = base_dir
            self.league_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_counter = 0
        self.snapshots: List[Snapshot] = []

        self.current_roles = np.ones(
            (self.num_envs, self.agents_per_env), dtype=bool
        )
        self.active_matches = [
            dict(type='self_play', snapshot=None, hero_index=None, states={})
            for _ in range(self.num_envs)
        ]
        self._update_global_mask()

        for env_idx in range(self.num_envs):
            self.assign_match(env_idx)

    # --------------------------------------------------------------------- #
    # Mask helpers
    # --------------------------------------------------------------------- #
    def _update_global_mask(self) -> None:
        self.global_role_mask = self.current_roles.reshape(-1)

    def get_global_mask(self) -> np.ndarray:
        return self.global_role_mask

    def get_env_role_mask(self, env_idx: int) -> np.ndarray:
        return self.current_roles[env_idx]

    def env_from_index(self, agent_index: int) -> int:
        return agent_index // self.agents_per_env

    # --------------------------------------------------------------------- #
    # Match scheduling and opponent actions
    # --------------------------------------------------------------------- #
    def assign_match(self, env_idx: int) -> None:
        use_pool = bool(self.snapshots) and self.random_state.random() < self.pool_probability
        if use_pool:
            snapshot = self._choose_snapshot()
            hero_index = self.random_state.randrange(self.agents_per_env)
            roles = np.zeros(self.agents_per_env, dtype=bool)
            roles[hero_index] = True
            self.current_roles[env_idx] = roles
            self.active_matches[env_idx] = dict(
                type='snapshot', snapshot=snapshot, hero_index=hero_index, states={}
            )
        else:
            self.current_roles[env_idx] = np.ones(self.agents_per_env, dtype=bool)
            self.active_matches[env_idx] = dict(
                type='self_play', snapshot=None, hero_index=None, states={}
            )

        self._update_global_mask()

    def override_actions(self, actions: torch.Tensor, observations: torch.Tensor,
                          env_idx: int, env_slice: slice) -> torch.Tensor:
        match = self.active_matches[env_idx]
        if match['type'] != 'snapshot':
            return actions

        snapshot: Snapshot = match['snapshot']
        hero_index = match['hero_index']
        states = match.setdefault('states', {})
        self._ensure_model_loaded(snapshot)

        local_offset = env_slice.start
        for local_idx in range(self.agents_per_env):
            if local_idx == hero_index:
                continue

            global_idx = local_offset + local_idx
            tensor_idx = global_idx - local_offset
            obs = observations[tensor_idx].detach().to(self.opponent_device)
            obs_batch = obs.unsqueeze(0).float()
            legal = (obs_batch == 0).to(self.opponent_device)
            state = states.get(local_idx)
            if state is None:
                state = self._init_state(snapshot.model, self.opponent_device)
                states[local_idx] = state

            with torch.no_grad():
                logits, _ = snapshot.model.forward_eval(obs_batch, state)

            if isinstance(logits, torch.distributions.Distribution):
                act = logits.mode[0]
            elif isinstance(logits, (tuple, list)):
                # MultiDiscrete: take argmax per head, respecting legal mask
                act = []
                for head, mask in zip(logits, legal.split(1, dim=1)):
                    masked = head.masked_fill(~mask.squeeze(0).bool(), -1e9)
                    act.append(torch.argmax(masked, dim=-1))
                act = torch.stack(act, dim=-1)[0]
            else:
                legal_mask = legal.squeeze(0).bool().to(logits.device)
                masked_logits = logits.clone()
                masked_logits = masked_logits.masked_fill(~legal_mask, -1e9)
                act = torch.argmax(masked_logits, dim=-1)[0]

            actions[tensor_idx] = act.to(actions.device)

        return actions

    # --------------------------------------------------------------------- #
    # Match result handling and logging
    # --------------------------------------------------------------------- #
    def on_step(self, env_idx: int, rewards: np.ndarray,
                done_mask: np.ndarray, stats=None) -> None:
        if not np.any(done_mask):
            return

        self.total_games += 1
        self.games_since_snapshot += 1

        match = self.active_matches[env_idx]
        if match['type'] == 'snapshot':
            hero_index = match['hero_index']
            hero_reward = float(rewards[hero_index])
            if hero_reward > 0:
                hero_score = 1.0
            elif hero_reward < 0:
                hero_score = 0.0
            else:
                hero_score = 0.5

            snapshot: Snapshot = match['snapshot']
            self._update_elo(snapshot, hero_score)
            snapshot.record(hero_score)

            if stats is not None:
                stats['league/hero_vs_snapshot_reward'].append(hero_reward)

        self.assign_match(env_idx)

        if stats is not None:
            stats['league/hero_elo'].append(self.hero_elo)
            stats['league/pool_size'].append(float(len(self.snapshots)))

    # --------------------------------------------------------------------- #
    # Snapshot management
    # --------------------------------------------------------------------- #
    def maybe_snapshot(self, epoch: int, global_step: int, policy: torch.nn.Module) -> None:
        if global_step - self.last_snapshot_step < self.snapshot_interval:
            return
        if self.games_since_snapshot < self.snapshot_min_games:
            return

        self.last_snapshot_step = global_step
        self.games_since_snapshot = 0
        self.snapshot_counter += 1

        filename = f'snapshot_{self.snapshot_counter:05d}.pt'
        path = self.league_dir / filename
        state = {k: v.detach().cpu() for k, v in policy.state_dict().items()}
        torch.save(state, path)

        snapshot = Snapshot(
            identifier=self.snapshot_counter,
            path=path,
            elo=self.hero_elo,
        )
        self.snapshots.append(snapshot)
        self._prune_snapshots()

    def _prune_snapshots(self) -> None:
        if self.max_snapshots <= 0 or len(self.snapshots) <= self.max_snapshots:
            return

        self.snapshots.sort(key=lambda snap: snap.elo)
        to_remove = self.snapshots[:-self.max_snapshots]
        self.snapshots = self.snapshots[-self.max_snapshots:]

        for snap in to_remove:
            if snap.model is not None:
                del snap.model
            try:
                snap.path.unlink()
            except FileNotFoundError:
                pass

        removed_ids = {snap.identifier for snap in to_remove}
        for env_idx, match in enumerate(self.active_matches):
            if match['type'] == 'snapshot' and match['snapshot'].identifier in removed_ids:
                self.assign_match(env_idx)

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #
    def _ensure_model_loaded(self, snapshot: Snapshot) -> None:
        if snapshot.model is not None:
            return

        model = copy.deepcopy(self.policy_template).to(self.opponent_device)
        state = torch.load(snapshot.path, map_location=self.opponent_device)
        state = {k.replace('module.', ''): v for k, v in state.items()}
        model.load_state_dict(state, strict=False)
        model.eval()
        for param in model.parameters():
            param.requires_grad_(False)

        snapshot.model = model

    def _init_state(self, model: torch.nn.Module, device: torch.device):
        if hasattr(model, 'lstm'):
            hidden_size = getattr(model, 'hidden_size', None)
            if hidden_size is None and hasattr(model, 'policy'):
                hidden_size = getattr(model.policy, 'hidden_size', None)
            if hidden_size is None:
                return {}
            return {
                'lstm_h': torch.zeros(1, hidden_size, device=device),
                'lstm_c': torch.zeros(1, hidden_size, device=device),
            }
        return None

    def _choose_snapshot(self) -> Snapshot:
        if len(self.snapshots) == 1:
            return self.snapshots[0]

        elos = np.array([snap.elo for snap in self.snapshots], dtype=np.float64)
        if np.allclose(elos.std(), 0):
            weights = np.ones_like(elos)
        else:
            weights = np.exp((elos - elos.mean()) / max(1.0, elos.std()))

        weights = np.maximum(weights, 1e-6)
        choice = self.random_state.choices(self.snapshots, weights=weights, k=1)[0]
        return choice

    def _update_elo(self, snapshot: Snapshot, hero_score: float) -> None:
        snapshot_score = 1.0 - hero_score
        expected_hero = 1.0 / (1.0 + math.pow(10.0, (snapshot.elo - self.hero_elo) / 400.0))
        expected_snapshot = 1.0 - expected_hero

        self.hero_elo += self.elo_k * (hero_score - expected_hero)
        snapshot.elo += self.elo_k * (snapshot_score - expected_snapshot)
