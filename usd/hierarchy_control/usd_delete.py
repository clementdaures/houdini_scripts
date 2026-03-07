"""Delete USD primitives listed in the controller's source_paths parameter.

Reads a whitespace-separated list of USD prim paths from the parent node's
source_paths parameter and removes each one from the editable stage.
Silently skips execution when the parameter is empty.
"""

from pxr import Sdf, Usd

node = hou.pwd()
ctrl = hou.node("..")

sources = [s.strip() for s in ctrl.parm("source_paths").eval().split()]

stage = node.editableStage()


def delete_prim(stage: Usd.Stage, src_path: str) -> bool:
    """Remove a prim from the stage at src_path.

    Args:
        stage: The editable USD stage.
        src_path: Absolute USD path of the prim to delete.

    Returns:
        True on success, False if the prim does not exist or is invalid.
    """
    prim = stage.GetPrimAtPath(src_path)
    if not prim or not prim.IsValid():
        return False

    stage.RemovePrim(src_path)
    return True


for src in sources:
    if not delete_prim(stage, src):
        print(f"Failed to delete: {src}")