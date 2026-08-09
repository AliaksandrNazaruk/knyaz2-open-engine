"""Готовый риг (FBX/blend) -> .glb со скелетом и скиннингом для мастерской.

    blender -b --factory-startup --python tools/fbx_to_glb.py -- "риг.fbx"
            [--out путь.glb] [--tris 300000] [--tex картинка.png]

--tris прореживает меш до указанного числа треугольников: миллион с лишним в
браузере тянуть незачем, силуэт и деформация от этого не страдают. Веса
прореживание сохраняет.
"""
import bpy, os, sys

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def opt(n, d=None):
    return argv[argv.index(n) + 1] if n in argv else d
SRC = argv[0]
TRIS = int(opt("--tris", "0") or 0)
TEX = opt("--tex")
OUT = opt("--out") or os.path.splitext(SRC)[0] + ".glb"

bpy.ops.wm.read_factory_settings(use_empty=True)
ext = os.path.splitext(SRC)[1].lower()
if ext == ".fbx":
    bpy.ops.import_scene.fbx(filepath=SRC)
elif ext == ".blend":
    bpy.ops.wm.open_mainfile(filepath=SRC)
else:
    bpy.ops.import_scene.gltf(filepath=SRC)

arms = [o for o in bpy.data.objects if o.type == 'ARMATURE']
meshes = [o for o in bpy.data.objects if o.type == 'MESH' and not o.hide_render]
assert arms, "в файле нет скелета"
arm = arms[-1]
print("скелет %r: костей %d" % (arm.name, len(arm.data.bones)))
for m in meshes:
    print("меш %r: вершин %d, треугольников %d, групп %d" % (
        m.name, len(m.data.vertices), len(m.data.polygons), len(m.vertex_groups)))

if TEX:
    img = bpy.data.images.load(TEX)
    for m in meshes:
        for mat in m.data.materials:
            if not mat or not mat.use_nodes:
                continue
            nt = mat.node_tree
            tex = next((n for n in nt.nodes if n.type == 'TEX_IMAGE'), None)
            if not tex:
                tex = nt.nodes.new("ShaderNodeTexImage")
                bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
                nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
            tex.image = img
    print("подставлена текстура", os.path.basename(TEX))

# картинки внутрь файла, иначе .glb уедет без них
for im in bpy.data.images:
    if im.source == 'FILE' and not im.packed_file:
        try:
            im.pack()
            print("упакована текстура", im.name, tuple(im.size))
        except Exception as e:
            print("не упаковалась", im.name, e)

if TRIS:
    for m in meshes:
        n = len(m.data.polygons)
        if n <= TRIS:
            continue
        bpy.context.view_layer.objects.active = m
        d = m.modifiers.new("dec", 'DECIMATE')
        d.ratio = TRIS / n
        bpy.ops.object.modifier_apply(modifier="dec")
        print("прорежен %r: %d -> %d треугольников" % (m.name, n, len(m.data.polygons)))

# поза покоя обязательна: экспортируем скелет, а не текущую позу
if arm.animation_data:
    arm.animation_data.action = None
for pb in arm.pose.bones:
    pb.matrix_basis.identity()
bpy.context.view_layer.update()

bpy.ops.export_scene.gltf(filepath=OUT, export_format='GLB',
                          export_skins=True, export_animations=False,
                          export_apply=False, export_yup=True)
print("записано %s  %.1f МБ" % (OUT, os.path.getsize(OUT) / 1024 / 1024))
