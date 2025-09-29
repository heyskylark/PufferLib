#include <stdlib.h>
#include <math.h>
#include <stdio.h>
#include "raylib.h"

#define PLAYER_X 1.0f
#define PLAYER_O -1.0f
#define EMPTY 0.0f

#define DONE 1
#define NOT_DONE 0

// Reward shaping
#define WIN_TIME_PENALTY 0.05f   // subtract per time step on wins
#define DRAW_PENALTY 0.25f       // slight negative for draws
#define STEP_PENALTY 0.01f       // per-step penalty to encourage faster games

typedef struct Log Log;
struct Log {
    float perf;
    float score;
    float episode_return;
    float episode_length;
    float winrate;
    float n;
};

typedef struct Client Client;
typedef struct CTicTacToe CTicTacToe;
struct CTicTacToe {
    // Puffer I/O
    float* observations;   // length 9, values in {1, -1, 0}
    int* actions;          // single int action 0..8 (cell index)
    float* rewards;        // scalar
    unsigned char* terminals; // scalar {0,1}
    Log log;
    Client* client;

    // Game state
    float board[9];        // 3x3 flattened
    int current_player;    // 0 == X (PLAYER_X), 1 == O (PLAYER_O)
    int tick;
};

static inline void ttt_allocate(CTicTacToe* env) {
    env->observations = (float*)calloc(9, sizeof(float));
    env->actions = (int*)calloc(1, sizeof(int));
    env->rewards = (float*)calloc(1, sizeof(float));
    env->terminals = (unsigned char*)calloc(1, sizeof(unsigned char));
}

static inline void ttt_free_allocated(CTicTacToe* env) {
    free(env->observations);
    free(env->actions);
    free(env->rewards);
    free(env->terminals);
}

static inline void ttt_add_log(CTicTacToe* env) {
    env->log.perf += (env->rewards[0] > 0.0f) ? 1.0f : 0.0f;
    env->log.score += env->rewards[0];
    env->log.episode_return += env->rewards[0];
    env->log.episode_length += env->tick;
    env->log.winrate += (env->rewards[0] > 0.0f) ? 1.0f : 0.0f;
    env->log.n += 1.0f;
}

static inline int ttt_check_winner(float* b) {
    int lines[8][3] = {
        {0,1,2},{3,4,5},{6,7,8}, // rows
        {0,3,6},{1,4,7},{2,5,8}, // cols
        {0,4,8},{2,4,6}          // diagonals
    };
    for (int i = 0; i < 8; i++) {
        float a = b[lines[i][0]];
        float c = b[lines[i][1]];
        float d = b[lines[i][2]];
        if (a != EMPTY && a == c && c == d) {
            return (a == PLAYER_X) ? 1 : -1; // X wins -> 1, O wins -> -1
        }
    }
    // Check draw
    for (int i = 0; i < 9; i++) {
        if (b[i] == EMPTY) return 0; // ongoing
    }
    return 2; // draw
}

static inline void ttt_compute_observation(CTicTacToe* env) {
    for (int i = 0; i < 9; i++) env->observations[i] = env->board[i];
}

static inline void c_close(CTicTacToe* env) {
    // Nothing heap-allocated inside env aside from client handled below
    if (IsWindowReady()) {
        CloseWindow();
    }
}

static inline void c_reset(CTicTacToe* env) {
    env->tick = 0;
    env->terminals[0] = NOT_DONE;
    env->rewards[0] = 0.0f;
    for (int i = 0; i < 9; i++) env->board[i] = EMPTY;
    // Randomize starting player to balance selfplay
    env->current_player = rand() & 1; // 0 or 1
    ttt_compute_observation(env);
}

static inline void ttt_end_game(CTicTacToe* env, float reward) {
    env->rewards[0] = reward;
    env->terminals[0] = DONE;
    ttt_add_log(env);
}

static inline void c_step(CTicTacToe* env) {
    env->tick += 1;
    env->rewards[0] = -STEP_PENALTY;

    if (env->terminals[0] == DONE) {
        c_reset(env);
        return;
    }

    int action = env->actions[0]; // 0..8
    if (action < 0 || action > 8 || env->board[action] != EMPTY) {
        // Invalid move loses immediately
        float reward = (env->current_player == 0) ? -1.0f : 1.0f;
        ttt_end_game(env, reward);
        ttt_compute_observation(env);
        return;
    }

    // Place mark for current player
    float mark = (env->current_player == 0) ? PLAYER_X : PLAYER_O;
    env->board[action] = mark;

    int st = ttt_check_winner(env->board);
    if (st == 1) { // X wins
        float shaped = 1.0f - WIN_TIME_PENALTY * (float)env->tick;
        if (shaped < 0.0f) shaped = 0.0f;
        ttt_end_game(env, (mark == PLAYER_X) ? shaped : -1.0f);
        ttt_compute_observation(env);
        return;
    } else if (st == -1) { // O wins
        float shaped = 1.0f - WIN_TIME_PENALTY * (float)env->tick;
        if (shaped < 0.0f) shaped = 0.0f;
        ttt_end_game(env, (mark == PLAYER_O) ? shaped : -1.0f);
        ttt_compute_observation(env);
        return;
    } else if (st == 2) { // draw
        ttt_end_game(env, -DRAW_PENALTY);
        ttt_compute_observation(env);
        return;
    }

    // Switch player and wait for next joint action
    env->current_player ^= 1;
    ttt_compute_observation(env);
}

// Rendering
static const Color PUFF_RED = (Color){187, 0, 0, 255};
static const Color PUFF_CYAN = (Color){0, 187, 187, 255};
static const Color PUFF_WHITE = (Color){241, 241, 241, 241};
static const Color PUFF_BACKGROUND = (Color){6, 24, 24, 255};

struct Client {
    int width;
    int height;
};

static inline Client* ttt_make_client(int width, int height) {
    Client* client = (Client*)calloc(1, sizeof(Client));
    client->width = width;
    client->height = height;
    InitWindow(width, height, "PufferLib Ray TicTacToe");
    SetTargetFPS(60);
    return client;
}

static inline void c_render(CTicTacToe* env) {
    if (IsKeyDown(KEY_ESCAPE)) {
        exit(0);
    }
    if (env->client == NULL) {
        env->client = ttt_make_client(480, 480);
    }
    const int W = env->client->width;
    const int H = env->client->height;
    const int cell = (W < H ? W : H) / 3;

    BeginDrawing();
    ClearBackground(PUFF_BACKGROUND);

    // Grid
    for (int i = 1; i < 3; i++) {
        DrawLine(i*cell, 0, i*cell, 3*cell, PUFF_WHITE);
        DrawLine(0, i*cell, 3*cell, i*cell, PUFF_WHITE);
    }

    // Pieces
    for (int i = 0; i < 9; i++) {
        int r = i / 3;
        int c = i % 3;
        float v = env->board[i];
        int x = c*cell;
        int y = r*cell;
        if (v == PLAYER_X) {
            // Draw X
            DrawLineEx((Vector2){x+16, y+16}, (Vector2){x+cell-16, y+cell-16}, 6, PUFF_CYAN);
            DrawLineEx((Vector2){x+cell-16, y+16}, (Vector2){x+16, y+cell-16}, 6, PUFF_CYAN);
        } else if (v == PLAYER_O) {
            // Draw O
            DrawCircleLines(x + cell/2, y + cell/2, cell/2 - 16, PUFF_RED);
            DrawCircleLines(x + cell/2, y + cell/2, cell/2 - 20, PUFF_RED);
        }
    }

    // Turn indicator
    const char* turn = (env->current_player == 0) ? "X" : "O";
    DrawText(TextFormat("Turn: %s", turn), 10, 3*cell + 10, 24, PUFF_WHITE);

    EndDrawing();
}
