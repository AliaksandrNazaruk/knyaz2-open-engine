"""Read-only QA report for the retargeted female walk blend."""

from pathlib import Path

import bpy


WORKSPACE = Path(r"C:\Users\User\Documents\Knyaz2Modding")
BLEND = WORKSPACE / "base_proportions_walk_mocap_female.blend"


def iter_fcurves(action):
    for layer in action.layers:
        for strip in layer.strips:
            for channelbag in strip.channelbags:
                yield from channelbag.fcurves


bpy.ops.wm.open_mainfile(filepath=str(BLEND))
scene = bpy.context.scene
rig = bpy.data.objects["RIG_User_Placed_Walk"]
mesh = bpy.data.objects["Character_Original_OBJ"]
action = rig.animation_data.action

fcurves = list(iter_fcurves(action))
cycles = sum(
    1
    for fcurve in fcurves
    for modifier in fcurve.modifiers
    if modifier.type == "CYCLES"
)

scene.frame_set(1)
first_pose = {bone.name: bone.matrix_basis.copy() for bone in rig.pose.bones}
scene.frame_set(27)
last_pose = {bone.name: bone.matrix_basis.copy() for bone in rig.pose.bones}
loop_error = max(
    abs(first_pose[name][row][column] - last_pose[name][row][column])
    for name in first_pose
    for row in range(4)
    for column in range(4)
)

unweighted = 0
weight_sums = []
for vertex in mesh.data.vertices:
    total = sum(group.weight for group in vertex.groups)
    weight_sums.append(total)
    if not vertex.groups:
        unweighted += 1

armature_modifiers = [
    modifier
    for modifier in mesh.modifiers
    if modifier.type == "ARMATURE" and modifier.object == rig
]

print(f"BLEND={BLEND}")
print(f"ACTIVE_ACTION={action.name}")
print(f"ACTION_RANGE={tuple(action.frame_range)}")
print(f"TIMELINE={scene.frame_start}-{scene.frame_end} FPS={scene.render.fps}")
print(f"FCURVES={len(fcurves)} CYCLES={cycles}")
print(f"LOOP_MATRIX_ERROR={loop_error:.12f}")
print(
    f"MESH_VERTICES={len(mesh.data.vertices)} "
    f"VERTEX_GROUPS={len(mesh.vertex_groups)} "
    f"ARMATURE_MODIFIERS={len(armature_modifiers)}"
)
print(
    f"UNWEIGHTED_VERTICES={unweighted} "
    f"WEIGHT_SUM_RANGE={min(weight_sums):.6f}-{max(weight_sums):.6f}"
)
print(f"SOURCE_CATEGORY={rig['walk_source_category']}")
print(f"SOURCE_FILE={rig['walk_source_file']}")
print(f"SOURCE_FRAMES={rig['walk_cycle_source_frames']}")
