# -*- coding: utf-8 -*-
"""Подготовить ролик фона стартового меню для браузера.

    python tools\\menu_video.py <исходник.mp4> [--crf 26] [--no-loop-fix]

Исходник обычно 1664x1248 и весит десятки мегабайт со звуком. Для фона меню
нужно ровно обратное: экран игры 1024x768 (то же 4:3), звук не нужен вовсе —
браузер не пускает автозапуск со звуком, — а файл должен быть маленьким,
потому что dev-сервер отдаёт его целиком, без Range.

Шов петли: ролик не замкнут, и на стыке виден рывок. Лечим склейкой —
последние LOOP_TAIL секунд растворяются в первых LOOP_TAIL, длительность
уменьшается на столько же. Ключ --no-loop-fix отключает склейку.

Заодно кладём кадр-заставку: пока видео не приехало, <video poster> держит
картинку, и меню не мигает чёрным.
"""
import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'knyaz2', 'web', 'static', 'menu')

WIDTH, HEIGHT = 1024, 768
FPS = 24
LOOP_TAIL = 1.0            # секунд перекрытия на склейке петли
POSTER_AT = 9.0            # секунда, с которой берём заставку


def ffmpeg_exe():
    """ffmpeg из imageio-ffmpeg, если системного нет."""
    from shutil import which
    found = which('ffmpeg')
    if found:
        return found
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def duration(source):
    from av import open as av_open
    with av_open(source) as container:
        return float(container.duration) / 1_000_000


def run(exe, args):
    result = subprocess.run([exe, '-hide_banner', '-loglevel', 'error', '-y', *args])
    if result.returncode:
        raise SystemExit(f'ffmpeg вернул {result.returncode}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source')
    parser.add_argument('--crf', type=int, default=26)
    parser.add_argument('--no-loop-fix', action='store_true')
    options = parser.parse_args()

    os.makedirs(OUT, exist_ok=True)
    exe = ffmpeg_exe()
    total = duration(options.source)
    video = os.path.join(OUT, 'intro.mp4')
    poster = os.path.join(OUT, 'intro-poster.jpg')

    scale = f'scale={WIDTH}:{HEIGHT}:flags=lanczos'
    if options.no_loop_fix:
        chain = scale
    else:
        # xfade склеивает два потока: «всё, кроме хвоста» и «хвост», причём
        # хвост наезжает на начало. Готовим оба входа из одного файла;
        # xfade требует постоянной частоты кадров, поэтому явный fps.
        body = total - LOOP_TAIL
        chain = (f'[0:v]{scale},trim=0:{body:.3f},setpts=PTS-STARTPTS,fps={FPS}[body];'
                 f'[0:v]{scale},trim={body:.3f}:{total:.3f},setpts=PTS-STARTPTS,fps={FPS}[tail];'
                 f'[tail][body]xfade=transition=fade:duration={LOOP_TAIL}:'
                 f'offset=0,format=yuv420p[v]')

    args = ['-i', options.source]
    args += (['-vf', f'{chain},format=yuv420p'] if options.no_loop_fix
             else ['-filter_complex', chain, '-map', '[v]'])
    args += ['-an', '-c:v', 'libx264', '-profile:v', 'high', '-preset', 'slow',
             '-crf', str(options.crf), '-pix_fmt', 'yuv420p',
             '-movflags', '+faststart', video]
    run(exe, args)

    run(exe, ['-ss', str(POSTER_AT), '-i', options.source, '-frames:v', '1',
              '-vf', scale, '-q:v', '4', poster])

    print(f'ролик {total:.2f} c -> menu/intro.mp4 '
          f'({os.path.getsize(video) / 1048576:.1f} МБ, {WIDTH}x{HEIGHT}, без звука)')
    print(f'заставка -> menu/intro-poster.jpg '
          f'({os.path.getsize(poster) / 1024:.0f} КБ)')


if __name__ == '__main__':
    main()
