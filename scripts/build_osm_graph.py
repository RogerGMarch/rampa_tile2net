#!/usr/bin/env python3
"""Build OSM-based pedestrian graph enriched with tile2net polygon widths.

Uses OSMnx for proper graph topology (ways split at all intersections).
"""

import sys, os, warnings, pickle
from pathlib import Path
import numpy as np
import geopandas as gpd
import pandas as pd
import networkx as nx
from shapely.geometry import Point
from scipy.spatial import KDTree

warnings.filterwarnings("ignore")
os.environ["USE_PYGEOS"] = "1"

# ---- Config ---------------------------------------------------------------
OUTPUT_ROOT = Path.home() / ".tile2net" / "projects" / "valencia_full_z20_grid"
METRIC_CRS = "EPSG:25830"

# Valencia bbox (S, W, N, E)
VALENCIA_BBOX = (39.2784496, -0.4325512, 39.566609, -0.2725205)
# OSMnx expects (N, S, E, W) or (S, N, E, W)?

# ---- STEP 1: Load all tile2net polygons with widths -----------------------
print("[1/3] Loading tile2net polygon widths...")

poly_dfs = []
for cell_dir in sorted(OUTPUT_ROOT.glob("val_g20_r*c*")):
    shp = cell_dir / "polygons" / "polygons.shp"
    if shp.exists():
        df = gpd.read_file(shp)
        if len(df) > 0:
            poly_dfs.append(df)

all_polygons = pd.concat(poly_dfs, ignore_index=True)
all_polygons = all_polygons.to_crs(METRIC_CRS)
print(f"  {len(all_polygons):,} polygons, mean width={all_polygons['width'].mean():.2f}m")

sindex = all_polygons.sindex

# For KD-Tree: centroids
poly_centroids = np.array([[g.centroid.x, g.centroid.y] for g in all_polygons.geometry])
poly_tree = KDTree(poly_centroids)
poly_widths = all_polygons["width"].values

# ---- STEP 2: Get OSM graph via OSMnx -------------------------------------
print("\n[2/3] Downloading OSM pedestrian graph via OSMnx...")
import osmnx as ox

# Download within bbox — filter to pedestrian-relevant tags
# OSMnx bbox: (left, bottom, right, top) in WGS84
bbox = (VALENCIA_BBOX[1], VALENCIA_BBOX[0], VALENCIA_BBOX[3], VALENCIA_BBOX[2])

G = ox.graph.graph_from_bbox(
    bbox=bbox,
    network_type="walk",
    simplify=True,
    retain_all=False,
    truncate_by_edge=True,
)

print(f"  OSM graph: {G.number_of_nodes():,} nodes, {G.number_of_edges():,} edges")

# Convert to undirected for analysis
G_undir = nx.Graph(G)
cc = list(nx.connected_components(G_undir))
cc.sort(key=len, reverse=True)
print(f"  Connected components: {len(cc)}")
print(f"  Largest component: {len(cc[0]):,} nodes ({len(cc[0])/G_undir.number_of_nodes()*100:.1f}%)")

# ---- STEP 3: Annotate edges with tile2net polygon widths ------------------
print("\n[3/3] Annotating OSM edges with tile2net polygon widths...")

# Project node coords to metric CRS
nodes_gdf, edges_gdf = ox.graph_to_gdfs(G, nodes=True, edges=True)
edges_gdf = edges_gdf.to_crs(METRIC_CRS)
nodes_gdf = nodes_gdf.to_crs(METRIC_CRS)
print(f"  Projected to {METRIC_CRS}")

# For each edge, find mean width from nearby polygons
def fast_edge_width_at_point(x: float, y: float) -> tuple[float, str]:
    """Get (mean width, source) from nearby polygons at a given metric coordinate."""
    query_pt = np.array([[x, y]])
    # Search within 5m
    dists, indices = poly_tree.query(query_pt, k=min(20, len(poly_widths)),
                                       distance_upper_bound=5.0)
    valid = [i for d, i in zip(dists[0], indices[0])
             if d != float('inf') and i < len(poly_widths)]
    if not valid:
        # Try wider search (30m)
        dists, indices = poly_tree.query(query_pt, k=min(50, len(poly_widths)),
                                           distance_upper_bound=30.0)
        valid = [i for d, i in zip(dists[0], indices[0])
                 if d != float('inf') and i < len(poly_widths)]
    if not valid:
        return 2.4, "missing"
    wvals = poly_widths[valid]
    return float(np.clip(np.median(wvals), 2.4, 12.0)), "tile2net_spatial"

# Prepare node coordinates in metric CRS for graph rebuild
node_id_to_pt = {}
for idx, row in nodes_gdf.iterrows():
    pt = row.geometry
    node_id_to_pt[idx] = (round(pt.x, 6), round(pt.y, 6))

# Build annotated graph
H = nx.MultiGraph()
annotated = 0
for u, v, k, d in G.edges(data=True, keys=True):
    # Get node coordinates in metric CRS
    nu = node_id_to_pt.get(u)
    nv = node_id_to_pt.get(v)
    if nu is None and u in nodes_gdf.index:
        nu = (round(nodes_gdf.loc[u].geometry.x, 6), round(nodes_gdf.loc[u].geometry.y, 6))
        node_id_to_pt[u] = nu
    if nv is None and v in nodes_gdf.index:
        nv = (round(nodes_gdf.loc[v].geometry.x, 6), round(nodes_gdf.loc[v].geometry.y, 6))
        node_id_to_pt[v] = nv
    if nu is None or nv is None:
        continue

    # Compute edge midpoint in metric CRS for width lookup
    mid_x = (nu[0] + nv[0]) / 2
    mid_y = (nu[1] + nv[1]) / 2

    # Compute width from nearest polygons
    width, width_source = fast_edge_width_at_point(mid_x, mid_y)

    hw = d.get("highway", "unknown")
    if isinstance(hw, list):
        hw = hw[0]

    f_type = f"osm_{hw}"

    # Get edge geometry in metric CRS
    import shapely.ops
    from pyproj import Transformer
    edge_geom = d.get("geometry")
    if edge_geom is not None:
        tf = Transformer.from_crs("EPSG:4326", METRIC_CRS, always_xy=True)
        edge_geom_metric = shapely.ops.transform(tf.transform, edge_geom)
    else:
        from shapely.geometry import LineString
        edge_geom_metric = LineString([Point(nu), Point(nv)])

    base_attrs = {
        "f_type": f_type,
        "width": float(width),
        "width_source": width_source,
        "source": "osm",
        "highway": hw,
        "length": float(d.get("length", edge_geom_metric.length)),
        "name": str(d.get("name", "")),
        "osm_id": str(d.get("osmid", "")),
        "geometry": edge_geom_metric,
    }

    if not H.has_node(nu):
        H.add_node(nu, x=nu[0], y=nu[1], geometry=Point(nu))
    if not H.has_node(nv):
        H.add_node(nv, x=nv[0], y=nv[1], geometry=Point(nv))

    H.add_edge(nu, nv, key=k, **base_attrs)
    annotated += 1

    if annotated % 10000 == 0:
        print(f"  Annotated: {annotated:,} / {G.number_of_edges():,}")

print(f"  Annotated graph: {H.number_of_nodes():,} nodes, {H.number_of_edges():,} edges")

# ---- Connectivity check ---------------------------------------------------
H_simple = nx.Graph(H)
cc2 = list(nx.connected_components(H_simple))
cc2.sort(key=len, reverse=True)
print(f"\n  Connected components: {len(cc2)}")
print(f"  Largest: {len(cc2[0]):,} nodes ({len(cc2[0])/H_simple.number_of_nodes()*100:.1f}%)")
top5 = sum(len(c) for c in cc2[:5])
print(f"  Top 5 cover: {top5:,} nodes ({top5/H_simple.number_of_nodes()*100:.1f}%)")
small = sum(1 for c in cc2 if len(c) <= 5)
print(f"  Tiny (<=5 nodes): {small} components")

# Edge types
from collections import Counter
f_types = Counter()
for u,v,k,d in H.edges(data=True, keys=True):
    f_types[d.get("f_type", "?")] += 1
print(f"\n  Edge types:")
for ft, cnt in f_types.most_common():
    print(f"    {ft}: {cnt:,}")

# ---- Save -----------------------------------------------------------------
output_gpickle = OUTPUT_ROOT / "valencia_osm_graph.gpickle"
output_graphml = OUTPUT_ROOT / "valencia_osm_graph.graphml"

with open(output_gpickle, "wb") as f:
    pickle.dump(H, f, protocol=pickle.HIGHEST_PROTOCOL)
print(f"\nSaved: {output_gpickle}")

# GraphML
gm = nx.MultiGraph()
for n, ndata in H.nodes(data=True):
    dd = dict(ndata)
    if "geometry" in dd:
        dd["geometry"] = dd["geometry"].wkt
    gm.add_node(n, **dd)
for u, v, k, edata in H.edges(data=True, keys=True):
    dd = dict(edata)
    if "geometry" in dd and dd["geometry"] is not None:
        dd["geometry"] = dd["geometry"].wkt
    if "name" in dd and isinstance(dd["name"], list):
        dd["name"] = ",".join(filter(None, dd["name"]))
nx.write_graphml(gm, str(output_graphml), named_key_ids=True)
print(f"Saved: {output_graphml}")
