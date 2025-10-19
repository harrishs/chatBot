import os

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
os.environ.setdefault("ENCRYPTION_KEY", "wvRwBW8Y7-P2eFoRhqNRdbi8ZjsIvkTCmFll1xQ3hl8=")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DJANGO_SECRET_KEY", "unit-test-secret")

django.setup()

from chat.utils import rag


@pytest.mark.parametrize(
    "answer,expected_substrings,unexpected",
    [
        (
            "Here is the deployment script::\n\n```bash\nexport API_KEY=abc123\necho done\n```",
            ["```bash", "echo done", "API_KEY"],
            ["abc123"],
        ),
        (
            "Store the token inline like this: `token=abc123`. Also run `git status`.",
            ["`git status`", "token="],
            ["abc123"],
        ),
        (
            "Use `api_key=` followed by `abc123` to authenticate.",
            ["api_key=", "[redacted sensitive data]"],
            ["abc123"],
        ),
    ],
)
def test_sanitize_answer_preserves_safe_code_while_redacting_secrets(
    answer, expected_substrings, unexpected
):
    sanitized = rag._sanitize_answer(answer, metadata_list=[])

    for substring in expected_substrings:
        assert substring in sanitized

    for substring in unexpected:
        assert substring not in sanitized


def test_sanitize_answer_retains_code_block_structure_after_redaction():
    answer = "```\n-----BEGIN RSA PRIVATE KEY-----\nsecret\n-----END RSA PRIVATE KEY-----\n```"
    sanitized = rag._sanitize_answer(answer, metadata_list=[])

    assert sanitized.startswith("```")
    assert sanitized.endswith("```")
    assert "[redacted sensitive data]" in sanitized
