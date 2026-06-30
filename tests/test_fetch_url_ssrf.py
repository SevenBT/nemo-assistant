"""SSRF 防护测试：直连校验 + 重定向逐跳复查。"""
import unittest
from unittest import mock

import httpx

from app.tools import fetch_url
from app.tools.fetch_url import FetchUrlTool, _check_url_safety


class CheckUrlSafetyTest(unittest.TestCase):
    def test_blocks_localhost_aliases(self):
        for host in ("http://localhost", "http://127.0.0.1", "http://0.0.0.0"):
            safe, reason = _check_url_safety(host)
            self.assertFalse(safe, host)
            self.assertTrue(reason)

    def test_rejects_non_http_scheme(self):
        safe, reason = _check_url_safety("ftp://example.com")
        self.assertFalse(safe)

    def test_allows_public_host_shape(self):
        # 不实际联网：8.8.8.8 是公网 IP，校验应放行。
        safe, _ = _check_url_safety("http://8.8.8.8")
        self.assertTrue(safe)


class _FakeResp:
    """模拟 httpx.Response 的最小子集。"""

    def __init__(self, *, is_redirect=False, location=None, url="http://x"):
        self.is_redirect = is_redirect
        self.headers = {"location": location} if location else {}
        self.url = url

    def raise_for_status(self):
        pass


class _FakeClient:
    """按预设序列返回响应，记录请求过的 URL。"""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requested = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url):
        self.requested.append(url)
        return self._responses.pop(0)


class RedirectSsrfTest(unittest.TestCase):
    def test_redirect_to_internal_is_blocked(self):
        # 首跳公网 -> 302 重定向到内网 127.0.0.1，应在第二跳被拦截。
        fake = _FakeClient([
            _FakeResp(is_redirect=True, location="http://127.0.0.1/admin"),
        ])
        with mock.patch.object(httpx, "Client", return_value=fake):
            result = FetchUrlTool(timeout=5).execute({"url": "http://8.8.8.8"})
        self.assertEqual(result["status"], "error")
        self.assertIn("127.0.0.1", result["data"]["url"])
        # 不应真的对内网发起 GET（第二跳在校验阶段就被拦下）。
        self.assertEqual(fake.requested, ["http://8.8.8.8"])

    def test_too_many_redirects(self):
        from app.i18n import t
        # 始终重定向到另一个公网地址，超过上限应报错。
        responses = [
            _FakeResp(is_redirect=True, location="http://8.8.8.8/next")
            for _ in range(10)
        ]
        fake = _FakeClient(responses)
        with mock.patch.object(httpx, "Client", return_value=fake):
            result = FetchUrlTool(timeout=5).execute({"url": "http://8.8.8.8"})
        self.assertEqual(result["status"], "error")
        self.assertIn(t("tool.fetch_url.msg.too_many_redirects").split("{")[0], result["data"]["message"])


if __name__ == "__main__":
    unittest.main()
