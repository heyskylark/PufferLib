#include "tictactoe.h"

#define Env CTicTacToe
#define MY_GET 1
#include "../env_binding.h"

static int my_init(Env* env, PyObject* args, PyObject* kwargs) {
    env->random_open_prob = unpack(kwargs, "random_open_prob");
    env->random_open_depth = unpack(kwargs, "random_open_depth");
    init(env);
    return 0;
}

static int my_log(PyObject* dict, Log* log) {
    assign_to_dict(dict, "perf", log->perf);
    assign_to_dict(dict, "score", log->score);
    assign_to_dict(dict, "episode_return", log->episode_return);
    assign_to_dict(dict, "episode_length", log->episode_length);
    assign_to_dict(dict, "x_winrate", log->x_winrate);
    assign_to_dict(dict, "o_winrate", log->o_winrate);
    assign_to_dict(dict, "draw_rate", log->draw_rate);
    assign_to_dict(dict, "n", log->n);
    return 0;
}

static PyObject* my_get(PyObject* dict, Env* env) {
    // Expose the current player (0 == X, 1 == O) to Python
    PyObject* v = PyLong_FromLong(env->current_player);
    if (v == NULL) {
        PyErr_SetString(PyExc_TypeError, "Failed to convert current_player");
        return NULL;
    }
    if (PyDict_SetItemString(dict, "current_player", v) < 0) {
        Py_DECREF(v);
        PyErr_SetString(PyExc_TypeError, "Failed to set current_player");
        return NULL;
    }
    Py_DECREF(v);
    Py_RETURN_NONE;
}
