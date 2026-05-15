#!/usr/bin/env python3
"""Fix graph fragmentation by snapping nearby endpoints and rebuilding."""

import pickle, sys
import numpy as np
import networkx as nx
from collections import defaultdict
from shapely.geometry import Point
from scipy.spatial import KDTree
import warnings
warnings.filterwarnings("ignore")

INPUT = "/home/roger/.tile2net/projects/valencia_full_z20_grid/valencia_full_z20.gpickle"
SNAP_TOLERANCE = 1.0   # metres — snap endpoints within this distance
GRID_SEARCH = 5.0       # metres — search radius for K-D tree query

print("Loading graph...")
with open(INPUT, "rb") as f:
    G = pickle.load(f)
print(f"  {G.number_of_nodes():,} nodes, {G.number_of_edges():,} edges")

# ---- STEP 1: Before stats ----------------------------------------------------
G_simple = nx.Graph(G)
cc_before = list(nx.connected_components(G_simple))
cc_before.sort(key=len, reverse=True)
print(f"\nBefore:")
print(f"  Components: {len(cc_before)}")
print(f"  Largest: {len(cc_before[0]):,} nodes ({len(cc_before[0])/G_simple.number_of_nodes()*100:.1f}%)")

# ---- STEP 2: Build K-D tree of all nodes -------------------------------------
all_nodes = list(G.nodes())
coords = np.array([[n[0], n[1]] for n in all_nodes])
tree = KDTree(coords)

print(f"\nKD-Tree built with {len(all_nodes):,} nodes")

# ---- STEP 3: Find endpoints to snap ------------------------------------------
# Focus on degree-1 nodes (dead ends that should connect to nearby nodes)
endpoints = [(all_nodes[i], i) for i, n in enumerate(all_nodes) if G.degree(n) == 1]
print(f"Degree-1 endpoints: {len(endpoints):,}")

# For each endpoint, find nearest non-same node
merge_map = {}  # old_node → new_node (snap target)

for node, idx in endpoints:
    # Find neighbors within GRID_SEARCH
    dists, indices = tree.query(coords[idx], k=min(50, len(coords)), distance_upper_bound=GRID_SEARCH)
    for d, j in zip(dists, indices):
        if j >= len(coords):
            continue
        target = all_nodes[j]
        if target == node:
            continue
        if d > 0 and d < SNAP_TOLERANCE:
            # Found a nearby node — snap to it
            merge_map[node] = target
            break

print(f"Endpoints to snap: {len(merge_map):,}")

# ---- STEP 4: Build new graph -------------------------------------------------
print(f"\nBuilding merged graph...")
H = nx.MultiGraph()
self_loops = 0
for u, v, key, data in G.edges(data=True, keys=True):
    cu = merge_map.get(u, u)
    cv = merge_map.get(v, v)

    if cu == cv:
        self_loops += 1
        continue

    if not H.has_node(cu):
        H.add_node(cu, x=cu[0], y=cu[1], geometry=Point(cu))
    if not H.has_node(cv):
        H.add_node(cv, x=cv[0], y=cv[1], geometry=Point(cv))

    H.add_edge(cu, cv, key=key, **data)

print(f"  New graph: {H.number_of_nodes():,} nodes, {H.number_of_edges():,} edges")
print(f"  Self-loops removed: {self_loops:,}")

# ---- STEP 5: After stats -----------------------------------------------------
print(f"\nAfter:")
H_simple = nx.Graph(H)
cc_after = list(nx.connected_components(H_simple))
cc_after.sort(key=len, reverse=True)
print(f"  Components: {len(cc_after)}")
print(f"  Largest: {len(cc_after[0]):,} nodes ({len(cc_after[0])/H_simple.number_of_nodes()*100:.1f}%)")
top5 = sum(len(c) for c in cc_after[:5])
print(f"  Top 5 cover: {top5:,} nodes ({top5/H_simple.number_of_nodes()*100:.1f}%)")
print(f"  Reduction: {len(cc_before) - len(cc_after):,} fewer components")

# ---- STEP 6: Save ------------------------------------------------------------
output = "/home/roger/.tile2net/projects/valencia_full_z20_grid/valencia_full_z20_fixed.gpickle"
with open(output, "wb") as f:
    pickle.dump(H, f, protocol=pickle.HIGHEST_PROTOCOL)

# GraphML with WKT
graphml = "/home/roger/.tile2net/projects/valencia_full_z20_grid/valencia_full_z20_fixed.graphml"
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
    gm.add_edge(u, v, key=k, **dd)
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    nx.write_graphml(gm, graphml, named_key_ids=True)

print(f"Saved: {output}")
print(f"Saved: {graphml}")
