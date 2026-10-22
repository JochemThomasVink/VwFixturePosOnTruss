"""
Write Pos on Truss

Vectorworks menu command (Python). Standalone: paste this whole file as the
script of the menu command (Tools > Plug-ins > Plug-in Manager > Custom
Plug-ins > New... > Menu Command, Edit Script..., language Python).

Collects every Lighting Device and every object carrying the "pws truss tape"
record, matches them on their Position name and writes each fixture's distance
from Side A of its truss (in cm) into the Lighting Device's POS_FIELD
(User Field 6).
"""

import math
import vs

# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

TAPE_RECORD = "pws truss tape"
FIXTURE_PON = "Lighting Device"

# Field names on the truss tape record. Matching ignores case, spaces,
# underscores and dashes, so "Truss Length" also matches "truss_length".
TAPE_FIELD_POSITION = "Position"
TAPE_FIELD_LENGTH = "Truss Length"

# Field names on the Lighting Device record.
FIX_FIELD_POSITION = "Position"
FIX_FIELD_UNIT = "Unit Number"

# Lighting Device field that receives the distance from Side A (cm).
# Matching ignores case and spaces, so this also finds "UserField6".
POS_FIELD = "User Field 6"

# Truss length values without a unit are read as millimetres.
LENGTH_UNITS_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "": 1.0}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _norm(name):
    return "".join(ch for ch in str(name).lower() if ch not in " _-")


def _record_fields(h, rec_name):
    """Return {normalised field name: value} for one record attached to h."""
    rec_h = None
    for i in range(1, vs.NumRecords(h) + 1):
        r = vs.GetRecord(h, i)
        if _norm(vs.GetName(r)) == _norm(rec_name):
            rec_h = r
            break
    if rec_h is None:
        return {}
    real_name = vs.GetName(rec_h)
    fields = {}
    for i in range(1, vs.NumFields(rec_h) + 1):
        fname = vs.GetFldName(rec_h, i)
        fields[_norm(fname)] = vs.GetRField(h, real_name, fname)
    return fields


def _find_field(h, rec_name, field_name):
    """Return (record name, field name) as spelled in the document for a field
    on one record of h, or None."""
    for i in range(1, vs.NumRecords(h) + 1):
        rec_h = vs.GetRecord(h, i)
        if _norm(vs.GetName(rec_h)) != _norm(rec_name):
            continue
        for j in range(1, vs.NumFields(rec_h) + 1):
            fname = vs.GetFldName(rec_h, j)
            if _norm(fname) == _norm(field_name):
                return vs.GetName(rec_h), fname
        return None
    return None


def _mm_per_unit():
    upi = vs.GetUnits()[3]  # document units per inch
    return 25.4 / upi if upi else 1.0


def _parse_length_mm(text):
    s = str(text).strip().lower().replace(",", ".").replace(" ", "")
    num = ""
    for ch in s:
        if ch.isdigit() or ch in ".-":
            num += ch
        else:
            break
    unit = s[len(num):]
    try:
        value = float(num)
    except ValueError:
        return None
    if unit not in LENGTH_UNITS_TO_MM:
        return None
    return value * LENGTH_UNITS_TO_MM[unit]


def _unit_sort_key(unit):
    try:
        return (0, float(unit), "")
    except ValueError:
        return (1, 0.0, unit)


# --------------------------------------------------------------------------
# Data collection
# --------------------------------------------------------------------------

def collect_tapes(mm, warnings):
    tapes = {}

    def cb(h):
        f = _record_fields(h, TAPE_RECORD)
        pos = str(f.get(_norm(TAPE_FIELD_POSITION), "")).strip()
        if not pos:
            warnings.append("Truss tape without a Position name skipped.")
            return
        length_raw = f.get(_norm(TAPE_FIELD_LENGTH), "")
        length = _parse_length_mm(length_raw)
        if length is None:
            warnings.append("Truss tape '{}': can't read truss length '{}'.".format(pos, length_raw))
            return
        if pos in tapes:
            warnings.append("Position '{}' has more than one truss tape; using the first.".format(pos))
            return
        x, y, z = vs.GetSymLoc3D(h)
        ok, _rx, _ry, rot_z, _mirror = vs.Get3DOrientation(h)
        if not ok:
            rot_z = vs.GetSymRot(h)
        tapes[pos] = {"x": x * mm, "y": y * mm, "rot": rot_z, "length": length}

    vs.ForEachObject(cb, "(R IN ['{}'])".format(TAPE_RECORD))
    return tapes


def collect_fixtures(mm):
    fixtures = []

    def cb(h):
        f = _record_fields(h, FIXTURE_PON)
        pos = str(f.get(_norm(FIX_FIELD_POSITION), "")).strip()
        if not pos:
            return
        x, y, z = vs.GetSymLoc3D(h)
        fixtures.append({
            "pos": pos,
            "unit": str(f.get(_norm(FIX_FIELD_UNIT), "")).strip(),
            "x": x * mm,
            "y": y * mm,
            "handle": h,
        })

    vs.ForEachObject(cb, "(PON='{}')".format(FIXTURE_PON))
    return fixtures


# --------------------------------------------------------------------------
# Calculation
# --------------------------------------------------------------------------

def distance_from_side_a(fix, tape):
    """Distance in mm from Side A of the truss, measured along the truss."""
    rad = math.radians(tape["rot"])
    dx = fix["x"] - tape["x"]
    dy = fix["y"] - tape["y"]
    along = dx * math.cos(rad) + dy * math.sin(rad)
    return tape["length"] / 2.0 + along


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def run():
    warnings = []
    mm = _mm_per_unit()

    tapes = collect_tapes(mm, warnings)
    if not tapes:
        vs.AlrtDialog("No objects with the '{}' record found.".format(TAPE_RECORD))
        return

    written, no_field, no_tape = 0, [], set()
    for fix in collect_fixtures(mm):
        tape = tapes.get(fix["pos"])
        if tape is None:
            no_tape.add(fix["pos"])
            continue
        target = _find_field(fix["handle"], FIXTURE_PON, POS_FIELD)
        if target is None:
            no_field.append(fix["unit"] or "?")
            continue
        from_a = distance_from_side_a(fix, tape)
        vs.SetRField(fix["handle"], target[0], target[1], str(int(round(from_a / 10.0))))
        vs.ResetObject(fix["handle"])
        written += 1

    msg = "Position on truss written to '{}' for {} fixture(s).".format(POS_FIELD, written)
    if no_field:
        warnings.append("No '{}' field on fixture(s): {}".format(
            POS_FIELD, ", ".join(sorted(no_field, key=_unit_sort_key))))
    if no_tape:
        warnings.append("Skipped fixtures on positions without a truss tape: "
                        + ", ".join(sorted(no_tape)))
    if warnings:
        msg += "\n\nWarnings:\n- " + "\n- ".join(warnings)
    vs.AlrtDialog(msg)


run()
