"""Перенос нашей позы на риг Mixamo (или любой другой FBX со схожим скелетом).

    blender -b --factory-startup --python tools/pose_to_mixamo.py -- "путь.fbx"
            [--action Stance_Combat] [--frame 1] [--out имя.blend] [--shots]

Позы переносятся МИРОВЫМИ направлениями костей, а не углами: у Mixamo своя поза
покоя и свой крен, и локальные повороты дали бы другую позу. Кости, которых у них
нет (у нас есть hip.L/R, у них таза-бедра нет), при таком переносе не мешают —
их вклад уже сидит в мировом направлении следующей кости.
"""
import bpy, math, os, sys
from mathutils import Vector, Matrix

ROOT = r"C:\Users\User\Documents\Knyaz2Modding"
RIG = os.path.join(ROOT, "hero_textured_rig.blend")
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def opt(n, d):
    return argv[argv.index(n) + 1] if n in argv else d
FBX = argv[0]
ACTION = opt("--action", "Stance_Combat")
FRAME = int(opt("--frame", "1"))
OUT = opt("--out", os.path.join(ROOT, "hero_mixamo_posed.blend"))
SHOTS = "--shots" in argv

MAP = {"root": "Hips", "spine_01": "Spine", "spine_02": "Spine1", "chest": "Spine2",
       "neck": "Neck", "head": "Head"}
for s, S in (("L", "Left"), ("R", "Right")):
    MAP["clavicle." + s] = S + "Shoulder"
    MAP["upper_arm." + s] = S + "Arm"
    MAP["forearm." + s] = S + "ForeArm"
    MAP["hand." + s] = S + "Hand"
    MAP["thigh." + s] = S + "UpLeg"
    MAP["shin." + s] = S + "Leg"
    MAP["foot." + s] = S + "Foot"
    MAP["toe." + s] = S + "ToeBase"

# ---- 1. снимаем нашу позу мировыми направлениями ----
bpy.ops.wm.open_mainfile(filepath=RIG)
src = bpy.data.objects["RIG_Hero"]
sc = bpy.context.scene
act = bpy.data.actions.get(ACTION)
assert act, "нет экшена %r; есть: %s" % (ACTION, [a.name for a in bpy.data.actions])
if not src.animation_data:
    src.animation_data_create()
src.animation_data.action = act
if src.animation_data.action_slot is None and len(act.slots):
    src.animation_data.action_slot = act.slots[0]

src.data.pose_position = 'REST'
bpy.context.view_layer.update()
rest_pelvis = (src.matrix_world @ src.pose.bones["root"].tail).copy()
src.data.pose_position = 'POSE'
sc.frame_set(FRAME)
bpy.context.view_layer.update()

DIR, H_SRC = {}, 0.0
for n in MAP:
    pb = src.pose.bones[n]
    d = (src.matrix_world @ pb.tail) - (src.matrix_world @ pb.head)
    d.normalize()
    DIR[n] = d.copy()
posed_pelvis = (src.matrix_world @ src.pose.bones["root"].tail).copy()
DELTA = posed_pelvis - rest_pelvis
mesh = bpy.data.objects["Character_Mesh"]
zs = [(mesh.matrix_world @ v.co).z for v in mesh.data.vertices]
H_SRC = max(zs) - min(zs)
print("наша поза %r кадр %d: снято %d направлений, сдвиг таза %s, рост %.4f"
      % (ACTION, FRAME, len(DIR), tuple(round(v, 3) for v in DELTA), H_SRC))

# ---- 2. подтягиваем FBX в ту же сцену ----
bpy.ops.import_scene.fbx(filepath=FBX)
tgt = [o for o in bpy.data.objects
       if o.type == 'ARMATURE' and any(b.name.endswith("Hips") for b in o.data.bones)]
assert tgt, "в FBX не нашёлся скелет с костью Hips"
tgt = tgt[-1]
pref = next(b.name[:-4] for b in tgt.data.bones if b.name.endswith("Hips"))
print("целевой скелет %r, префикс костей %r, костей %d" % (tgt.name, pref, len(tgt.data.bones)))
if tgt.animation_data:
    tgt.animation_data.action = None            # своя мокап-дорожка Mixamo мешает

tmesh = [o for o in bpy.data.objects if o.type == 'MESH' and o.parent == tgt]
H_TGT = 1.0
if tmesh:
    zs = [(tmesh[0].matrix_world @ v.co).z for v in tmesh[0].data.vertices]
    H_TGT = max(zs) - min(zs)
print("рост цели %.4f, коэффициент %.4f" % (H_TGT, H_TGT / H_SRC))

M3 = tgt.matrix_world.to_3x3()
M3inv = M3.inverted()
def to_arm(d):                                   # мировое направление -> оси арматуры
    v = M3inv @ d
    v.normalize()
    return v

order, seen = [], set()
def emit(b):
    if b.name in seen:
        return
    if b.parent:
        emit(b.parent)
    seen.add(b.name)
    order.append(b.name)
for b in tgt.data.bones:
    emit(b)

bpy.context.view_layer.objects.active = tgt
bpy.ops.object.mode_set(mode='POSE')
for pb in tgt.pose.bones:
    pb.rotation_mode = 'QUATERNION'
    pb.rotation_quaternion = (1, 0, 0, 0)
    pb.location = (0, 0, 0)
bpy.context.view_layer.update()

rest_head = {n: tgt.pose.bones[n].head.copy() for n in order}
applied, report = 0, []
inv = {pref + v: k for k, v in MAP.items()}
for name in order:
    ours = inv.get(name)
    if not ours:
        continue
    pb = tgt.pose.bones[name]
    cur = (pb.tail - pb.head)
    if cur.length < 1e-6:
        continue
    cur.normalize()
    want = to_arm(DIR[ours])
    q = cur.rotation_difference(want)
    m = pb.matrix.copy()
    loc = m.to_translation()
    pb.matrix = Matrix.Translation(loc) @ (q.to_matrix() @ m.to_3x3()).to_4x4()
    bpy.context.view_layer.update()
    got = (pb.tail - pb.head).normalized()
    report.append((ours, name, math.degrees(got.angle(want))))
    applied += 1

# перенос таза: тот же мировой сдвиг, масштабированный по росту
hips = tgt.pose.bones[pref + "Hips"]
d_arm = M3inv @ (DELTA * (H_TGT / H_SRC))
hips.matrix = Matrix.Translation(d_arm) @ hips.matrix
bpy.context.view_layer.update()
bpy.ops.object.mode_set(mode='OBJECT')

print()
print("перенесено костей: %d" % applied)
print("%-14s %-26s %8s" % ("наша", "их", "ошибка°"))
worst = 0.0
for a, b, e in report:
    worst = max(worst, e)
    if e > 0.01:
        print("%-14s %-26s %8.3f" % (a, b, e))
print("макс ошибка направления: %.4f°" % worst)

if SHOTS:
    OUTDIR = os.path.join(ROOT, "tools", "mixamo_shots")
    os.makedirs(OUTDIR, exist_ok=True)
    for o in bpy.data.objects:
        if o.type in {'ARMATURE'}:
            o.hide_render = True
    if "Character_Mesh" in bpy.data.objects:
        bpy.data.objects["Character_Mesh"].hide_render = True
    if "Character_LowPoly" in bpy.data.objects:
        bpy.data.objects["Character_LowPoly"].hide_render = True
    sc.render.engine = 'BLENDER_WORKBENCH'
    sc.display.shading.light = 'STUDIO'
    sc.display.shading.color_type = 'TEXTURE'
    sc.display.shading.show_shadows = False
    sc.render.film_transparent = True
    sc.render.resolution_x = sc.render.resolution_y = 220
    sc.render.image_settings.color_mode = 'RGBA'
    TILT = math.degrees(math.asin(math.tan(math.atan(16.0 / 29.0))))
    AZ = {"SE": 0, "E": 315, "NE": 270, "N": 225, "NW": 180, "W": 135, "SW": 90, "S": 45}
    zs = [(tmesh[0].matrix_world @ v.co).z for v in tmesh[0].data.vertices]
    TGTP = Vector((0, 0, min(zs)))
    cam = bpy.data.objects.new("C", bpy.data.cameras.new("C"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.type = 'ORTHO'
    cam.data.ortho_scale = sc.render.resolution_x / 46.01
    t = math.radians(TILT)
    for nm, a in AZ.items():
        ra = math.radians(a)
        cam.location = TGTP + Vector((12 * math.cos(t) * math.sin(ra),
                                      -12 * math.cos(t) * math.cos(ra), 12 * math.sin(t)))
        cam.rotation_euler = (math.pi / 2 - t, 0, ra)
        sc.render.filepath = os.path.join(OUTDIR, "mx_%s.png" % nm)
        bpy.ops.render.render(write_still=True)
    print("контрольные кадры:", OUTDIR)

bpy.ops.wm.save_as_mainfile(filepath=OUT)
print("сохранено:", OUT)
