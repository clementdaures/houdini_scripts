"""Flatten and move USD primitives into a destination parent prim.

Reads whitespace-separated source paths from source_paths and a single
destination path from dest_path on the parent node. Each source prim is
recursively copied (attributes, relationships, children) under the destination,
then removed from its original location. Silently skips execution when inputs
are empty or misconfigured.
"""
from pxr import Sdf, Usd, UsdGeom, Gf

node = hou.pwd()
ctrl = hou.node("..")
sources = [s.strip() for s in ctrl.parm("source_paths").eval().split()]
dests = [d.strip() for d in ctrl.parm("dest_path").eval().split()]
stage = node.editableStage()

def get_world_transform(stage, src_path):
    """Returns the full composed world transform matrix of a prim."""
    xform_cache = UsdGeom.XformCache()
    src_prim = stage.GetPrimAtPath(src_path)
    return xform_cache.GetLocalToWorldTransform(src_prim)

def move_and_flatten_prim(stage, src_path, dst_path, world_xform=None):
    src_prim = stage.GetPrimAtPath(src_path)
    if not src_prim.IsValid():
        return False

    dst_prim = stage.DefinePrim(dst_path, src_prim.GetTypeName())

    for key, value in src_prim.GetAllAuthoredMetadata().items():
        if key == "active":
            continue
        dst_prim.SetMetadata(key, value)

    for attr in src_prim.GetAttributes():
        if not attr.HasAuthoredValue():
            continue

        if world_xform is not None and attr.GetName().startswith("xformOp:"):
            continue

        dst_attr = dst_prim.CreateAttribute(attr.GetName(), attr.GetTypeName())

        if attr.GetVariability() == Sdf.VariabilityUniform:
            dst_attr.SetVariability(Sdf.VariabilityUniform)

        time_samples = attr.GetTimeSamples()
        if time_samples:
            for time in time_samples:
                val = attr.Get(time)
                if val is not None:
                    dst_attr.Set(val, time)
        else:
            val = attr.Get()
            if val is not None:
                dst_attr.Set(val)

    if world_xform is not None and dst_prim.IsA(UsdGeom.Xformable):
        xformable = UsdGeom.Xformable(dst_prim)
        xformable.ClearXformOpOrder()
        xform_op = xformable.AddXformOp(
            UsdGeom.XformOp.TypeTransform,
            UsdGeom.XformOp.PrecisionDouble
        )
        xform_op.Set(world_xform)

    for rel in src_prim.GetRelationships():
        if rel.HasAuthoredTargets():
            dst_rel = dst_prim.CreateRelationship(rel.GetName())
            dst_rel.SetTargets(rel.GetTargets())

    for child in src_prim.GetChildren():
        child_name = child.GetName()
        move_and_flatten_prim(stage, f"{src_path}/{child_name}", f"{dst_path}/{child_name}", world_xform=None)

    return True

if sources and len(dests) == 1:
    dst_root = dests[0]

    world_xforms = {}
    for src in sources:
        world_xforms[src] = get_world_transform(stage, src)

    successful_sources = []
    for src in sources:
        src_path_obj = Sdf.Path(src)
        new_dst = f"{dst_root}/{src_path_obj.name}"

        if move_and_flatten_prim(stage, src, new_dst, world_xform=world_xforms[src]):
            successful_sources.append(src)
            print(f"Copied: {src} -> {new_dst}")
        else:
            print(f"Failed to move: {src}")

    for src in successful_sources:
        prim = stage.GetPrimAtPath(src)
        if prim.IsValid():
            prim.SetActive(False)
            print(f"Deactivated: {src}")
