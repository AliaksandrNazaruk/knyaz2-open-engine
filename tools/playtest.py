# -*- coding: utf-8 -*-
"""
Запуск игры из тестового зеркала и снятие скриншотов.

    python tools\\playtest.py start [сек]     запустить и снять экран
    python tools\\playtest.py shot [имя]      снять экран
    python tools\\playtest.py key ESC         нажать клавишу
    python tools\\playtest.py click X Y       щёлкнуть мышью
    python tools\\playtest.py windows         перечислить окна игры
    python tools\\playtest.py stop            закрыть игру
"""
import ctypes
import os
import subprocess
import sys
import time

RIG = os.path.join(os.path.expanduser('~'), 'Documents', 'Knyaz2Test')
EXE = os.path.join(RIG, 'konung2.exe')
SHOTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'shots')
os.makedirs(SHOTS, exist_ok=True)

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()

VK = {'ESC': 0x1B, 'ENTER': 0x0D, 'SPACE': 0x20, 'UP': 0x26, 'DOWN': 0x28,
      'LEFT': 0x25, 'RIGHT': 0x27, 'F1': 0x70, 'N': 0x4E, 'Y': 0x59, 'TAB': 0x09}


def shot(name='shot'):
    from PIL import ImageGrab
    img = ImageGrab.grab(all_screens=False)
    path = os.path.join(SHOTS, f'{name}.png')
    img.save(path)
    # немного статистики, чтобы понять, не чёрный ли кадр
    small = img.convert('RGB').resize((64, 48))
    px = list(small.getdata())
    nonblack = sum(1 for p in px if sum(p) > 30)
    print(f"{path}  {img.size}  непустых пикселей: {nonblack}/{len(px)}")
    return path


#: Игра рисует интерфейс в сетке 1024x768, но в полноэкранном режиме может
#: переключать монитор в другое разрешение — тогда экранные координаты клика
#: не совпадают с координатами на скриншоте. Пересчитываем по факту.
UI_W, UI_H = 1024, 768


def ui_scale():
    """Множители перевода координат интерфейса в экранные."""
    w = user32.GetSystemMetrics(0)
    h = user32.GetSystemMetrics(1)
    return w / UI_W, h / UI_H


def click_ui(x, y, double=False):
    """Клик по точке интерфейса (координаты как на скриншоте 1024x768)."""
    kx, ky = ui_scale()
    click(int(x * kx), int(y * ky), double)


def windows():
    found = []
    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                rect = ctypes.create_string_buffer(16)
                user32.GetWindowRect(hwnd, rect)
                import struct as _s
                l, t, r, b = _s.unpack('<4i', rect.raw)
                found.append((hwnd, buf.value, (l, t, r - l, b - t)))
        return True

    user32.EnumWindows(EnumProc(cb), 0)
    for hwnd, title, rect in found:
        print(f"  hwnd=0x{hwnd:X} {rect}  {title}")
    return found


def focus_game():
    """Вернуть окно игры на передний план.

    Игра — полноэкранное DirectDraw-приложение: потеряв фокус, оно
    сворачивается и отдаёт разрешение рабочему столу. Поэтому мало
    SetForegroundWindow — окно надо ещё и развернуть.
    """
    for hwnd, title, rect in windows():
        if 'onung' in title or 'нязь' in title:
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)        # SW_RESTORE
                time.sleep(1.2)
            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)
            time.sleep(0.5)
            return hwnd
    return None


def key(name):
    vk = VK.get(name.upper(), ord(name[0].upper()) if name else 0)
    focus_game()
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.05)
    user32.keybd_event(vk, 0, 2, 0)
    print(f"нажата {name}")


def click(x, y, double=False):
    focus_game()
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.2)
    for _ in range(2 if double else 1):
        user32.mouse_event(2, 0, 0, 0, 0)   # LEFTDOWN
        time.sleep(0.05)
        user32.mouse_event(4, 0, 0, 0, 0)   # LEFTUP
        time.sleep(0.1)
    print(f"клик ({x}, {y})" + (" x2" if double else ""))


def scroll(x, y, hold=2.5):
    """Подвести курсор к краю экрана — игра прокручивает камеру."""
    focus_game()
    user32.SetCursorPos(int(x), int(y))
    time.sleep(hold)
    print(f"камера: курсор в ({x}, {y}) на {hold} с")


def start(wait=15):
    if not os.path.exists(EXE):
        sys.exit(f"нет {EXE} — соберите зеркало: tools\\make_testrig.ps1")
    p = subprocess.Popen([EXE], cwd=RIG)
    print(f"запущено, pid {p.pid}, ждём {wait} с")
    time.sleep(wait)
    windows()
    shot('start')


def demo(hero=0, hover=None):
    """Полный проход одним процессом: запуск, новая игра, выбор героя, осмотр.

    Всё делается без возврата в консоль: полноэкранная игра сворачивается,
    как только фокус уходит другому окну, и после этого её не поднять.
    hero — номер портрета 0..5, hover — список точек (x, y) для наведения.
    """
    stop()
    time.sleep(1)
    injector = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            '..', 'hook', 'build', 'inject.exe')
    hookdll = os.path.join(RIG, 'konung_hook.dll')
    if '--inject' in sys.argv and os.path.exists(injector) and os.path.exists(hookdll):
        # запуск через инжектор: наш код внутри процесса ещё до старта движка
        subprocess.run([injector, EXE, hookdll], cwd=RIG)
        print("запущено через инжектор")
        p = None
    else:
        p = subprocess.Popen([EXE], cwd=RIG)
        print(f"pid {p.pid}, ждём загрузки")
    time.sleep(22)
    key('ESC')                                    # пропустить заставку
    time.sleep(4)
    shot('demo_menu')
    print(f"масштаб интерфейса: {ui_scale()}")
    click_ui(512, 390)                            # НОВАЯ ИГРА
    time.sleep(4)
    shot('demo_heroes')
    portraits = [(145, 155), (300, 155), (465, 155),
                 (145, 285), (300, 285), (465, 285)]
    click_ui(*portraits[hero])
    time.sleep(2.5)
    click_ui(145, 708)                            # ОК
    time.sleep(20)
    shot('demo_world')
    for i, (x, y) in enumerate(hover or []):
        user32.SetCursorPos(int(x), int(y))
        time.sleep(1.5)
        shot(f'demo_hover{i}_{x}_{y}')


def stop():
    subprocess.run(['taskkill', '/F', '/IM', 'konung2.exe'], capture_output=True)
    print("игра закрыта")


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'shot'
    if cmd == 'start':
        start(int(sys.argv[2]) if len(sys.argv) > 2 else 15)
    elif cmd == 'shot':
        time.sleep(float(sys.argv[3]) if len(sys.argv) > 3 else 0)
        shot(sys.argv[2] if len(sys.argv) > 2 else 'shot')
    elif cmd == 'key':
        key(sys.argv[2])
        time.sleep(1.5)
        shot('after_' + sys.argv[2])
    elif cmd == 'click':
        click(sys.argv[2], sys.argv[3], double='--double' in sys.argv)
        time.sleep(1.5)
        shot('after_click')
    elif cmd == 'demo':
        pts = [tuple(map(int, a.split(','))) for a in sys.argv[3:]]
        demo(int(sys.argv[2]) if len(sys.argv) > 2 else 0, pts)
    elif cmd == 'scroll':
        scroll(sys.argv[2], sys.argv[3], float(sys.argv[4]) if len(sys.argv) > 4 else 2.5)
        shot('scroll_' + sys.argv[2] + '_' + sys.argv[3])
    elif cmd == 'windows':
        windows()
    elif cmd == 'stop':
        stop()
    else:
        print(__doc__)
