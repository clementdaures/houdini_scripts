"""Reference USD primitives into a destination parent prim.

Reads whitespace-separated source paths from source_paths and a single
destination path from dest_path on the parent node. Each valid source prim
is added as an internal reference (no asset path) under the destination. Prims
that cannot be resolved are skipped with a warning. Silently skips execution
when inputs are empty or misconfigured.
"""

from pxr import Sdf, Usd

node = hou.pwd()
ctrl = hou.node("..")

sources = [s.strip() for s in ctrl.parm("source_paths").eval().split()]
dests   = [d.strip() for d in ctrl.parm("dest_path").eval().split()]

stage        = node.editableStage()
session_layer = stage.GetSessionLayer()


if sources and len(dests) == 1:
    dst = dests[0]

    dst_parent_path = Sdf.Path(dst).GetParentPath()
    if not stage.GetPrimAtPath(dst_parent_path):
        stage.DefinePrim(dst_parent_path)

    for src in sources:
        src_prim = stage.GetPrimAtPath(src)

        if not src_prim or not src_prim.IsValid():
            print(f"Source not found: {src}")
            continue

        src_name  = Sdf.Path(src).name
        final_dst = dst + "/" + src_name

        dst_prim = stage.DefinePrim(final_dst)
        dst_prim.GetReferences().AddReference(assetPath="", primPath=src)