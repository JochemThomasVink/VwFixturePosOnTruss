"""
Truss Tape Tool

Vectorworks tool (Python). Standalone: paste this whole file as the script of
a Tool plug-in (Tools > Plug-ins > Plug-in Manager > Custom Plug-ins > New...
> Tool, Edit Script..., language Python).

The user draws a line from the start (Side A) to the end (Side B) of a truss
and enters the truss system name plus the names of the west, east, north and
south sides. The tool places a truss tape marker symbol at the centre of the
line, rotated along it, with the "pws truss tape" record filled in:

  Position      the truss system name
  Side A Label  name of the compass side the line starts at
  Side B Label  name of the compass side the line ends at
  Truss Length  length of the line

The four side names are also stored in a second record (DIR_RECORD), which
FixturePOS uses to name the chord a fixture hangs on.

The marker is an ordinary symbol instance, so it can be copied, moved and
edited in the Object Info palette like any other truss tape.
"""

import math
import os
import re
import vs

# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

TAPE_RECORD = "pws truss tape"
TAPE_FIELD_POSITION = "Position"
TAPE_FIELD_SIDE_A = "Side A Label"
TAPE_FIELD_SIDE_B = "Side B Label"
TAPE_FIELD_LENGTH = "Truss Length"

# Second record on the marker with the four side names (read by FixturePOS).
DIR_RECORD = "Truss Tape Directions"
DIRECTIONS = ["West", "East", "North", "South"]
DEFAULT_DIRECTION_NAMES = {"West": "SR", "East": "SL", "North": "US", "South": "DS"}

# Marker symbol. Leave SYMBOL_NAME empty to find it automatically:
#   1. the symbol used by truss tapes already in the drawing,
#   2. a symbol definition in the drawing with the truss tape record,
#   3. a symbol with "truss tape" in its name in the Libraries/LIBRARY_SUBFOLDER
#      folders (including workgroup folders) or in LIBRARY_FILE,
#   4. otherwise a simple arrow symbol named FALLBACK_SYMBOL is created.
SYMBOL_NAME = ""
LIBRARY_SUBFOLDER = "Annotations"
LIBRARY_FILE = "~/Vectorworks Cloud Services/VRF Workgroup/Libraries/Annotations/PWS Truss Tape.vwx"
FALLBACK_SYMBOL = "PWS Truss Tape Marker"

# Remembers the last used names between uses of the tool.
SETTINGS_CATEGORY = "TrussTapeTool"

LIBRARIES_FOLDER = 13  # Vectorworks folder index for "Libraries"
SYMBOL_DEF = 16        # object type of a symbol definition
SYMBOL_INSTANCE = 15   # object type of a symbol instance
TEXT_FIELD = 4         # NewField type for text


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _norm(name):
    return "".join(ch for ch in str(name).lower() if ch not in " _-")


def _attached_record(h, rec_name):
    """Handle of the record named rec_name attached to h, or None."""
    for i in range(1, vs.NumRecords(h) + 1):
        r = vs.GetRecord(h, i)
        if _norm(vs.GetName(r)) == _norm(rec_name):
            return r
    return None


def _is_symbol_def(h):
    return h is not None and vs.GetTypeN(h) == SYMBOL_DEF


def _mm_per_unit():
    upi = vs.GetUnits()[3]  # document units per inch
    return 25.4 / upi if upi else 1.0


def _load_setting(name, default):
    ok, value = vs.GetSavedSetting(SETTINGS_CATEGORY, name)
    return value if ok and value else default


def _existing_positions():
    names = set()

    def cb(h):
        r = _attached_record(h, TAPE_RECORD)
        if r is None:
            return
        for i in range(1, vs.NumFields(r) + 1):
            fname = vs.GetFldName(r, i)
            if _norm(fname) == _norm(TAPE_FIELD_POSITION):
                names.add(str(vs.GetRField(h, vs.GetName(r), fname)).strip())

    vs.ForEachObject(cb, "(R IN ['{}'])".format(TAPE_RECORD))
    return names


def _suggest_name(last, used):
    """Next free name after the last one used: LX3 -> LX4 (skipping names
    that are already in the drawing)."""
    m = re.match(r"^(.*?)(\d+)$", last or "")
    if not m:
        return last or ""
    prefix, digits = m.group(1), m.group(2)
    n = int(digits)
    while True:
        n += 1
        candidate = prefix + str(n).zfill(len(digits))
        if candidate not in used:
            return candidate


# --------------------------------------------------------------------------
# Marker symbol
# --------------------------------------------------------------------------

def _symbol_in_document():
    if SYMBOL_NAME:
        return SYMBOL_NAME if _is_symbol_def(vs.GetObject(SYMBOL_NAME)) else None

    used = []

    def cb(h):
        if vs.GetTypeN(h) == SYMBOL_INSTANCE:
            used.append(vs.GetSymName(h))

    vs.ForEachObject(cb, "(R IN ['{}'])".format(TAPE_RECORD))
    for name in used:
        if _is_symbol_def(vs.GetObject(name)):
            return name

    list_id, count = vs.BuildResourceList(SYMBOL_DEF, 0, "")
    for i in range(1, count + 1):
        name = vs.GetNameFromResourceList(list_id, i)
        h = vs.GetObject(name)
        if _is_symbol_def(h) and _attached_record(h, TAPE_RECORD) is not None:
            return name
    return None


def _symbol_from_library():
    lists = []
    try:
        lists.append(vs.BuildResourceList2(SYMBOL_DEF, -LIBRARIES_FOLDER, LIBRARY_SUBFOLDER, True))
    except Exception:
        pass
    path = os.path.expanduser(LIBRARY_FILE)
    if os.path.exists(path):
        lists.append(vs.BuildResourceListN(SYMBOL_DEF, path))

    for list_id, count in lists:
        for i in range(1, count + 1):
            name = vs.GetNameFromResourceList(list_id, i)
            wanted = (name == SYMBOL_NAME) if SYMBOL_NAME else ("trusstape" in _norm(name))
            if not wanted:
                continue
            h = vs.ImportResourceToCurrentFile(list_id, i)
            if _is_symbol_def(h):
                return vs.GetName(h)
    return None


def _create_fallback_symbol():
    """Simple marker: an arrow pointing from Side A to Side B (local +X)."""
    if _is_symbol_def(vs.GetObject(FALLBACK_SYMBOL)):
        return FALLBACK_SYMBOL
    u = 1.0 / _mm_per_unit()  # document units per mm
    vs.BeginSym(FALLBACK_SYMBOL)
    for a, b in [((-250, 0), (250, 0)),       # shaft
                 ((250, 0), (170, 60)),       # arrow head
                 ((250, 0), (170, -60)),
                 ((0, -120), (0, 120))]:      # centre tick
        vs.MoveTo((a[0] * u, a[1] * u))
        vs.LineTo((b[0] * u, b[1] * u))
    vs.EndSym()
    return FALLBACK_SYMBOL


def marker_symbol():
    """Return (symbol name, how it was found)."""
    name = _symbol_in_document()
    if name:
        return name, "document"
    name = _symbol_from_library()
    if name:
        return name, "library"
    return _create_fallback_symbol(), "created"


def _ensure_record(rec_name, field_names):
    """Create the record format (text fields) if the document doesn't have it."""
    if vs.GetObject(rec_name) is not None:
        return
    for field in field_names:
        vs.NewField(rec_name, field, "", TEXT_FIELD, 0)


def _write_fields(h, rec_name, values):
    """Attach rec_name to h if needed and set fields. Returns missing fields."""
    if _attached_record(h, rec_name) is None:
        vs.SetRecord(h, rec_name)
    r = _attached_record(h, rec_name)
    if r is None:
        return list(values)
    real_rec = vs.GetName(r)
    real_fields = {}
    for i in range(1, vs.NumFields(r) + 1):
        fname = vs.GetFldName(r, i)
        real_fields[_norm(fname)] = fname
    missing = []
    for field, value in values.items():
        real = real_fields.get(_norm(field))
        if real is None:
            missing.append(field)
        else:
            vs.SetRField(h, real_rec, real, value)
    return missing


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------

def end_directions(p1, p2):
    """Compass sides of the start and end of the line: a line drawn left to
    right starts at the West side and ends at the East side, etc. Diagonal
    lines use whichever axis they run along most."""
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    if abs(dx) >= abs(dy):
        return ("West", "East") if dx > 0 else ("East", "West")
    return ("South", "North") if dy > 0 else ("North", "South")


# --------------------------------------------------------------------------
# Dialog
# --------------------------------------------------------------------------

def ask_user(length_text, start_dir, end_dir):
    """Ask for the truss name and side names. Returns a dict, or None."""
    names = {d: _load_setting(d, DEFAULT_DIRECTION_NAMES[d]) for d in DIRECTIONS}
    suggested = _suggest_name(_load_setting("Last Name", ""), _existing_positions())

    dlg = vs.CreateLayout("Truss Tape", False, "OK", "Cancel")
    vs.CreateStaticText(dlg, 10, "Truss system name:", 18)
    vs.CreateEditText(dlg, 11, suggested, 16)
    edit_ids = {}
    for n, d in enumerate(DIRECTIONS):
        vs.CreateStaticText(dlg, 20 + 2 * n, d + " side:", 10)
        vs.CreateEditText(dlg, 21 + 2 * n, names[d], 8)
        edit_ids[d] = 21 + 2 * n
    vs.CreateStaticText(dlg, 30, "", 46)

    vs.SetFirstLayoutItem(dlg, 10)
    vs.SetRightItem(dlg, 10, 11, 0, 0)
    vs.SetBelowItem(dlg, 10, 20, 0, 1)   # West
    vs.SetRightItem(dlg, 20, 21, 0, 0)
    vs.SetRightItem(dlg, 21, 22, 2, 0)   # East
    vs.SetRightItem(dlg, 22, 23, 0, 0)
    vs.SetBelowItem(dlg, 20, 24, 0, 0)   # North
    vs.SetRightItem(dlg, 24, 25, 0, 0)
    vs.SetRightItem(dlg, 25, 26, 2, 0)   # South
    vs.SetRightItem(dlg, 26, 27, 0, 0)
    vs.SetBelowItem(dlg, 24, 30, 0, 1)   # preview

    result = {}

    def preview():
        a = vs.GetItemText(dlg, edit_ids[start_dir])
        b = vs.GetItemText(dlg, edit_ids[end_dir])
        return "Length {}    Side A: {} ({})  →  Side B: {} ({})".format(
            length_text, a, start_dir, b, end_dir)

    def handler(item, data):
        if item == 12255 or item in edit_ids.values():  # 12255 = dialog setup
            vs.SetItemText(dlg, 30, preview())
            if item == 12255:
                vs.SetFocusOnItem(dlg, 11)
        elif item == 1:  # OK
            result["name"] = vs.GetItemText(dlg, 11).strip()
            for d in DIRECTIONS:
                result[d] = vs.GetItemText(dlg, edit_ids[d]).strip()
        return item

    if vs.RunLayoutDialog(dlg, handler) != 1 or not result:
        return None
    return result


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def place_truss_tape(p1, p2):
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = math.hypot(dx, dy)
    if length <= 0:
        return
    start_dir, end_dir = end_directions(p1, p2)
    length_text = vs.Num2StrF(length)

    answer = ask_user(length_text, start_dir, end_dir)
    if answer is None:
        return
    if not answer["name"]:
        vs.AlrtDialog("No truss system name entered; no truss tape placed.")
        return

    symbol, source = marker_symbol()
    _ensure_record(TAPE_RECORD, [TAPE_FIELD_POSITION, TAPE_FIELD_SIDE_A,
                                 TAPE_FIELD_SIDE_B, TAPE_FIELD_LENGTH])
    _ensure_record(DIR_RECORD, DIRECTIONS)

    centre = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
    rotation = math.degrees(math.atan2(dy, dx))  # local +X points from A to B
    vs.Symbol(symbol, centre, rotation)
    h = vs.LNewObj()

    missing = _write_fields(h, TAPE_RECORD, {
        TAPE_FIELD_POSITION: answer["name"],
        TAPE_FIELD_SIDE_A: answer[start_dir],
        TAPE_FIELD_SIDE_B: answer[end_dir],
        TAPE_FIELD_LENGTH: length_text,
    })
    missing += _write_fields(h, DIR_RECORD, {d: answer[d] for d in DIRECTIONS})
    vs.ResetObject(h)

    vs.SetSavedSetting(SETTINGS_CATEGORY, "Last Name", answer["name"])
    for d in DIRECTIONS:
        vs.SetSavedSetting(SETTINGS_CATEGORY, d, answer[d])

    notes = []
    if source == "created":
        notes.append("No truss tape symbol found in the drawing or libraries, so a "
                     "simple marker symbol '{}' was created.".format(symbol))
    if missing:
        notes.append("These fields were not found on the marker's records: "
                     + ", ".join(missing))
    if notes:
        vs.AlrtDialog("\n\n".join(notes))


vs.GetLine(place_truss_tape)
