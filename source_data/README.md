# source_data

Official source files the knowledge graph is built from. Dutch government open
data, committed here so the repo is self-contained and anyone can rebuild the
graph after cloning.

- `Maastricht-DSO-production-2026-10-02/` — the STOP/TPOD delivery package
  (aanleverpakket) of the Omgevingsplan gemeente Maastricht (gm0935): the
  regulation text (`Regeling/Tekst.xml`) and the IMOW object files
  (`OW-bestanden/`).
- `Maastricht-boundary-RD.geojson` — the municipal boundary polygon in
  RD / EPSG:28992.

These are the default inputs for `../prototype/build_graph.py` (`--package`,
`--boundary`) and `../prototype/spatial.py`.
