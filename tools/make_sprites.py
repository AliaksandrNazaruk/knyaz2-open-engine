"""Спрайтовый лист из готового .blend с позой. Восемь направлений, игровой масштаб.

    blender -b --factory-startup --python tools/make_sprites.py -- [файл.blend]
            [--cell 160] [--px 46.01] [--out лист.png] [--frames 1]

Камера — ортографическая, наклон 33.48°, 46.01 пикселя на мировую единицу: ровно
как в игре. Точка ног попадает в (cell/2, cell*0.8) каждой клетки, рядом кладётся
json с этим якорем и порядком направлений.
"""
import bpy, json, math, os, sys
from mathutils import Vector

ROOT = r"C:\Users\User\Documents\Knyaz2Modding"
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def opt(n, d=None):
    return argv[argv.index(n) + 1] if n in argv else d
SRC = argv[0] if argv and not argv[0].startswith("--") else \
      os.path.join(ROOT, "hero_mixamo_posed.blend")
CELL = int(opt("--cell", "160"))
PX = float(opt("--px", "46.01"))
FRAMES = [int(x) for x in opt("--frames", "1").split(",")]
OUT = opt("--out", os.path.join(ROOT, "sprites",
                                os.path.splitext(os.path.basename(SRC))[0] + ".png"))
os.makedirs(os.path.dirname(OUT), exist_ok=True)

DIRS = ["W", "NW", "N", "NE", "E", "SE", "S", "SW"]
AZ = {"SE": 0, "E": 315, "NE": 270, "N": 225, "NW": 180, "W": 135, "SW": 90, "S": 45}
TILT = math.degrees(math.asin(math.tan(math.atan(16.0 / 29.0))))
ANCHOR_FRAC = 0.80

bpy.ops.wm.open_mainfile(filepath=SRC)
sc = bpy.context.scene

meshes = [o for o in bpy.data.objects
          if o.type == 'MESH' and not o.hide_render and len(o.data.vertices) > 100]
assert meshes, "в файле нет видимого меша"
# если мешей несколько (наш старый + импортированный) — берём самый крупный
meshes.sort(key=lambda m: len(m.data.polygons), reverse=True)
main = meshes[0]
for o in bpy.data.objects:
    if o.type == 'MESH' and o is not main:
        o.hide_render = True
    if o.type == 'ARMATURE':
        o.hide_render = True
print("меш %r: %d треугольников" % (main.name, len(main.data.polygons)))

dg = bpy.context.evaluated_depsgraph_get()
ev = main.evaluated_get(dg).to_mesh()
zs = [(main.matrix_world @ v.co).z for v in ev.vertices]
FOOT = min(zs)
print("точка ног z = %.4f, рост %.4f" % (FOOT, max(zs) - FOOT))

sc.render.engine = 'BLENDER_WORKBENCH'
sc.display.shading.light = 'STUDIO'
sc.display.shading.color_type = 'TEXTURE'
sc.display.shading.show_shadows = False
sc.render.film_transparent = True
sc.render.resolution_x = sc.render.resolution_y = CELL
sc.render.resolution_percentage = 100
sc.render.image_settings.file_format = 'PNG'
sc.render.image_settings.color_mode = 'RGBA'

cam_d = bpy.data.cameras.new("SpriteCam")
cam = bpy.data.objects.new("SpriteCam", cam_d)
sc.collection.objects.link(cam)
sc.camera = cam
cam_d.type = 'ORTHO'
cam_d.ortho_scale = CELL / PX
# поднимаем цель, чтобы точка ног села на 80 % высоты кадра, а не в центр
TGT = Vector((0.0, 0.0, FOOT + (ANCHOR_FRAC - 0.5) * cam_d.ortho_scale))
t = math.radians(TILT)
D = 20.0

TMP = os.path.join(ROOT, "sprites", "_tmp")
os.makedirs(TMP, exist_ok=True)
tiles = []
for fi, fr in enumerate(FRAMES):
    sc.frame_set(fr)
    for d in DIRS:
        ra = math.radians(AZ[d])
        cam.location = TGT + Vector((D * math.cos(t) * math.sin(ra),
                                     -D * math.cos(t) * math.cos(ra), D * math.sin(t)))
        cam.rotation_euler = (math.pi / 2 - t, 0, ra)
        p = os.path.join(TMP, "t_%d_%s.png" % (fr, d))
        sc.render.filepath = p
        bpy.ops.render.render(write_still=True)
        tiles.append((fi, d, p))

# склейка листа средствами Blender, без сторонних библиотек
W, H = CELL * len(DIRS), CELL * len(FRAMES)
sheet = bpy.data.images.new("sheet", W, H, alpha=True)
buf = [0.0] * (W * H * 4)
for fi, d, p in tiles:
    im = bpy.data.images.load(p)
    px = list(im.pixels)
    col = DIRS.index(d)
    # у Blender начало картинки внизу, строки идут снизу вверх
    row_from_bottom = len(FRAMES) - 1 - fi
    for y in range(CELL):
        src = y * CELL * 4
        dst = ((row_from_bottom * CELL + y) * W + col * CELL) * 4
        buf[dst:dst + CELL * 4] = px[src:src + CELL * 4]
    bpy.data.images.remove(im)
sheet.pixels = buf
sheet.file_format = 'PNG'
sheet.filepath_raw = OUT
sheet.save()

meta = {"cell": CELL, "px_per_unit": PX, "tilt": round(TILT, 4),
        "anchor": [CELL // 2, int(CELL * ANCHOR_FRAC)],
        "dirs": DIRS, "frames": FRAMES, "source": os.path.basename(SRC),
        "note": "столбцы — направления в порядке dirs, строки — кадры; "
                "anchor — точка ног внутри клетки"}
mp = os.path.splitext(OUT)[0] + ".json"
json.dump(meta, open(mp, "w"), ensure_ascii=False, indent=1)
for _, _, p in tiles:
    os.remove(p)
os.rmdir(TMP)
print("лист %dx%d -> %s" % (W, H, OUT))
print("описание -> %s" % mp)
