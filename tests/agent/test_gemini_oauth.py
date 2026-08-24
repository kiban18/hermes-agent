import unittest
from unittest.mock import patch

from agent import gemini_oauth
from agent.gemini_cloudcode_adapter import unwrap_cloudcode_payload, wrap_cloudcode_request
from agent.gemini_oauth import _needs_refresh


class GeminiOauthTests(unittest.TestCase):
    def test_wrap_cloudcode_request_shape(self):
        wrapped = wrap_cloudcode_request(
            model="gemini-2.5-flash",
            request={"contents": [{"role": "user", "parts": [{"text": "hi"}]}]},
            project="numeric-habitat-487420-i6",
            user_prompt_id="hermes-test",
        )
        self.assertEqual(wrapped["model"], "gemini-2.5-flash")
        self.assertEqual(wrapped["project"], "numeric-habitat-487420-i6")
        self.assertEqual(wrapped["request"]["contents"][0]["parts"][0]["text"], "hi")

    def test_unwrap_cloudcode_payload(self):
        inner = unwrap_cloudcode_payload(
            {
                "traceId": "abc",
                "response": {
                    "candidates": [
                        {"content": {"parts": [{"text": "GCA_OK"}]}}
                    ]
                },
            }
        )
        self.assertEqual(inner["candidates"][0]["content"]["parts"][0]["text"], "GCA_OK")
        self.assertEqual(inner["responseId"], "abc")

    def test_needs_refresh_missing_token(self):
        self.assertTrue(_needs_refresh({}))

    def test_needs_refresh_future_expiry(self):
        self.assertFalse(
            _needs_refresh({"access_token": "ya29.x", "expiry_date": 9_999_999_999_000})
        )

    def test_oauth_client_credentials_come_from_protected_scope(self):
        values = {
            "GEMINI_CLI_CLIENT_ID": "client-id",
            "GEMINI_CLI_CLIENT_SECRET": "client-secret",
        }
        with patch.object(gemini_oauth, "get_secret", side_effect=values.get):
            self.assertEqual(
                gemini_oauth._resolve_oauth_client_credentials(),
                ("client-id", "client-secret"),
            )


if __name__ == "__main__":
    unittest.main()
