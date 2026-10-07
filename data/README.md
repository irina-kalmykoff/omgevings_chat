# data

| Folder | Contents | In git |
| --- | --- | --- |
| `raw/` | DSO snapshot: STOP/TPOD package, IMOW files, API dumps | no |
| `manifests/` | one manifest per snapshot: source, download date, file hashes | yes |
| `corpus/` | normalized text components (`jsonl`) produced by ingestion | no |
| `eval/` | evaluation questions with reference evidence | yes |

Everything is built from a local snapshot recorded in `manifests/`. Graph
construction, experiments and tests never call the live DSO API.

Once the evaluation set in `eval/` is frozen, it is not changed.

## Getting the snapshot

The raw files are not in git. Get the current snapshot from the team's shared
storage and place it under `raw/` so that the paths match the manifest. The
manifest lists a SHA-256 hash for every file, so you can check that your copy
is identical.

Current snapshot: [`maastricht-dso-2026-10-02`](manifests/maastricht-dso-2026-10-02.json)
— the STOP/TPOD delivery package of the Omgevingsplan gemeente Maastricht
(gm0935, expression `nld@34`), downloaded from DSO production on 2026-10-02,
plus the municipal boundary in RD / EPSG:28992.

```
data/raw/
├── Maastricht-boundary-RD.geojson
└── Maastricht-DSO-production-2026-10-02/
    ├── pakbon.xml
    ├── Regeling/          # regulation text and STOP metadata
    └── OW-bestanden/      # IMOW object files
```
