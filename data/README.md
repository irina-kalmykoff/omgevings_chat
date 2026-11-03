# data

| Folder | Contents | In git |
| --- | --- | --- |
| `manifests/` | one manifest per snapshot: source, download date, file hashes | yes |
| `corpus/` | derived corpus output (`jsonl`), if you export one | no |

Everything is built from a local snapshot recorded in `manifests/`. Graph
construction, experiments and tests never call the live DSO API.

## The snapshot

The current snapshot is committed in [`source_data/`](../source_data):
[`maastricht-dso-2026-10-02`](manifests/maastricht-dso-2026-10-02.json), the
STOP/TPOD delivery package of the Omgevingsplan gemeente Maastricht (gm0935,
expression `nld@34`), downloaded from DSO production on 2026-10-02, plus the
municipal boundary in RD / EPSG:28992. The manifest lists a SHA-256 hash for
every file; all of them match the committed copy.

```
source_data/
├── Maastricht-boundary-RD.geojson
└── Maastricht-DSO-production-2026-10-02/
    ├── pakbon.xml
    ├── Regeling/          # regulation text and STOP metadata
    └── OW-bestanden/      # IMOW object files
```

A newer snapshot goes next to it under `source_data/`, with its own manifest
here; pass it to `omgkg build-graph --snapshot <dir>`.
