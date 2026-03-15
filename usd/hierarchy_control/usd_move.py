"""Flatten and move USD primitives into a destination parent prim.

Reads whitespace-separated source paths from source_paths and a single
destination path from dest_path on the parent node. Each source prim is
recursively copied (attributes, relationships, children) under the destination,
then removed from its original location. Silently skips execution when inputs
are empty or misconfigured.
"""
from pxr import Sdf, Usd, UsdGeom

node = hou.pwd()
ctrl = hou.node("..")

sources = [s.strip() for s in ctrl.parm("source_paths").eval().split()]
dests   = [d.strip() for d in ctrl.parm("dest_path").eval().split()]

stage = node.editableStage()

def flatten_and_move_prim(stage: Usd.Stage, src_path: str, dst_path: str) -> bool:
    """Recursively copy a prim to dst_path and remove the original.
    Copies the prim type, all authored attributes (with their values), and all
    relationships. Child prims are processed recursively before the source is
    deleted.
    Args:
        stage: The editable USD stage.
        src_path: Absolute USD path of the source prim.
        dst_path: Absolute USD path of the destination prim.
    Returns:
        True on success, False if the source prim does not exist or is
        invalid.
    """
    src_prim = stage.GetPrimAtPath(src_path)
    
    if not src_prim or not src_prim.IsValid():
        return False
        
    dst_parent = Sdf.Path(dst_path).GetParentPath()
    UsdGeom.Xform.Define(stage, dst_parent)
    dst_prim = stage.DefinePrim(dst_path, src_prim.GetTypeName())
    
    for attr in src_prim.GetAttributes():
        src_attr = src_prim.GetAttribute(attr.GetName())
        if src_attr.Get() is not None:
            dst_attr = dst_prim.CreateAttribute(attr.GetName(), src_attr.GetTypeName())
            dst_attr.Set(src_attr.Get())
            
    if src_prim.HasAuthoredTypeName():
        dst_prim.SetTypeName(src_prim.GetTypeName())
        
    for rel in src_prim.GetRelationships():
        src_rel = src_prim.GetRelationship(rel.GetName())
        dst_rel = dst_prim.CreateRelationship(rel.GetName())
        dst_rel.SetTargets(src_rel.GetTargets())
        
    for child in src_prim.GetChildren():
        child_name = child.GetName()
        flatten_and_move_prim(stage, src_path + "/" + child_name, dst_path + "/" + child_name)
        
    stage.RemovePrim(src_path)
    
    return True

if sources and len(dests) == 1:
    dst = dests[0]
    UsdGeom.Xform.Define(stage, dst)
    
    for src in sources:
        src_name = Sdf.Path(src).name
        new_dst  = dst + "/" + src_name
        
        if not flatten_and_move_prim(stage, src, new_dst):
            print(f"Failed to move: {src}")
