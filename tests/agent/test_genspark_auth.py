import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent.genspark_auth import (
    GENSPARK_LLM_BASE_URL,
    resolve_genspark_api_key,
    resolve_genspark_runtime_credentials,
)


class GensparkAuthTests(unittest.TestCase):
    def test_reads_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"api_key": "gsk-test-key"}))
            with mock.patch(
                "agent.genspark_auth.genspark_config_path", return_value=path
            ):
                with mock.patch.dict("os.environ", {"GSK_API_KEY": ""}, clear=False):
                    self.assertEqual(resolve_genspark_api_key(), "gsk-test-key")

    def test_runtime_credentials_shape(self):
        with mock.patch(
            "agent.genspark_auth.resolve_genspark_api_key", return_value="gsk-test-key"
        ):
            creds = resolve_genspark_runtime_credentials()
        self.assertEqual(creds["base_url"], GENSPARK_LLM_BASE_URL)
        self.assertEqual(creds["source"], "gsk-cli")
        self.assertTrue(creds["api_key"])


if __name__ == "__main__":
    unittest.main()
