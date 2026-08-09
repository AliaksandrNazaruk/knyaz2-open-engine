"""Библиотека стартовых поз для мастерской персонажа.

    blender -b --factory-startup --python tools/export_pose_lib.py

Пишет tools/webanim/poselib.json. Позы хранятся МИРОВЫМИ поворотами костей, а не
локальными: у другой модели скелет подгоняется под её пропорции, и локальные
повороты дали бы другую позу. Мировые переносятся через любой скелет тем же
приёмом, что и ретаргет мокапа.
"""
import bpy, json, os

ROOT = r"C:\Users\User\Documents\Knyaz2Modding"
SAVE = os.path.join(ROOT, "hero_textured_rig.blend")
OUT = os.path.join(ROOT, "tools", "webanim", "poselib.json")

# что берём: имя в списке -> (экшен, кадр)
WANT = [
    ("Боевая стойка",      "Stance_Combat", 1),
    ("Шаг — касание",      "Walk_In_Place_Female_Neutral_TECMIDIA__retarget", 1),
    ("Шаг — проходящая",   "Walk_In_Place_Female_Neutral_TECMIDIA__retarget", 8),
    ("Шаг — отталкивание", "Walk_In_Place_Female_Neutral_TECMIDIA__retarget", 14),
    ("Шаг — вынос",        "Walk_In_Place_Female_Neutral_TECMIDIA__retarget", 21),
    ("Простой",            "Walk_In_Place_Procedural_Backup__retarget", 1),
]

bpy.ops.wm.open_mainfile(filepath=SAVE)
arm = bpy.data.objects["RIG_Hero"]
sc = bpy.context.scene
if not arm.animation_data:
    arm.animation_data_create()
names = [b.name for b in arm.data.bones]

lib = {"bones": names, "poses": {}}
for label, act_name, frame in WANT:
    act = bpy.data.actions.get(act_name)
    if not act:
        print("нет экшена", act_name)
        continue
    arm.animation_data.action = act
    if arm.animation_data.action_slot is None and len(act.slots):
        arm.animation_data.action_slot = act.slots[0]
    sc.frame_set(frame)
    bpy.context.view_layer.update()
    # Храним НАПРАВЛЕНИЕ каждой кости в мире. Кватернион не годится: у меня ось
    # кости строится минимальным поворотом, крен произвольный, и чужой кватернион
    # принёс бы лишнюю скрутку. Направление же переносится через любой скелет.
    world = []
    for n in names:
        pb = arm.pose.bones[n]
        d = (pb.tail - pb.head)
        d.normalize()
        world.append([round(c, 5) for c in d])
    lib["poses"][label] = {"dir": world,
                           "root_loc": [round(c, 5) for c in arm.pose.bones["root"].location]}
    print("%-22s из %s кадр %d" % (label, act_name, frame))

# ---- нейтральная стойка: строим направлениями, а не из мокапа ----
# Мокапа спокойного стояния у нас нет, а поза нужна простая и предсказуемая:
# корпус прямой, руки вдоль тела, ноги ровно. Скрутку рук задаём отдельно —
# без неё ладони остались бы развёрнутыми вперёд, как в позе привязки.
arm.animation_data.action = None
for pb in arm.pose.bones:
    pb.matrix_basis.identity()
bpy.context.view_layer.update()
rest_dir = {}
for n in names:
    pb = arm.pose.bones[n]
    d = (pb.tail - pb.head)
    d.normalize()
    rest_dir[n] = [round(c, 5) for c in d]

def unit(v):
    from mathutils import Vector as V
    q = V(v)
    q.normalize()
    return [round(c, 5) for c in q]

NEUTRAL = dict(rest_dir)
NEUTRAL.update({
    "root": [0, 0, 1], "spine_01": [0, 0, 1], "spine_02": [0, 0, 1],
    "chest": [0, 0, 1], "neck": unit([0, -0.06, 1]), "head": unit([0, -0.04, 1]),
})
for s, k in (("L", 1), ("R", -1)):
    NEUTRAL["upper_arm." + s] = unit([0.17 * k, 0.03, -0.985])
    NEUTRAL["forearm." + s] = unit([0.09 * k, -0.10, -0.99])
    NEUTRAL["hand." + s] = unit([0.05 * k, -0.13, -0.99])
    NEUTRAL["thigh." + s] = unit([0.035 * k, 0.0, -1])
    NEUTRAL["shin." + s] = unit([0.005 * k, 0.02, -1])
TWIST = {}
for s, k in (("L", 1), ("R", -1)):
    TWIST["upper_arm." + s] = 55 * k          # пронация: ладони к бёдрам
    TWIST["forearm." + s] = 14 * k
lib["poses"]["Нейтральная стойка"] = {
    "dir": [NEUTRAL[n] for n in names],
    "twist": [TWIST.get(n, 0) for n in names],
    "root_loc": [0, 0, 0]}
print("%-22s построена направлениями" % "Нейтральная стойка")

json.dump(lib, open(OUT, "w"), ensure_ascii=False, separators=(",", ":"))
print("\nзаписано %s  %.1f КБ" % (OUT, os.path.getsize(OUT) / 1024))
