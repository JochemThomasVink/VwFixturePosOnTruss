"""
FixturePOS - Fixture position on truss

Vectorworks menu command (Python).

Collects every Lighting Device and every object carrying the "pws truss tape"
record, matches them on their Position name and calculates where each fixture
sits along its truss (measured from Side A and from Side B).

The result is written to one worksheet per position, named
"<WS_PREFIX><Position>", and each fixture's distance from Side A (cm) is
written into its Lighting Device POS_FIELD (User Field 6). Running the
command again updates both; worksheets are updated in place, so worksheet
instances placed on sheet layers keep working.
"""

import math
import vs

# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

TAPE_RECORD = "pws truss tape"
FIXTURE_PON = "Lighting Device"
WS_PREFIX = "Truss Pos - "

# New position worksheets are made by duplicating this worksheet, so its print
# settings (Printer Setup scaling, margins, header/footer) carry over. Set it
# up once by hand; if it doesn't exist a blank worksheet is created instead.
TEMPLATE_WS = "Truss Pos Template"

# Field names on the truss tape record. Matching ignores case, spaces,
# underscores and dashes, so "Side A Label" also matches "side_a_label".
TAPE_FIELD_POSITION = "Position"
TAPE_FIELD_SIDE_A = "Side A Label"
TAPE_FIELD_SIDE_B = "Side B Label"
TAPE_FIELD_LENGTH = "Truss Length"

# Field names on the Lighting Device record.
FIX_FIELD_POSITION = "Position"
FIX_FIELD_UNIT = "Unit Number"
FIX_FIELD_TYPE = "Inst Type"
FIX_FIELD_SYMBOL = "Symbol Name"

# Lighting Device field that receives the distance from Side A (cm).
# Matching ignores case and spaces, so this also finds "UserField6".
POS_FIELD = "User Field 6"

# Field shown in the "Address" worksheet column (any record on the fixture).
ADDRESS_FIELD = "UniverseAdress"
ADDRESS_FIELD_ALIASES = ["UniverseAddress"]

# Fixtures further than this from the truss centre line (mm) get flagged.
MAX_OFFSET_MM = 1000.0

# Chord column: which side of the truss tape's centre line the fixture hangs
# on, named by the stage direction that side faces. Assumes the usual plan
# orientation (audience at the bottom): +Y = upstage, +X = stage left.
# Truss tapes placed with the Truss Tape tool carry their own side names in
# DIR_RECORD; those take priority over these defaults.
STAGE_DIRECTIONS = {"+x": "SL", "-x": "SR", "+y": "US", "-y": "DS"}
DIR_RECORD = "Truss Tape Directions"
DIR_FIELDS = {"+x": "East", "-x": "West", "+y": "North", "-y": "South"}
# Fixtures closer than this to the centre line (mm) are shown as "Centre".
CHORD_TOLERANCE_MM = 20.0

# Truss length values without a unit are read as millimetres.
LENGTH_UNITS_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "": 1.0}

# Class hierarchy holding one class per fixture type ("Lighting-Fixtures-*-*").
TYPE_CLASS_PREFIX = "Lighting-Fixtures-"

TYPE_COL = 2     # worksheet column holding the fixture type
ADDRESS_COL = 6  # worksheet column holding the address (formatted as text)
HEADER = ["Unit #", "Fixture Type", "From {a} (cm)", "From {b} (cm)", "Chord", "Address", "Note"]

# Worksheet layout: row 1 = position name, row 2 = truss info, row 3 = header.
FIRST_DATA_ROW = 4
NAME_ROW_HEIGHT = 48  # pixels
NAME_TEXT_SIZE = 48
BODY_TEXT_SIZE = 10

# Column widths in pixels (A-G). Total ~500 px fits A4 portrait with margins.
COLUMN_WIDTHS = [40, 125, 75, 75, 45, 60, 80]


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


def _class_rgb(class_name):
    """Fill colour of a class as (r, g, b) in 0-65535.

    A solid fill (or no fill) is drawn with the fill background colour; the
    foreground colour is only used by bitmap patterns.
    """
    if vs.GetClFPat(class_name) > 1:
        return tuple(vs.GetClFillFore(class_name))
    return tuple(vs.GetClFillBack(class_name))


def _is_type_class(name):
    """True for classes shaped like "Lighting-Fixtures-*-*"."""
    if not name.lower().startswith(TYPE_CLASS_PREFIX.lower()):
        return False
    return "-" in name[len(TYPE_CLASS_PREFIX):].strip("-")


def _symbol_def(name):
    """Handle to a symbol definition by name, or None if it isn't one."""
    if not name:
        return None
    h = vs.GetObject(name)
    if h is None or vs.GetTypeN(h) != 16:  # 16 = symbol definition
        return None
    return h


def _classes_in_symbol(sym, depth=0):
    """Class names of the objects inside a symbol definition, descending into
    groups and nested symbols. Plug-in objects are not entered."""
    found = []
    h = vs.FInSymDef(sym)
    count = 0
    while h is not None and count < 5000:
        count += 1
        found.append(vs.GetClass(h))
        if depth < 4:
            t = vs.GetTypeN(h)
            if t == 11:  # group
                found += _classes_in_group(h, depth + 1)
            elif t == 15:  # symbol instance
                nested = _symbol_def(vs.GetSymName(h))
                if nested is not None:
                    found += _classes_in_symbol(nested, depth + 1)
        h = vs.NextObj(h)
    return found


def _classes_in_group(group, depth):
    found = []
    h = vs.FInGroup(group)
    count = 0
    while h is not None and count < 5000:
        count += 1
        found.append(vs.GetClass(h))
        if depth < 4 and vs.GetTypeN(h) == 11:
            found += _classes_in_group(h, depth + 1)
        h = vs.NextObj(h)
    return found


_symbol_class_cache = {}


def _fixture_type_class(h, symbol_name, fixture_type):
    """Find the "Lighting-Fixtures-*-*" class that colours a fixture's 2D symbol.

    1. A matching class used inside its symbol definition.
    2. The Lighting Device's own class, if it matches.
    3. A matching class whose last segment equals the fixture type.
    """
    if symbol_name not in _symbol_class_cache:
        found = None
        sym = _symbol_def(symbol_name)
        if sym is not None:
            for name in _classes_in_symbol(sym):
                if _is_type_class(name):
                    found = name
                    break
        _symbol_class_cache[symbol_name] = found
    if _symbol_class_cache[symbol_name]:
        return _symbol_class_cache[symbol_name]

    own = vs.GetClass(h)
    if _is_type_class(own):
        return own

    key = _norm(fixture_type)
    if key:
        for i in range(1, vs.ClassNum() + 1):
            name = vs.ClassList(i)
            if _is_type_class(name) and _norm(name.split("-")[-1]) == key:
                return name
    return None


def _unit_sort_key(unit):
    try:
        return (0, float(unit), "")
    except ValueError:
        return (1, 0.0, unit)


# --------------------------------------------------------------------------
# Data collection
# --------------------------------------------------------------------------

def _tape_directions(h):
    """Side names for a truss tape: from DIR_RECORD where filled in, else the
    STAGE_DIRECTIONS defaults."""
    f = _record_fields(h, DIR_RECORD)
    return {key: str(f.get(_norm(field), "")).strip() or STAGE_DIRECTIONS[key]
            for key, field in DIR_FIELDS.items()}


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
        tapes[pos] = {
            "x": x * mm,
            "y": y * mm,
            "rot": rot_z,
            "length": length,
            "side_a": str(f.get(_norm(TAPE_FIELD_SIDE_A), "")).strip() or "Side A",
            "side_b": str(f.get(_norm(TAPE_FIELD_SIDE_B), "")).strip() or "Side B",
            "dirs": _tape_directions(h),
        }

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
            "type": str(f.get(_norm(FIX_FIELD_TYPE), "")).strip(),
            "class": _fixture_type_class(
                h, str(f.get(_norm(FIX_FIELD_SYMBOL), "")).strip(),
                str(f.get(_norm(FIX_FIELD_TYPE), "")).strip()),
            "x": x * mm,
            "y": y * mm,
            "address": _field_value(h, [ADDRESS_FIELD] + ADDRESS_FIELD_ALIASES),
            "handle": h,
        })

    vs.ForEachObject(cb, "(PON='{}')".format(FIXTURE_PON))
    return fixtures


# --------------------------------------------------------------------------
# Calculation
# --------------------------------------------------------------------------

def place_on_truss(fix, tape):
    """Return (distance from side A in mm, perpendicular offset in mm)."""
    rad = math.radians(tape["rot"])
    dx = fix["x"] - tape["x"]
    dy = fix["y"] - tape["y"]
    along = dx * math.cos(rad) + dy * math.sin(rad)
    across = -dx * math.sin(rad) + dy * math.cos(rad)
    return tape["length"] / 2.0 + along, across


def _find_field(h, field_names):
    """Return (record name, field name) of the first record on h that has one
    of field_names, or None."""
    wanted = {_norm(n) for n in field_names}
    for i in range(1, vs.NumRecords(h) + 1):
        rec_h = vs.GetRecord(h, i)
        for j in range(1, vs.NumFields(rec_h) + 1):
            fname = vs.GetFldName(rec_h, j)
            if _norm(fname) in wanted:
                return vs.GetName(rec_h), fname
    return None


def _record_field_name(h, rec_name, field_name):
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


def _field_value(h, field_names):
    """Value of the first matching field on any record of h, or ""."""
    target = _find_field(h, field_names)
    if target is None:
        return ""
    return str(vs.GetRField(h, target[0], target[1])).strip()


def chord_side(tape, offset):
    """Stage direction of the truss side a fixture hangs on, from its
    perpendicular offset to the truss tape's centre line."""
    if abs(offset) < CHORD_TOLERANCE_MM:
        return "Centre"
    rad = math.radians(tape["rot"])
    nx, ny = -math.sin(rad), math.cos(rad)  # left of the Side A -> B direction
    if offset < 0:
        nx, ny = -nx, -ny
    names = tape.get("dirs", STAGE_DIRECTIONS)
    if abs(nx) >= abs(ny):
        return names["+x" if nx > 0 else "-x"]
    return names["+y" if ny > 0 else "-y"]


def build_rows(tape, fixtures, color_log):
    rows = []
    for fix in fixtures:
        from_a, offset = place_on_truss(fix, tape)
        from_b = tape["length"] - from_a
        notes = []
        if from_a < 0 or from_b < 0:
            notes.append("outside truss")
        if abs(offset) > MAX_OFFSET_MM:
            notes.append("{:.0f} cm off truss line".format(offset / 10.0))
        values = [
            fix["unit"],
            fix["type"],
            str(int(round(from_a / 10.0))),
            str(int(round(from_b / 10.0))),
            chord_side(tape, offset),
            fix["address"],
            ", ".join(notes),
        ]
        cls = fix["class"]
        rgb = _class_rgb(cls) if cls else None
        color_log.setdefault(fix["type"] or "(no type)", (cls, rgb))
        rows.append((from_a, values, rgb))
    rows.sort(key=lambda r: (r[0], _unit_sort_key(r[1][0])))
    return [(r[1], r[2]) for r in rows]


# --------------------------------------------------------------------------
# Worksheet output
# --------------------------------------------------------------------------

def _worksheet_from_template(name):
    """Duplicate TEMPLATE_WS under a new name. Returns the handle, or None."""
    tpl = vs.GetObject(TEMPLATE_WS)
    if tpl is None or vs.GetTypeN(tpl) != 18:  # 18 = worksheet
        return None
    dup = vs.CreateDuplicateObject(tpl, vs.GetParent(tpl))
    if dup is None or vs.GetTypeN(dup) != 18:
        return None
    vs.SetName(dup, name)
    return dup


def write_worksheet(pos, tape, rows):
    name = WS_PREFIX + pos
    info = "{} → {}   |   length {:g} m".format(
        tape["side_a"], tape["side_b"], tape["length"] / 1000.0)
    header = [h.format(a=tape["side_a"], b=tape["side_b"]) for h in HEADER]
    n_cols = len(header)
    blank = [""] * (n_cols - 1)
    table = [[pos] + blank, [info] + blank, header] + [values for values, _ in rows]
    n_rows = len(table)

    ws = vs.GetObject(name)
    created = None
    if ws is None or vs.GetTypeN(ws) != 18:  # 18 = worksheet
        ws = _worksheet_from_template(name)
        if ws is None:
            ws = vs.CreateWS(name, n_rows, n_cols)
            created = "blank"
        else:
            created = "template"
    if created != "blank":
        cur_rows, cur_cols = vs.GetWSRowColumnCount(ws)
        vs.WorksheetSplitCells(ws, 1, 1, cur_rows, cur_cols)
        if cur_rows < n_rows:
            vs.InsertWSRows(ws, cur_rows + 1, n_rows - cur_rows)
        elif cur_rows > n_rows:
            vs.DeleteWSRows(ws, n_rows + 1, cur_rows - n_rows)
        if cur_cols < n_cols:
            vs.InsertWSColumns(ws, cur_cols + 1, n_cols - cur_cols)
        elif cur_cols > n_cols:
            vs.DeleteWSColumns(ws, n_cols + 1, cur_cols - n_cols)
        vs.SetWSCellFormula(ws, 1, 1, n_rows, n_cols, "")

    # Print settings: don't print column letters / row numbers ("Print Tabs").
    vs.SetObjectVariableBoolean(ws, 84, False)  # 84 = ovWSShowTabs

    # Reset formatting of the whole sheet, so a rerun never leaves stale styles.
    font = vs.GetWSCellTextFormat(ws, n_rows, 1)[0]
    vs.SetWSCellFill(ws, 1, 1, n_rows, n_cols, 0, 0, 0, -1)
    vs.SetWSCellTextColor(ws, 1, 1, n_rows, n_cols, vs.RGBToColorIndex(0, 0, 0))
    vs.SetWSCellTextFormat(ws, 1, 1, n_rows, n_cols, font, BODY_TEXT_SIZE, 0)
    vs.SetWSCellAlignment(ws, 1, 1, n_rows, n_cols, 0)
    vs.SetWSCellNumberFormat(ws, 1, 1, n_rows, n_cols, 0, 0, "", "")

    # Address as text, set before writing so DMX addresses don't become dates.
    vs.SetWSCellNumberFormat(ws, 1, ADDRESS_COL, n_rows, ADDRESS_COL, 13, 0, "", "")

    for r, row in enumerate(table, start=1):
        for c, value in enumerate(row, start=1):
            if value != "":
                vs.SetWSCellFormula(ws, r, c, r, c, value)

    # Row 1: position name, merged across the table, tall, large, bold, centred.
    vs.WorksheetMergeCells(ws, 1, 1, 1, n_cols)
    vs.SetWSRowHeight(ws, 1, 1, NAME_ROW_HEIGHT, False, True)
    vs.SetWSCellTextFormat(ws, 1, 1, 1, n_cols, font, NAME_TEXT_SIZE, 1)
    vs.SetWSCellAlignment(ws, 1, 1, 1, n_cols, 2)      # centre
    vs.SetWSCellVertAlignment(ws, 1, 1, 1, n_cols, 3)  # middle

    # Rows 2-3: truss info and header in bold.
    vs.SetWSCellTextFormat(ws, 2, 1, 3, n_cols, font, BODY_TEXT_SIZE, 1)

    # Colour the fixture type cells with their class fill colour, with white
    # text on dark colours so the name stays readable.
    white = vs.RGBToColorIndex(65535, 65535, 65535)
    for r, (_, rgb) in enumerate(rows, start=FIRST_DATA_ROW):
        if rgb is None:
            continue
        color = vs.RGBToColorIndex(rgb[0], rgb[1], rgb[2])
        vs.SetWSCellFill(ws, r, TYPE_COL, r, TYPE_COL, 1, color, color, -1)
        luminance = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 65535.0
        if luminance < 0.5:
            vs.SetWSCellTextColor(ws, r, TYPE_COL, r, TYPE_COL, white)

    for c, width in enumerate(COLUMN_WIDTHS, start=1):
        vs.SetWSColumnWidth(ws, c, c, width)
    # Wrap header and note text instead of letting it run out of the column.
    vs.SetWSCellWrapTextFlag(ws, 1, 1, n_rows, n_cols, False)
    vs.SetWSCellWrapTextFlag(ws, 3, 1, 3, n_cols, True)
    vs.SetWSCellWrapTextFlag(ws, FIRST_DATA_ROW, n_cols, n_rows, n_cols, True)
    vs.RecalculateWS(ws)
    return created


# --------------------------------------------------------------------------
# Record field output
# --------------------------------------------------------------------------

def write_position_fields(fixtures, tapes):
    """Write each fixture's distance from Side A (cm) into POS_FIELD.
    Returns (number written, unit numbers of fixtures without the field)."""
    written, no_field = 0, []
    for fix in fixtures:
        tape = tapes.get(fix["pos"])
        if tape is None:
            continue
        target = _record_field_name(fix["handle"], FIXTURE_PON, POS_FIELD)
        if target is None:
            no_field.append(fix["unit"] or "?")
            continue
        from_a, _offset = place_on_truss(fix, tape)
        vs.SetRField(fix["handle"], target[0], target[1], str(int(round(from_a / 10.0))))
        vs.ResetObject(fix["handle"])
        written += 1
    return written, no_field


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

    fixtures = collect_fixtures(mm)
    by_pos = {}
    for fix in fixtures:
        by_pos.setdefault(fix["pos"], []).append(fix)

    from_template, blank, updated = [], [], []
    color_log = {}
    for pos in sorted(tapes):
        rows = build_rows(tapes[pos], by_pos.get(pos, []), color_log)
        result = write_worksheet(pos, tapes[pos], rows)
        {"template": from_template, "blank": blank}.get(result, updated).append(pos)

    written, no_field = write_position_fields(fixtures, tapes)
    if no_field:
        warnings.append("No '{}' field on fixture(s): {}".format(
            POS_FIELD, ", ".join(sorted(no_field, key=_unit_sort_key))))

    unmatched = sorted(p for p in by_pos if p not in tapes)
    if unmatched:
        warnings.append("Fixtures on positions without a truss tape: " + ", ".join(unmatched))

    msg = "Fixture positions on truss\n\n"
    if from_template:
        msg += "Created from '{}': {}\n".format(TEMPLATE_WS, ", ".join(from_template))
    if blank:
        msg += "Created: " + ", ".join(blank) + "\n"
        warnings.append("No usable '{}' worksheet, so new worksheets use default print "
                        "settings. Set their Printer Setup scaling by hand.".format(TEMPLATE_WS))
    if updated:
        msg += "Updated: " + ", ".join(updated) + "\n"
    msg += "Position written to '{}' for {} fixture(s).\n".format(POS_FIELD, written)
    msg += "\nFixture type colours:\n"
    for ftype in sorted(color_log):
        cls, rgb = color_log[ftype]
        if cls is None:
            msg += "- {}: no {}* class found\n".format(ftype, TYPE_CLASS_PREFIX)
        else:
            msg += "- {}: {}  #{}  palette #{}\n".format(
                ftype, cls, "".join("{:02X}".format(int(round(v / 257.0))) for v in rgb),
                vs.RGBToColorIndex(rgb[0], rgb[1], rgb[2]))
    if warnings:
        msg += "\nWarnings:\n- " + "\n- ".join(warnings)
    vs.AlrtDialog(msg)


if __name__ == "__main__":
    run()
