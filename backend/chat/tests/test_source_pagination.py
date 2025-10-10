import os
from unittest.mock import patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
os.environ.setdefault(
    "ENCRYPTION_KEY", "8wfsecdopt6Fz6ZRlo6RLWF2zOWITlzv9uVSXnscJFA="
)

import django  # noqa: E402

django.setup()  # noqa: E402

from django.core.management import call_command  # noqa: E402
from django.test import TestCase  # noqa: E402

from chat.encryption import encrypt_api_key  # noqa: E402
from chat.models import (  # noqa: E402
    ChatBotInstance,
    Company,
    ConfluencePage,
    ConfluenceSync,
    Credential,
    JiraComment,
    JiraIssue,
    JiraSync,
)
from chat.utils.confluence import fetch_confluence_pages  # noqa: E402
from chat.utils.jira import fetch_jira_issues  # noqa: E402


call_command("migrate", run_syncdb=True, verbosity=0)


class DummyResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):  # pragma: no cover - compatibility shim
        return None


class SourcePaginationTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Pagination Co")
        self.chatbot = ChatBotInstance.objects.create(
            company=self.company,
            name="Paginator",
        )
        self.credential = Credential.objects.create(
            company=self.company,
            name="Atlassian",
            email="user@example.com",
            _api_key=encrypt_api_key("token"),
        )

    def test_fetch_jira_issues_handles_multiple_pages(self):
        sync = JiraSync.objects.create(
            chatBot=self.chatbot,
            board_url="https://example.atlassian.net/jira/software/c/projects/TEST/boards/1",
            credential=self.credential,
        )

        issue_pages = {
            0: {
                "startAt": 0,
                "maxResults": 2,
                "total": 3,
                "issues": [
                    {
                        "id": "1",
                        "key": "TEST-1",
                        "fields": {
                            "summary": "Issue one",
                            "description": "First issue",
                            "status": {"name": "To Do"},
                            "created": "2024-01-01T00:00:00.000+0000",
                            "updated": "2024-01-02T00:00:00.000+0000",
                        },
                    },
                    {
                        "id": "2",
                        "key": "TEST-2",
                        "fields": {
                            "summary": "Issue two",
                            "description": "Second issue",
                            "status": {"name": "In Progress"},
                            "created": "2024-01-03T00:00:00.000+0000",
                            "updated": "2024-01-04T00:00:00.000+0000",
                        },
                    },
                ],
            },
            2: {
                "startAt": 2,
                "maxResults": 2,
                "total": 3,
                "isLast": True,
                "issues": [
                    {
                        "id": "3",
                        "key": "TEST-3",
                        "fields": {
                            "summary": "Issue three",
                            "description": "Third issue",
                            "status": {"name": "Done"},
                            "created": "2024-01-05T00:00:00.000+0000",
                            "updated": "2024-01-06T00:00:00.000+0000",
                        },
                    }
                ],
            },
        }

        comment_pages = {
            "TEST-1": {
                0: {
                    "startAt": 0,
                    "maxResults": 2,
                    "total": 3,
                    "comments": [
                        {
                            "id": "c1",
                            "created": "2024-01-02T01:00:00.000+0000",
                            "author": {"displayName": "Alice"},
                            "body": {"type": "doc", "content": []},
                        },
                        {
                            "id": "c2",
                            "created": "2024-01-02T02:00:00.000+0000",
                            "author": {"displayName": "Bob"},
                            "body": {"type": "doc", "content": []},
                        },
                    ],
                },
                2: {
                    "startAt": 2,
                    "maxResults": 2,
                    "total": 3,
                    "isLast": True,
                    "comments": [
                        {
                            "id": "c3",
                            "created": "2024-01-02T03:00:00.000+0000",
                            "author": {"displayName": "Carol"},
                            "body": {"type": "doc", "content": []},
                        }
                    ],
                },
            },
            "TEST-2": {
                0: {
                    "startAt": 0,
                    "maxResults": 50,
                    "total": 1,
                    "isLast": True,
                    "comments": [
                        {
                            "id": "c4",
                            "created": "2024-01-04T01:00:00.000+0000",
                            "author": {"displayName": "Dana"},
                            "body": {"type": "doc", "content": []},
                        }
                    ],
                }
            },
            "TEST-3": {
                0: {
                    "startAt": 0,
                    "maxResults": 50,
                    "total": 0,
                    "isLast": True,
                    "comments": [],
                }
            },
        }

        def fake_get(url, *_, **kwargs):
            params = kwargs.get("params") or {}
            if "/rest/api/3/search" in url:
                start = params.get("startAt", 0)
                return DummyResponse(issue_pages.get(start, {"issues": []}))
            if "/comment" in url:
                issue_key = url.split("/issue/")[1].split("/")[0]
                start = params.get("startAt", 0)
                return DummyResponse(comment_pages[issue_key].get(start, {"comments": []}))
            raise AssertionError(f"Unexpected URL {url}")

        with patch("chat.utils.jira._SESSION.get", side_effect=fake_get):
            processed = fetch_jira_issues(sync)

        self.assertEqual(len(processed), 3)
        self.assertEqual(JiraIssue.objects.count(), 3)
        self.assertEqual(
            JiraComment.objects.filter(issue__issue_key="TEST-1").count(),
            3,
        )
        self.assertEqual(
            JiraComment.objects.filter(issue__issue_key="TEST-2").count(),
            1,
        )

    def test_fetch_confluence_pages_follows_cursor(self):
        sync = ConfluenceSync.objects.create(
            chatBot=self.chatbot,
            space_url="https://example.atlassian.net/wiki/spaces/CONF/pages/1",
            credential=self.credential,
        )

        first_page = {
            "results": [
                {
                    "id": "1",
                    "title": "Welcome",
                    "body": {"storage": {"value": "<p>Welcome</p>"}},
                    "version": {"when": "2024-02-01T00:00:00.000+0000"},
                    "_links": {"webui": "/spaces/CONF/pages/1"},
                }
            ],
            "start": 0,
            "limit": 1,
            "size": 3,
            "_links": {
                "next": "/rest/api/content/search?cql=space%3D%22CONF%22&start=1&limit=1",
            },
        }

        second_page = {
            "results": [
                {
                    "id": "2",
                    "title": "About",
                    "body": {"storage": {"value": "<p>About</p>"}},
                    "version": {"when": "2024-02-02T00:00:00.000+0000"},
                    "_links": {"webui": "/spaces/CONF/pages/2"},
                }
            ],
            "start": 1,
            "limit": 1,
            "size": 3,
            "_links": {
                "next": "https://example.atlassian.net/wiki/rest/api/content/search?cql=space%3D%22CONF%22&start=2&limit=1",
            },
        }

        final_page = {
            "results": [
                {
                    "id": "3",
                    "title": "Contact",
                    "body": {"storage": {"value": "<p>Contact</p>"}},
                    "version": {"when": "2024-02-03T00:00:00.000+0000"},
                    "_links": {"webui": "/spaces/CONF/pages/3"},
                }
            ],
            "start": 2,
            "limit": 1,
            "size": 3,
            "_links": {},
        }

        responses = [
            DummyResponse(first_page),
            DummyResponse(second_page),
            DummyResponse(final_page),
        ]

        def fake_get(url, *_, **kwargs):
            if not responses:
                raise AssertionError("No more responses available")
            params = kwargs.get("params")
            if params:
                self.assertIn("cql", params)
            return responses.pop(0)

        with patch("chat.utils.confluence._SESSION.get", side_effect=fake_get):
            pages = fetch_confluence_pages(sync)

        self.assertEqual(len(pages), 3)
        self.assertEqual(ConfluencePage.objects.count(), 3)
        titles = list(
            ConfluencePage.objects.order_by("title").values_list("title", flat=True)
        )
        self.assertEqual(titles, ["About", "Contact", "Welcome"])
