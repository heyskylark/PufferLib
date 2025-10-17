# Azuki TCG – Policy, PettingZoo AEC, and League Training Specification

## 1. Training Overview
- **Goal**: Train competitive Azuki agents via self-play on the C environment, using PettingZoo’s AEC API and PufferLib integration to support multi-head action policies and league-managed opponents.
- **Key Components**
  1. **C Environment Core & Binding** (`pufferlib/ocean/azuki/*.c`, `puffer/azuki_puffer.h`, `binding.c`) – houses engine logic plus NumPy-facing bridge.
  2. **PettingZoo Wrapper** (`pufferlib/ocean/azuki/env.py`, TBD) – high-level Python env that mirrors TicTacToe wrapper semantics.
  3. **Policy Architecture** – multi-head actor (ActionType + parameters) with shared encoder.
  4. **League Manager** – extended from `pufferlib/ocean/tictactoe/league.py` with Azuki-specific logic.
  5. **Training Loop** – built on PufferLib RL harness (PPO baseline, optional VPG/IMPALA).

## 2. Environment Interface (PettingZoo AEC)
- Agents: `["player_0", "player_1"]`.
- Selection logic:
  - Start-of-turn agent: active player.
  - Response window: defender becomes `agent_selection`. After NO_OP/response, revert to attacker.
  - Post-terminal: mimic TicTacToe approach (pending terminal step to clear other agent).
- Observations: `float32[AZK_OBS_LEN]` from binding; optionally apply perspective flip (swap self/opponent features) for symmetry.
- Legal action masks: provided via `infos[agent]["action_mask_headX"]` or `infos[agent]["action_mask"]` depending on binding output.
- Rewards: zero-sum; shaped deltas (optional) align with engine spec.
- Termination handling: `terminations[agent]` toggled sequentially; truncated episodes flagged when turn cap reached (60 full turns).

## 3. Action Representation & Policy Heads
### 3.1 Action Heads
- **Head 0** – `Discrete(13)` for `ActionType` (index order includes `ACT_NOOP` at 0, `ACT_END_TURN` at 10).
- **Heads 1–3** – `Discrete` spaces sized `[16, 8, 8]` (tunable):
  - Head 1: hand indices, slot indices, ability indices.
  - Head 2: target kind/slot combos.
  - Head 3: auxiliary selectors (e.g., gate slot choice, replacement flag).
- Mask semantics:
  - Provide per-head mask arrays in `env.info["mask_head_i"]`.
  - When only NO_OP is legal, masks for Heads 1–3 reduce to `[1,0,...]` or zero-out (policy should ignore using mask).
  - Inactive agent (not selected) receives all-zero masks, signaling no-op step (mirrors TicTacToe `legal_mask` behavior).
  - During action selection, policy applies mask then performs per-head `argmax` (unless overridden by exploration strategy).

### 3.2 Policy Network
- **Encoder + Recurrent Core**:
  - Observation vector passes through a lightweight pre-MLP (e.g., `obs -> LayerNorm -> Linear(4096) -> ReLU`).
  - Output feeds a single-layer LSTM with hidden size 4096 (OpenAI Five style). Hidden/cell state shared between policy and value heads.
- **Heads**:
  - Policy head splits into `pi_type`, `pi_p0`, `pi_p1`, `pi_p2` linear projections from the LSTM hidden state.
  - Value head: small MLP (`hidden -> Linear(1024) -> ReLU -> Linear(1)`) consuming the same LSTM hidden output.
- **Masking & Selection**:
  - Masks applied by setting invalid logits to a large negative constant prior to selection.
  - Default action selection: mask then `argmax` for each head (deterministic). Exploration achieved via ε-greedy or entropy injection before argmax.
- **NO_OP Handling**:
  - Policy only sees `ACT_NOOP` when response window is active; masks ensure main-phase logits for NO_OP are clamped.

## 4. Experience Collection
- **Vectorized Envs**: Use PufferLib `VecEnv` to batch multiple Azuki games (≤12 environments to align with Ryzen 5900X cores).
- **Rollout Length**: 128–256 steps recommended due to long episodes.
- **Advantage Estimation**: GAE(λ), with gamma ~0.99, λ ~0.95.
- **Reward Shaping (optional)**:
  - `+0.02` per net damage inflicted on opponent leader.
  - `-0.02` per damage received.
  - `+0.01` per successful portal.
  - `-0.01` illegal action attempt (should be prevented by masks; fallback penalty).
- **Truncation**: If turn cap hit, mark truncation, zero reward, bootstrap value with discount.

## 5. League Training Specification
### 5.1 Core Concepts (borrowed from `tictactoe/league.py`)
- `LeagueManager` maintains:
  - Hero policy (trainable).
  - Snapshot pool (`Snapshot` dataclass) with ELO ranking.
  - Match scheduling (self-play vs. snapshot opponents).
  - Role masks to alternate hero/opponent positions.
- Snapshot lifecycle:
  - Capture model every `snapshot_interval` environment steps (e.g., 10k) if `games_since_snapshot >= snapshot_min_games`.
  - Limit to `max_snapshots`, prune lowest ELO.
- Opponent selection:
  - With probability `pool_probability`, sample snapshot; otherwise self-play.
  - When using snapshot, designate hero index for env; others use frozen policy.

### 5.2 Azuki-Specific Adaptations
- **Multi-Head Actions**:
  - Snapshot model forward pass outputs tuple of head logits; override logic must mask invalid moves using environment masks (similar to TicTacToe `legal` array but per head).
  - League manager overrides hero actions only for non-hero indices.
- **Legal Mask Propagation**:
  - Ensure `env.info["mask_heads"]` accessible to league (store per-env state).
  - When overriding snapshot move, apply mask to each head before argmax sampling.
- **Observation Features**:
  - Provide `is_response_window`, `actor_is_defender` to snapshot for context.
  - Optionally maintain RNN state inside `Snapshot` (set `model.forward_eval` signature to accept state; store per-agent state in `match['states']`).
- **Role Mask**:
  - Use `LeagueManager.get_global_mask()` to indicate hero-controlled agents (1) vs. snapshot (0).
  - Multi-agent environment has 2 agents; mask size equals `num_envs * 2`.
- **Reward Logging**:
  - hero_score derived from hero reward sign (win/loss/draw).
  - Update ELO: `new_elo = old + k*(score - expected_score)`.

### 5.3 League Persistence
- `league_dir = <data_dir>/league/azuki[/run_id]`.
- Store:
  - `snapshots/` subdir with serialized model weights & metadata JSON.
  - `matches.log` summarizing hero vs. opponent results.
  - `league_state.json` for resume support.
- On resume:
  - Reload snapshot metadata, weights on demand.
  - Reset counters (`total_games`, `hero_elo`, etc.) from file.

## 6. Training Pipeline Reference Implementation
1. **Initialize Environment**
   ```python
   from pufferlib.ocean.azuki import Azuki
   env = Azuki(seed=seed, flip_perspective=True)
   vecenv = pufferlib.vector.make(env, num_envs)
   ```
2. **Build Policy**
   ```python
   policy = AzukiPolicy(obs_dim=AZK_OBS_LEN,
                        head_sizes=(13,16,8,8),
                        hidden_sizes=(512,512))
   ```
3. **Configure PPO**
   - `learning_rate`: 3e-4 (with cosine schedule).
   - `clip_range`: 0.2; `entropy_coef`: 0.01; `value_coef`: 0.5.
   - Gradient norm clip: 0.5.
4. **Integrate League**
   ```python
   league = LeagueManager(config=league_cfg,
                          policy=policy,
                          vecenv=vecenv,
                          device=device,
                          data_dir="experiments/azuki",
                          env_name="azuki_v0")
   ```
   - Attach to rollout loop: override actions for snapshot-controlled agents via `league.override_actions`.
   - After each env step, call `league.on_step`.
5. **Logging**
   - Use W&B or TensorBoard to log `hero_win_rate`, `best_snapshot_elo`, `illegal_action_rate`, and `reward_shaping_terms`.
   - periodically run evaluation matches vs. scripted baseline.

## 7. Baselines & Evaluation
- **Random Policy**: uniform sampling of legal moves; ensures mask coverage.
- **Scripted Baseline**: heuristic agent (prioritize equipping weapons, maintain defender). Use to sanity-check RL improvements.
- **Metrics**:
  - Win rate vs. random & scripted.
  - Average turns per game.
  - Illegal action frequency (should be 0).
  - Effective explore: number of unique cards played per match.
- **Evaluation Schedule**: every N updates run 256 evaluation games without learning updates; freeze policy parameters.

## 8. Reproducibility & Determinism
- Seed all RNG sources: environment (`env_reset(seed)`), NumPy, PyTorch, league random state.
- Store seeds & config in run metadata; log environment commit hash.
- Save policy snapshots with `state_dict` and `optimizer_state` plus `league_state`.
- For bug reproduction, capture replay log from engine + policy action trace.

## 9. Integration Notes with `env_binding.h`
- Follow existing harness expectations:
  - `env_init` takes numpy buffers (obs, actions, rewards, terminals, truncations) + seed.
  - Validate arrays contiguous and correct dtype (float32 for obs, int32 for actions).
  - Provide optional kwargs (e.g., `IKZ_token_rule`, `max_turns`) by injecting into kwargs dict before `my_init`.
- `my_get` should return dictionary including:
  ```python
  {
      "obs_len": AZK_OBS_LEN,
      "action_heads": 4,
      "action_head_sizes": [13, 16, 8, 8],
      "mask_len": 0,  # if using per-head masks in infos
      "num_agents": 2,
      "supports_league": True
  }
  ```
- Implement `my_shared` to expose flattened legal masks when required (e.g., for CPU-side mask application).

## 10. Testing & Validation
- **Unit Tests**:
  - `tests/test_binding_shapes.py` – verifies `env_get` metadata, buffer lengths.
  - `tests/test_masks_policy.py` – ensures policy head masks align with environment.
  - `tests/test_noop_mask_behavior.py` – confirm NO_OP only legal in response windows.
  - `tests/test_league_snapshot.py` – simulate snapshot override using dummy logits.
- **Integration Tests**:
  - Run short PPO training (1000 steps) verifying loss decreases and no illegal actions.
  - League smoke test: create dummy snapshot, ensure override path executes and statistics update.
- **CI Hooks**:
  - Format check for Python wrapper.
  - Run `pytest` on training helpers with `--disable-warnings`.

## 11. Future Enhancements
- Multi-agent curriculum (mentor policies, scripted gate combos).
- Mask compression (bitmasks) to reduce bandwidth for distributed training.
- On-policy vs. off-policy comparison (IMPALA, V-trace).
- Visual observation for potential transformer-based agents (long-term).

---
**Maintainers**: Brandon, Codex Agent  
**Last Updated**: _2025-10-16_  
**Related Docs**: `azuki-env-tech-spec.md`, `azuki-env-milestones.md`, `pufferlib/ocean/tictactoe/tictactoe.py`, `pufferlib/ocean/tictactoe/league.py`
