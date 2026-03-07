# -*- coding: utf-8 -*-
"""SVG to JSON custom node shape converter for Houdini.

Converts simple SVG files into the JSON format expected by Houdini's
custom node shape system (accessible via the Z shortcut in the Node Graph
context). Each SVG is sampled into a polyline outline, from which connector
positions, flag hit-zones, and the icon bounding box are automatically derived.

Typical usage::

    # Edit INPUT_FOLDER to point at a directory of SVG files, then run:
    python svg_to_json_houdini.py

Note:
    Only the longest sub-path of each SVG is used as the node outline.
    Multi-path SVGs (e.g. compound shapes) are partially supported: all
    sub-paths contribute to normalisation but only the longest defines the
    silhouette.

Attributes:
    INPUT_FOLDER (str): Absolute path to the directory containing SVG files.
        Output JSON files are written to the same directory.
    SAMPLE_POINTS (int): Number of points sampled uniformly along each
        SVG sub-path. Higher values increase fidelity and file size.
    CONNECTOR_OFFSET (float): Distance (in normalised units) added beyond
        the shape's bounding-box edge when placing input/output connectors.
    FLAG_ANGLES (list[float]): Angular positions (degrees, CCW from +X) of
        the four connector flag hit-zones.
    FLAG_ARC (float): Half-angular width (degrees) of each flag zone.
        Currently informational; zones are collapsed to single points.

Author: Clement Daures
Created: 2026
Version: 1.0.0
"""


# ----- IMPORT -----


import os
import json
import math
import numpy as np
from svgpathtools import svg2paths, Path


# ----- CONFIG -----


INPUT_FOLDER  = r"D:\hou_nodes\atlas"
SAMPLE_POINTS = 300

# How far to push connectors outside the shape boundary
CONNECTOR_OFFSET = 0.15

# Angular positions for the 4 flag hit-zones
FLAG_ANGLES = [180.0, 225.0, 315.0, 0.0]
FLAG_ARC    = 30.0


# ----- SVG SAMPLING -----


def sample_path(path: Path, n: int = SAMPLE_POINTS) -> np.ndarray:
    """Sample n evenly-spaced points along an SVG path.

    Args:
        path: SVG path to sample.
        n: Number of sample points.

    Returns:
        Array of shape (n, 2) with [x, y] in SVG space (Y down).
    """
    pts = []
    for i in range(n):
        t = i / (n - 1)
        p = path.point(t)
        pts.append([p.real, p.imag])
    return np.array(pts)


def compute_normalization(raw_list: list[np.ndarray]) -> tuple[float, float, float]:
    """Compute the bounding-box centre and uniform scale for a set of paths.

    Args:
        raw_list: Sampled point arrays in SVG space.

    Returns:
        (cx, cy, scale) — bounding-box centre and largest dimension
        multiplied by 1.25 for margin.
    """
    merged = np.vstack(raw_list)
    mn = merged.min(axis=0)
    mx = merged.max(axis=0)
    cx, cy = (mn + mx) / 2
    scale  = float(max(mx - mn))
    return float(cx), float(cy), scale * 1.25


def norm(pts: np.ndarray, cx: float, cy: float, scale: float) -> list[list[float]]:
    """Normalise points to Houdini space, flipping the Y axis.

    Translates, scales, and inverts Y so that SVG's top-left origin maps
    to Houdini's bottom-left origin.

    Args:
        pts: [x, y] pairs in SVG space.
        cx: Bounding-box centre X.
        cy: Bounding-box centre Y.
        scale: Uniform scale factor.

    Returns:
        Normalised [x, y] pairs rounded to 6 decimal places.
    """
    return [[round((x - cx) / scale, 6), round(-(y - cy) / scale, 6)]
            for x, y in pts]


# ----- DEFINE PERIMETER -----


def arc_lengths(outline: list[list[float]]) -> np.ndarray:
    """Return cumulative arc lengths along a polyline, starting at 0.0.

    Args:
        outline: Ordered [x, y] vertices.

    Returns:
        1-D array of cumulative distances, length len(outline).
    """
    pts  = np.array(outline)
    segs = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    return np.concatenate([[0.0], np.cumsum(segs)])


def outward_normal_angle(outline: list[list[float]], idx: int) -> float:
    """Return the outward normal angle at vertex idx, in degrees [0, 360).

    The tangent is estimated by finite differences; the outward direction
    is resolved by comparing both candidate normals against the centroid.

    Args:
        outline: Closed polyline vertices in Houdini space.
        idx: Vertex index.

    Returns:
        Outward normal angle in degrees, CCW from +X.
    """
    n    = len(outline)
    prev = np.array(outline[(idx - 1) % n])
    nxt  = np.array(outline[(idx + 1) % n])
    tang = nxt - prev

    # Two candidate normals (perpendicular to tangent)
    n1 = np.array([ tang[1], -tang[0]])
    n2 = np.array([-tang[1],  tang[0]])

    # The outward one points away from the centroid
    pts      = np.array(outline)
    centroid = pts.mean(axis=0)
    pt       = np.array(outline[idx])

    outward = n1 if np.dot(n1, pt - centroid) >= 0 else n2
    return float(round(math.degrees(math.atan2(outward[1], outward[0])) % 360, 3))


def inward_normal_angle(outline: list[list[float]], idx: int) -> float:
    """Return the inward normal angle at vertex idx — outward rotated 180°.

    Args:
        outline: Closed polyline vertices in Houdini space.
        idx: Vertex index.

    Returns:
        Inward normal angle in degrees [0, 360).
    """
    return float((outward_normal_angle(outline, idx) + 180.0) % 360.0)


# ----- CONNECTOR PLACEMENT -----

def place_connectors(outline: list[list[float]], n_ports: int, edge: str = "top") -> list[list[float]]:
    """Place n_ports connectors along the top or bottom edge of a shape.

    Connectors are pushed CONNECTOR_OFFSET units beyond the bounding box.
    Their X positions are sampled from outline vertices in the outermost
    30 % band of the chosen edge.

    Args:
        outline: Normalised shape silhouette vertices.
        n_ports: Number of connectors to place.
        edge: "top" (inputs) or "bottom" (outputs).

    Returns:
        List of [x, y, angle] triples; angle is 90.0 for top and
        270.0 for bottom.
    """
    if n_ports == 0:
        return []

    pts = np.array(outline)
    xs = pts[:, 0]
    ys = pts[:, 1]

    y_min, y_max = ys.min(), ys.max()
    x_min, x_max = xs.min(), xs.max()

    # Determine the target Y level (Global edge + Offset)
    if edge == "top":
        target_y = y_max + CONNECTOR_OFFSET
        target_angle = 90.0
        # Filter points in the top 30% of the shape to find candidate X positions
        mask = ys >= (y_max - (y_max - y_min) * 0.3)
    else:
        target_y = y_min - CONNECTOR_OFFSET
        target_angle = 270.0
        # Filter points in the bottom 30%
        mask = ys <= (y_min + (y_max - y_min) * 0.3)

    candidates = sorted(np.where(mask)[0].tolist(), key=lambda i: pts[i, 0])

    if not candidates:
        if n_ports == 1:
            return [[0.0, float(target_y), target_angle]]
        x_positions = np.linspace(x_min * 0.8, x_max * 0.8, n_ports)
        return [[round(float(x), 6), round(float(target_y), 6), target_angle] for x in x_positions]

    # Pick n_ports evenly spaced by index across the sorted candidate points
    if n_ports == 1:
        chosen_indices = [candidates[len(candidates) // 2]]
    else:
        idxs = np.linspace(0, len(candidates) - 1, n_ports, dtype=int)
        chosen_indices = [candidates[i] for i in idxs]

    result = []
    for idx in chosen_indices:
        # Use the original X from the outline, but the forced Global Y
        orig_x = pts[idx, 0]

        result.append([
            round(float(orig_x), 6),
            round(float(target_y), 6),
            target_angle
        ])

    return result


# ----- FLAG AREA -----


def point_polar_angle(pt: list[float]) -> float:
    """Return the polar angle of a point in degrees [0, 360).

    Args:
        pt: [x, y] point.

    Returns:
        Angle in degrees, CCW from +X.
    """
    return math.degrees(math.atan2(pt[1], pt[0])) % 360


def angular_distance(a: float, b: float) -> float:
    """Return the shortest angular distance between two angles.

    Args:
        a: First angle in degrees.
        b: Second angle in degrees.

    Returns:
        Shortest arc in degrees, range [0, 180].
    """
    d = abs(a - b) % 360
    return d if d <= 180 else 360 - d


def build_flag_zones(outline: list[list[float]]) -> dict[str, dict]:
    """Build the four connector flag hit-zones as degenerate point pairs.

    Each zone is collapsed to a single repeated point placed just outside
    the shape's radial extent — clickable but visually invisible.

    Args:
        outline: Normalised shape silhouette vertices.

    Returns:
        Slot indices "0"–"3" mapped to {"outline": [[x,y],[x,y]]}.
    """
    pts = np.array(outline)
    # Position the points slightly outside the silhouette's radius
    max_dist = np.max(np.linalg.norm(pts, axis=1)) * 1.02

    flags = {}
    for slot, center_deg in enumerate(FLAG_ANGLES):
        rad = math.radians(center_deg)
        x = math.cos(rad) * max_dist
        y = math.sin(rad) * max_dist

        # We provide the same point twice to satisfy the list requirement
        # but create a zero-length segment.
        flags[str(slot)] = {"outline": [[round(x, 6), round(y, 6)],
                                        [round(x, 6), round(y, 6)]]}
    return flags


# ----- ICON BOUNDING BOX -----

def compute_icon_bbox(outline: list[list[float]]) -> list[list[float]]:
    """Return a small square icon bounding box centred on the shape.

    Args:
        outline: Normalised shape silhouette vertices.

    Returns:
        [[x_min, y_min], [x_max, y_max]] corners of a 0.16-unit
        square centred at the shape's bounding-box centre.
    """
    pts = np.array(outline)
    # Calculate the center of the actual bounding box
    min_p = pts.min(axis=0)
    max_p = pts.max(axis=0)
    center = (min_p + max_p) / 2

    half_size = 0.08

    return [
        [round(float(center[0] - half_size), 6), round(float(center[1] - half_size), 6)],
        [round(float(center[0] + half_size), 6), round(float(center[1] + half_size), 6)]
    ]


# ----- CONNECTOR ESTIMATION -----


def estimate_connector_count(outline: list[list[float]], edge: str = "top") -> int:
    """Estimate the number of connectors on an edge from shape geometry.

    Counts sign changes in the Y profile of outline points within the
    outermost 30 % band, using them as a proxy for the number of convex lobes.

    Args:
        outline: Normalised shape silhouette vertices.
        edge: "top" or "bottom".

    Returns:
        Estimated connector count, minimum 1.
    """
    pts  = np.array(outline)
    ys   = pts[:, 1]
    y_min, y_max = ys.min(), ys.max()
    band = (y_max - y_min) * 0.30
    mask = (ys >= y_max - band) if edge == "top" else (ys <= y_min + band)
    cand = np.where(mask)[0]
    if not len(cand):
        return 1
    ordered = sorted(cand, key=lambda i: pts[i, 0])
    ey      = pts[ordered, 1]
    dy      = np.diff(ey)
    signs   = np.sign(dy)
    nz      = signs[signs != 0]
    changes = int(np.sum(np.abs(np.diff(nz)) > 0)) if len(nz) > 1 else 0
    return max(1, (changes + 2) // 2)


# ----- MAIN FUNCTIONS -----


def convert_svg(svg_path: str) -> dict | None:
    """Convert a single SVG file to a Houdini node shape dictionary.

    Samples all sub-paths, selects the longest as the silhouette, normalises
    it, then derives flags, connectors, and the icon box.

    Args:
        svg_path: Path to the input .svg file.

    Returns:
        Shape dict with keys name, flags, outline, inputs,
        outputs, icon; or None if no paths are found.
    """
    paths, _ = svg2paths(svg_path)
    if not paths: return None

    base_name = os.path.splitext(os.path.basename(svg_path))[0]
    raw_paths = [sample_path(p) for p in paths]

    main_path = max(raw_paths, key=len)

    cx, cy, scale = compute_normalization([main_path])
    global_outline = norm(main_path, cx, cy, scale)

    flags = build_flag_zones(global_outline)

    n_inputs = estimate_connector_count(global_outline, "top")
    n_outputs = estimate_connector_count(global_outline, "bottom")

    inputs = place_connectors(global_outline, n_inputs, edge="top")
    outputs = place_connectors(global_outline, n_outputs, edge="bottom")
    icon = compute_icon_bbox(global_outline)

    return {
        "name": base_name,
        "flags": flags,
        "outline": global_outline,
        "inputs": inputs,
        "outputs": outputs,
        "icon": icon,
    }


def main() -> None:
    """Batch-convert all SVG files in INPUT_FOLDER to Houdini JSON shapes.

    Writes a .json file alongside each .svg source. Files with no
    parseable paths are skipped with a console message.
    """
    svg_files = [f for f in os.listdir(INPUT_FOLDER) if f.lower().endswith(".svg")]
    if not svg_files:
        print(f"No SVG files found in {INPUT_FOLDER}")
        return

    for file in svg_files:
        svg_path  = os.path.join(INPUT_FOLDER, file)
        json_path = os.path.join(INPUT_FOLDER, file.replace(".svg", ".json"))

        data = convert_svg(svg_path)
        if data is None:
            print(f"Skipped: {data}\n")
            continue

        with open(json_path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Saved: {os.path.basename(json_path)}\n")

    print("Conversion successful")


if __name__ == "__main__":
    main()