"""Unit tests for secret redaction and logging."""

import json
import logging
import unittest

from ailen.core.logging import SecretRedactingFormatter, redact_secrets


class TestLogging(unittest.TestCase):
    """Test suite for AILEN logging and redaction."""

    def test_redact_bearer_token(self):
        msg = "Sending request with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        redacted = redact_secrets(msg)
        self.assertNotIn("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", redacted)
        self.assertIn("Bearer [REDACTED]", redacted)

    def test_redact_openai_key(self):
        msg = "Using OpenAI key sk-abcdef1234567890abcdef1234567890 for request"
        redacted = redact_secrets(msg)
        self.assertNotIn("sk-abcdef1234567890abcdef1234567890", redacted)
        self.assertIn("sk-[REDACTED]", redacted)

    def test_redact_password_and_token_fields(self):
        msg = 'Configuring auth: "password": "supersecretpassword123", "token": "abcdef987654321"'
        redacted = redact_secrets(msg)
        self.assertNotIn("supersecretpassword123", redacted)
        self.assertNotIn("abcdef987654321", redacted)
        self.assertIn('"password": "[REDACTED]"', redacted)
        self.assertIn('"token": "[REDACTED]"', redacted)

    def test_redacting_formatter_json(self):
        formatter = SecretRedactingFormatter(json_format=True)
        record = logging.LogRecord(
            name="ailen.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="User login with Bearer sec_token_1234567890",
            args=(),
            exc_info=None,
        )
        formatted = formatter.format(record)
        parsed = json.loads(formatted)
        self.assertEqual(parsed["level"], "INFO")
        self.assertEqual(parsed["name"], "ailen.test")
        self.assertIn("Bearer [REDACTED]", parsed["message"])
        self.assertNotIn("sec_token_1234567890", parsed["message"])


if __name__ == "__main__":
    unittest.main()
