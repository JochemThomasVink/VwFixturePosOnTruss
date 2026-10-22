# FixturePOS

Vectorworks 2026 Python plug-ins for lighting plots that use paperwork.show
truss tapes (`pws truss tape` record).

| File | Plug-in type | What it does |
|---|---|---|
| `FixturePOS.py` | Menu command | For every truss tape, works out where each Lighting Device sits along the truss. Writes one worksheet per position and fills each fixture's **User Field 6** with its distance from Side A (cm). |
| `TrussTapeTool.py` | Tool | Draw a line from the start (Side A) to the end (Side B) of a truss, enter the truss name and the West/East/North/South side names, and it places a truss tape marker symbol with the record filled in. |
| `launcher_write_fields.py` | Menu command (legacy) | Standalone version of the User Field 6 step. `FixturePOS.py` now does this itself; kept for reference. |

All scripts are standalone: each file only imports Python's standard library
and Vectorworks' `vs` module.

## Installing

1. In Vectorworks: **Tools > Plug-ins > Plug-in Manager > Custom Plug-ins > New...**
   - `FixturePOS.py`: choose **Menu Command**
   - `TrussTapeTool.py`: choose **Tool**
2. **Edit Script...**, set the language to **Python**, and paste the whole file.
3. Add the command/tool to your workspace (**Tools > Workspaces > Edit Current Workspace**).

To share with a team, copy the `.vsm` / `.vst` that the Plug-in Manager
creates (in your user `Plug-ins` folder) into the workgroup folder's
`Plug-ins` folder. The script is stored inside that file, so re-paste and
re-copy after every change.

## Drawing conventions

- Truss tapes: symbol instances with the `pws truss tape` record
  (`Position`, `Side A Label`, `Side B Label`, `Truss Length`). The marker sits
  at the centre of the truss and its rotation points from Side A to Side B.
- Optional `Truss Tape Directions` record on a marker (added by the tool)
  holds the West/East/North/South side names, used for the worksheet's Chord
  column. Without it the Chord column uses SR/SL/US/DS (+X = stage left,
  +Y = upstage).
- Fixture type colours come from the fill colour of the
  `Lighting-Fixtures-*-*` class found in each fixture's symbol.
- The Address column reads a fixture field named `UniverseAdress`.
- New worksheets are duplicated from a worksheet named `Truss Pos Template`
  when it exists, so its Printer Setup (e.g. fit all rows on one page) carries
  over.

All names above are settings at the top of each script.

## Status

The scripts have been syntax-checked and dry-run against a stand-in `vs`
module; behaviour inside Vectorworks is confirmed only as far as noted in
the commit history.
