# data/

Runtime inputs the application reads but does not generate. **Nothing in
this directory except this file is in version control.**

The staff rosters name real University of Lagos employees, and this
repository is public, so they are git-ignored (see `PRIVACY_NOTICE.md`).
They are operational data an operator supplies, not source.

| File | What it is |
|---|---|
| `unilag_staff.json` | Staff names, used by `StaffValidator` to decide whether an author is affiliated with the institution |
| `unilag_staff_detailed.json` | The same roster with faculty and department fields |
| `staff_department_map.json` | Surname and full-name to faculty/department mappings |

## Running without them

Everything works. `StaffValidator` logs a warning, loads an empty name set,
and every name check returns false, so affiliation is decided by the other
signals the pipeline uses (ROR match, structured author-affiliation fields,
verified employment records). The only loss is roster-based confirmation,
which downgrades some records from `affiliation_confidence: "strong"` to
`"weak"`.

The test suite skips the roster tests rather than failing when the files are
absent.

## Rebuilding them

```bash
python scripts/harvest_staff_openalex.py
python scripts/merge_staff_department_data.py
```

On the Hugging Face Space these paths are not used at all: the Space reads
and writes `/data` on its persistent volume instead.
