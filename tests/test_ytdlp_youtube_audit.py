"""Unit tests for YouTube / cookie handling in ytdlp_service (no network)."""
import os
import sys
import unittest
from unittest import mock

# Project root on path
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


class TestYouTubeAttemptList(unittest.TestCase):
    def test_no_cookies_starts_with_tv_embedded(self):
        from services import ytdlp_service as m

        base = m._apply_common_ydl_opts({"quiet": True})
        attempts = m._build_youtube_attempt_list(base, None)
        names = [n for n, _ in attempts]
        self.assertEqual(names[0], "yt_tv_embedded")
        self.assertIn("yt_web_default", names)
        self.assertEqual(len(names), 5)

    def test_with_cookies_prefers_default_with_cookies(self):
        from services import ytdlp_service as m

        base = m._apply_common_ydl_opts({"quiet": True})
        attempts = m._build_youtube_attempt_list(base, "/tmp/fake_cookies.txt")
        names = [n for n, _ in attempts]
        self.assertEqual(names[0], "yt_default_with_cookies")
        self.assertIn("yt_mweb_with_cookies", names)
        self.assertGreaterEqual(len(names), 11)

    def test_should_disable_not_on_bot_message(self):
        from services import ytdlp_service as m

        bot_err = RuntimeError(
            "Sign in to confirm you're not a bot. Use --cookies-from-browser"
        )
        self.assertFalse(m._should_disable_cookies(bot_err))

        malformed = RuntimeError("malformed cookie file format")
        self.assertTrue(m._should_disable_cookies(malformed))

        unloadable = RuntimeError("could not load cookies")
        self.assertTrue(m._should_disable_cookies(unloadable))


class TestCookieConfiguration(unittest.TestCase):
    def test_get_cookie_file_missing_env_path(self):
        from services.ytdlp_service import _get_cookie_file

        missing = os.path.join(_ROOT, "__no_such_cookie_file__.txt")
        self.assertFalse(os.path.exists(missing))
        with mock.patch.dict(os.environ, {"YTDLP_COOKIEFILE": missing}):
            self.assertIsNone(_get_cookie_file())

    def test_reset_analysis_cache_clears(self):
        import services.ytdlp_service as m

        with m.ANALYSIS_CACHE_LOCK:
            m.ANALYSIS_CACHE["x"] = {"created_at": 0, "info": {}}
        m.reset_analysis_cache()
        self.assertEqual(len(m.ANALYSIS_CACHE), 0)


class TestHandlersKeys(unittest.TestCase):
    def test_i18n_has_youtube_keys_all_langs(self):
        from services.i18n import TRANSLATIONS

        for lang in ("en", "uz", "ru"):
            self.assertIn("extract_failed_youtube", TRANSLATIONS[lang])
            self.assertIn("download_failed_youtube_cookies", TRANSLATIONS[lang])


if __name__ == "__main__":
    unittest.main()
