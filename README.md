
# Tile2Net

![Python application](https://github.com/VIDA-NYU/tile2net/actions/workflows/test.yml/badge.svg)

<!-- HTML image formatting does not cooperate with Sphinx! -->
<!-- 
<p align="left">
<img src="./images/overview.png" alt="Overview" width="50%">
</p> -->

![Overview](./images/overview.jpg)


Tile2Net is an end-to-end tool for automated mapping of pedestrian infrastructure from aerial imagery. We trained a
semantic segmentation model to detect roads, sidewalk, crosswalk, and footpath from orthorectified imagery. The results
are then converted to geo-referenced polygons and finally a topologically interconnected centerline network is
generated. This work is as an important step towards a robust and open-source framework that enables comprehensive
digitization of pedestrian infrastructure, which we argue to be a key missing link to more accurate and reliable
pedestrian modeling and analyses. By offering low-cost solutions to create planimetric dataset describing pedestrian
environment, we enable cities with a tight budget to create datasets describing pedestrian environment which otherwise
would
not be possible at a comparable cost and time.

The model is presented in our [paper](https://www.sciencedirect.com/science/article/pii/S0198971523000133) published at
the *Computers Environment and Urban Systems* journal.

**Mapping the walk: A scalable computer vision approach for generating sidewalk network datasets from aerial imagery**\
Maryam Hosseini, Andres Sevtsuk, Fabio Miranda, Roberto M. Cesar Jr, Claudio T. Silva\
*Computers, Environment and Urban Systems, 101 (2023) 101950*

```
@article{hosseini2023mapping,
  title={Mapping the walk: A scalable computer vision approach for generating sidewalk network datasets from aerial imagery},
  author={Hosseini, Maryam and Sevtsuk, Andres and Miranda, Fabio and Cesar Jr, Roberto M and Silva, Claudio T},
  journal={Computers, Environment and Urban Systems},
  volume={101},
  pages={101950},
  year={2023},
  publisher={Elsevier}
}
```

## Updates:
- Tile2Net in Esri's Pedestrian Infrastructure Classification model: [ArcGIS Living Atlas](https://www.arcgis.com/home/item.html?id=c0d520baa30d4b47ab36232231c17875) 
- Tile2Net now supports Alameda County. You can find the list of supported regions [here](https://github.com/VIDA-NYU/tile2net/blob/main/BASICS.md#supported-regions)
- Tile2Net now supports the whole Oregon state. You can find the list of supported regions [here](https://github.com/VIDA-NYU/tile2net/blob/main/BASICS.md#supported-regions).
- Tile2Net was featured in [Planitizen](https://www.planetizen.com/news/2023/03/122206-mapping-sidewalks-improved-connectivity)! 
- Tile2Net was featured in [MIT News Spotlight](https://news.mit.edu/2023/open-source-tool-mapping-sidewalks-0315#:~:text=Now%20MIT%20researchers%2C%20along%20with,want%20to%20expand%20pedestrian%20infrastructure)!

## Getting Started

1. [What is New?](#what-is-new)
2. [Semantic Segmentation Requirements](#semantic-segmentation-requirements)
3. [Installation](#installation)
4. [Create Your First Project](#create-your-first-project)
5. [Run Our Example](#run-our-example)
6. [Running in the Terminal](#running-in-the-terminal)
7. [Running Interactively](#running-interactively)


## What is New?

This is the Beta Version release of our code, featuring updated API and improved model compared to our baseline and
published results.  
During this experimental release, we encourage and welcome your feedback to help us improve the tool before publishing
it as a PyPI and Conda package.

If your region of interest is not supported by our tool yet, but the high-resolution orthorectified tiles are publicly
available, you can add the information of your region together with the link to the tiles
under [this](https://github.com/VIDA-NYU/tile2net/issues/11) topic, and we will do our best to include that region to our
catalogue of supported regions.

Compared to our 2022 trained model (published in Feb. 2023), the semantic segmentation model is now trained on more
data, including Manhattan, making it more generalizable.  
Additionally, the network generation algorithm is now more generalized, not fine-tuned and fitted to any specific
datasets, and thus should perform better on cities outside the training domain.  
However, it is important to note that this also means the resulting network of Boston, Cambridge, NYC, and DC may differ
from models specifically fine-tuned and fitted to each city, as described in the paper.

Aside from that, we have updated the code to work with the most recent, stable version of PyTorch (2.0.0) and Shapely (
2.0.0), removing dependencies on apex and PyGeos.

## Semantic Segmentation Requirements

- Hardware: ==1 CUDA-enabled GPU for inference
- Software:  ***CUDA==11.7, Python==3.10.9, pytorch==2.0.0***

## Installation

It is highly recommended to create a virtual environment using either pip or conda to install Tile2Net and its
dependencies. You can clone the repository by running the commands:

```
git clone git@github.com:VIDA-NYU/tile2net.git
cd tile2net
```

Activate your virtual environment and install locally:

```
conda create --name testenv python=3.11
conda activate testenv
python -m pip install -e .
```

## Create Your First Project

In general, you will interact with the tool through two main components, `generate` and `inference`, both of which work
with the Raster module.
`generate`, as its name indicates, generates the project structure, downloads the weights and in case your region of
interest is supported by Tile2Net, also prepares the image tiles, and finally outputs a JSON text regarding the raster
specifications and the paths to the various resources. To know more about the basic concepts behind the tool, please
read [this.](https://github.com/VIDA-NYU/tile2net/blob/main/BASICS.md)

`inference` will then run the semantic segmentation model on the prepared tiles (or your own tile data which should be
prepared following the guidelines [here](https://github.com/VIDA-NYU/tile2net/blob/main/DATA_PREPARE.md)), detect roads,
sidewalks, footpaths, and crosswalks in your image data
and outputs the polygons and network data for your region. All output maps are in WGS 84 Web Mercator (espg:4326), to
best integrate with world-wide industry platforms such as Google Maps, Mapbox and Esri.

The weights used by the semantic segmentation model are available on
the [Google Drive](https://drive.google.com/drive/folders/1cu-MATHgekWUYqj9TFr12utl6VB-XKSu).

## Run Our Example

An [example.sh](https://github.com/VIDA-NYU/tile2net/blob/main/examples/example.sh) script is also available, which
will prompt the user for a path where the project should be created and saved. It will then download the tiles
corresponding to Boston Commons and Public Garden, creates larger tiles (stitched together) for inference, run
inference, create the polygon and network of this region. The sample area is small, just so you can test your
environment settings and GPU, and see what to look for.

To run that, open your terminal and run:

```
bash ./examples/example.sh 
```

## Running in the Terminal

To run the model in the terminal, you need to pass three main arguments:  _location_ -l, _name_ -n, and _output_dir_ -o.
There are other default parameters that you can modify, such as zoom level, tile_step, stitch_step, but the first three
are required to create a `Raster` object for your region.

Currently `python -m tile2net generate` and `python -m tile2net inference` are supported. The tool also supports
piping results e.g. `python -m tile2net generate <args> | python -m tile2net inference` to allow for the whole process to be
run in a single command.

To run the program in the terminal you can use the following command (replace <> with the appropriate information):

```
python -m tile2net generate -l <coordinate or address> -n <project name> -o <path to output directory>
```

Once that command is run and generate the respective files, use the command below to run inference and get the polygons
and network. You can find the path to your city_info JSON file from the output of generate command above, look for the
path printed in front of `INFO       Dumping to`:

```
python -m tile2net inference --city_info <path to your region info json>
```


Or, you can pip the whole process and run it using only one line of code! (note that in piping scenario, you don't need to pass `city_info` argument. 

```
python -m tile2net generate -l <coordinate or address> -n <project name> -o <path to output directory> | python -m tile2net inference
```

## Running Interactively

Tile2Net may also be run interactively in a Jupyter notebook by importing with `from tile2net import Raster`. To view
the project structure and paths, access the `Raster.project` attribute and subattributes.

The Raster instance can also be created from the city info json file with the method `Raster.from_info()`.

This tool is currently in early development and is not yet ready for production use. The API is subject to change.

To see more, there is an [inference.ipynb](https://github.com/VIDA-NYU/tile2net/blob/main/examples/inference.ipynb)
interactive notebook to demonstrate
how to run the inference process interactively.

## GPU requirement

Tile2Net requires a **CUDA-enabled GPU** for inference.  The model loads automatically from
Google Drive on first run.  If you are only running post-processing or the API, no GPU is
required.

## Dependency management

This fork uses **[uv](https://docs.astral.sh/uv/)** for dependency management:

```bash
uv sync                        # install all deps (CUDA PyTorch index is auto-configured)
python -m pip install -e .     # traditional alternative
```

Dependencies are pinned in `requirements-dev.txt`.  Python **3.10 or 3.11** only (`>=3.10,<3.12`).

## CRS convention

| Layer | Storage CRS | Notes |
|-------|-------------|-------|
| Tile download (WMS) | EPSG:3857 (Web Mercator) | Slippy-map tiles |
| Inference output | EPSG:4326 (WGS84) | Polygons + network shapefiles |
| Post-processing | EPSG:25830 (metric, UTM 30N) | All measurements, filtering, gap-fill, graph |
| DuckDB (polygons / network) | EPSG:4326 (WGS84) | GeoJSON-ready for the API |
| DuckDB (graph) | metric CRS | Node coords + edge lengths in metres |
| API responses | EPSG:4326 (WGS84) | GeoJSON FeatureCollections |

The metric CRS is controlled by the single `PostProcessConfig.metric_crs` parameter
(default `EPSG:25830` for Valencia / UTM Zone 30N).

---

## Post-Processing Pipeline

After inference produces raw polygons and a centreline network, the post-processor
cleans, filters, gap-fills, and annotates the output to produce a **weighted
NetworkX MultiGraph**.

### Programmatic usage

```python
from tile2net.postprocess import PedestrianPostProcessor, OSMViarioSource, PostProcessConfig

processor = PedestrianPostProcessor(
    polygon_path="polygons/final/final.shp",
    network_path="network/project-Network-XX/project-Network-XX.shp",
    viario=OSMViarioSource(cache_path="osm_cache.json"),
    config=PostProcessConfig(metric_crs="EPSG:25830"),
)
result = processor.run()        # → PostProcessResult (polygons, network, graph)
result.save("output_dir/")      # → shapefiles + graph.gpickle + graph.graphml
```

### Pipeline steps

1. Load & clean tile2net polygons (simplify, buffer open/close, area filter)
2. Fetch reference **viario** (OSM Overpass or official municipal data)
3. Drop polygons far from any viario edge (distance filter, 10 m default)
4. Fetch OSM **blocking mask** (buildings + leisure areas like stadiums)
5. Subtract blocking mask from polygons
6. **Gap-fill** — add footway centreline and road-edge sidewalk fills from OSM
7. Estimate polygon widths (`2·area / perimeter`)
8. Load tile2net network centreline
9. **Annotate edges** with width from nearby polygons (dual-radius search + node propagation)
10. Build `nx.MultiGraph` with `f_type`, `width`, `length`, `source`, `geometry` attributes

### Width assignment guarantee

Every edge is assigned a width via a three-layer fallback:

| Layer | Method | Typical coverage |
|-------|--------|-----------------|
| 1 — spatial | Find nearby polygon, apply hydraulic radius | ~92% |
| 2 — node propagation | Borrow mean width from incident edges at shared endpoints | +2% |
| 3 — global median | Assign median of all known widths | → 100% |

After step 3 every network edge and graph edge has a non-NaN width.

---

## DuckDB Storage

Outputs can be persisted to a local **DuckDB** database with spatial extension support.

### Tables

| Table | Columns | Purpose |
|-------|---------|---------|
| `tiles` | `project_name`, `tx`, `ty`, `zoom`, `image BLOB` | Orthophoto tile PNGs |
| `polygons` | `project_name`, `row_id`, `f_type`, `width`, `source`, `geom GEOMETRY` | Cleaned polygons (WGS84) |
| `network` | `project_name`, `row_id`, `f_type`, `width`, `width_source`, `length`, `source`, `geom GEOMETRY` | Annotated centreline network (WGS84) |
| `graph_nodes` | `project_name`, `node_id`, `x`, `y`, `geom GEOMETRY` | Graph nodes (metric CRS) |
| `graph_edges` | `project_name`, `from_node`, `to_node`, `edge_key`, `f_type`, `width`, `width_source`, `length`, `source`, `geom GEOMETRY` | Graph edges (metric CRS) |

The API also maintains a central **registry** database at `~/.tile2net/registry.db`:

| Table | Columns | Purpose |
|-------|---------|---------|
| `projects` | `name`, `location`, `zoom`, `crs`, `metric_crs`, `source`, `tile_step`, `stitch_step`, `viario_type`, `viario_url`, `output_dir`, `bbox_s`, `bbox_w`, `bbox_n`, `bbox_e`, `status`, `created_at`, `updated_at` | Project metadata registry |

### `width_source` provenance

Every network edge and graph edge includes a `width_source` column that tracks
**how** the width was assigned:

| Value | Meaning |
|-------|---------|
| `spatial` | Direct measurement from a nearby polygon (hydraulic radius) |
| `propagation` | Interpolated from incident edges at shared endpoint nodes |
| `median` | Global-median fallback for orphan leaf edges with no nearby data |

### Usage

```python
from tile2net.duckdb import get_project_db, write_polygons, write_network, write_graph
from tile2net.duckdb import read_polygons, read_network, read_graph, write_tiles, read_tile

con = get_project_db("path/to/project")

# Persist processor output
write_polygons(con, "valencia_centre", result.polygons)
write_network(con, "valencia_centre", result.network)
write_graph(con, "valencia_centre", result.graph)

# Read back
gdf_poly = read_polygons(con, "valencia_centre")   # GeoDataFrame (WGS84)
gdf_net  = read_network(con, "valencia_centre")    # GeoDataFrame (WGS84)
graph    = read_graph(con, "valencia_centre")       # nx.MultiGraph
```

---

## REST API

A FastAPI server wraps the full pipeline — project registration, async pipeline
execution, and GeoJSON queries.

### Start the server

```bash
# Using uv
uv run python -m tile2net.api

# Or the registered console script
tile2net-api
```

The API is available at `http://localhost:8000`.  Open `/docs` or `/redoc` for
the interactive OpenAPI documentation.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Health check |
| `POST` | `/projects/` | Register a new city project |
| `GET` | `/projects/` | List all projects |
| `GET` | `/projects/{name}` | Project detail + pipeline status |
| `PATCH` | `/projects/{name}` | Update project config |
| `DELETE` | `/projects/{name}` | Delete project and all data |
| `POST` | `/projects/{name}/pipeline` | Start pipeline (async) |
| `GET` | `/projects/{name}/pipeline/status` | Poll pipeline progress |
| `DELETE` | `/projects/{name}/pipeline` | Cancel running pipeline |
| `GET` | `/projects/{name}/polygons` | GeoJSON polygons (filter: `f_type`, `bbox`) |
| `GET` | `/projects/{name}/network` | GeoJSON network (filter: `f_type`, `bbox`, `min_width`) |
| `GET` | `/projects/{name}/graph` | Graph summary (nodes, edges, total length) |
| `GET` | `/projects/{name}/graph/edges` | GeoJSON graph edges |

### Quick start

```bash
# 1. Register a city (bbox or nominatim address)
curl -X POST http://localhost:8000/projects/ \
  -H "Content-Type: application/json" \
  -d '{"name":"valencia_centre","location":"39.469,-0.381,39.478,-0.369"}'

# 2. Run the pipeline (async — generate → infer → postprocess → persist)
curl -X POST http://localhost:8000/projects/valencia_centre/pipeline \
  -H "Content-Type: application/json" \
  -d '{"skip_generate":true}'

# 3. Poll until status == "completed"
curl http://localhost:8000/projects/valencia_centre/pipeline/status | jq .status

# 4. Query results
curl "http://localhost:8000/projects/valencia_centre/polygons?f_type=sidewalk&limit=5"
curl "http://localhost:8000/projects/valencia_centre/network?min_width=3.0"
curl "http://localhost:8000/projects/valencia_centre/graph"
```

### Pipeline stages

The `POST /projects/{name}/pipeline` endpoint runs these stages in order:

| Stage | Progress | What happens |
|-------|----------|-------------|
| `generating` | 0% → 33% | Downloads slippy-map tiles from the configured source, stitches them |
| `inferring` | 33% → 66% | Runs HRNet+OCRNet semantic segmentation on the stitched tiles |
| `postprocessing` | 66% → 100% | Cleans polygons, gap-fills via OSM, estimates widths, builds graph, persists to DuckDB |

Cancellation is **best-effort** — the current stage completes before the pipeline stops.

---

## Running Tests

```bash
# Post-processing + DuckDB + API tests (needs test data on disk)
uv run pytest -s tests/test_postprocess.py tests/test_api.py -v

# Namespace unit test (no GPU required)
uv run pytest -s tests/test_namespace.py

# GPU-required integration tests
uv run pytest -s tests/test_remote.py    # --remote mode
uv run pytest -s tests/test_local.py     # --local mode
```

Tests output to stdout; always pass `-s`.

