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

    ob, _ = vecenv.reset()
    driver = vecenv.driver_env

    # Prepare RNN state if needed
    use_rnn = cfg['train'].get('use_rnn', False)
    state = {}
    if use_rnn and hasattr(policy, 'hidden_size'):
        num_agents = getattr(vecenv, 'num_agents', ob.shape[0])
        state = dict(
            lstm_h=torch.zeros(num_agents, policy.hidden_size, device=args.device),
            lstm_c=torch.zeros(num_agents, policy.hidden_size, device=args.device),
        )

    # Decide who is X (0) vs O (1). Our env alternates internally, but we can
    # interpret human moves as needed. Human goes first => X.
    human_is_x = args.go_first

    def get_legal(board):
        # board is [-1,0,1] floats
        return [i for i, v in enumerate(board) if v == 0.0]

    while True:
        render = driver.render()
        # Poll current player from C binding (optional)
        # info = driver.get() if exposed; else infer from board parity
        board = ob[0].astype(np.float32)
        num_filled = (board != 0).sum()
        current_is_x = (num_filled % 2 == 0)

        human_turn = (current_is_x and human_is_x) or ((not current_is_x) and (not human_is_x))
        legal = get_legal(board)

        if human_turn:
            print('\nBoard indices:')
            print('0 1 2\n3 4 5\n6 7 8')
            print(f'Legal moves: {legal}')
            while True:
                try:
                    mv = int(input('Your move [0-8]: ').strip())
                except KeyboardInterrupt:
                    sys.exit(0)
                except Exception:
                    mv = -1
                if mv in legal:
                    break
                print('Invalid move. Try again.')
            atn = np.array([mv], dtype=np.int32)
        else:
            with torch.no_grad():
                t = torch.as_tensor(ob, device=args.device)
                logits, value = policy.forward_eval(t, state)
                # sample greedy over legal moves only
                # prefer vecenv.single_action_space if present
                action_space = getattr(vecenv, 'single_action_space', None)
                if action_space is not None and hasattr(action_space, 'n'):
                    probs = torch.softmax(logits, dim=-1)[0].cpu().numpy()
                    legal_arr = np.array(legal, dtype=np.int64)
                    if legal_arr.size == 0:
                        mv = int(np.argmax(probs))
                    else:
                        mv = int(legal_arr[np.argmax(probs[legal_arr])])
                else:
                    mv = int(np.random.choice(legal)) if len(legal) > 0 else 0
            atn = np.array([mv], dtype=np.int32)
            print(f'AI plays: {mv}')

        ob, rew, done, trunc, info = vecenv.step(atn)
        if done[0] or trunc[0]:
            render = driver.render()
            r = float(rew[0])
            if r > 0:
                print('Result: You win!' if human_turn else 'Result: AI wins!')
            elif r < 0:
                print('Result: AI wins!' if human_turn else 'Result: You win!')
            else:
                print('Result: Draw')
            choice = input('Play again? [y/N]: ').strip().lower()
            if choice != 'y':
                break
            ob, _ = vecenv.reset()


if __name__ == '__main__':
    main()


