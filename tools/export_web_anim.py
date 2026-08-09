"""Выгрузка героя в компактный пакет для браузерного редактора анимаций.

    blender -b --factory-startup --python tools/export_web_anim.py

Пишет tools/webanim/payload.json: облегчённый меш со скиннингом (base64 типизированных
массивов), скелет с матрицами покоя и уже готовые циклы как стартовые ключи.
"""
import bpy, base64, json, os, struct, array
from mathutils import Vector

ROOT = r"C:\Users\User\Documents\Knyaz2Modding"
SRC = os.path.join(ROOT, "hero_textured_rig.blend")
OUT = os.path.join(ROOT, "tools", "webanim")
os.makedirs(OUT, exist_ok=True)
TARGET_TRIS = 24000

bpy.ops.wm.open_mainfile(filepath=SRC)
arm = bpy.data.objects["RIG_Hero"]
low = bpy.data.objects["Character_LowPoly"]

work = low.copy()
work.data = low.data.copy()
work.name = "web_export"
work.hide_viewport = work.hide_render = False
bpy.context.scene.collection.objects.link(work)
bpy.context.view_layer.objects.active = work
if len(work.data.polygons) > TARGET_TRIS:
    d = work.modifiers.new("dec", 'DECIMATE')
    d.ratio = TARGET_TRIS / len(work.data.polygons)
    bpy.ops.object.modifier_apply(modifier="dec")
me = work.data
me.calc_loop_triangles()
print("экспорт: %d вершин, %d треугольников" % (len(me.vertices), len(me.loop_triangles)))
assert len(me.vertices) < 65536, "слишком много вершин для 16-битных индексов"

# все кости, включая недеформирующую root — она несёт перемещение тела
deform = [b.name for b in arm.data.bones]
bidx = {n: i for i, n in enumerate(deform)}
skinnable = {b.name for b in arm.data.bones if b.use_deform}
gname = {g.index: g.name for g in work.vertex_groups}

nv = len(me.vertices)
pos = array.array("f"); nor = array.array("f")
si = array.array("B"); sw = array.array("B")
for v in me.vertices:
    pos.extend(v.co)
    nor.extend(v.normal)
    ws = []
    for g in v.groups:
        n = gname.get(g.group)
        if n in skinnable and g.weight > 0:
            ws.append((g.weight, bidx[n]))
    ws.sort(reverse=True)
    ws = ws[:4]
    tot = sum(w for w, _ in ws) or 1.0
    for k in range(4):
        if k < len(ws):
            si.append(ws[k][1]); sw.append(max(0, min(255, round(ws[k][0] / tot * 255))))
        else:
            si.append(0); sw.append(0)

idx = array.array("H")
for t in me.loop_triangles:
    idx.extend(t.vertices)

bones = []
for n in deform:
    b = arm.data.bones[n]
    m = b.matrix_local
    bones.append(dict(
        name=n,
        parent=bidx[b.parent.name] if b.parent else -1,
        deform=n in skinnable,
        rest=[c for row in zip(*m) for c in row],          # column-major 4x4
        head=list(b.head_local), tail=list(b.tail_local),
        length=(b.tail_local - b.head_local).length))

# --- готовые циклы как стартовые ключи ---
sc = bpy.context.scene
clips = {}
for act in bpy.data.actions:
    if not act.name.endswith("__retarget"):
        continue
    arm.animation_data.action = act
    if arm.animation_data.action_slot is None and len(act.slots):
        arm.animation_data.action_slot = act.slots[0]
    f0, f1 = int(act.frame_range[0]), int(act.frame_range[1])
    keys = {}
    for f in range(f0, f1 + 1):
        sc.frame_set(f)
        bpy.context.view_layer.update()
        keys[str(f - f0 + 1)] = dict(
            bones={pb.name: [round(c, 5) for c in pb.rotation_quaternion]
                   for pb in arm.pose.bones},
            root=[round(c, 5) for c in arm.pose.bones["root"].location])
    clips[act.name.replace("__retarget", "")] = dict(length=f1 - f0 + 1, keys=keys)
    print("  цикл %-40s %d кадров" % (act.name, f1 - f0 + 1))

def b64(a):
    return base64.b64encode(a.tobytes()).decode("ascii")

payload = dict(
    counts=dict(verts=nv, tris=len(idx) // 3, bones=len(bones)),
    bounds=dict(lo=[min(v.co[i] for v in me.vertices) for i in range(3)],
                hi=[max(v.co[i] for v in me.vertices) for i in range(3)]),
    bones=bones,
    all_bone_names=[b.name for b in arm.data.bones],
    buffers=dict(pos=b64(pos), nor=b64(nor), skin_idx=b64(si), skin_wt=b64(sw), idx=b64(idx)),
    clips=clips)

p = os.path.join(OUT, "payload.json")
json.dump(payload, open(p, "w"), separators=(",", ":"))
print("записано %s  %.2f MB" % (p, os.path.getsize(p) / 1024 / 1024))
