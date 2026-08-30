import math, random

CELL_W, CELL_H = 58, 16
ANCHOR_X_ODD, ANCHOR_X_EVEN, ANCHOR_Y = 29, 58, 16

def anchor(row, col):
    return (col*CELL_W + (ANCHOR_X_ODD if row & 1 else ANCHOR_X_EVEN), row*CELL_H + ANCHOR_Y)

# --- камера: yaw 45, pitch theta, орто ---
YAW = math.radians(45.0)
SIN_T = 16.0/29.0
THETA = math.asin(SIN_T)
L = CELL_W/2 / math.cos(YAW)          # мировых пикселей на 3D-единицу решётки

def project(p3):
    """3D (x,y,z), z вверх -> мировые пиксели (экран без камеры), в единицах L."""
    x, y, z = p3
    sy, cy = math.sin(YAW), math.cos(YAW)
    st, ct = math.sin(THETA), math.cos(THETA)
    sx = (-x*sy + y*cy) * L
    sy_up = (x*st*cy + y*st*sy + z*ct) * L
    return (sx, -sy_up)                # экранный Y вниз

def plane(X, Y):
    """мировые пиксели -> u (SE), v (NE)"""
    return (X/CELL_W + Y/(2*CELL_H), X/CELL_W - Y/(2*CELL_H))

def to3d(X, Y, height=0.0):
    u, v = plane(X, Y)
    return (-u, v, height/ (2*CELL_H) * SIN_T**0 )   # высота — отдельно, см. ниже

print(f"yaw   = 45.000000 deg")
print(f"pitch = {math.degrees(THETA):.6f} deg   (asin(16/29)); НЕ 30 и НЕ atan(16/29)={math.degrees(math.atan(SIN_T)):.4f}")
print(f"L     = {L:.6f} мировых пикселей на единицу решётки  (= 29*sqrt(2))")
print()

# --- доказательство: проекция 3D воспроизводит heroAnchor точно ---
worst = 0.0
random.seed(1)
for _ in range(200000):
    row = random.randrange(256); col = random.randrange(160)
    X, Y = anchor(row, col)
    u, v = plane(X, Y)
    px, py = project((-u, v, 0.0))
    worst = max(worst, abs(px - X), abs(py - Y))
print(f"худшая ошибка проекции по 200 000 клеткам сетки: {worst:.3e} px")

# --- проверка на восьми направлениях ---
STEPS = [(-58,0),(-29,-16),(0,-32),(29,-16),(58,0),(29,16),(0,32),(-29,16)]
for i,(dx,dy) in enumerate(STEPS):
    u,v = plane(dx,dy)
    px,py = project((-u,v,0.0))
    yaw = (math.degrees(math.atan2(-(-u), v)) ) % 360     # yaw модели вокруг Z
    print(f"  dir {i}: шаг ({dx:4d},{dy:4d}) -> латтис (u={u:+.2f}, v={v:+.2f}) -> обратно ({px:+.3f},{py:+.3f})  yaw={yaw:7.2f}")

# Прогон: python tools/hd_projection_check.py
# Числа и вывод — docs/HD_RENDERER_PASS2.md §1.
