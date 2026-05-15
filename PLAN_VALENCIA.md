# Build Full Valencia Pedestrian Graph — Zoom 20

## Overview

Build a weighted NetworkX MultiGraph for the full city of Valencia, Spain at zoom 20
by splitting the municipal bbox into a 6×6 grid, processing each cell independently,
and merging sub-graphs.

## Area

- **Location**: `Valencia, Spain`
- **Source**: Nominatim via osmnx (`ox.geocode_to_gdf`)
- **Expected bbox**: ~S=39.278, W=-0.433, N=39.567, E=-0.272 (~20km × 32km)

## Grid

- 6×6 = 36 cells
- Each cell: ~3.3km × 5.3km, ~20k base tiles, ~1270 stitched tiles (stitch_step=4)

## Pipeline per cell

1. `Raster(location=cell_bbox, zoom=20, source="esri_world", output_dir=...)` — tile grid
2. `raster.generate(step=4)` — download + stitch tiles
3. `raster.inference()` — GPU inference via subprocess (`python -m tile2net inference`)
4. `PedestrianPostProcessor(...).run()` — clean, gap-fill, annotate widths, build graph
5. Cell result saved as `.gpickle` + `.graphml`

## Checkpoints

File: `~/.tile2net/projects/valencia_full_z20_grid/checkpoint.json`

```json
{
  "bbox": [39.278, -0.433, 39.567, -0.272],
  "grid_size": 6,
  "zoom": 20,
  "stitch_step": 4,
  "completed": [[0,0], [0,1]],
  "in_progress": {"row": 0, "col": 2, "step": "inference"},
  "cell_graphs": {}
}
```

On restart, loads checkpoint → skips completed cells → resumes `in_progress` if set.

### Step states in `in_progress`

| step | meaning | resume action |
|------|---------|---------------|
| `generate` | tile download/stitch started | re-run generate for that cell |
| `inference` | GPU inference started | re-run inference (safe to re-run — overwrites output) |
| `postprocess` | post-processing started | re-run postprocessing |

## ESRI Rate Limiting

- Tile downloads via `Raster.download()` use `ThreadPoolExecutor` (default max workers)
- ESRI tolerates ~100 req/s for World Imagery
- No additional throttling needed for per-cell downloads (~20k tiles × 0.2s / 32 threads ≈ 2 min/cell)

## Merge

- `nx.compose_all()` over 36 sub-graphs
- Deduplicate overlapping edges at cell boundaries (within 2m spatial tolerance)
- Save `valencia_full_z20.gpickle` + `valencia_full_z20.graphml`

## Execution

```bash
screen -S valencia_graph -L -Logfile valencia_build.log
uv run python scripts/build_valencia_full.py
```

## Estimated Runtime

- ~2 min/cell for tile download
- ~5-15 min/cell for GPU inference (depends on model + tile count)
- ~2-5 min/cell for postprocessing
- Total per cell: ~10-25 min
- Total for 36 cells: ~6-15 hours
