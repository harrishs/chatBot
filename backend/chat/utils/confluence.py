import requests
from urllib.parse import urlparse, urlencode
from chat.models import ConfluencePage
from chat.encryption import decrypt_api_key
from chat.utils.embeddings import save_document

def get_confluence_base_url(space_url):
    """
    Extract base URL from Confluence space URL
    Example: https://yourcompany.atlassian.net/wiki/spaces/ABC/pages/1234
    => https://yourcompany.atlassian.net
    """
    parsed = urlparse(space_url)
    return f"{parsed.scheme}://{parsed.netloc}"

def extract_space_key(space_url):
    """
    Extract space key from Confluence space URL
    Example: https://yourcompany.atlassian.net/wiki/spaces/ABC/pages/1234
    => ABC
    """
    try:
        parts = space_url.split("/spaces/")
        if len(parts) > 1:
            return parts[1].split("/")[0]
    except Exception as e:
        print(f"Error extracting space key: {e}")
    return ""

def fetch_confluence_pages(sync):
    try:
        api_key = decrypt_api_key(sync.credential._api_key)
        email = sync.credential.email
        base_url = get_confluence_base_url(sync.space_url)
        space_key = extract_space_key(sync.space_url)
        cql_query = f'space="{space_key}"'
        query_params = {
            "cql": cql_query,
            "expand": "body.storage,version",
            "limit": 100,  # Adjust limit as needed
        }
        query_string = urlencode(query_params)
        url = f"{base_url}/wiki/rest/api/content/search?{query_string}"

        auth = (email, api_key)
        headers = {
            "Accept": "application/json"
        }

        response = requests.get(url, auth=auth, headers=headers)
        response.raise_for_status()

        pages = response.json().get("results", [])

        for page in pages:
            title = page.get("title", "")
            content = page.get("body", {}).get("storage", {}).get("value", "")
            last_updated = page.get("version", {}).get("when", "")
            page_url = f"{base_url}/wiki{page.get('_links', {}).get('webui', '')}"

            ConfluencePage.objects.update_or_create(
                sync=sync,
                title=title,
                defaults={
                    "content": content,
                    "url": page_url,
                    "last_updated": last_updated
                }
            )

        print(f"Successfully fetched {len(pages)} pages from Confluence space{sync.space_url}")

    except Exception as e:

        print(f"Request error while fetching Confluence pages: {e}")

def ingest_confluence_pages(sync):
    pages = ConfluencePage.objects.filter(sync=sync)
    for page in pages:
        save_document(
            company=sync.chatBot.company,
            source="confluence",
            source_id=page.id,
            content=page.content
        )