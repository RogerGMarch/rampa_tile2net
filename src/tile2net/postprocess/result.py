"""PostProcessResult — container for PedestrianPostProcessor outputs."""
from __future__ import annotations

import dataclasses
import pickle
from pathlib import Path

import geopandas as gpd
import networkx as nx


@dataclasses.dataclass
class PostProcessResult:
    """Holds all outputs of :class:`~tile2net.postprocess.PedestrianPostProcessor`.

    Attributes
    ----------
    polygons:
        Cleaned sidewalk/crosswalk/road polygons.
        Columns: ``f_type``, ``width`` (metres), ``source``, ``geometry``.
    network:
        Pedestrian centerline network.
        Columns: ``f_type``, ``width`` (metres), ``width_source`` (``spatial``,
        ``propagation``, or ``median``), ``length`` (metres),
        ``source``, ``geometry``.
    graph:
        NetworkX ``MultiGraph`` built from *network*.
        Node attributes: ``x``, ``y``, ``geometry`` (Shapely Point).
        Edge attributes: ``f_type``, ``width``, ``width_source``, ``length``, ``source``,
        ``geometry`` (Shapely LineString).
    """

    polygons: gpd.GeoDataFrame
    network: gpd.GeoDataFrame
    graph: nx.MultiGraph

    def save(self, output_dir: str | Path) -> None:
        """Write outputs to *output_dir*.

        Creates::

            output_dir/
                polygons/polygons.shp     – cleaned polygon shapefile
                network/network.shp       – annotated network shapefile
                graph.gpickle             – NetworkX graph (full fidelity)
                graph.graphml             – NetworkX graph (geometry as WKT)
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        poly_dir = out / "polygons"
        poly_dir.mkdir(exist_ok=True)
        self.polygons.to_file(poly_dir / "polygons.shp")

        net_dir = out / "network"
        net_dir.mkdir(exist_ok=True)
        self.network.to_file(net_dir / "network.shp")

        with open(out / "graph.gpickle", "wb") as fh:
            pickle.dump(self.graph, fh, protocol=pickle.HIGHEST_PROTOCOL)

        self._write_graphml(out / "graph.graphml")

    def _write_graphml(self, path: Path) -> None:
        """Write graph with geometry serialised as WKT strings."""
        G = self.graph.copy()
        for u, v, k, data in G.edges(data=True, keys=True):
            if data.get("geometry") is not None:
                G[u][v][k]["geometry"] = data["geometry"].wkt
        for node, data in G.nodes(data=True):
            if data.get("geometry") is not None:
                G.nodes[node]["geometry"] = data["geometry"].wkt
        nx.write_graphml(G, str(path), named_key_ids=True)
