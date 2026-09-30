"""Parse local configuration as data; never execute shell or print secrets."""
from pathlib import Path
import re
import shlex
from urllib.parse import urlsplit

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / 'api-config.local.env'


def read_config(path=DEFAULT_CONFIG):
    values = {}
    wanted = ('API_BASE_URL', 'API_KEY', 'API_MODEL')
    for line in Path(path).read_text().splitlines():
        match = re.match(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$', line)
        if not match or match[1] not in wanted:
            continue
        key = match[1]
        if key in values:
            raise ValueError('Duplicate config field: ' + key)
        parts = shlex.split(match[2], comments=True, posix=True)
        if len(parts) > 1:
            raise ValueError('Quote whitespace in config field: ' + key)
        values[key] = parts[0] if parts else ''
    missing = [k for k in wanted if not values.get(k)]
    if missing:
        raise ValueError('Missing config fields: ' + ', '.join(missing))
    url = urlsplit(values['API_BASE_URL'])
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('API_BASE_URL must be an HTTPS base URL without embedded credentials or query')
    return values
