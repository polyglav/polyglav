def format_results(query: str, results: list[dict]) -> str:
    lines = [f'Search results for "{query}":\n']
    for i, r in enumerate(results, 1):
        title = r.get('title', '')
        url = r.get('url', '')
        snippet = r.get('snippet', '')
        lines.append(f'  {i}. {title}')
        lines.append(f'     {url}')
        if snippet:
            lines.append(f'     ({snippet})')
        lines.append('')
    return '\n'.join(lines)


def format_context(query: str, results: list[dict]) -> str:
    parts = [f'Web search results for "{query}":']
    for i, r in enumerate(results, 1):
        title = r.get('title', '')
        url = r.get('url', '')
        snippet = r.get('snippet', '')
        parts.append(f'{i}. {title}')
        parts.append(f'   URL: {url}')
        if snippet:
            parts.append(f'   Snippet: {snippet}')
    return '\n'.join(parts)
