"""Retarget a verified female neutral mocap walk to the user-placed rig.

Run with Blender 5.x:
    blender --background --python tools/retarget_female_walk.py

The source clip comes from the TECMIDIA/UFSC Locomotion Dataset and is
explicitly labelled ``female neutral`` by the dataset authors.
"""

from __future__ import annotations

import math
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


WORKSPACE = Path(r"C:\Users\User\Documents\Knyaz2Modding")
INPUT_BLEND = WORKSPACE / "base_proportions_walk_mocap_neutral.blend"
OUTPUT_BLEND = WORKSPACE / "base_proportions_walk_mocap_female.blend"
SOURCE_BVH = (
    WORKSPACE
    / "mocap_sources"
    / "tecmidia_female_neutral"
    / "vicon"
    / "F_neutral_Walk_001.bvh"
)

TARGET_RIG_NAME = "RIG_User_Placed_Walk"
TARGET_MESH_NAME = "Character_Original_OBJ"
ACTION_NAME = "Walk_In_Place_Female_Neutral_TECMIDIA"

OUTPUT_FPS = 24
SOURCE_FPS = 120
GROUND_Z = -1.188

# The BVH walks along -X after import.  The character faces -Y, so rotate the
# source motion +90 degrees around Z before transferring it.
SOURCE_TO_TARGET = Matrix.Rotation(math.radians(90.0), 4, "Z")


FEATURE_BONES = (
    "Spine",
    "Head",
    "LeftShoulder",
    "LeftArm",
    "LeftForeArm",
    "LeftHand",
    "RightShoulder",
    "RightArm",
    "RightForeArm",
    "RightHand",
    "LeftUpLeg",
    "LeftLeg",
    "LeftFoot",
    "LeftToeBase",
    "RightUpLeg",
    "RightLeg",
    "RightFoot",
    "RightToeBase",
)


# Target bones are listed in hierarchy order.  Values are source bones whose
# evaluated global orientation is copied after coordinate-system alignment.
ROTATION_MAP = (
    ("spine_01", "Hips"),
    ("spine_02", "Spine"),
    ("chest", "Spine"),
    ("neck", "Head"),
    ("clavicle.L", "LeftShoulder"),
    ("upper_arm.L", "LeftArm"),
    ("forearm.L", "LeftForeArm"),
    ("hand.L", "LeftHand"),
    ("clavicle.R", "RightShoulder"),
    ("upper_arm.R", "RightArm"),
    ("forearm.R", "RightForeArm"),
    ("hand.R", "RightHand"),
    ("thigh.L", "LeftUpLeg"),
    ("shin.L", "LeftLeg"),
    ("foot.L", "LeftFoot"),
    ("thigh.R", "RightUpLeg"),
    ("shin.R", "RightLeg"),
    ("foot.R", "RightFoot"),
)


# These deforming chains must preserve the roll of the approved target rest
# rig.  Copying an absolute BVH bone frame would twist the mesh around the
# segment even when the joint direction itself is correct.
DIRECTION_RETARGET_BONES = {
    "clavicle.L",
    "upper_arm.L",
    "forearm.L",
    "hand.L",
    "clavicle.R",
    "upper_arm.R",
    "forearm.R",
    "hand.R",
    "thigh.L",
    "shin.L",
    "foot.L",
    "thigh.R",
    "shin.R",
    "foot.R",
}


def armature_rotation(source_pose_bone) -> Matrix:
    """Return an aligned, orthonormal global rotation for a source bone."""

    source_rotation = source_pose_bone.matrix.to_3x3().normalized()
    return (SOURCE_TO_TARGET.to_3x3() @ source_rotation).normalized()


def direction_rotation(target_data_bone, source_pose_bone) -> Matrix:
    """Match a source segment direction while preserving target bone roll.

    BVH bone roll is an export convention and is not reliably transferable to
    a differently constructed rest rig.  A minimal swing from the target rest
    direction avoids twisting shoes around their longitudinal axis.
    """

    desired_direction = aligned_position(
        source_pose_bone.tail - source_pose_bone.head
    ).normalized()
    rest_direction = (
        target_data_bone.tail_local - target_data_bone.head_local
    ).normalized()
    swing = rest_direction.rotation_difference(desired_direction)
    target_rest_rotation = target_data_bone.matrix_local.to_3x3().normalized()
    return (swing.to_matrix() @ target_rest_rotation).normalized()


def aligned_position(position: Vector) -> Vector:
    return SOURCE_TO_TARGET.to_3x3() @ position


def pose_feature(source_rig) -> tuple[float, ...]:
    """Joint-position descriptor invariant to root translation."""

    root = source_rig.pose.bones["Hips"].head.copy()
    values: list[float] = []
    for name in FEATURE_BONES:
        bone = source_rig.pose.bones[name]
        for point in (bone.head, bone.tail):
            relative = point - root
            values.extend(relative)
    return tuple(values)


def feature_distance(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)) / len(a))


def find_cycle(scene, source_rig) -> tuple[int, int, list[tuple[float, int, int]]]:
    """Find two same-phase frames spanning one full gait cycle."""

    # Frame 1 is a calibration pose in this BVH.  Work inside the stable pass.
    sample_frames = list(range(90, 851, 2))
    features: dict[int, tuple[float, ...]] = {}
    roots: dict[int, Vector] = {}
    floor_heights: dict[int, float] = {}

    for frame in sample_frames:
        scene.frame_set(frame)
        features[frame] = pose_feature(source_rig)
        roots[frame] = source_rig.pose.bones["Hips"].head.copy()
        floor_heights[frame] = min(
            source_rig.pose.bones["LeftFoot"].head.z,
            source_rig.pose.bones["LeftToeBase"].head.z,
            source_rig.pose.bones["RightFoot"].head.z,
            source_rig.pose.bones["RightToeBase"].head.z,
        )

    global_floor = min(floor_heights.values())
    candidates: list[tuple[float, int, int]] = []

    # A normal full gait is roughly 0.8-1.45 seconds.  The displacement check
    # rejects accidental pose matches from pauses or half cycles.
    for start in sample_frames:
        for period in range(96, 175, 2):
            end = start + period
            if end not in features:
                continue
            displacement = (roots[end] - roots[start]).length
            if not 0.55 <= displacement <= 1.55:
                continue

            score = feature_distance(features[start], features[end])
            # Prefer a loop boundary with at least one foot close to the floor.
            score += max(0.0, floor_heights[start] - global_floor - 0.018) * 0.35
            candidates.append((score, start, end))

    if not candidates:
        raise RuntimeError("No full gait cycle could be detected in the BVH")

    candidates.sort(key=lambda item: item[0])
    score, start, end = candidates[0]
    print("CYCLE_CANDIDATES")
    for candidate in candidates[:8]:
        print("  score={:.7f} start={} end={} period={}".format(
            candidate[0], candidate[1], candidate[2], candidate[2] - candidate[1]
        ))
    print(f"SELECTED_CYCLE start={start} end={end} score={score:.7f}")
    return start, end, candidates[:8]


def set_pose_bone_matrix(pose_bone, rotation: Matrix, head: Vector) -> None:
    matrix = rotation.to_4x4()
    matrix.translation = head
    pose_bone.matrix = matrix


def point_bone_towards(pose_bone, data_bone, direction: Vector) -> None:
    """Aim a connector bone while retaining its target rest roll."""

    if direction.length_squared < 1e-10:
        return
    rest_direction = (data_bone.tail_local - data_bone.head_local).normalized()
    swing = rest_direction.rotation_difference(direction.normalized())
    rest_rotation = data_bone.matrix_local.to_3x3().normalized()
    rotation = (swing.to_matrix() @ rest_rotation).normalized()
    set_pose_bone_matrix(pose_bone, rotation, pose_bone.head.copy())


def key_pose(rig, frame: int) -> None:
    for pose_bone in rig.pose.bones:
        pose_bone.keyframe_insert("location", frame=frame, group=pose_bone.name)
        pose_bone.keyframe_insert("rotation_quaternion", frame=frame, group=pose_bone.name)
        pose_bone.keyframe_insert("scale", frame=frame, group=pose_bone.name)


def iter_action_fcurves(action):
    for layer in action.layers:
        for strip in layer.strips:
            for channelbag in strip.channelbags:
                yield from channelbag.fcurves


def evaluated_mesh_min_z(scene, mesh_object) -> float:
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = mesh_object.evaluated_get(depsgraph)
    world = evaluated.matrix_world
    return min((world @ vertex.co).z for vertex in evaluated.data.vertices)


def main() -> None:
    if not INPUT_BLEND.exists():
        raise FileNotFoundError(INPUT_BLEND)
    if not SOURCE_BVH.exists():
        raise FileNotFoundError(SOURCE_BVH)

    bpy.ops.wm.open_mainfile(filepath=str(INPUT_BLEND))
    scene = bpy.context.scene
    target_rig = bpy.data.objects[TARGET_RIG_NAME]
    target_mesh = bpy.data.objects[TARGET_MESH_NAME]

    previous_action = None
    if target_rig.animation_data and target_rig.animation_data.action:
        previous_action = target_rig.animation_data.action
        previous_action.use_fake_user = True

    # Detaching the heavy target animation and hiding the mesh makes cycle
    # analysis much faster while retaining the already-approved weights.
    target_rig.animation_data_create()
    target_rig.animation_data.action = None
    target_mesh.hide_viewport = True

    bpy.ops.import_anim.bvh(
        filepath=str(SOURCE_BVH),
        global_scale=0.01,
        frame_start=1,
        use_fps_scale=False,
        update_scene_fps=False,
    )
    source_rig = bpy.context.object
    source_rig.name = "SOURCE_TECMIDIA_Female_Neutral"
    source_action = source_rig.animation_data.action

    cycle_start, cycle_end, _ = find_cycle(scene, source_rig)
    source_period = cycle_end - cycle_start
    output_period = max(16, round(source_period * OUTPUT_FPS / SOURCE_FPS))
    output_last_key = output_period + 1

    # Gather a neutral center and a scale for pelvis bob/sway.  Forward motion
    # is intentionally removed because the requested animation is in-place.
    source_root_positions: list[Vector] = []
    source_floor_positions: list[float] = []
    for frame in range(cycle_start, cycle_end + 1, 2):
        scene.frame_set(frame)
        root_position = aligned_position(source_rig.pose.bones["Hips"].head)
        source_root_positions.append(root_position)
        source_floor_positions.append(min(
            aligned_position(source_rig.pose.bones["LeftFoot"].head).z,
            aligned_position(source_rig.pose.bones["LeftToeBase"].head).z,
            aligned_position(source_rig.pose.bones["RightFoot"].head).z,
            aligned_position(source_rig.pose.bones["RightToeBase"].head).z,
        ))

    mean_root = sum(source_root_positions, Vector()) / len(source_root_positions)
    mean_source_hip_height = mean_root.z - min(source_floor_positions)
    target_root_bone = target_rig.data.bones["root"]
    motion_scale = target_root_bone.length / mean_source_hip_height
    target_rest_pelvis = target_root_bone.tail_local.copy()

    new_action = bpy.data.actions.get(ACTION_NAME)
    if new_action:
        bpy.data.actions.remove(new_action)
    new_action = bpy.data.actions.new(ACTION_NAME)
    target_rig.animation_data.action = new_action

    for pose_bone in target_rig.pose.bones:
        pose_bone.rotation_mode = "QUATERNION"

    for output_frame in range(1, output_last_key + 1):
        phase = (output_frame - 1) / output_period
        source_frame_float = cycle_start + source_period * phase
        source_frame = int(math.floor(source_frame_float))
        source_subframe = source_frame_float - source_frame
        scene.frame_set(source_frame, subframe=source_subframe)

        for pose_bone in target_rig.pose.bones:
            pose_bone.matrix_basis.identity()
        bpy.context.view_layer.update()

        source_hips = source_rig.pose.bones["Hips"]
        root_rotation = armature_rotation(source_hips)
        source_root = aligned_position(source_hips.head)

        pelvis_delta = Vector((
            (source_root.x - mean_root.x) * motion_scale,
            0.0,
            (source_root.z - mean_root.z) * motion_scale,
        ))
        desired_pelvis = target_rest_pelvis + pelvis_delta
        root_head = desired_pelvis - root_rotation @ Vector((0.0, target_root_bone.length, 0.0))
        set_pose_bone_matrix(target_rig.pose.bones["root"], root_rotation, root_head)
        bpy.context.view_layer.update()

        # The target rig has small explicit pelvis-to-hip connector bones; the
        # source skeleton starts its thigh bones directly at the hip joints.
        # These parents must be oriented before their thigh/shin/foot children.
        source_hip_center = aligned_position(source_hips.head)
        for side, source_name in (("L", "LeftUpLeg"), ("R", "RightUpLeg")):
            source_hip = aligned_position(source_rig.pose.bones[source_name].head)
            point_bone_towards(
                target_rig.pose.bones[f"hip.{side}"],
                target_rig.data.bones[f"hip.{side}"],
                source_hip - source_hip_center,
            )
            bpy.context.view_layer.update()

        for target_name, source_name in ROTATION_MAP:
            target_bone = target_rig.pose.bones[target_name]
            source_bone = source_rig.pose.bones[source_name]
            if target_name in DIRECTION_RETARGET_BONES:
                rotation = direction_rotation(
                    target_rig.data.bones[target_name], source_bone
                )
            else:
                rotation = armature_rotation(source_bone)
            set_pose_bone_matrix(
                target_bone,
                rotation,
                target_bone.head.copy(),
            )
            bpy.context.view_layer.update()

        key_pose(target_rig, output_frame)

    # Exact sole-to-ground correction from the fully deformed high-resolution
    # mesh.  This avoids estimating shoe thickness from the skeleton alone.
    target_mesh.hide_viewport = False
    for output_frame in range(1, output_last_key + 1):
        scene.frame_set(output_frame)
        min_z = evaluated_mesh_min_z(scene, target_mesh)
        correction = GROUND_Z - min_z
        root_pose = target_rig.pose.bones["root"]
        corrected = root_pose.matrix.copy()
        corrected.translation.z += correction
        root_pose.matrix = corrected
        root_pose.keyframe_insert("location", frame=output_frame, group="root")
        root_pose.keyframe_insert("rotation_quaternion", frame=output_frame, group="root")
        root_pose.keyframe_insert("scale", frame=output_frame, group="root")
        print(
            f"GROUND frame={output_frame:02d} before={min_z:.6f} "
            f"correction={correction:+.6f}"
        )

    # Force the duplicate key to the exact first pose.  Playback uses frames
    # 1..output_period; the extra key is the mathematically correct next frame
    # and guarantees a seamless interpolation/cycles boundary.
    scene.frame_set(1)
    first_pose = {
        pose_bone.name: pose_bone.matrix_basis.copy()
        for pose_bone in target_rig.pose.bones
    }
    scene.frame_set(output_last_key)
    for pose_bone in target_rig.pose.bones:
        pose_bone.matrix_basis = first_pose[pose_bone.name]
    key_pose(target_rig, output_last_key)

    for fcurve in iter_action_fcurves(new_action):
        for keyframe in fcurve.keyframe_points:
            keyframe.interpolation = "LINEAR"
        cycles = fcurve.modifiers.new("CYCLES")
        cycles.mode_before = "REPEAT"
        cycles.mode_after = "REPEAT"

    # Keep provenance alongside the animation instead of relying on filenames.
    target_rig["walk_source_dataset"] = "TECMIDIA/UFSC Locomotion Dataset"
    target_rig["walk_source_category"] = "female neutral"
    target_rig["walk_source_file"] = SOURCE_BVH.name
    target_rig["walk_source_url"] = "https://tecmidia.ufsc.br/en/locomotion-dataset/"
    target_rig["walk_source_license"] = (
        "Free for research and commercial products; source data may not be resold"
    )
    target_rig["walk_cycle_source_frames"] = f"{cycle_start}-{cycle_end}"
    target_rig["walk_cycle_output_frames"] = output_period

    license_text = bpy.data.texts.get("MOCAP_SOURCE_TECMIDIA")
    if license_text:
        bpy.data.texts.remove(license_text)
    license_text = bpy.data.texts.new("MOCAP_SOURCE_TECMIDIA")
    license_text.write(
        "Female neutral locomotion mocap from TECMIDIA/UFSC.\n"
        "Source: https://tecmidia.ufsc.br/en/locomotion-dataset/\n"
        "The dataset page states that the data may be included in commercially "
        "sold products but may not be resold directly, even in converted form.\n"
    )

    # Remove the imported source skeleton/action from the deliverable.  The BVH
    # remains in mocap_sources for auditability and future re-retargeting.
    source_armature = source_rig.data
    bpy.data.objects.remove(source_rig, do_unlink=True)
    if source_armature.users == 0:
        bpy.data.armatures.remove(source_armature)
    if source_action and source_action.users == 0:
        bpy.data.actions.remove(source_action)

    target_rig.animation_data.action = new_action
    scene.render.fps = OUTPUT_FPS
    scene.frame_start = 1
    scene.frame_end = output_period
    scene.frame_set(1)

    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT_BLEND))

    # Final verification after save.
    ground_values = []
    for frame in range(1, output_period + 1):
        scene.frame_set(frame)
        ground_values.append(evaluated_mesh_min_z(scene, target_mesh))

    fcurve_count = sum(1 for _ in iter_action_fcurves(new_action))
    modifier_count = sum(
        len(fcurve.modifiers) for fcurve in iter_action_fcurves(new_action)
    )
    print(f"OUTPUT_BLEND={OUTPUT_BLEND}")
    print(f"ACTION={new_action.name}")
    print(f"OUTPUT_PERIOD={output_period}")
    print(f"FCURVES={fcurve_count} CYCLES_MODIFIERS={modifier_count}")
    print(
        "GROUND_RANGE min={:.6f} max={:.6f}".format(
            min(ground_values), max(ground_values)
        )
    )
    if previous_action:
        print(f"BACKUP_ACTION={previous_action.name}")


if __name__ == "__main__":
    main()
