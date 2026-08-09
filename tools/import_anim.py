"""Загрузка анимации из браузерного редактора обратно в риг.

    blender -b --factory-startup --python tools/import_anim.py -- клип.json [ещё.json ...] [--shots]

Создаёт в hero_textured_rig.blend экшен с именем из файла, ставит ключи на всех
кадрах (между ключами редактора — линейная интерполяция поворотов), сохраняет файл.
С --shots дополнительно рендерит контрольную полосу кадров в tools/webanim/.
"""
import bpy, json, os, sys, math
from mathutils import Quaternion, Vector

ROOT = r"C:\Users\User\Documents\Knyaz2Modding"
SAVE = os.path.join(ROOT, "hero_textured_rig.blend")
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
SHOTS = "--shots" in argv
files = [a for a in argv if not a.startswith("--")]
assert files, "укажи хотя бы один json из редактора"

bpy.ops.wm.open_mainfile(filepath=SAVE)
arm = bpy.data.objects["RIG_Hero"]
mesh = bpy.data.objects["Character_Mesh"]
sc = bpy.context.scene
if not arm.animation_data:
    arm.animation_data_create()
for pb in arm.pose.bones:
    pb.rotation_mode = 'QUATERNION'

made = []
for path in files:
    o = json.load(open(path, encoding="utf-8"))
    names = o["bones"]
    unknown = [n for n in names if n not in arm.pose.bones]
    assert not unknown, "в риге нет костей: %s" % unknown
    keys = {int(k): v for k, v in o["keys"].items()}
    kf = sorted(keys)
    length = int(o["length"])
    print("%-30s кадров %d, ключей %d: %s" % (o["name"], length, len(kf), kf))

    act = bpy.data.actions.get(o["name"]) or bpy.data.actions.new(o["name"])
    act.use_fake_user = True
    arm.animation_data.action = act
    if arm.animation_data.action_slot is None and len(act.slots):
        arm.animation_data.action_slot = act.slots[0]

    def sample(f):
        if f in keys:
            return keys[f]
        lo = [k for k in kf if k <= f]
        hi = [k for k in kf if k >= f]
        if not lo: return keys[hi[0]]
        if not hi: return keys[lo[-1]]
        a, b = lo[-1], hi[0]
        t = (f - a) / (b - a)
        A, B = keys[a], keys[b]
        return dict(
            q=[list(Quaternion(A["q"][i]).slerp(Quaternion(B["q"][i]), t))
               for i in range(len(names))],
            loc=[A["loc"][i] + (B["loc"][i] - A["loc"][i]) * t for i in range(3)])

    for f in range(1, length + 1):
        s = sample(f)
        for i, n in enumerate(names):
            pb = arm.pose.bones[n]
            pb.rotation_quaternion = Quaternion(s["q"][i]).normalized()
            pb.keyframe_insert("rotation_quaternion", frame=f)
        rb = arm.pose.bones["root"]
        rb.location = Vector(s["loc"])
        rb.keyframe_insert("location", frame=f)
    made.append((o["name"], length, o.get("fps", 24)))

name, length, fps = made[-1]
act = bpy.data.actions[name]
arm.animation_data.action = act
sc.frame_start, sc.frame_end = 1, length
sc.render.fps = int(fps)

# контроль: меш действительно шевелится и не рвётся
dom = {}
for v in mesh.data.vertices:
    best, bw = None, -1.0
    for g in v.groups:
        if g.weight > bw: bw, best = g.weight, g.group
    dom[v.index] = mesh.vertex_groups[best].name if best is not None else "?"
arm.data.pose_position = 'REST'
dg = bpy.context.evaluated_depsgraph_get(); dg.update()
rest = [v.co.copy() for v in mesh.evaluated_get(dg).to_mesh().vertices]
arm.data.pose_position = 'POSE'
worst, moved = (0.0, "", 0), 0.0
for f in range(1, length + 1, max(1, length // 8)):
    sc.frame_set(f)
    dg = bpy.context.evaluated_depsgraph_get(); dg.update()
    pos = [v.co.copy() for v in mesh.evaluated_get(dg).to_mesh().vertices]
    moved = max(moved, max((pos[i] - rest[i]).length for i in range(0, len(pos), 97)))
    for e in mesh.data.edges:
        a, b = e.vertices
        l0 = (rest[a] - rest[b]).length
        if l0 < 2e-3: continue
        dl = (pos[a] - pos[b]).length - l0
        if dl > worst[0]: worst = (dl, dom[a], f)
print("макс смещение вершины: %.3f;  макс удлинение ребра: %.4f (%s, кадр %d)"
      % (moved, worst[0], worst[1], worst[2]))

if SHOTS:
    OUT = os.path.join(ROOT, "tools", "webanim")
    arm.hide_render = True
    sc.render.engine = 'BLENDER_WORKBENCH'
    sc.display.shading.light = 'STUDIO'
    sc.display.shading.color_type = 'TEXTURE'
    sc.display.shading.show_shadows = False
    sc.render.resolution_x = sc.render.resolution_y = 360
    cam = bpy.data.objects.get("ChkCam")
    if not cam:
        cam = bpy.data.objects.new("ChkCam", bpy.data.cameras.new("ChkCam"))
        sc.collection.objects.link(cam)
    cam.data.type = 'ORTHO'; cam.data.ortho_scale = 2.15
    cam.location = Vector((4.3, -4.3, 0)); cam.rotation_euler = (math.radians(90), 0, math.radians(45))
    sc.camera = cam
    for i in range(4):
        sc.frame_set(1 + round(i * (length - 1) / 3))
        sc.render.filepath = os.path.join(OUT, "chk_%d.png" % i)
        bpy.ops.render.render(write_still=True)
    print("контрольные кадры в", OUT)

sc.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=SAVE)
print("сохранено:", SAVE, "| экшены:", [m[0] for m in made])
