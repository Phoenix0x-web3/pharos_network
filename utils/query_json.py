from urllib.parse import urlparse, parse_qs, unquote, urlencode, quote, urlunparse

def query_to_json(url):
    parsed = urlparse(url)
    query_raw = parse_qs(parsed.query)

    query = {k: unquote(v[0]) for k, v in query_raw.items()}

    return query

def json_to_query(url: str, params: dict) -> str:
    parsed = urlparse(url)

    query = urlencode(params)

    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        query,
        parsed.fragment,
    ))