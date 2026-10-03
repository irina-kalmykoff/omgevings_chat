# Neo4j local setup

Step-by-step guide to run Neo4j 5 (with the APOC plugin) in Docker and connect to it from Python.

At the end you will have:

| What            | Where                    |
| --------------- | ------------------------ |
| Neo4j Browser   | http://localhost:7474    |
| Bolt (drivers)  | `bolt://localhost:7687`  |
| Username        | `neo4j`                  |
| Password        | `testpassword`           |
| Container name  | `neo4j-omgeving`         |

> `testpassword` is fine for a local development database. Never reuse it for anything reachable from the internet.

---

## 1. Install Docker Desktop

Neo4j runs inside a Docker container, so Docker is the only thing you need to install for the database itself.

### macOS

1. Check your chip:  → **About This Mac**. "Apple M1/M2/M3/M4" = Apple Silicon, "Intel" = Intel.
2. Download Docker Desktop from https://www.docker.com/products/docker-desktop/ and pick the matching version (**Mac with Apple chip** or **Mac with Intel chip**).
3. Open the downloaded `Docker.dmg` and drag **Docker** into **Applications**.
4. Start **Docker** from Applications. On first launch:
   - read and accept the Docker Subscription Service Agreement (free for personal, education and small business use),
   - enter your Mac password when it asks to install its helper ("Use recommended settings" is fine),
   - signing in to a Docker account is optional; you can skip it.
5. Wait until the whale icon in the menu bar stops animating.

### Windows

1. Download Docker Desktop for Windows from the same page and run the installer.
2. Keep **Use WSL 2** selected. Restart when asked.
3. Start Docker Desktop and accept the agreement.

### Linux

Follow https://docs.docker.com/engine/install/ for your distribution (or install Docker Desktop for Linux).

### Check Docker works

Open a terminal and run:

```bash
docker --version
docker info
```

`docker info` should print details about the server. If it says *Cannot connect to the Docker daemon*, Docker Desktop is not running yet.

---

## 2. Start the Neo4j container

Run this once:

```bash
docker run -d --name neo4j-omgeving \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/testpassword \
  -e NEO4J_PLUGINS='["apoc"]' \
  neo4j:5
```

What each part does:

| Part | Meaning |
| --- | --- |
| `-d` | run in the background |
| `--name neo4j-omgeving` | name of the container, used in later commands |
| `-p 7474:7474` | Neo4j Browser (web UI) |
| `-p 7687:7687` | Bolt protocol, used by Python and other drivers |
| `-e NEO4J_AUTH=neo4j/testpassword` | username / password |
| `-e NEO4J_PLUGINS='["apoc"]'` | installs the APOC procedures library |
| `neo4j:5` | latest Neo4j 5.x image (works on Apple Silicon and Intel) |

The first run downloads the image (a few hundred MB), so it can take a minute.

### Wait until it has started

```bash
docker logs -f neo4j-omgeving
```

When you see a line ending in `Started.`, press `Ctrl+C` (this only stops following the log, not Neo4j).

### Optional: keep your data on your own disk

Without a volume, data lives inside the container: it survives `docker stop` / `docker start`, but is **lost if the container is removed**. To store it in a folder on your machine instead, add a `-v` line when you first create the container:

```bash
docker run -d --name neo4j-omgeving \
  -p 7474:7474 -p 7687:7687 \
  -v "$HOME/neo4j-omgeving/data:/data" \
  -e NEO4J_AUTH=neo4j/testpassword \
  -e NEO4J_PLUGINS='["apoc"]' \
  neo4j:5
```

---

## 3. Open Neo4j Browser

1. Go to http://localhost:7474
2. Connect URL: `neo4j://localhost:7687` (if that fails, try `bolt://localhost:7687`)
3. Username `neo4j`, password `testpassword`.
4. Check APOC is installed by running this query in the top bar:

   ```cypher
   RETURN apoc.version();
   ```

   It should return a version number such as `"5.26.x"`.

---

## 4. Set up Python and test the driver

Use a virtual environment so the packages don't interfere with other projects.

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install neo4j lxml
```

Save this as `smoke_test.py`. It only proves that Python can reach the container:

```python
from neo4j import GraphDatabase

driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "testpassword"))
driver.verify_connectivity()
print("connected")
driver.close()
```

Run it:

```bash
python smoke_test.py
```

Expected output:

```
connected
```

### Optional: JupyterLab

```bash
pip install jupyterlab
jupyter lab
```

Notebooks started this way use the same `.venv`, so `import neo4j` works. If another Jupyter is already running on port 8888, start this one on another port: `jupyter lab --port 8889`.

---

## 5. Everyday commands

| Task | Command |
| --- | --- |
| Is it running? | `docker ps` |
| Stop Neo4j | `docker stop neo4j-omgeving` |
| Start it again | `docker start neo4j-omgeving` |
| View logs | `docker logs neo4j-omgeving` |
| Open a Cypher shell | `docker exec -it neo4j-omgeving cypher-shell -u neo4j -p testpassword` |
| Delete the container (**data is lost unless you used a volume**) | `docker rm -f neo4j-omgeving` |

You can also start and stop the container from the **Containers** tab in Docker Desktop. Docker Desktop must be running for Neo4j to be reachable.

---

## 6. Troubleshooting

**`docker: command not found`**
Docker Desktop is not installed, or the terminal was opened before installing it. Open a new terminal window.

**`Cannot connect to the Docker daemon`**
Start Docker Desktop and wait for the whale icon to stop animating.

**`Conflict. The container name "/neo4j-omgeving" is already in use`**
The container already exists. Start it with `docker start neo4j-omgeving` instead of `docker run`.

**`Bind for 0.0.0.0:7474 failed: port is already allocated`**
Another Neo4j (e.g. Neo4j Desktop) is using the port. Stop it, or map different host ports, e.g. `-p 7475:7474 -p 7688:7687` (then use those ports in the browser and in Python).

**Login fails with the right password**
`NEO4J_AUTH` is only applied the very first time the database starts. If you changed it afterwards, either use the original password or remove and recreate the container (`docker rm -f neo4j-omgeving`, then step 2 again; without a volume this deletes the data).

**Python: `ServiceUnavailable` / `Couldn't connect to localhost:7687`**
The container is not running or is still starting. Check `docker ps` and `docker logs neo4j-omgeving`.

**Python: `ModuleNotFoundError: No module named 'neo4j'`**
The virtual environment is not active, or Jupyter is using a different kernel. Run `source .venv/bin/activate` (or pick the `.venv` interpreter/kernel in your editor).

**`Unknown function 'apoc.version'`**
The container was created without `NEO4J_PLUGINS='["apoc"]'`. Remove it and create it again with the command from step 2.

---

## 7. Load and query the graph (reproducible)

Everything needed to rebuild the graph from scratch lives in this folder, so a
teammate can reproduce it end to end:

| File | What it is |
| --- | --- |
| `build_graph.py` | parses a STOP/TPOD delivery package and loads the full graph |
| `constraints.cypher` | the schema (uniqueness constraints); applied automatically by `build_graph.py`, kept here as the canonical definition |
| `queries.cypher` | exploration and demo queries, one block each |

### Load

With the container running (steps 2–4) and the `.venv` active, from this folder:

```bash
python build_graph.py
```

The source files are committed in [`../source_data`](../source_data), which is
the default `--package` / `--boundary` location, so no arguments are needed.
Pass `--package` / `--boundary` only to load data from elsewhere.

On success it prints `loaded: 876 structure nodes, 597 regelteksten, ...`.
It is idempotent: the load uses `MERGE`, so re-running does not duplicate nodes.

### Query

Open `queries.cypher` and run one block at a time in Neo4j Browser
(copy a block, Cmd/Ctrl+Enter). Run them individually so node-returning queries
render as a graph rather than a table of statements.

To run a whole `.cypher` file headless (tabular output, good for a sanity check
in CI or a script):

```bash
docker exec -i neo4j-omgeving cypher-shell -u neo4j -p testpassword < queries.cypher
```

### Reset

To wipe the data and reload (constraints are kept):

```cypher
MATCH (n) DETACH DELETE n;
```

then re-run the load command above.

### Known gap

`Locatie` nodes are reference ids only — the geometry (GIO) files are not in the
current delivery package, so point/polygon → applicable-rules queries are not yet
possible. Everything else (structure, rules, activities, cross-references) is loaded.

---

## 8. Geographic boundary (RD / EPSG:28992)

`Maastricht-boundary-RD.geojson` is the municipal boundary polygon in Rijksdriehoek
coordinates. Every rule in this package applies to the whole municipality
(`ambtsgebied`), so attaching this one polygon to that Locatie node makes
"point -> which rules apply" possible at the municipal level.

The boundary loads automatically as part of `python build_graph.py` (it is the
default `--boundary`), so after a normal load the ambtsgebied `Locatie` node
already carries `geometry_geojson`, `srid` (28992) and a bounding box.

`spatial.py` does the point-in-polygon test (ray casting, no extra dependency)
and returns the rules that apply at an RD point:

```bash
python spatial.py 177088 318726     # a point in Maastricht
```

### Limitation

This is municipal-level only. Selecting rules by *zone* (a specific
gebiedsaanwijzing or bestemmingsvlak) needs the per-rule GIO geometries, which
are not in the current delivery package. Those would attach to additional
`Locatie` nodes the same way.
