"""Tool dependency manager.

Installs per-tool Python dependencies into an isolated site-packages directory
so user tool scripts can import third-party libraries without polluting the
main application environment.
"""
import importlib.metadata
import json
import re
import subprocess
import sys
from pathlib import Path

from app.core.config import TOOL_SITE_PACKAGES


def _normalize_name(name: str) -> str:
    """Normalize package name for comparison (PEP 503)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _parse_requirement(req: str) -> str:
    """Extract the bare package name from a requirement string like 'requests>=2.28'."""
    return re.split(r"[><=!~;@\[]", req, maxsplit=1)[0].strip()


class ToolDependencyManager:
    """Manages Python package dependencies for user tools."""

    def __init__(self, site_packages: Path | None = None):
        self._site_packages = site_packages or TOOL_SITE_PACKAGES
        self._site_packages.mkdir(parents=True, exist_ok=True)

    @property
    def site_packages_path(self) -> Path:
        return self._site_packages

    def is_installed(self, package: str) -> bool:
        """Check if a package is available (either in isolated dir or globally)."""
        name = _normalize_name(_parse_requirement(package))
        # Check isolated site-packages first
        metadata_dirs = list(self._site_packages.glob(f"{name}-*.dist-info")) + \
                        list(self._site_packages.glob(f"{name.replace('-', '_')}-*.dist-info"))
        if metadata_dirs:
            return True
        # Fall back to global environment
        try:
            importlib.metadata.distribution(name)
            return True
        except importlib.metadata.PackageNotFoundError:
            return False

    def get_missing(self, dependencies: list[str]) -> list[str]:
        """Return dependencies that are not yet installed."""
        return [dep for dep in dependencies if not self.is_installed(dep)]

    def install(self, dependencies: list[str]) -> tuple[bool, str]:
        """Install dependencies into the isolated site-packages.

        Returns (success, message).
        """
        if not dependencies:
            return True, ""
        try:
            result = subprocess.run(
                [
                    sys.executable, "-m", "pip", "install",
                    "--target", str(self._site_packages),
                    "--quiet",
                    "--disable-pip-version-check",
                ] + dependencies,
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode != 0:
                return False, result.stderr.strip()
            return True, ""
        except subprocess.TimeoutExpired:
            return False, "依赖安装超时（5分钟）"
        except Exception as e:
            return False, str(e)

    def ensure_deps(self, dependencies: list[str]) -> tuple[bool, str]:
        """Check and install missing dependencies.

        Returns (success, message). If all deps are present, returns (True, "").
        """
        missing = self.get_missing(dependencies)
        if not missing:
            return True, ""
        return self.install(missing)
