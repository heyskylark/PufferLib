//#define RAYLIB_IMPLEMENTATION
#include "tictactoe.h"
#include <string.h>
#include <time.h>

static int key_to_cell() {
    if (IsKeyPressed(KEY_ONE)) return 0;
    if (IsKeyPressed(KEY_TWO)) return 1;
    if (IsKeyPressed(KEY_THREE)) return 2;
    if (IsKeyPressed(KEY_FOUR)) return 3;
    if (IsKeyPressed(KEY_FIVE)) return 4;
    if (IsKeyPressed(KEY_SIX)) return 5;
    if (IsKeyPressed(KEY_SEVEN)) return 6;
    if (IsKeyPressed(KEY_EIGHT)) return 7;
    if (IsKeyPressed(KEY_NINE)) return 8;
    return -1;
}

// Minimax for perfect play
static int minimax(float* board, float mark_to_move) {
    int st = ttt_check_winner(board);
    if (st == 1) return +1;   // X win
    if (st == -1) return -1;  // O win
    if (st == 2) return 0;    // draw

    int best = (mark_to_move == PLAYER_X) ? -2 : 2;
    for (int i = 0; i < 9; i++) {
        if (board[i] != EMPTY) continue;
        board[i] = mark_to_move;
        int score = minimax(board, -mark_to_move);
        board[i] = EMPTY;
        if (mark_to_move == PLAYER_X) {
            if (score > best) best = score;
        } else {
            if (score < best) best = score;
        }
    }
    return best;
}

static int best_move_for(float* board, float mark) {
    int best_move = -1;
    int best_score = (mark == PLAYER_X) ? -2 : 2;
    for (int i = 0; i < 9; i++) {
        if (board[i] != EMPTY) continue;
        board[i] = mark;
        int score = minimax(board, -mark);
        board[i] = EMPTY;
        if (mark == PLAYER_X) {
            if (score > best_score) { best_score = score; best_move = i; }
        } else {
            if (score < best_score) { best_score = score; best_move = i; }
        }
    }
    // Fallback (shouldn't happen): pick first empty
    if (best_move == -1) {
        for (int i = 0; i < 9; i++) if (board[i] == EMPTY) return i;
    }
    return best_move;
}

static void interactive() {
    CTicTacToe env = {0};
    ttt_allocate(&env);
    c_reset(&env);

    int frame = 0;
    while (!WindowShouldClose()) {
        // Human plays X (env.current_player == 0)
        if (env.current_player == 0) {
            int cell = key_to_cell();
            if (cell != -1) {
                env.actions[0] = cell;
                c_step(&env);
            }
        } else {
            // Bot plays O every few frames
            if (frame % 12 == 0) {
                int move = best_move_for(env.board, PLAYER_O);
                env.actions[0] = move;
                c_step(&env);
            }
        }

        c_render(&env);
        frame = (frame + 1) % 60;
    }

    c_close(&env);
    ttt_free_allocated(&env);
}

static void performance_test() {
    CTicTacToe env = {0};
    ttt_allocate(&env);
    c_reset(&env);

    long test_time = 3;
    long start = time(NULL);
    long steps = 0;
    while (time(NULL) - start < test_time) {
        // Random legal move
        int a = rand() % 9;
        for (int i = 0; i < 9; i++) { if (env.board[(a+i)%9] == EMPTY) { a = (a+i)%9; break; } }
        env.actions[0] = a;
        c_step(&env);
        steps++;
    }
    printf("SPS: %ld\n", steps / test_time);
    c_close(&env);
    ttt_free_allocated(&env);
}

int main() {
    // performance_test();
    interactive();
    return 0;
}
