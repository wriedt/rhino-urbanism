#! python 3
# -*- coding: utf-8 -*-
# Author: Rune Wriedt (runewriedt@gmail.com)
# Version: 1.0
# Date: 2026-06-15
# Description:
# Computes total horizontal section area of closed Breps / closed Breps inside blocks.
# For each solid, the script:
#   1. Finds the lowest horizontal planar face(s)
#   2. Sums the area of those base face(s)
#   3. Uses the base face centroid Z as the local base height
#   4. Creates a World XY section plane at base Z + 1.5 metres
#   5. Intersects the closed Brep with that plane
#   6. Calculates the true filled plan area from the resulting closed section curves
#      Nested curves are treated with an even/odd rule:
#        - outer loops add area
#        - loops inside outer loops subtract area
#        - loops inside holes add area again
#
# This is intended for Danish GFA-style checks where a sloping roof/floor volume
# is counted by its horizontal area at 1.5 m above the local base height.

import Rhino
import rhinoscriptsyntax as rs
import scriptcontext as sc
from System.Drawing import Color
from System.Windows.Forms import Clipboard
import math

import Eto.Forms as forms
import Eto.Drawing as drawing

WARN_LAYER_NAME = "QuickArea_Warnings"
WARN_LAYER_COLOR = Color.FromArgb(230, 50, 50)

# The legal/measuring offset is 1.5 metres.
# It is converted to the current Rhino model unit system in offset_1p5m_in_model_units().
SECTION_HEIGHT_METRES = 1.5


def ensure_layer(name, color):
    layers = sc.doc.Layers
    idx = layers.Find(name, True)
    if idx < 0:
        la = Rhino.DocObjects.Layer()
        la.Name = name
        la.Color = color
        idx = layers.Add(la)
    return idx


class WarningTagger(object):
    """Creates warning layer lazily; can be disabled to avoid creating dots/layers."""
    def __init__(self, enabled=True, layer_name=WARN_LAYER_NAME, layer_color=WARN_LAYER_COLOR):
        self.enabled = enabled
        self.layer_name = layer_name
        self.layer_color = layer_color
        self._layer_ready = False

    def _ensure(self):
        if not self.enabled:
            return
        if not self._layer_ready:
            ensure_layer(self.layer_name, self.layer_color)
            self._layer_ready = True

    def add_dot(self, text, point):
        if not self.enabled:
            return None
        self._ensure()
        dot_id = rs.AddTextDot(text, point)
        if dot_id:
            rs.ObjectLayer(dot_id, self.layer_name)
        return dot_id

    @property
    def layer_created(self):
        return self._layer_ready and self.enabled


def offset_1p5m_in_model_units():
    """
    Returns 1.5 metres converted to the active Rhino document units.

    Examples:
      - model in metres      -> 1.5
      - model in centimetres -> 150.0
      - model in millimetres -> 1500.0

    This keeps the script useful even if the file is not using metres as its unit system.
    """
    try:
        scale = Rhino.RhinoMath.UnitScale(
            Rhino.UnitSystem.Meters,
            sc.doc.ModelUnitSystem
        )
        return SECTION_HEIGHT_METRES * scale
    except:
        # Conservative fallback: if the conversion fails, use the raw value.
        # In a metres model this is correct.
        return SECTION_HEIGHT_METRES


def try_face_plane(face, tol):
    is_planar, plane = face.TryGetPlane(tol)
    return is_planar, (plane if is_planar else None)


def is_near_horizontal(normal, ang_tol_rad):
    """
    Tests whether a face normal is nearly vertical, meaning the face itself is nearly horizontal.

    The face normal may point up or down depending on Brep orientation, so we compare to both +Z and -Z.
    """
    if not normal.IsValid or normal.IsZero:
        return False
    n = Rhino.Geometry.Vector3d(normal)
    n.Unitize()
    z = Rhino.Geometry.Vector3d(0, 0, 1)
    a = Rhino.Geometry.Vector3d.VectorAngle(n, z)
    a = min(a, abs(math.pi - a))
    return a <= ang_tol_rad


def lowest_horizontal_planar_faces(brep, tol, loose_ang_rad):
    """
    Finds the lowest horizontal planar face candidates on a Brep.

    This is intentionally close to the uploaded QuickArea_v3 logic:
      - first collect planar faces that are approximately horizontal
      - use their area centroid Z as the height reference
      - keep faces whose centroid Z equals the lowest candidate Z within tolerance
    """
    candidates = []

    for i, f in enumerate(brep.Faces):
        is_planar, plane = try_face_plane(f, tol)
        if not is_planar or plane is None:
            continue
        if not is_near_horizontal(plane.Normal, loose_ang_rad):
            continue

        amp = Rhino.Geometry.AreaMassProperties.Compute(f)
        z = amp.Centroid.Z if amp else f.GetBoundingBox(True).Center.Z
        candidates.append((f, i, z))

    if not candidates:
        return []

    min_z = min(z for _, _, z in candidates)
    return [(f, i, z) for (f, i, z) in candidates if abs(z - min_z) <= tol]


def base_area_and_z_from_lowest_faces(brep, tol, loose_ang_rad, strict_ang_rad):
    """
    Returns:
      (success, base_area, base_z, base_face_count, problem_text)

    This is the original QuickArea-style base calculation:
      - find the lowest approximately horizontal planar face candidates
      - require them to be strictly horizontal before counting them
      - sum their Rhino face areas

    The face area returned by AreaMassProperties.Compute(face) respects trimmed face
    boundaries, so holes in a base face should already be subtracted by Rhino.
    """
    lowest = lowest_horizontal_planar_faces(brep, tol, loose_ang_rad)
    if not lowest:
        return False, 0.0, None, 0, "No horizontal planar base face found"

    total_base_area = 0.0
    usable_z_values = []
    usable_face_count = 0

    for face, face_index, z in lowest:
        is_planar, plane = try_face_plane(face, tol)
        if not is_planar or plane is None:
            continue
        if not is_near_horizontal(plane.Normal, strict_ang_rad):
            continue

        amp = Rhino.Geometry.AreaMassProperties.Compute(face)
        if amp is None or amp.Area <= tol * tol:
            continue

        total_base_area += amp.Area
        usable_z_values.append(z)
        usable_face_count += 1

    if not usable_z_values or total_base_area <= tol * tol:
        return False, 0.0, None, 0, "Lowest base face is not strictly horizontal or has no measurable area"

    # Use the minimum centroid Z to avoid accidentally lifting the section plane.
    return True, total_base_area, min(usable_z_values), usable_face_count, None


def clean_joined_section_curves(raw_curves, tol):
    """
    Joins raw Brep/plane intersection segments into closed section loops.

    Brep-plane intersections commonly return several curve segments rather than complete loops.
    Area calculation requires closed curves, so we join first and then keep only closed curves.
    """
    if not raw_curves:
        return [], []

    joined = Rhino.Geometry.Curve.JoinCurves(raw_curves, tol)
    if not joined:
        joined = raw_curves

    closed = []
    open_or_invalid = []

    for crv in joined:
        if crv is None:
            continue
        if crv.IsClosed:
            closed.append(crv)
        else:
            open_or_invalid.append(crv)

    return closed, open_or_invalid


def curve_area_and_centroid(curve):
    """
    Returns (success, absolute_area, centroid).

    AreaMassProperties.Compute(curve) works for closed planar curves.
    We use absolute area because loop orientation can vary.
    """
    amp = Rhino.Geometry.AreaMassProperties.Compute(curve)
    if amp is None:
        return False, 0.0, Rhino.Geometry.Point3d.Unset

    return True, abs(amp.Area), amp.Centroid


def true_filled_area_from_section_loops(section_loops, section_plane, tol):
    """
    Calculates filled section area using nested closed curves.

    Why this is needed:
      A closed perimeter block can section as two loops:
        - outer facade loop
        - inner courtyard loop
      Summing both would over-count the courtyard. Instead, the inner loop must subtract.

    Method:
      1. Compute an area and centroid for each closed loop.
      2. For each loop, count how many larger loops contain its centroid.
      3. Even nesting depth means filled material -> add area.
      4. Odd nesting depth means void/courtyard -> subtract area.

    This is the standard even/odd region rule, and also handles islands inside holes.
    """
    loop_data = []

    for crv in section_loops:
        ok, area, centroid = curve_area_and_centroid(crv)
        if not ok or area <= tol * tol or not centroid.IsValid:
            continue
        loop_data.append({
            "curve": crv,
            "area": area,
            "centroid": centroid,
            "depth": 0
        })

    if not loop_data:
        return 0.0, 0, []

    # Larger loops must be tested first because only a larger loop can contain a smaller loop.
    loop_data.sort(key=lambda d: d["area"], reverse=True)

    for i, item in enumerate(loop_data):
        pt = item["centroid"]
        depth = 0

        for j, other in enumerate(loop_data):
            if i == j:
                continue
            if other["area"] <= item["area"]:
                continue

            containment = other["curve"].Contains(pt, section_plane, tol)
            if containment == Rhino.Geometry.PointContainment.Inside:
                depth += 1

        item["depth"] = depth

    total = 0.0
    for item in loop_data:
        if item["depth"] % 2 == 0:
            total += item["area"]
        else:
            total -= item["area"]

    return total, len(loop_data), loop_data


def section_area_of_solid_at_1p5m(brep, tol, loose_ang_rad, strict_ang_rad):
    """
    Returns:
      (success, section_area, base_area, base_z, section_z, loop_count, base_face_count, problem_text)

    The section area is the filled horizontal section area of the actual closed Brep volume.
    The base area is the original QuickArea-style area of the lowest horizontal planar face(s).
    """
    ok, base_area, base_z, base_face_count, base_problem = base_area_and_z_from_lowest_faces(
        brep,
        tol,
        loose_ang_rad,
        strict_ang_rad
    )

    if not ok:
        return False, 0.0, 0.0, None, None, 0, 0, base_problem

    section_z = base_z + offset_1p5m_in_model_units()
    section_plane = Rhino.Geometry.Plane(
        Rhino.Geometry.Point3d(0, 0, section_z),
        Rhino.Geometry.Vector3d.ZAxis
    )

    success, raw_curves, raw_points = Rhino.Geometry.Intersect.Intersection.BrepPlane(
        brep,
        section_plane,
        tol
    )

    if not success or not raw_curves:
        return False, 0.0, base_area, base_z, section_z, 0, base_face_count, "No section curves at 1.5 m above base"

    closed_loops, open_curves = clean_joined_section_curves(raw_curves, tol)

    if not closed_loops:
        return False, 0.0, base_area, base_z, section_z, 0, base_face_count, "Section did not produce closed loops"

    area, loop_count, loop_data = true_filled_area_from_section_loops(
        closed_loops,
        section_plane,
        tol
    )

    if area <= tol * tol:
        return False, 0.0, base_area, base_z, section_z, loop_count, base_face_count, "Section area is zero or below tolerance"

    # Open curves indicate possible tolerance or modelling issues.
    # We still return the area from the closed loops, but report the warning upstream.
    if open_curves:
        return True, area, base_area, base_z, section_z, loop_count, base_face_count, "Warning: some section curves were open and ignored"

    return True, area, base_area, base_z, section_z, loop_count, base_face_count, None


def format_area_with_units(area_value):
    try:
        unit_name = rs.UnitSystemName(model_units=True, singular=False)
        return "{:.6g} {}²".format(area_value, unit_name) if unit_name else "{:.6g}".format(area_value)
    except:
        return "{:.6g}".format(area_value)


def format_percent(value):
    """Formats a percentage with enough precision to be useful in a dialog."""
    return "{:.2f}%".format(value)


def lowest_bbox_point(obj_id):
    bb = rs.BoundingBox(obj_id)
    if not bb:
        return None
    return sorted(bb, key=lambda p: p.Z)[0]


# Ensures 1893.5 -> 1894 instead of Python's banker's rounding.
def round_half_up(x):
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(abs(x) + 0.5))


def _xform_multiply(a, b):
    # Returns transform equivalent to applying b, then a (a*b).
    return Rhino.Geometry.Transform.Multiply(a, b)


def extract_solids_from_instance(instance_obj, parent_xform, out_list, origin_id, visited_idef_ids):
    """
    Recursively extracts Breps from a block instance into out_list.

    Each entry appended:
      (origin_id, kind, brep_world)

    kind == "Solid" for closed Breps
    kind == "Open"  for non-solid Breps
    """
    if instance_obj is None:
        return

    idef = instance_obj.InstanceDefinition
    if idef is None:
        return

    # Avoid infinite recursion if a block somehow references itself.
    if idef.Id in visited_idef_ids:
        return
    visited_idef_ids.add(idef.Id)

    def_objects = idef.GetObjects()
    if not def_objects:
        visited_idef_ids.remove(idef.Id)
        return

    for dobj in def_objects:
        if dobj is None:
            continue
        geo = dobj.Geometry
        if geo is None:
            continue

        if dobj.ObjectType == Rhino.DocObjects.ObjectType.InstanceReference:
            child_inst = dobj
            child_xf = child_inst.InstanceXform
            total = _xform_multiply(parent_xform, child_xf)
            extract_solids_from_instance(child_inst, total, out_list, origin_id, visited_idef_ids)
            continue

        brep = Rhino.Geometry.Brep.TryConvertBrep(geo)
        if brep is None:
            continue

        brep_dup = brep.DuplicateBrep()
        if brep_dup is None:
            continue

        if not brep_dup.Transform(parent_xform):
            continue

        if brep_dup.IsSolid:
            out_list.append((origin_id, "Solid", brep_dup))
        else:
            out_list.append((origin_id, "Open", brep_dup))

    visited_idef_ids.remove(idef.Id)


def ask_invalid_dialog():
    """
    Returns:
      "cancel" | "continue_tag" | "continue_no_tag"
    """
    dlg = forms.Dialog[bool]()
    dlg.Title = "QuickArea – Invalid Selection"
    dlg.Padding = drawing.Padding(12)
    dlg.Resizable = False

    msg = forms.Label()
    msg.Text = (
        "Some selected items are invalid/open (or blocks contain open Breps),\n"
        "and will not be processed.\n\n"
        "How would you like to continue?"
    )

    btn_cancel = forms.Button()
    btn_cancel.Text = "Cancel"
    btn_tag = forms.Button()
    btn_tag.Text = "Continue and tag invalid"
    btn_no_tag = forms.Button()
    btn_no_tag.Text = "Continue without tagging"

    for b in (btn_cancel, btn_tag, btn_no_tag):
        b.Width = 210

    layout = forms.DynamicLayout()
    layout.Spacing = drawing.Size(8, 8)
    layout.AddRow(msg)
    layout.AddRow(None)
    layout.AddRow(btn_tag)
    layout.AddRow(btn_no_tag)
    layout.AddRow(btn_cancel)
    dlg.Content = layout

    choice = {"value": "cancel"}

    def _set(val):
        choice["value"] = val
        dlg.Close(True)

    btn_cancel.Click += lambda s, e: _set("cancel")
    btn_tag.Click += lambda s, e: _set("continue_tag")
    btn_no_tag.Click += lambda s, e: _set("continue_no_tag")

    dlg.ShowModal(Rhino.UI.RhinoEtoApp.MainWindow)
    return choice["value"]


def show_result_dialog(pretty_section_area, pretty_base_area, rounded_section_value, rounded_base_value, reduction_percent, solid_count, loop_count, base_face_count):
    dlg = forms.Dialog[bool]()
    dlg.Title = "QuickArea – 1.5 m Section Result"
    dlg.Padding = drawing.Padding(12)
    dlg.Resizable = False

    label = forms.Label()
    label.Text = (
        "Base plane area:\n"
        "{}\n"
        "Rounded base value: {}\n\n"
        "1.5 m section area:\n"
        "{}\n"
        "Rounded section value: {}\n\n"
        "Reduction from base to 1.5 m section:\n"
        "{}\n\n"
        "Closed solids processed: {}\n"
        "Base faces used: {}\n"
        "Section loops used: {}\n"
    ).format(
        pretty_base_area,
        rounded_base_value,
        pretty_section_area,
        rounded_section_value,
        format_percent(reduction_percent),
        solid_count,
        base_face_count,
        loop_count
    )

    btn_copy = forms.Button()
    btn_copy.Text = "Copy to clipboard"
    btn_ok = forms.Button()
    btn_ok.Text = "OK"

    btn_copy.Width = 180
    btn_ok.Width = 100

    layout = forms.DynamicLayout()
    layout.Spacing = drawing.Size(8, 8)
    layout.AddRow(label)
    layout.AddRow(None)
    layout.AddRow(btn_copy, btn_ok)
    dlg.Content = layout

    def on_copy(sender, e):
        Clipboard.SetText(str(rounded_section_value))
        dlg.Close(True)

    def on_ok(sender, e):
        dlg.Close(True)

    btn_copy.Click += on_copy
    btn_ok.Click += on_ok

    dlg.ShowModal(Rhino.UI.RhinoEtoApp.MainWindow)


def main():
    ids = rs.GetObjects(
        "Select closed Breps (volumes) and/or Blocks to compute 1.5 m section area",
        rs.filter.surface | rs.filter.polysurface | rs.filter.instance,
        preselect=True,
        select=True
    )
    if not ids:
        return

    doc_tol = sc.doc.ModelAbsoluteTolerance

    # A loose filter is used to find candidate base faces.
    # A strict filter is then used to reject faces that are not truly World XY horizontal.
    loose_filter_deg = 30.0
    loose_filter_rad = math.radians(loose_filter_deg)
    strict_deg = 1.0
    strict_rad = math.radians(strict_deg)

    invalid_ids = []
    open_item_ids = []
    solids = []  # (origin_id, brep_world)

    # First pass: gather closed Breps and detect invalid/open geometry.
    for oid in ids:
        rh_obj = sc.doc.Objects.FindId(oid)
        if rh_obj is None:
            invalid_ids.append(oid)
            continue

        if rh_obj.ObjectType == Rhino.DocObjects.ObjectType.InstanceReference:
            inst = rh_obj
            xform = inst.InstanceXform  # block instance transform to world coordinates
            extracted = []
            extract_solids_from_instance(inst, xform, extracted, origin_id=oid, visited_idef_ids=set())

            if not extracted:
                invalid_ids.append(oid)
                continue

            for origin_id, kind, brep_world in extracted:
                if kind == "Solid":
                    solids.append((origin_id, brep_world))
                else:
                    open_item_ids.append(origin_id)
            continue

        brep = rs.coercebrep(oid)
        if brep is None:
            invalid_ids.append(oid)
            continue
        if brep.IsSolid:
            solids.append((oid, brep))
        else:
            open_item_ids.append(oid)

    any_invalid_selection = bool(invalid_ids or open_item_ids)

    tag_invalid = False
    if any_invalid_selection:
        choice = ask_invalid_dialog()
        if choice == "cancel":
            return
        elif choice == "continue_tag":
            tag_invalid = True
        elif choice == "continue_no_tag":
            tag_invalid = False

    tagger = WarningTagger(enabled=tag_invalid)

    if not solids:
        if tag_invalid:
            rs.UnselectAllObjects()
            rs.SelectObjects(list(set(invalid_ids + open_item_ids)))
            for oid in invalid_ids:
                pt = lowest_bbox_point(oid)
                if pt:
                    tagger.add_dot("INVALID / NO SOLIDS", pt)
            for oid in open_item_ids:
                pt = lowest_bbox_point(oid)
                if pt:
                    tagger.add_dot("OPEN BREP", pt)

        rs.MessageBox("No closed Breps to process (including inside selected blocks).", 48, "QuickArea")
        return

    if any_invalid_selection and tag_invalid:
        rs.UnselectAllObjects()
        rs.SelectObjects(list(set(invalid_ids + open_item_ids)))

        for oid in invalid_ids:
            pt = lowest_bbox_point(oid)
            if pt:
                tagger.add_dot("INVALID / NO SOLIDS", pt)

        for oid in open_item_ids:
            pt = lowest_bbox_point(oid)
            if pt:
                tagger.add_dot("OPEN BREP", pt)

    total_section_area = 0.0
    total_base_area = 0.0
    total_loops = 0
    total_base_faces = 0
    problems = []  # (origin_id, reason)
    warnings = []  # (origin_id, warning_text)

    for origin_id, brep in solids:
        ok, section_area, base_area, base_z, section_z, loop_count, base_face_count, problem = section_area_of_solid_at_1p5m(
            brep,
            doc_tol,
            loose_filter_rad,
            strict_rad
        )

        # Good result, but with a non-fatal warning such as ignored open curves.
        if ok:
            total_section_area += section_area
            total_base_area += base_area
            total_loops += loop_count
            total_base_faces += base_face_count
            if problem:
                warnings.append((origin_id, problem))
            continue

        # Failed result.
        problems.append((origin_id, problem))

        amp_brep = Rhino.Geometry.AreaMassProperties.Compute(brep)
        cen = amp_brep.Centroid if amp_brep else brep.GetBoundingBox(True).Center
        tagger.add_dot(problem, cen)

    if problems or warnings:
        if tag_invalid and problems:
            rs.UnselectAllObjects()
            rs.SelectObjects(list({p[0] for p in problems}))

        lines = []

        if problems:
            lines.append("Some solids could not be counted:")
            by_obj = {}
            for oid, reason in problems:
                by_obj.setdefault(oid, []).append(reason)

            for oid, items in by_obj.items():
                lines.append("- Object {}: {} issue(s)".format(str(oid)[:8], len(items)))
                for reason in items:
                    lines.append("    • {}".format(reason))

        if warnings:
            if lines:
                lines.append("")
            lines.append("Some solids were counted with warnings:")
            by_obj = {}
            for oid, warning in warnings:
                by_obj.setdefault(oid, []).append(warning)

            for oid, items in by_obj.items():
                lines.append("- Object {}: {} warning(s)".format(str(oid)[:8], len(items)))
                for warning in items:
                    lines.append("    • {}".format(warning))

        if tag_invalid and tagger.layer_created:
            lines.append("\nProblem items were tagged with TextDots on layer '{}'.".format(WARN_LAYER_NAME))

        rs.MessageBox("\n".join(lines), 48, "QuickArea – 1.5 m Section Issues")

    pretty_section = format_area_with_units(total_section_area)
    pretty_base = format_area_with_units(total_base_area)

    rounded_section_value = round_half_up(total_section_area)
    rounded_base_value = round_half_up(total_base_area)

    if total_base_area > doc_tol * doc_tol:
        reduction_percent = ((total_base_area - total_section_area) / total_base_area) * 100.0
    else:
        reduction_percent = 0.0

    print("QuickArea — Total base plane area: {}".format(pretty_base))
    print("QuickArea — Total 1.5 m section area: {}".format(pretty_section))
    print("QuickArea — Reduction from base to 1.5 m section: {}".format(format_percent(reduction_percent)))
    print("QuickArea — Rounded section value copied on request: {}".format(rounded_section_value))

    show_result_dialog(
        pretty_section,
        pretty_base,
        rounded_section_value,
        rounded_base_value,
        reduction_percent,
        len(solids),
        total_loops,
        total_base_faces
    )


if __name__ == "__main__":
    main()
