"""
笔记反向链接图。
移植自 noteration/db/link_graph.py。

基于 NetworkX（可选）构建有向图，JSON 持久化。
支持增量更新、反向链接查询、孤立节点检测等。
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict

from app.core.wiki_links import parse_wiki_links, resolve_link
from app.core.config import NOTES_DIR, DATA_DIR

logger = logging.getLogger(__name__)

_GRAPH_FILE = DATA_DIR / "notes" / "link_graph.json"

_nx: Any = None


def get_nx() -> Any:
    global _nx
    if _nx is None:
        try:
            import networkx as nx
            _nx = nx
        except ImportError:
            pass
    return _nx


def has_nx() -> bool:
    return get_nx() is not None


class LinkGraph:
    """
    有向图：边 A → B 表示笔记 A 包含 [[link to B]]。
    无 NetworkX 时使用 dict 回退实现。
    """

    def __init__(self, notes_dir: Path | None = None) -> None:
        self.notes_dir = notes_dir or NOTES_DIR
        self._graph_path = _GRAPH_FILE
        self._lock = threading.RLock()
        self._adj: dict[str, set[str]] = {}
        self._radj: dict[str, set[str]] = {}
        self._G = None
        self._file_mtimes: Dict[str, float] = {}

        nx = get_nx()
        if nx:
            self._G = nx.DiGraph()

    # ── Helpers ───────────────────────────────────────────────────────

    def _get_note_id(self, path: Path) -> str:
        """绝对路径 -> 相对 ID（如 folder/note）。"""
        try:
            rel = path.relative_to(self.notes_dir)
            return str(rel.with_suffix(""))
        except ValueError:
            return path.stem

    def _resolve_target_to_id(self, target: str) -> str | None:
        """解析 [[target]] 为相对 note_id。"""
        path = resolve_link(target, self.notes_dir)
        if path:
            return self._get_note_id(path)
        return None

    # ── Build ─────────────────────────────────────────────────────────

    def build_from_vault(self, force: bool = False) -> int:
        """
        扫描所有 .md 文件，提取 [[wiki-links]]，构建图。
        增量更新基于文件 mtime。返回总边数。
        """
        with self._lock:
            if force:
                self._adj.clear()
                self._radj.clear()
                self._file_mtimes.clear()
                if self._G is not None:
                    self._G.clear()

            current_md_files = list(self.notes_dir.rglob("*.md"))
            current_ids = {self._get_note_id(f) for f in current_md_files}

            # 移除已删除文件的节点
            stale_ids = set(self._adj.keys()) - current_ids
            for stale_id in stale_ids:
                self._remove_node(stale_id)

            # 处理新增或修改的文件
            for md_file in sorted(current_md_files):
                src_id = self._get_note_id(md_file)
                try:
                    mtime = md_file.stat().st_mtime
                except Exception:
                    continue
                if not force and self._file_mtimes.get(src_id) == mtime:
                    continue
                self._process_single_note(md_file, src_id, mtime)

            self.save()
            return sum(len(dsts) for dsts in self._adj.values())

    def update_note(self, note_path: Path) -> None:
        """单个笔记变更时增量更新图。"""
        with self._lock:
            src_id = self._get_note_id(note_path)
            try:
                mtime = note_path.stat().st_mtime
            except Exception:
                return
            self._process_single_note(note_path, src_id, mtime)
            self.save()

    def _process_single_note(self, note_path: Path, src_id: str, mtime: float) -> None:
        """解析单个笔记并更新其边。"""
        old_targets = set(self._adj.get(src_id, set()))
        for dst in old_targets:
            self._radj.get(dst, set()).discard(src_id)
        self._adj[src_id] = set()
        if self._G is not None:
            if src_id in self._G:
                self._G.remove_edges_from([(src_id, dst) for dst in old_targets])
        self._ensure_node(src_id)
        try:
            text = note_path.read_text(encoding="utf-8")
            for link in parse_wiki_links(text):
                dst_id = self._resolve_target_to_id(link.target)
                if dst_id and dst_id != src_id:
                    self._add_edge(src_id, dst_id)
            self._file_mtimes[src_id] = mtime
        except Exception as e:
            logger.error(f"Failed to process note {note_path}: {e}")

    def _remove_node(self, node_id: str) -> None:
        """完全移除节点及其所有边。"""
        targets = self._adj.pop(node_id, set())
        for dst in targets:
            self._radj.get(dst, set()).discard(node_id)
        sources = self._radj.pop(node_id, set())
        for src in sources:
            self._adj.get(src, set()).discard(node_id)
        self._file_mtimes.pop(node_id, None)
        if self._G is not None and node_id in self._G:
            self._G.remove_node(node_id)

    # ── Queries ───────────────────────────────────────────────────────

    def backlinks(self, note_id: str) -> list[str]:
        """返回链接到指定笔记的所有笔记。"""
        with self._lock:
            return sorted(self._radj.get(note_id, set()))

    def forward_links(self, note_id: str) -> list[str]:
        """返回指定笔记链接到的所有笔记。"""
        with self._lock:
            return sorted(self._adj.get(note_id, set()))

    def all_nodes(self) -> list[str]:
        with self._lock:
            return sorted(self._adj.keys())

    def orphans(self) -> list[str]:
        """返回没有任何反向链接的笔记。"""
        with self._lock:
            return [n for n in self._adj if not self._radj.get(n)]

    def most_linked(self, top_n: int = 10) -> list[tuple[str, int]]:
        """按反向链接数排序的 Top-N 笔记。"""
        with self._lock:
            counts = [
                (n, len(self._radj.get(n, set())))
                for n in self._adj
            ]
            return sorted(counts, key=lambda x: -x[1])[:top_n]

    def shortest_path(self, src: str, dst: str) -> list[str] | None:
        """计算两个笔记间的最短路径。"""
        with self._lock:
            nx = get_nx()
            if self._G is None or nx is None:
                return self._bfs_path(src, dst)
            try:
                return nx.shortest_path(self._G, src, dst)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                return None

    def stats(self) -> dict:
        with self._lock:
            n_nodes = len(self._adj)
            n_edges = sum(len(v) for v in self._adj.values())
            return {
                "nodes": n_nodes,
                "edges": n_edges,
                "orphans": len(self.orphans()),
            }

    # ── Serialization ─────────────────────────────────────────────────

    def save(self) -> None:
        with self._lock:
            self._graph_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "nodes": list(self._adj.keys()),
                "edges": [
                    {"src": src, "dst": dst}
                    for src, dsts in self._adj.items()
                    for dst in dsts
                ],
                "file_mtimes": self._file_mtimes,
            }
            tmp_path = self._graph_path.with_suffix(".tmp")
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                tmp_path.replace(self._graph_path)
            except Exception as e:
                logger.error(f"Failed to save link graph: {e}")
                if tmp_path.exists():
                    tmp_path.unlink()

    def load(self) -> bool:
        """从 JSON 加载图。成功返回 True。"""
        with self._lock:
            if not self._graph_path.exists():
                return False
            try:
                with open(self._graph_path, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                return False
            self._adj.clear()
            self._radj.clear()
            if self._G is not None:
                self._G.clear()
            self._file_mtimes = data.get("file_mtimes", {})
            for node in data.get("nodes", []):
                self._ensure_node(node)
            for edge in data.get("edges", []):
                self._add_edge(edge["src"], edge["dst"])
            return True

    # ── Internal Helpers ──────────────────────────────────────────────

    def _ensure_node(self, name: str) -> None:
        self._adj.setdefault(name, set())
        self._radj.setdefault(name, set())
        if self._G is not None and name not in self._G:
            self._G.add_node(name)

    def _add_edge(self, src: str, dst: str) -> None:
        self._ensure_node(src)
        self._ensure_node(dst)
        self._adj[src].add(dst)
        self._radj[dst].add(src)
        if self._G is not None:
            self._G.add_edge(src, dst)

    def _bfs_path(self, src: str, dst: str) -> list[str] | None:
        """无 NetworkX 时的 BFS 最短路径。"""
        if src == dst:
            return [src]
        visited = {src}
        queue: list[list[str]] = [[src]]
        while queue:
            path = queue.pop(0)
            node = path[-1]
            for neighbor in self._adj.get(node, set()):
                if neighbor == dst:
                    return path + [dst]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(path + [neighbor])
        return None
