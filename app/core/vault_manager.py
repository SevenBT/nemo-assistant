"""
文件系统笔记管理器，使用 .md 文件存储。
基于 noteration 的 vault 方式，替代 SQLite 存储。
"""

from __future__ import annotations

import re
import shutil
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from app.core.config import NOTES_DIR, NOTES_IMAGES_DIR, TRASH_DIR


@dataclass
class VaultNote:
    """表示一个 .md 笔记文件。"""
    path: Path
    title: str
    content: str
    folder: str | None = None  # relative folder path within NOTES_DIR
    created_at: str = ""
    modified_at: str = ""
    tags: list[str] = field(default_factory=list)

    @property
    def stem(self) -> str:
        return self.path.stem

    @property
    def relative_path(self) -> str:
        """相对于 NOTES_DIR 的路径。"""
        try:
            return str(self.path.relative_to(NOTES_DIR))
        except ValueError:
            return self.path.name


@dataclass
class SearchResult:
    """搜索结果。"""
    title: str
    snippet: str
    path: Path
    score: float = 0.0


class VaultManager:
    """文件系统笔记管理器，管理 .md 文件的 CRUD 和搜索。"""

    def __init__(self, notes_dir: Path | None = None) -> None:
        self.notes_dir = notes_dir or NOTES_DIR
        self.images_dir = NOTES_IMAGES_DIR
        self.trash_dir = TRASH_DIR
        self._ensure_dirs()
        # mtime cache for search: {path_str: (mtime, content)}
        self._cache: dict[str, tuple[float, str]] = {}

    def _ensure_dirs(self) -> None:
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.trash_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ CRUD

    def list_notes(self, folder: str | None = None) -> list[VaultNote]:
        """列出所有笔记，按修改时间倒序。"""
        search_dir = self.notes_dir / folder if folder else self.notes_dir
        if not search_dir.exists():
            return []
        notes = []
        for md_file in search_dir.rglob("*.md"):
            # 跳过 trash 目录
            if self.trash_dir in md_file.parents:
                continue
            notes.append(self._load_note(md_file))
        notes.sort(key=lambda n: n.modified_at, reverse=True)
        return notes

    def get_note(self, name: str) -> VaultNote | None:
        """按文件名（不含扩展名）获取笔记。"""
        from app.core.wiki_links import resolve_link
        path = resolve_link(name, self.notes_dir)
        if path and path.exists():
            return self._load_note(path)
        return None

    def create_note(
        self, title: str, content: str = "", folder: str | None = None
    ) -> VaultNote:
        """创建新笔记。"""
        filename = self._sanitize_filename(title)
        target_dir = self.notes_dir / folder if folder else self.notes_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{filename}.md"
        # 避免重名
        counter = 1
        while path.exists():
            path = target_dir / f"{filename}_{counter}.md"
            counter += 1
        path.write_text(content, encoding="utf-8")
        return self._load_note(path)

    def update_note(self, path: Path, content: str) -> VaultNote:
        """更新笔记内容。"""
        path.write_text(content, encoding="utf-8")
        return self._load_note(path)

    def rename_note(self, path: Path, new_title: str) -> VaultNote:
        """重命名笔记文件。"""
        new_filename = self._sanitize_filename(new_title)
        new_path = path.parent / f"{new_filename}.md"
        if new_path.exists() and new_path != path:
            counter = 1
            while new_path.exists():
                new_path = path.parent / f"{new_filename}_{counter}.md"
                counter += 1
        path.rename(new_path)
        return self._load_note(new_path)

    def delete_note(self, path: Path) -> None:
        """将笔记移入回收站（软删除）。"""
        if not path.exists():
            return
        trash_path = self.trash_dir / path.name
        counter = 1
        while trash_path.exists():
            trash_path = self.trash_dir / f"{path.stem}_{counter}{path.suffix}"
            counter += 1
        shutil.move(str(path), str(trash_path))

    def purge_note(self, path: Path) -> None:
        """永久删除笔记。"""
        if path.exists():
            path.unlink()

    def restore_note(self, trash_path: Path) -> VaultNote | None:
        """从回收站恢复笔记。"""
        if not trash_path.exists():
            return None
        target = self.notes_dir / trash_path.name
        counter = 1
        while target.exists():
            target = self.notes_dir / f"{trash_path.stem}_{counter}{trash_path.suffix}"
            counter += 1
        shutil.move(str(trash_path), str(target))
        return self._load_note(target)

    def get_trash(self) -> list[VaultNote]:
        """获取回收站中的笔记。"""
        notes = []
        for md_file in self.trash_dir.glob("*.md"):
            notes.append(self._load_note(md_file))
        notes.sort(key=lambda n: n.modified_at, reverse=True)
        return notes

    def purge_all_trash(self) -> None:
        """清空回收站。"""
        for md_file in self.trash_dir.glob("*.md"):
            md_file.unlink()

    # ------------------------------------------------------------------ Folders

    def list_folders(self) -> list[str]:
        """列出 notes_dir 下的所有子目录（相对路径）。"""
        folders = []
        for d in sorted(self.notes_dir.iterdir()):
            if d.is_dir() and d != self.images_dir and d != self.trash_dir:
                folders.append(d.name)
        return folders

    def create_folder(self, name: str) -> Path:
        """创建子目录。"""
        folder_path = self.notes_dir / self._sanitize_filename(name)
        folder_path.mkdir(parents=True, exist_ok=True)
        return folder_path

    def rename_folder(self, old_name: str, new_name: str) -> Path | None:
        """重命名文件夹。"""
        old_path = self.notes_dir / old_name
        if not old_path.exists():
            return None
        new_path = self.notes_dir / self._sanitize_filename(new_name)
        if new_path.exists():
            return None
        old_path.rename(new_path)
        return new_path

    def delete_folder(self, name: str) -> None:
        """删除文件夹，将其中的笔记移到根目录。"""
        folder_path = self.notes_dir / name
        if not folder_path.exists():
            return
        for md_file in folder_path.glob("*.md"):
            target = self.notes_dir / md_file.name
            counter = 1
            while target.exists():
                target = self.notes_dir / f"{md_file.stem}_{counter}.md"
                counter += 1
            shutil.move(str(md_file), str(target))
        # 删除空目录
        shutil.rmtree(str(folder_path), ignore_errors=True)

    def move_note_to_folder(self, path: Path, folder: str | None) -> Path:
        """将笔记移入指定文件夹（None 表示根目录）。"""
        target_dir = self.notes_dir / folder if folder else self.notes_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / path.name
        if target == path:
            return path
        counter = 1
        while target.exists():
            target = target_dir / f"{path.stem}_{counter}.md"
            counter += 1
        shutil.move(str(path), str(target))
        return target

    # ------------------------------------------------------------------ Search

    def search(
        self,
        query: str,
        case_sensitive: bool = False,
        use_regex: bool = False,
        max_results: int = 200,
    ) -> list[SearchResult]:
        """全文搜索笔记内容和标题。"""
        if not query.strip():
            return []

        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            if use_regex:
                pattern = re.compile(query, flags)
            else:
                pattern = re.compile(re.escape(query), flags)
        except re.error:
            return []

        results: list[SearchResult] = []
        for md_file in self.notes_dir.rglob("*.md"):
            if self.trash_dir in md_file.parents:
                continue
            text = self._get_cached_content(md_file)
            if text is None:
                continue
            matches = list(pattern.finditer(text))
            if not matches:
                continue

            score = len(matches) * 10.0
            for m in matches:
                line_num = text[: m.start()].count("\n") + 1
                if line_num <= 3:
                    score += 5

            first = matches[0]
            start = max(0, first.start() - 40)
            end = min(len(text), first.end() + 40)
            snippet = text[start:end].replace("\n", " ").strip()
            snippet = pattern.sub(lambda m: f"**{m.group()}**", snippet)

            title = self._extract_title(md_file, text)
            results.append(SearchResult(
                title=title, snippet=snippet, path=md_file, score=score
            ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:max_results]

    # ------------------------------------------------------------------ Internal

    def _load_note(self, path: Path) -> VaultNote:
        """从文件加载笔记。"""
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            content = ""
        stat = path.stat()
        created_at = datetime.fromtimestamp(stat.st_ctime).isoformat()
        modified_at = datetime.fromtimestamp(stat.st_mtime).isoformat()
        title = self._extract_title(path, content)
        # 确定 folder
        folder = None
        try:
            rel = path.relative_to(self.notes_dir)
            if len(rel.parts) > 1:
                folder = str(rel.parent)
        except ValueError:
            pass
        return VaultNote(
            path=path,
            title=title,
            content=content,
            folder=folder,
            created_at=created_at,
            modified_at=modified_at,
        )

    def _extract_title(self, path: Path, content: str) -> str:
        """从内容第一行 # 标题提取，否则用文件名。"""
        first_line = content.split("\n", 1)[0].strip() if content else ""
        if first_line.startswith("#"):
            return first_line.lstrip("#").strip()
        return path.stem

    def _get_cached_content(self, path: Path) -> str | None:
        """带 mtime 缓存的文件内容读取。"""
        path_str = str(path)
        try:
            mtime = path.stat().st_mtime
            if path_str in self._cache:
                cached_mtime, content = self._cache[path_str]
                if mtime == cached_mtime:
                    return content
            content = path.read_text(encoding="utf-8")
            self._cache[path_str] = (mtime, content)
            return content
        except Exception:
            return None

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """将标题转为安全的文件名。"""
        # 移除不安全字符
        safe = re.sub(r'[<>:"/\\|?*]', '', name)
        safe = safe.strip('. ')
        return safe or "untitled"
