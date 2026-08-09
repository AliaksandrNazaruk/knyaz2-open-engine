/* Общая часть посредников: журнал и чтение состояния игры. */
#ifndef KONUNG_PROBE_H
#define KONUNG_PROBE_H

#include <windows.h>

void probe_init(HINSTANCE self, const char *tag);
void probe_stop(void);
void log_line(const char *fmt, ...);

/* ловушка на таблицу кадров: watch.c */
void watch_start(void);
void watch_rearm(void);
void watch_stop(void);

#endif
