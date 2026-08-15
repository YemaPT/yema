from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from yema.clients.yemapt import get_pt_download_url_from_key
from yema.config.utils import fetch_yemapt_basic_info


class _Response:
    status = 200
    reason = "OK"

    def __init__(self, payload: dict[str, object]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class YemaptOpenApiTest(unittest.TestCase):
    @patch("yema.config.utils.is_debug_enabled", return_value=False)
    @patch("yema.config.utils.urllib.request.urlopen")
    def test_fetch_basic_info_uses_post(self, urlopen, _debug) -> None:
        urlopen.return_value = _Response({"success": True, "data": {"id": 1}})

        result = fetch_yemapt_basic_info("api-key", "https://example.test/")

        self.assertTrue(result["success"])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.test/openApi/user/fetchBasicInfo.json")
        self.assertEqual(request.get_method(), "POST")

    @patch("yema.clients.yemapt.fetch_with_remote_disconnect_retry")
    def test_generate_download_key_uses_documented_post_endpoint(self, fetch) -> None:
        fetch.return_value = (
            _Response({}),
            json.dumps({"success": True, "data": "key+/="}).encode("utf-8"),
        )

        url = get_pt_download_url_from_key(123, "api-key", False, "https://example.test/")

        request = fetch.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://example.test/openApi/torrent/generateDownloadKey.json?id=123",
        )
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(url, "https://example.test/api/torrent/download1?token=key%2B%2F%3D")


if __name__ == "__main__":
    unittest.main()
