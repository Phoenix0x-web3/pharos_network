from urllib.parse import urlparse, parse_qs, unquote


def query_to_json(url):
    parsed = urlparse(url)
    query_raw = parse_qs(parsed.query)

    query = {k: unquote(v[0]) for k, v in query_raw.items()}

    return query