"""litellm_loader 测试 —— 环境变量设置、缓存、错误归因区分。"""
import importlib
import os
import sys
import threading
import unittest
from unittest import mock

from app.core import litellm_loader
from app.core.litellm_loader import LiteLLMUnavailableError, load_litellm


class LiteLLMLoaderTest(unittest.TestCase):
    def setUp(self):
        # 每个用例前清缓存，保证独立
        previous = litellm_loader._litellm
        self.addCleanup(setattr, litellm_loader, "_litellm", previous)
        litellm_loader._litellm = None

    def test_sets_local_cost_map_env_before_import(self):
        # 清掉环境变量与缓存，调用后应被设为 "True"
        os.environ.pop("LITELLM_LOCAL_MODEL_COST_MAP", None)
        with mock.patch.object(
            litellm_loader.importlib.util, "find_spec", return_value=object()
        ), mock.patch.dict(sys.modules, {"litellm": mock.MagicMock(__name__="litellm")}):
            load_litellm()
        self.assertEqual(os.environ.get("LITELLM_LOCAL_MODEL_COST_MAP"), "True")

    def test_missing_package_reports_not_installed(self):
        with mock.patch.object(
            litellm_loader.importlib.util, "find_spec", return_value=None
        ):
            with self.assertRaises(LiteLLMUnavailableError) as ctx:
                load_litellm()
        self.assertIn("未安装", str(ctx.exception))

    def test_import_failure_reports_import_error_not_missing(self):
        # 包存在（find_spec 非 None）但 import 抛异常 → 应报"导入失败"，不是"未安装"。
        # 拦截 builtins.__import__：仅对 "litellm" 抛错，其余照常。
        real_import = __import__

        def fake_import(name, *args, **kwargs):
            if name == "litellm":
                raise ImportError("missing sub-dependency 'foo'")
            return real_import(name, *args, **kwargs)

        with mock.patch.object(
            litellm_loader.importlib.util, "find_spec", return_value=object()
        ), mock.patch("builtins.__import__", side_effect=fake_import):
            with self.assertRaises(LiteLLMUnavailableError) as ctx:
                load_litellm()
        msg = str(ctx.exception)
        self.assertIn("导入失败", msg)
        self.assertNotIn("未安装", msg)

    def test_result_is_cached(self):
        sentinel = mock.MagicMock(__name__="litellm")
        with mock.patch.object(
            litellm_loader.importlib.util, "find_spec", return_value=object()
        ), mock.patch.dict(sys.modules, {"litellm": sentinel}):
            first = load_litellm()
        # 第二次调用即使 find_spec 改为 None 也应返回缓存值
        with mock.patch.object(
            litellm_loader.importlib.util, "find_spec", return_value=None
        ):
            second = load_litellm()
        self.assertIs(first, second)

    def test_warmup_is_nonblocking_and_shared_with_early_request(self):
        started = threading.Event()
        release = threading.Event()
        sentinel = object()
        results = []

        def slow_import():
            started.set()
            self.assertTrue(release.wait(3))
            litellm_loader._litellm = sentinel
            return sentinel

        with mock.patch.object(litellm_loader, "_import_litellm", side_effect=slow_import) as importer:
            self.assertTrue(litellm_loader.warm_litellm_async())
            warmup = litellm_loader._warmup_thread
            request = threading.Thread(target=lambda: results.append(load_litellm()))
            try:
                self.assertTrue(started.wait(1))
                self.assertTrue(warmup.is_alive())
                self.assertFalse(litellm_loader.warm_litellm_async())
                request.start()
            finally:
                release.set()
                warmup.join(3)
                if request.ident is not None:
                    request.join(3)
            self.assertFalse(warmup.is_alive())
            self.assertFalse(request.is_alive())
            importer.assert_called_once_with()
        self.assertEqual(results, [sentinel])
        self.assertFalse(litellm_loader.warm_litellm_async())

    def test_failed_warmup_leaves_request_retryable(self):
        with mock.patch.object(
            litellm_loader, "_import_litellm",
            side_effect=LiteLLMUnavailableError("temporarily unavailable"),
        ):
            self.assertTrue(litellm_loader.warm_litellm_async())
            litellm_loader._warmup_thread.join(3)
            self.assertFalse(litellm_loader._warmup_thread.is_alive())
        self.assertIsNone(litellm_loader._litellm)
        sentinel = object()
        with mock.patch.object(litellm_loader, "_import_litellm", return_value=sentinel):
            self.assertIs(load_litellm(), sentinel)

    def test_thread_start_failure_does_not_break_startup(self):
        with mock.patch.object(threading.Thread, "start", side_effect=RuntimeError("failed")):
            self.assertFalse(litellm_loader.warm_litellm_async())
        self.assertIsNone(litellm_loader._warmup_thread)


if __name__ == "__main__":
    unittest.main()
