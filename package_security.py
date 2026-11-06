"""Keep ephemeral signed URLs and login/session material out of shareable text."""
import re
from urllib.parse import urlparse, urlunparse

# Captures HTTP URLs until whitespace or a Markdown/HTML URL delimiter.
URL = re.compile(r'https://[^\s<>"\']+', re.I)
SENSITIVE_PARAMS = ('signature=', 'token=', 'googleaccessid=', 'expires=', 'x-goog-', 'x-amz-')


def redact_signed_urls(value: str) -> str:
    def replace(match):
        text = match.group(0)
        # Preserve final Markdown brackets so the text stays readable.
        suffix = ''
        while text and text[-1] in ').,;':
            suffix = text[-1] + suffix
            text = text[:-1]
        parts = urlparse(text)
        if parts.hostname in ('storage.googleapis.com', 'cdn.qwiklabs.com') or any(x in parts.query.lower() for x in SENSITIVE_PARAMS):
            return urlunparse((parts.scheme, parts.netloc, parts.path, '', '', '')) + suffix
        return text + suffix
    return URL.sub(replace, value)


def scrub_data(value):
    if isinstance(value, dict):
        return {k: scrub_data(v) for k, v in value.items()
                if k.lower() not in {'cookies', 'cookie', 'authorization', 'access_token', 'refresh_token', 'csrf'}}
    if isinstance(value, list):
        return [scrub_data(v) for v in value]
    if isinstance(value, str):
        return redact_signed_urls(value)
    return value
