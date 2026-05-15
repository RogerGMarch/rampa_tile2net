#!/usr/bin/env python3
"""Render the Valencia pedestrian graph over a map basemap as a PNG."""

import pickle
import warnings
import numpy as np
import geopandas as gpd
import networkx as nx
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from shapely.geometry import LineString
import contextily as ctx

# ---- Load graph -------------------------------------------------------------
print("Loading graph...")
with open("/home/roger/.tile2net/projects/valencia_full_z20_grid/valencia_osm_graph.gpickle", "rb") as f:
    G = pickle.load(f)
print(f"  {G.number_of_nodes():,} nodes, {G.number_of_edges():,} edges")

# ---- Extract edges as GeoDataFrame ------------------------------------------
print("Extracting edges...")
edges = []
for u, v, key, data in G.edges(data=True, keys=True):
    geom = data.get("geometry")
    if geom is None or geom.is_empty:
        continue
    ft = data.get("f_type", "unknown")
    edges.append({
        "f_type": ft,
        "width": data.get("width", 0.0),
        "length": data.get("length", 0.0),
        "geometry": geom,
    })

gdf = gpd.GeoDataFrame(edges, crs="EPSG:25830")
print(f"  {len(gdf):,} edges with geometry")

# ---- Reproject to web mercator for basemap ----------------------------------
print("Reprojecting to EPSG:3857 for basemap...")
gdf = gdf.to_crs("EPSG:3857")

# ---- Setup plot -------------------------------------------------------------
warnings.filterwarnings("ignore")

# Color map by f_type
type_colors = {
    "osm_footway": "#e41a1c",
    "osm_pedestrian": "#377eb8",
    "osm_path": "#4daf4a",
    "osm_steps": "#984ea3",
    "osm_living_street": "#ff7f00",
    "osm_service": "#a65628",
    "osm_residential": "#f781bf",
    "osm_tertiary": "#ffff33",
    "osm_secondary": "#a6cee3",
    "osm_primary": "#fb9a99",
    "osm_trunk": "#b2df8a",
    "osm_unclassified": "#cab2d6",
}
default_color = "#cccccc"

fig, ax = plt.subplots(figsize=(24, 18), dpi=150)

# Plot edges grouped by f_type
f_types_seen = set()
for f_type in sorted(gdf["f_type"].unique()):
    subset = gdf[gdf["f_type"] == f_type]
    color = type_colors.get(f_type, default_color)
    alpha = 0.6 if f_type == "sidewalk" else 0.7
    linewidth = 0.15 if f_type in ("sidewalk", "sidewalk_connection") else 0.3
    subset.plot(
        ax=ax,
        color=color,
        linewidth=linewidth,
        alpha=alpha,
        label=f_type,
    )
    f_types_seen.add(f_type)

# ---- Basemap ----------------------------------------------------------------
print("Adding basemap (this may take a moment)...")
try:
    ctx.add_basemap(
        ax,
        source=ctx.providers.Esri.WorldImagery,
        zoom=14,
        attribution=False,
    )
except Exception as e:
    print(f"  Basemap unavailable: {e}")
    ax.set_facecolor("#1a1a2e")

# ---- Legend -----------------------------------------------------------------
legend_elements = []
for f_type, color in type_colors.items():
    if f_type in f_types_seen:
        legend_elements.append(
            Line2D([0], [0], color=color, linewidth=2, label=f_type)
        )
ax.legend(
    handles=legend_elements,
    loc="lower left",
    fontsize=8,
    framealpha=0.8,
    title="Edge type",
    title_fontsize=9,
)

# ---- Title & cleanup --------------------------------------------------------
ax.set_title(
    "Valencia Walking Network — OSM + tile2net widths\n"
    f"{G.number_of_nodes():,} nodes  ·  {G.number_of_edges():,} edges  ·  "
    f"{len(f_types_seen)} edge types",
    fontsize=14,
    pad=12,
)
ax.set_axis_off()

# ---- Save -------------------------------------------------------------------
outpath = "/media/M2_disk/roger/tile2net/tile2net/valencia_walking_network.png"
fig.savefig(outpath, dpi=150, bbox_inches="tight", pad_inches=0.2, facecolor="white")
print(f"\nSaved: {outpath}")
plt.close()
