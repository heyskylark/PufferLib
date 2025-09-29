#include "tictactoe.h"

#define Env CTicTacToe
#define MY_GET 1
#include "../env_binding.h"

static int my_init(Env* env, PyObject* args, PyObject* kwargs) {
    c_reset(env);
    return 0;
}

static int my_log(PyObject* dict, Log* log) {
    assign_to_dict(dict, "perf", log->perf);
    assign_to_dict(dict, "score", log->score);
    assign_to_dict(dict, "episode_return", log->episode_return);
    assign_to_dict(dict, "episode_length", log->episode_length);
    assign_to_dict(dict, "winrate", log->winrate);
    assign_to_dict(dict, "n", log->n);
    return 0;
}

static PyObject* my_get(PyObject* dict, Env* env) {
    PyObject* current = PyLong_FromLong(env->current_player);
    if (current == NULL) {
        return NULL;
    }
    if (PyDict_SetItemString(dict, "current_player", current) < 0) {
        Py_DECREF(current);
        return NULL;
    }
    Py_DECREF(current);
    return dict;
}
