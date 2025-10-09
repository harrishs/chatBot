import os

import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
os.environ.setdefault("ENCRYPTION_KEY", "8wfsecdopt6Fz6ZRlo6RLWF2zOWITlzv9uVSXnscJFA=")

import django

django.setup()

from chat.utils.jira import extract_plain_text_from_adf


def test_extract_plain_text_from_adf_mixed_format_comment():
    body = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "First line"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "Second line"},
                ],
            },
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "emoji",
                        "attrs": {"shortName": ":sparkles:"},
                    },
                    {"type": "text", "text": " Mixed content"},
                ],
            },
        ],
    }

    result = extract_plain_text_from_adf(body)

    assert result == "First line\nSecond line\n:sparkles: Mixed content"


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"type": "doc", "content": [{"type": "paragraph", "content": []}]},
    ],
)
def test_extract_plain_text_from_adf_returns_empty_string_for_no_text(body):
    assert extract_plain_text_from_adf(body) == ""
