"""Reads graphify-out/graph_annotated.json and provides graph navigation queries."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class GraphNode:
    id: str
    label: str
    file_type: str
    source_file: str
    source_location: str = ""      # e.g. "L15" — line within source_file
    norm_label: str = ""
    origin: str = ""               # "ast" | None(semantic)
    community: int | None = None
    degree: int = 0                # incident-edge count; graphify's importance metric
    codemapper: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    source: str
    target: str
    relation: str
    confidence: str = "EXTRACTED"
    confidence_score: float = 1.0


class GraphIndex:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._nodes: dict[str, GraphNode] = {}
        self._adj: dict[str, list[GraphEdge]] = {}   # outgoing edges per node id
        self._radj: dict[str, list[GraphEdge]] = {}  # incoming edges per node id
        self._loaded = False

    def load(self) -> None:
        path = self.root / "graphify-out" / "graph_annotated.json"
        if not path.exists():
            path = self.root / "graphify-out" / "graph.json"
        if not path.exists():
            raise FileNotFoundError(
                f"No graph found at {path.parent}. Run 'codemapper2 build' first."
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        self._parse(data)
        self._loaded = True

    def _parse(self, data: dict) -> None:
        # NetworkX node-link format: {"nodes": [...], "links": [...]}
        for raw_node in data.get("nodes", []):
            node_id = str(raw_node.get("id", ""))
            node = GraphNode(
                id=node_id,
                label=str(raw_node.get("label", raw_node.get("name", node_id))),
                file_type=str(raw_node.get("file_type", raw_node.get("type", "code"))),
                source_file=str(raw_node.get("source_file", raw_node.get("file", ""))),
                source_location=str(raw_node.get("source_location", "")),
                norm_label=str(raw_node.get("norm_label", "")),
                origin=str(raw_node.get("_origin") or ""),
                community=raw_node.get("community"),
                codemapper=raw_node.get("codemapper", {}),
                raw=raw_node,
            )
            self._nodes[node_id] = node
            self._adj[node_id] = []
            self._radj[node_id] = []

        for raw_edge in data.get("links", data.get("edges", [])):
            edge = GraphEdge(
                source=str(raw_edge.get("source", "")),
                target=str(raw_edge.get("target", "")),
                relation=str(raw_edge.get("relation", raw_edge.get("type", ""))),
                confidence=str(raw_edge.get("confidence", "EXTRACTED")),
                confidence_score=float(raw_edge.get("confidence_score", 1.0)),
            )
            if edge.source in self._adj:
                self._adj[edge.source].append(edge)
            if edge.target in self._radj:
                self._radj[edge.target].append(edge)

        # Degree = incident-edge count (graphify's importance metric for god nodes).
        for node_id, node in self._nodes.items():
            node.degree = len(self._adj.get(node_id, [])) + len(self._radj.get(node_id, []))

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def get_node(self, node_id: str) -> GraphNode | None:
        self._ensure_loaded()
        return self._nodes.get(node_id)

    def find_by_label(self, name: str) -> list[GraphNode]:
        self._ensure_loaded()
        name_lower = name.lower()
        return [n for n in self._nodes.values() if name_lower in n.label.lower()]

    def find_by_file(self, file_path: str) -> list[GraphNode]:
        self._ensure_loaded()
        fp = file_path.replace("\\", "/")
        return [n for n in self._nodes.values() if fp in n.source_file.replace("\\", "/")]

    def get_neighbors(self, node_id: str, relation: str | None = None) -> list[tuple[GraphEdge, GraphNode]]:
        """Outgoing neighbors, optionally filtered by edge relation type."""
        self._ensure_loaded()
        results = []
        for edge in self._adj.get(node_id, []):
            if relation and edge.relation != relation:
                continue
            target = self._nodes.get(edge.target)
            if target:
                results.append((edge, target))
        return results

    def get_incoming(self, node_id: str, relation: str | None = None) -> list[tuple[GraphEdge, GraphNode]]:
        """Incoming neighbors (callers, importers), optionally filtered by relation."""
        self._ensure_loaded()
        results = []
        for edge in self._radj.get(node_id, []):
            if relation and edge.relation != relation:
                continue
            source = self._nodes.get(edge.source)
            if source:
                results.append((edge, source))
        return results

    def get_community(self, node_id: str) -> list[GraphNode]:
        """All nodes in the same community as node_id."""
        self._ensure_loaded()
        node = self._nodes.get(node_id)
        if node is None or node.community is None:
            return []
        return [n for n in self._nodes.values() if n.community == node.community]

    def get_god_nodes(
        self,
        n: int = 10,
        stale_only: bool = False,
        min_complexity: int | None = None,
        dead_only: bool = False,
    ) -> list[GraphNode]:
        """Top-N nodes by degree (graphify's importance metric), filterable by
        codemapper quality signals from the annotated graph."""
        self._ensure_loaded()
        candidates = list(self._nodes.values())

        if stale_only:
            candidates = [c for c in candidates if c.codemapper.get("stale_docstring")]
        if min_complexity is not None:
            candidates = [c for c in candidates if c.codemapper.get("complexity", 0) >= min_complexity]
        if dead_only:
            candidates = [c for c in candidates if c.codemapper.get("dead")]

        candidates.sort(key=lambda x: x.degree, reverse=True)
        return candidates[:n]

    def all_nodes(self) -> list[GraphNode]:
        self._ensure_loaded()
        return list(self._nodes.values())

    def node_count(self) -> int:
        self._ensure_loaded()
        return len(self._nodes)

    def community_count(self) -> int:
        self._ensure_loaded()
        communities = {n.community for n in self._nodes.values() if n.community is not None}
        return len(communities)
