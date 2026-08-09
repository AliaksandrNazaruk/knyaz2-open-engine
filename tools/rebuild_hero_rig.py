"""Пересборка рига героя из model.glb + texture_diffuse.jpg.

Запуск:
    blender -b --factory-startup --python tools/rebuild_hero_rig.py -- [joints.json]

Без аргумента берутся координаты, снятые с геометрии автоматически.
С аргументом — твои координаты из joint_editor.html.

Что делает: импорт glb -> сварка вершин по швам -> материал с текстурой ->
скелет по координатам -> веса (bone heat на упрощённой копии + перенос) ->
ретаргет мокап-циклов со старого рига -> проверки -> сохранение .blend.
"""
import bpy, bmesh, json, os, sys, math, time
from mathutils import Vector, Matrix

ROOT = r"C:\Users\User\Documents\Knyaz2Modding"
GLB = r"C:\Users\User\Downloads\model.glb"
TEX = r"C:\Users\User\Downloads\texture_diffuse.jpg"
MOCAP = os.path.join(ROOT, "base_proportions_walk_mocap_female.blend")
OLD_RIG = os.path.join(ROOT, "tools", "old_rig_template.json")
SAVE = os.path.join(ROOT, "hero_textured_rig.blend")
H_OLD = 2.134

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
JOINTS = argv[0] if argv else None

t0 = time.time()
def log(*a):
    print("[%5.1fs]" % (time.time() - t0), *a, flush=True)

DEFAULT_JOINTS = {
  "common": {"ground": [0.0, 0.020, -0.9537], "pelvis": [0.0, 0.0, 0.010],
             "spine1": [0.0, -0.015, 0.375], "spine2": [0.0, -0.014, 0.395],
             "neck_base": [0.0, 0.020, 0.612], "head_base": [0.0, 0.020, 0.755],
             "head_top": [0.0, 0.015, 0.930]},
  "L": {"shoulder": [0.165, 0.060, 0.562], "elbow": [0.520, 0.066, 0.425],
        "wrist": [0.715, 0.052, 0.376], "hand_tip": [0.850, 0.030, 0.370],
        "hip": [0.092, 0.020, 0.050], "knee": [0.073, 0.035, -0.420],
        "ankle": [0.052, 0.030, -0.875], "toe": [0.057, -0.120, -0.930],
        "toe_tip": [0.057, -0.165, -0.940]},
  "R": {"shoulder": [-0.165, 0.060, 0.562], "elbow": [-0.520, 0.066, 0.425],
        "wrist": [-0.715, 0.052, 0.376], "hand_tip": [-0.850, 0.030, 0.370],
        "hip": [-0.095, 0.020, 0.050], "knee": [-0.074, 0.030, -0.420],
        "ankle": [-0.062, 0.035, -0.875], "toe": [-0.075, -0.120, -0.930],
        "toe_tip": [-0.075, -0.165, -0.940]}}

J = json.load(open(JOINTS, encoding="utf-8")) if JOINTS else DEFAULT_JOINTS
log("координаты суставов: %s" % (JOINTS or "по умолчанию (замер по геометрии)"))

# ---------------------------------------------------------------- меш
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=GLB)
mesh = [o for o in bpy.data.objects if o.type == 'MESH'][0]
mesh.name = mesh.data.name = "Character_Mesh"
bpy.context.view_layer.objects.active = mesh
mesh.select_set(True)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
n0 = len(mesh.data.vertices)
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.remove_doubles(threshold=1e-5)
bpy.ops.mesh.normals_make_consistent(inside=False)
bpy.ops.object.mode_set(mode='OBJECT')
mesh.select_set(False)
bm = bmesh.new(); bm.from_mesh(mesh.data)
nm = sum(1 for e in bm.edges if not e.is_manifold); bm.free()
log("меш: %d -> %d вершин, немногообразных рёбер %d" % (n0, len(mesh.data.vertices), nm))

mat = bpy.data.materials.new("Hero_Diffuse")
mat.use_nodes = True
nt = mat.node_tree
bsdf = nt.nodes["Principled BSDF"]
bsdf.inputs["Roughness"].default_value = 0.7
img = nt.nodes.new("ShaderNodeTexImage"); img.location = (-400, 300)
img.image = bpy.data.images.load(TEX)
nt.links.new(img.outputs["Color"], bsdf.inputs["Base Color"])
mesh.data.materials.clear(); mesh.data.materials.append(mat)

Z_FEET = min(v.co.z for v in mesh.data.vertices)
H_NEW = max(v.co.z for v in mesh.data.vertices) - Z_FEET

# ---------------------------------------------------------------- скелет
C, S = J["common"], {"L": J["L"], "R": J["R"]}
V = lambda t: Vector(t)
SPEC = [("root", V(C['ground']), V(C['pelvis']), None, False, False),
        ("spine_01", V(C['pelvis']), V(C['spine1']), "root", True, True),
        ("spine_02", V(C['spine1']), V(C['spine2']), "spine_01", True, True),
        ("chest", V(C['spine2']), V(C['neck_base']), "spine_02", True, True),
        ("neck", V(C['neck_base']), V(C['head_base']), "chest", True, True),
        ("head", V(C['head_base']), V(C['head_top']), "neck", True, True)]
for s in ("L", "R"):
    q = S[s]
    # Ключица — КОРОТКАЯ кость у основания шеи, ребёнок груди.
    # Если вести её от spine2 (пояс), она пересекает весь торс и автовеса отдают
    # ей ~36 000 вершин грудной клетки: поворот ключицы раздувает плечи.
    clav_head = V(C['neck_base']).lerp(V(q['shoulder']), 0.12)
    SPEC += [("clavicle.%s" % s,  clav_head, V(q['shoulder']), "chest", False, True),
             ("upper_arm.%s" % s, V(q['shoulder']), V(q['elbow']), "clavicle.%s" % s, True, True),
             ("forearm.%s" % s,   V(q['elbow']), V(q['wrist']), "upper_arm.%s" % s, True, True),
             ("hand.%s" % s,      V(q['wrist']), V(q['hand_tip']), "forearm.%s" % s, True, True),
             ("hip.%s" % s,       V(C['pelvis']), V(q['hip']), "root", False, True),
             ("thigh.%s" % s,     V(q['hip']), V(q['knee']), "hip.%s" % s, True, True),
             ("shin.%s" % s,      V(q['knee']), V(q['ankle']), "thigh.%s" % s, True, True),
             ("foot.%s" % s,      V(q['ankle']), V(q['toe']), "shin.%s" % s, True, True),
             ("toe.%s" % s,       V(q['toe']), V(q['toe_tip']), "foot.%s" % s, True, True)]

arm = bpy.data.objects.new("RIG_Hero", bpy.data.armatures.new("Hero_Armature"))
bpy.context.scene.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode='EDIT')
eb = arm.data.edit_bones
for name, head, tail, parent, conn, deform in SPEC:
    b = eb.new(name); b.head, b.tail, b.roll = head, tail, 0.0
    b.use_deform = deform                      # root — управляющая, не деформирует
    if parent:
        b.parent = eb[parent]; b.use_connect = conn
bpy.ops.object.mode_set(mode='OBJECT')
log("скелет: %d костей, деформирующих %d" % (
    len(arm.data.bones), sum(1 for b in arm.data.bones if b.use_deform)))

outside = []
for name, head, tail, parent, conn, deform in SPEC:
    ok, loc, nor, _ = mesh.closest_point_on_mesh(head)
    if (head - loc).dot(nor) >= 0:
        outside.append(name + ":head")
print("   суставы вне меша: %s" % (outside or "нет"))

# ---------------------------------------------------------------- веса
proxy = mesh.copy(); proxy.data = mesh.data.copy()
proxy.name = proxy.data.name = "Character_LowPoly"
bpy.context.scene.collection.objects.link(proxy)
bpy.context.view_layer.objects.active = proxy
d = proxy.modifiers.new("dec", 'DECIMATE'); d.ratio = 0.08
bpy.ops.object.modifier_apply(modifier="dec")
bpy.ops.object.select_all(action='DESELECT')
proxy.select_set(True); arm.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.parent_set(type='ARMATURE_AUTO')       # bone heat тянет только ~80k полигонов
wp = sum(1 for v in proxy.data.vertices if any(g.weight > 0 for g in v.groups))
log("веса на упрощённой копии (%d полигонов): %d / %d вершин" % (
    len(proxy.data.polygons), wp, len(proxy.data.vertices)))
assert wp > 0, "bone heat не дал весов даже на упрощённой копии"

bpy.ops.object.select_all(action='DESELECT')
mesh.select_set(True); proxy.select_set(True)
bpy.context.view_layer.objects.active = proxy
bpy.ops.object.data_transfer(data_type='VGROUP_WEIGHTS', vert_mapping='POLYINTERP_NEAREST',
                             layers_select_src='ALL', layers_select_dst='NAME')
bpy.ops.object.select_all(action='DESELECT')
mesh.select_set(True); bpy.context.view_layer.objects.active = mesh
bpy.ops.object.vertex_group_limit_total(limit=4)
bpy.ops.object.vertex_group_normalize_all(lock_active=False)
if not any(m.type == 'ARMATURE' for m in mesh.modifiers):
    mesh.modifiers.new("Armature", 'ARMATURE').object = arm
for m in mesh.modifiers:
    if m.type == 'ARMATURE':
        m.object = arm
mesh.parent = arm
proxy.hide_viewport = proxy.hide_render = True
w = sum(1 for v in mesh.data.vertices if any(g.weight > 0 for g in v.groups))
log("веса на полном меше: %d / %d (%.2f%%)" % (w, len(mesh.data.vertices),
                                               100.0 * w / len(mesh.data.vertices)))

# ---------------------------------------------------------------- ретаргет
with bpy.data.libraries.load(MOCAP, link=False) as (src, dst):
    dst.actions = list(src.actions)
sources = [a for a in bpy.data.actions if not a.name.endswith("__retarget")]
for a in sources:
    a.use_fake_user = True

old = json.load(open(OLD_RIG, encoding="utf-8"))
helper = bpy.data.objects.new("RIG_OLD_helper", bpy.data.armatures.new("old_arm"))
bpy.context.scene.collection.objects.link(helper)
bpy.context.view_layer.objects.active = helper
bpy.ops.object.mode_set(mode='EDIT')
ebs, done = helper.data.edit_bones, []
def emit(n):
    if n in done: return
    if old[n]['parent']: emit(old[n]['parent'])
    done.append(n)
for n in old: emit(n)
for n in done:
    s = old[n]; b = ebs.new(n)
    b.head, b.tail, b.roll = Vector(s['head']), Vector(s['tail']), s['roll']
    if s['parent']:
        b.parent = ebs[s['parent']]; b.use_connect = s['use_connect']
bpy.ops.object.mode_set(mode='OBJECT')

order = []
def emit2(b):
    if b.parent and b.parent.name not in order: emit2(b.parent)
    if b.name not in order: order.append(b.name)
for b in arm.data.bones: emit2(b)
REST = {b.name: b.matrix_local.to_3x3() for b in arm.data.bones}
PAR = {b.name: (b.parent.name if b.parent else None) for b in arm.data.bones}
for pb in arm.pose.bones: pb.rotation_mode = 'QUATERNION'
for m in mesh.modifiers:
    if m.type == 'ARMATURE': m.show_viewport = False

SCALE = H_NEW / H_OLD
sc = bpy.context.scene
helper.animation_data_create(); arm.animation_data_create()
for src_act in sources:
    f0, f1 = int(src_act.frame_range[0]), int(src_act.frame_range[1])
    helper.animation_data.action = src_act
    if helper.animation_data.action_slot is None and len(src_act.slots):
        helper.animation_data.action_slot = src_act.slots[0]
    tgt = bpy.data.actions.new(src_act.name + "__retarget")
    tgt.use_fake_user = True
    arm.animation_data.action = tgt
    for f in range(f0, f1 + 1):
        sc.frame_set(f); bpy.context.view_layer.update()
        T = {}
        for name in order:
            p = PAR[name]
            Rp = T[p] if p else Matrix.Identity(3)
            rel = (REST[p].inverted() @ REST[name]) if p else REST[name]
            T[name] = (helper.pose.bones[name].matrix.to_3x3().normalized()
                       if name in helper.pose.bones else Rp @ rel)
            pb = arm.pose.bones[name]
            pb.rotation_quaternion = ((Rp @ rel).inverted() @ T[name]).to_quaternion()
            if name == "root":
                pb.location = helper.pose.bones["root"].location * SCALE
                pb.keyframe_insert("location", frame=f)
            pb.keyframe_insert("rotation_quaternion", frame=f)
    log("ретаргет %-42s кадры %d..%d" % (tgt.name, f0, f1))
bpy.data.objects.remove(helper, do_unlink=True)
for m in mesh.modifiers:
    if m.type == 'ARMATURE': m.show_viewport = True

act = bpy.data.actions["Walk_In_Place_Female_Neutral_TECMIDIA__retarget"]
arm.animation_data.action = act
if arm.animation_data.action_slot is None and len(act.slots):
    arm.animation_data.action_slot = act.slots[0]
sc.frame_start, sc.frame_end = int(act.frame_range[0]), int(act.frame_range[1])
sc.render.fps = 24

# ---------------------------------------------------------------- проверка деформации
me = mesh.data
dom = {}
for v in me.vertices:
    best, bw = None, -1.0
    for g in v.groups:
        if g.weight > bw: bw, best = g.weight, g.group
    dom[v.index] = mesh.vertex_groups[best].name if best is not None else None
arm.data.pose_position = 'REST'
dg = bpy.context.evaluated_depsgraph_get(); dg.update()
rest = [v.co.copy() for v in mesh.evaluated_get(dg).to_mesh().vertices]
arm.data.pose_position = 'POSE'
worst_all = (0.0, "", 0)
for f in (int(act.frame_range[0]), 8, 14, 21):
    sc.frame_set(f); dg = bpy.context.evaluated_depsgraph_get(); dg.update()
    pos = [v.co.copy() for v in mesh.evaluated_get(dg).to_mesh().vertices]
    for e in me.edges:
        a, b = e.vertices
        l0 = (rest[a] - rest[b]).length
        if l0 < 2e-3: continue
        dl = (pos[a] - pos[b]).length - l0
        if dl > worst_all[0]: worst_all = (dl, dom[a] or "?", f)
print()
log("макс удлинение ребра (рёбра длиннее 2 мм): %.4f ед. — группа %s, кадр %d" % worst_all)
foot = [i for i, c in enumerate(rest) if c.z < Z_FEET + 0.09]
cnt = {}
for i in foot: cnt[dom[i]] = cnt.get(dom[i], 0) + 1
print("   вершины стопы (%d) по главной кости: %s" % (
    len(foot), sorted(cnt.items(), key=lambda kv: -kv[1])[:6]))

sc.frame_set(sc.frame_start)
bpy.ops.wm.save_as_mainfile(filepath=SAVE)
log("сохранено: %s" % SAVE)
