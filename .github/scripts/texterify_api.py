"""
Shared HTTP client setup for talking to Texterify's API directly, instead of via
txty-cli (its `download` and `add` commands cover both directions of this
pipeline, but add nothing over calling the API ourselves).

Auth is two headers, `Auth-Email`/`Auth-Secret` - the same mechanism the
official CLI uses.

Required environment variables:
    TXTY_AUTH_EMAIL, TXTY_AUTH_SECRET  - from the Texterify access token page
    TXTY_PROJECT_ID                    - the Texterify project id

Optional environment variables:
    TXTY_API_BASE_URL - base URL of the Texterify API
        (default: https://app.texterify.com/api)
    TXTY_API_VERSION - API version path segment (default: "v1")
"""

import os

import requests

API_BASE_URL = os.environ.get("TXTY_API_BASE_URL", "https://app.texterify.com/api")
API_VERSION = os.environ.get("TXTY_API_VERSION", "v1")
PROJECT_ID = os.environ["TXTY_PROJECT_ID"]


def api_url(path: str) -> str:
    """Build a full Texterify API URL from a path fragment."""
    return f"{API_BASE_URL}/{API_VERSION}/{path}"


def make_session() -> requests.Session:
    """Return a requests.Session authenticated with Texterify's auth headers."""
    session = requests.Session()
    session.headers.update(
        {
            "Auth-Email": os.environ["TXTY_AUTH_EMAIL"],
            "Auth-Secret": os.environ["TXTY_AUTH_SECRET"],
            "Accept": "application/json",
        }
    )
    return session
