"""
抓取网页内容工具 — 获取 URL 页面并提取正文文本。

功能：
  - 自动识别 JSON 响应和 HTML 页面
  - HTML 页面使用 BeautifulSoup 提取正文（去除导航、脚本等噪音）
  - 优先从 <main>、<article>、#content 等语义标签提取
  - 超长内容自动截断（默认 20000 字符）
  - SSRF 防护：阻止访问内网和本机地址

依赖：
  - httpx: HTTP 客户端
  - beautifulsoup4: HTML 解析（可选，缺失时返回原始文本）
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Any, TYPE_CHECKING
from urllib.parse import urljoin, urlparse

from app.tools.base import BuiltinTool
from app.tools.schema import Str, tool_params

if TYPE_CHECKING:
    from app.tools.context import ToolContext

# 正文最大字符数，防止超长页面撑爆 LLM 上下文
_MAX_CONTENT = 20_000

# SSRF 防护：禁止访问的内网网段
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _check_url_safety(url: str) -> tuple[bool, str]:
    """
    检查 URL 是否安全（非内网地址）。

    Returns:
        (is_safe, error_message) — 安全时 error_message 为空
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, f"不支持的协议: {parsed.scheme}"

    hostname = parsed.hostname
    if not hostname:
        return False, "无效的 URL"

    # 直接拦截 localhost 别名
    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return False, "禁止访问本机地址"

    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return False, f"无法解析域名: {hostname}"

    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        for network in _BLOCKED_NETWORKS:
            if ip in network:
                return False, f"禁止访问内网地址: {hostname} ({ip})"

    return True, ""


class FetchUrlTool(BuiltinTool):
    """网页内容抓取工具。"""

    def __init__(self, timeout: int = 20):
        self._timeout = timeout

    @classmethod
    def create(cls, ctx: "ToolContext") -> "FetchUrlTool":
        """从上下文获取 HTTP 超时配置。"""
        return cls(timeout=ctx.http_timeout)

    @property
    def name(self) -> str:
        return "fetch_url"

    @property
    def description(self) -> str:
        return "抓取网页内容并提取正文文本，适合阅读文章、查看在线文档、获取网页信息"

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "url",
            url=Str("要抓取的网页 URL，如 'https://example.com/article'"),
        )

    @property
    def read_only(self) -> bool:
        """只读操作（不修改任何状态），可并发执行。"""
        return True

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        import json
        import httpx

        url = params.get("url", "").strip()
        if not url:
            return {"status": "error", "data": {"message": "url is required"}}
        # 自动补全协议前缀
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        # SSRF 防护：检查目标地址是否安全
        safe, reason = _check_url_safety(url)
        if not safe:
            return {"status": "error", "data": {"message": reason, "url": url}}

        # 模拟浏览器请求头，避免被反爬拦截
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        try:
            # 手动逐跳跟随重定向：每一跳都重新做 SSRF 校验，
            # 防止外网 URL 经 30x 重定向到内网地址绕过首跳检查。
            _MAX_REDIRECTS = 5
            with httpx.Client(
                headers=headers, timeout=self._timeout, follow_redirects=False
            ) as client:
                for _ in range(_MAX_REDIRECTS + 1):
                    safe, reason = _check_url_safety(url)
                    if not safe:
                        return {"status": "error", "data": {"message": reason, "url": url}}
                    resp = client.get(url)
                    if resp.is_redirect:
                        location = resp.headers.get("location")
                        if not location:
                            break
                        url = urljoin(str(resp.url), location)
                        continue
                    break
                else:
                    return {"status": "error", "data": {"message": "重定向次数过多", "url": url}}
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")

            # JSON 响应直接序列化返回
            if "json" in content_type:
                try:
                    body = json.dumps(resp.json(), ensure_ascii=False)[:_MAX_CONTENT]
                    return {"status": "success", "data": {"url": str(resp.url), "type": "json", "content": body}}
                except Exception:
                    pass

            # HTML 页面：用 BeautifulSoup 提取正文
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, "html.parser")
                # 移除噪音标签
                for tag in soup(["script", "style", "nav", "header", "footer", "aside", "iframe", "noscript"]):
                    tag.decompose()
                # 优先从语义标签提取正文
                main_el = soup.find("main") or soup.find("article") or soup.find(id="content") or soup.find(class_="content")
                raw = (main_el or soup).get_text(separator="\n", strip=True)
                # 清理空行
                lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
                text = "\n".join(lines)
                title_el = soup.find("title")
                title = title_el.get_text(strip=True) if title_el else ""
                truncated = len(text) > _MAX_CONTENT
                return {
                    "status": "success",
                    "data": {
                        "url": str(resp.url), "title": title, "type": "html",
                        "content": text[:_MAX_CONTENT], "truncated": truncated, "total_chars": len(text),
                    },
                }
            except ImportError:
                # beautifulsoup4 未安装，返回原始文本
                text = resp.text[:_MAX_CONTENT]
                return {"status": "success", "data": {"url": str(resp.url), "type": "raw", "content": text}}

        except Exception as e:
            return {"status": "error", "data": {"message": str(e), "url": url}}
