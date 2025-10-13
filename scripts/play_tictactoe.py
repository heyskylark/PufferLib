import argparse
import os
import sys

import numpy as np
import torch

import pufferlib
from pufferlib.pufferl import load_config, load_env, load_policy


def load_latest_checkpoint(env_name: str, device: str):
    base = 'experiments'
    if not os.path.isdir(base):
        return None
    files = [f for f in os.listdir(base) if f.startswith(env_name) and f.endswith('.pt')]
    if not files:
        # try subfolders created per run
        runs = [d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)) and d.startswith(env_name)]
        if not runs:
            return None
        latest_run = max(runs, key=lambda d: os.path.getctime(os.path.join(base, d)))
        run_dir = os.path.join(base, latest_run)
        checkpoints = [os.path.join(run_dir, f) for f in os.listdir(run_dir) if f.endswith('.pt')]
        if not checkpoints:
            return None
        return max(checkpoints, key=os.path.getctime)
    return os.path.join(base, max(files, key=lambda f: os.path.getctime(os.path.join(base, f))))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--go-first', action='store_true', help='Human plays X and moves first')
    parser.add_argument('--checkpoint', type=str, default='latest', help='Path to model .pt or "latest"')
    parser.add_argument('--device', type=str, default='cpu')
    args = parser.parse_args()

    env_name = 'puffer_tictactoe'
    # Prevent load_config from re-parsing our custom CLI flags
    _argv = sys.argv
    sys.argv = [sys.argv[0]]
    try:
        cfg = load_config(env_name)
    finally:
        sys.argv = _argv
    cfg['train']['device'] = args.device
    cfg['env']['num_envs'] = 1
    cfg['vec'] = dict(backend='Serial', num_envs=1)

    vecenv = load_env(env_name, cfg)
    policy = load_policy(cfg, vecenv, env_name)
    policy.eval()

    # Load checkpoint
    if args.checkpoint == 'latest':
        ckpt = load_latest_checkpoint(env_name, args.device)
    else:
        ckpt = args.checkpoint
    if ckpt:
        state_dict = torch.load(ckpt, map_location=args.device)
        state_dict = {k.replace('module.', ''): v for k, v in state_dict.items()}
        policy.load_state_dict(state_dict, strict=False)
        print(f'Loaded checkpoint: {ckpt}')
    else:
        print('No checkpoint found; playing with randomly initialized policy.')

    driver = vecenv.driver_env
    game = driver.env.aec_env

    def stack_observations():
        return np.stack([game.observe('X'), game.observe('O')], dtype=np.float32)

    def get_legal_moves(mask, board):
        if mask is not None:
            return np.flatnonzero(mask).astype(int).tolist()
        return [i for i, v in enumerate(board) if v == 0.0]

    def print_board(board):
        symbols = {1.0: 'X', -1.0: 'O', 0.0: ' '}
        rows = []
        for r in range(3):
            row = [symbols.get(board[3*r + c], ' ') for c in range(3)]
            rows.append(' | '.join(row))
        separator = '\n---------\n'
        print('\nBoard:')
        print(separator.join(rows))

    def prompt_human(agent, board, legal_moves):
        print('\nBoard indices:')
        print('0 1 2\n3 4 5\n6 7 8')
        print_board(board)
        print(f'{agent} legal moves: {legal_moves}')
        while True:
            try:
                mv = int(input(f'Your move for {agent} [0-8]: ').strip())
            except KeyboardInterrupt:
                print()
                sys.exit(0)
            except Exception:
                mv = -1
            if mv in legal_moves:
                return mv
            print('Invalid move. Try again.')

    def pick_ai_move(logits, legal_moves):
        if not legal_moves:
            return 0
        logits = logits.detach().cpu().float()
        masked = torch.full_like(logits, -1e9)
        masked[legal_moves] = logits[legal_moves]
        return int(torch.argmax(masked).item())

    def init_state():
        use_rnn = cfg['train'].get('use_rnn', False)
        if not use_rnn or not hasattr(policy, 'hidden_size'):
            return {}
        num_agents = driver.num_agents
        device = args.device
        return dict(
            lstm_h=torch.zeros(num_agents, policy.hidden_size, device=device),
            lstm_c=torch.zeros(num_agents, policy.hidden_size, device=device),
        )

    human_is_x = args.go_first
    human_agent = 'X' if human_is_x else 'O'

    try:
        while True:
            vecenv.reset()
            state = init_state()

            while game.agents:
                driver.render()
                if getattr(game, '_pending_terminal', False):
                    game.step(None)
                    continue

                agent = game.agent_selection
                _, _, terminated, truncated, info = game.last()

                if terminated or truncated:
                    game.step(None)
                    continue

                board = game.observe('X').astype(np.float32)
                legal = get_legal_moves(info.get('action_mask'), board)

                obs_stack = stack_observations()
                obs_tensor = torch.as_tensor(obs_stack, device=args.device)
                with torch.no_grad():
                    logits, _ = policy.forward_eval(obs_tensor, state)

                if agent == human_agent:
                    mv = prompt_human(agent, board, legal)
                else:
                    agent_idx = 0 if agent == 'X' else 1
                    mv = pick_ai_move(logits[agent_idx], legal)
                    print(f'AI ({agent}) plays: {mv}')

                game.step(int(mv))

            driver.render()
            x_reward = float(game.rewards.get('X', 0.0))
            if x_reward > 0:
                winner = 'X'
            elif x_reward < 0:
                winner = 'O'
            else:
                winner = None

            if winner is None:
                print('Result: Draw')
            elif winner == human_agent:
                print('Result: You win!')
            else:
                print('Result: AI wins!')

            choice = input('Play again? [y/N]: ').strip().lower()
            if choice != 'y':
                break
    finally:
        vecenv.close()


if __name__ == '__main__':
    main()
