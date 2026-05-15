#!/usr/bin/env python3
"""Render a detailed map of a small Valencia area with walking network
and tile2net polygon geometries over a basemap.

Shows:
- Network edges colored by width (thin=blue → wide=red)
- Tile2net polygons (sidewalk=red, crosswalk=blue, road=green) semi-transparent
- ESRI World Imagery basemap
"""

import pickle, warnings
import numpy as np
import geopandas as gpd
import pandas as pd
import networkx as nx
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable
from pathlib import Path
from shapely.geometry import box
import contextily as ctx

warnings.filterwarnings("ignore")

# ---- Config ---------------------------------------------------------------
AREA_BBOX = (39.470, -0.380, 39.477, -0.370)  # Valencia city centre (S,W,N,E)
METRIC_CRS = "EPSG:25830"
OUTPUT_PNG = "/media/M2_disk/roger/tile2net/tile2net/valencia_detail.png"
GRAPH_PATH = "/home/roger/.tile2net/projects/valencia_full_z20_grid/valencia_osm_graph.gpickle"
POLY_ROOT = "/home/roger/.tile2net/projects/valencia_full_z20_grid"

print(f"Area: S={AREA_BBOX[0]:.4f} W={AREA_BBOX[1]:.4f} N={AREA_BBOX[2]:.4f} E={AREA_BBOX[3]:.4f}")
area_box_wgs = box(AREA_BBOX[1], AREA_BBOX[0], AREA_BBOX[3], AREA_BBOX[2])

# ---- Load graph, crop to area ----------------------------------------------
print("Loading graph...")
with open(GRAPH_PATH, "rb") as f:
    G = pickle.load(f)

# Convert area bbox to metric CRS
area_gdf = gpd.GeoDataFrame(geometry=[area_box_wgs], crs="EPSG:4326").to_crs(METRIC_CRS)
area_box_metric = area_gdf.geometry.iloc[0]

# Extract edges in area
edges = []
for u, v, k, d in G.edges(data=True, keys=True):
    geom = d.get("geometry")
    if geom is None or geom.is_empty:
        continue
    if geom.intersects(area_box_metric):
        edges.append({
            "f_type": d.get("f_type", "?"),
            "width": float(d.get("width", 0)),
            "length": float(d.get("length", 0)),
            "highway": d.get("highway", ""),
            "geometry": geom,
        })

gdf_edges = gpd.GeoDataFrame(edges, crs=METRIC_CRS)
print(f"  Edges in area: {len(gdf_edges):,}")

# ---- Load polygons, crop to area -------------------------------------------
print("Loading tile2net polygons...")
poly_dfs = []
for cell_dir in sorted(Path(POLY_ROOT).glob("val_g20_r*c*")):
    shp = cell_dir / "polygons" / "polygons.shp"
    if shp.exists():
        df = gpd.read_file(shp)
        if len(df) > 0:
            # Crop to area (in metric CRS)
            df = df.to_crs(METRIC_CRS)
            df = df[df.intersects(area_box_metric)]
            if len(df) > 0:
                poly_dfs.append(df)

all_polys = pd.concat(poly_dfs, ignore_index=True) if poly_dfs else gpd.GeoDataFrame()
all_polys = all_polys.to_crs(METRIC_CRS)
print(f"  Polygons in area: {len(all_polys):,}")

# ---- Setup plot ------------------------------------------------------------
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(30, 14), dpi=150)

for ax, title in [(ax1, "Network edges (colored by width)"),
                   (ax2, "Tile2net polygons + network")]:

    # Basemap
    try:
        ctx.add_basemap(ax, source=ctx.providers.Esri.WorldImagery,
                        zoom=18, attribution=False, crs=METRIC_CRS)
    except Exception:
        ax.set_facecolor("#1a1a2e")

    # Set extent to the area bbox in metric CRS
    ax.set_xlim(area_box_metric.bounds[0], area_box_metric.bounds[2])
    ax.set_ylim(area_box_metric.bounds[1], area_box_metric.bounds[3])
    ax.set_title(title, fontsize=12, pad=8)
    ax.set_axis_off()

# ---- Left panel: network edges by width ------------------------------------
norm = Normalize(vmin=2.4, vmax=8.0)
cmap = plt.cm.coolwarm_r  # blue=thin, red=wide

gdf_walk = gdf_edges[gdf_edges["f_type"].str.contains("footway|path|pedestrian|steps|living_street")]
gdf_road = gdf_edges[~gdf_edges.index.isin(gdf_walk.index)]

# Draw road-with-sidewalk edges (light grey, thinner)
gdf_road.plot(ax=ax1, color="#888888", linewidth=0.3, alpha=0.5)
# Draw walkable edges colored by width
for _, row in gdf_walk.iterrows():
    color = cmap(norm(row["width"]))
    ax1.plot(*row.geometry.xy, color=color, linewidth=0.8, alpha=0.85)

# Colorbar
sm = ScalarMappable(norm=norm, cmap=cmap)
cbar = fig.colorbar(sm, ax=ax1, shrink=0.6, pad=0.02)
cbar.set_label("Edge width (m)", fontsize=10)

# Legend
legend_el = [
    Line2D([0], [0], color=cmap(norm(2.4)), linewidth=2, label="Narrow (2.4m)"),
    Line2D([0], [0], color=cmap(norm(5.0)), linewidth=2, label="Medium (5m)"),
    Line2D([0], [0], color=cmap(norm(8.0)), linewidth=2, label="Wide (8m+)"),
    Line2D([0], [0], color="#888888", linewidth=2, label="Road + sidewalk"),
]
ax1.legend(handles=legend_el, loc="lower right", fontsize=8, framealpha=0.8)

# ---- Right panel: polygons + network ---------------------------------------
# Draw polygons with f_type colors
poly_colors = {"sidewalk": "#ff4444", "crosswalk": "#4444ff", "road": "#44ff44"}
for f_type, color in poly_colors.items():
    subset = all_polys[all_polys["f_type"] == f_type]
    if len(subset) > 0:
        subset.plot(ax=ax2, color=color, alpha=0.3, edgecolor="none", linewidth=0)

# Draw network edges on top (black)
gdf_edges.plot(ax=ax2, color="#222222", linewidth=0.5, alpha=0.7)

# Legend for polygons
poly_legend = [Patch(color=c, alpha=0.3, label=ft) for ft, c in poly_colors.items()]
poly_legend.append(Line2D([0], [0], color="#222222", linewidth=1.5, label="Walking network"))
ax2.legend(handles=poly_legend, loc="lower right", fontsize=8, framealpha=0.8)

# ---- Save ------------------------------------------------------------------
plt.suptitle(
    f"Valencia City Centre — Walking Network + tile2net Polygons\n"
    f"{len(gdf_edges):,} edges, {len(all_polys):,} polygons",
    fontsize=14, y=0.98,
)
fig.savefig(OUTPUT_PNG, dpi=150, bbox_inches="tight", pad_inches=0.3, facecolor="white")
plt.close()
print(f"\nSaved: {OUTPUT_PNG}")
