"""Рендер героя игровой изометрической камерой.

    blender -b --factory-startup --python tools/render_iso.py -- [--px 47.24] [--out каталог] [--pose relaxed]

Камера ортографическая, наклон 33.48° — выведен из шага юнита по диагонали (29,16):
мировой азимут 45° даёт экранный угол atan(16/29)=28.9°, значит sin(наклона)=tan(28.9°).
Цель камеры — ТОЧКА НОГ (0,0,низ меша), она же якорь спрайта, и попадает в центр кадра.
"""
import bpy, math, os, sys, json
from mathutils import Vector, Matrix

ROOT = r"C:\Users\User\Documents\Knyaz2Modding"
SAVE = os.path.join(ROOT, "hero_textured_rig.blend")
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def opt(name, default):
    return argv[argv.index(name) + 1] if name in argv else default

PX_PER_UNIT = float(opt("--px", "47.24"))
OUT = opt("--out", os.path.join(ROOT, "tools", "isoshots"))
POSE = opt("--pose", "relaxed")
RES = int(opt("--res", "200"))
os.makedirs(OUT, exist_ok=True)

ELEV = math.degrees(math.atan(16.0 / 29.0))          # 28.9° — экранный угол диагонали
TILT = math.degrees(math.asin(math.tan(math.radians(ELEV))))   # 33.48° — наклон камеры
# Направление спрайта -> азимут камеры (0 = камера перед моделью, модель смотрит в -Y).
# ВЫВЕДЕНО ЗАМЕРОМ, не из таблицы шагов: спрайт с индексом d нарисован смотрящим
# по вектору шага индекса d+1 — подписи блоков анимации сдвинуты на одну позицию.
# Проверено на всех 8: ширина силуэта (макс на SE/NW, мин на NE/SW) и вид (SE — лицо
# в камеру, NE — профиль вправо) совпадают только при этой раскладке.
AZ = {"SE": 0, "E": 315, "NE": 270, "N": 225, "NW": 180, "W": 135, "SW": 90, "S": 45}

bpy.ops.wm.open_mainfile(filepath=SAVE)
arm = bpy.data.objects["RIG_Hero"]
mesh = bpy.data.objects["Character_Mesh"]
sc = bpy.context.scene
if arm.animation_data:
    arm.animation_data.action = None
for pb in arm.pose.bones:
    pb.rotation_mode = 'QUATERNION'
    pb.rotation_quaternion = (1, 0, 0, 0)
    pb.location = (0, 0, 0)

REST = {b.name: b.matrix_local.to_3x3().normalized() for b in arm.data.bones}
PAR = {b.name: (b.parent.name if b.parent else None) for b in arm.data.bones}
order = []
def emit(b):
    if b.parent and b.parent.name not in order: emit(b.parent)
    if b.name not in order: order.append(b.name)
for b in arm.data.bones: emit(b)

ACTION = opt("--action", "")
if ACTION:                                  # поза из экшена (например, из редактора)
    act = bpy.data.actions[ACTION]
    if not arm.animation_data:
        arm.animation_data_create()
    arm.animation_data.action = act
    if arm.animation_data.action_slot is None and len(act.slots):
        arm.animation_data.action_slot = act.slots[0]
    sc.frame_set(int(opt("--frame", "1")))
    bpy.context.view_layer.update()
    print("поза из экшена %s, кадр %s" % (ACTION, opt("--frame", "1")))
elif POSE == "relaxed":
    TARGET = {"upper_arm.L": Vector((0.40, 0.06, -0.91)), "forearm.L": Vector((0.30, -0.20, -0.93)),
              "upper_arm.R": Vector((-0.40, 0.06, -0.91)), "forearm.R": Vector((-0.30, -0.20, -0.93))}
    W = {}
    for name in order:
        p = PAR[name]
        Rp = W[p] if p else Matrix.Identity(3)
        rel = (REST[p].inverted() @ REST[name]) if p else REST[name]
        base = Rp @ rel
        if name in TARGET:
            d0 = (base @ Vector((0, 1, 0))).normalized()
            R = d0.rotation_difference(TARGET[name].normalized()).to_matrix() @ base
            axis = (R @ Vector((0, 1, 0))).normalized()
            sgn = 1.0 if name.endswith(".L") else -1.0
            k = 1.0 if name.startswith("upper_arm") else 0.25
            R = Matrix.Rotation(math.radians(55 * sgn * k), 3, axis) @ R   # пронация ладоней
            W[name] = R
        else:
            W[name] = base
        arm.pose.bones[name].rotation_quaternion = (base.inverted() @ W[name]).to_quaternion()
    bpy.context.view_layer.update()

Z_FEET = min((mesh.matrix_world @ v.co).z for v in mesh.data.vertices)
TGT = Vector((0.0, 0.0, Z_FEET))
arm.hide_render = True

sc.render.engine = 'BLENDER_WORKBENCH'
sc.display.shading.light = 'STUDIO'
sc.display.shading.color_type = 'SINGLE'
sc.display.shading.show_shadows = False
sc.render.film_transparent = True
sc.render.resolution_x = sc.render.resolution_y = RES
sc.render.image_settings.file_format = 'PNG'
sc.render.image_settings.color_mode = 'RGBA'

cam = bpy.data.objects.get("IsoCam")
if not cam:
    cam = bpy.data.objects.new("IsoCam", bpy.data.cameras.new("IsoCam"))
    sc.collection.objects.link(cam)
sc.camera = cam
cam.data.type = 'ORTHO'
cam.data.ortho_scale = RES / PX_PER_UNIT
D = 12.0
t = math.radians(TILT)

if "--sweep" in argv:                      # перебор азимутов для подгонки под оригинал
    step = int(opt("--sweep", "15"))
    AZ = {"a%03d" % a: a for a in range(0, 360, step)}

meta = dict(tilt=TILT, screen_diag_angle=ELEV, px_per_unit=PX_PER_UNIT, res=RES,
            ortho_scale=cam.data.ortho_scale, z_feet=Z_FEET, anchor=[RES / 2, RES / 2], az=AZ)
for name, a in AZ.items():
    ra = math.radians(a)
    cam.location = TGT + Vector((D * math.cos(t) * math.sin(ra),
                                 -D * math.cos(t) * math.cos(ra),
                                 D * math.sin(t)))
    cam.rotation_euler = (math.pi / 2 - t, 0, ra)
    sc.render.filepath = os.path.join(OUT, "iso_%s.png" % name)
    bpy.ops.render.render(write_still=True)
    print("  %-3s азимут %+4d°" % (name, a))

json.dump(meta, open(os.path.join(OUT, "iso.json"), "w"), indent=1)
print("наклон камеры %.2f°, %.2f px на единицу, ortho_scale %.4f" % (TILT, PX_PER_UNIT, cam.data.ortho_scale))
print("записано в", OUT)
