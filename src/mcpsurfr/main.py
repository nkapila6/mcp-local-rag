import asyncio, base64, logging
from pathlib import Path
from typing import List, Dict

from fastmcp import FastMCP, Context
from fastmcp.server.providers.skills import SkillsDirectoryProvider
from mcp.types import Icon, ToolAnnotations

_HERE = Path(__file__).parent

# ddgs text backends. "auto" is ddgs's metasearch: it queries several engines in
# parallel and moves on when one is blocked, so it's the dependable default.
BACKENDS = ("auto", "brave", "duckduckgo", "google", "grokipedia", "mojeek", "startpage", "wikipedia", "yahoo")

INSTRUCTIONS = """\
Local web search with on-device re-ranking, no API keys.

- rag_search_ddgs: the default for lookups. Uses ddgs "auto" metasearch, which tries several engines and skips blocked ones.
- deep_research: broader topics. Give it 2-5 specific, related search_terms. Default backend is "auto".
- Google often blocks scrapers. When it returns nothing, the server retries with "auto" and says so.
- Results are page text (up to 10k chars each) with source URLs. Cite the URLs.

Full guide: the skill resource skill://mcpsurfr-search/SKILL.md"""

_ICON = Icon(
    src="data:image/svg+xml;base64," + base64.b64encode((_HERE / "icon.svg").read_bytes()).decode(),
    mime_type="image/svg+xml",
    sizes=["any"],
)
# these tools only read the web, so clients can treat them as safe to call
_READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)

mcp = FastMCP("mcpsurfr", instructions=INSTRUCTIONS, website_url="https://github.com/nkapila6/mcpsurfr", icons=[_ICON])
# serves the bundled skill as resources, so clients don't have to install it by hand
mcp.add_provider(SkillsDirectoryProvider(roots=_HERE / "skills"))
log = logging.getLogger(__name__)

def add_score_to_dict(query: str, results: List[Dict]) -> List[Dict]:
    """Add similarity scores to search results."""
    # Import heavy dependencies only when needed (slow import!)
    from importlib.resources import files
    from mcpsurfr.utils.fetch import fetch_embedder, get_path_str
    from mcpsurfr.utils.embedder import cosine_similarity

    path = get_path_str(files('mcpsurfr.embedder').joinpath('embedder.tflite'))
    embedder = fetch_embedder(path)
    query_embedding = embedder.embed(query)
    bodies = embedder.embed_batch([i['body'] for i in results])

    for i, body in zip(results, bodies):
        i['score'] = cosine_similarity(body, query_embedding)

    return results

# the search, ranking and fetching below are all blocking, so they run on threads
# to keep the server answering pings and progress while a search is in flight

async def _search(ctx: Context, query: str, backend: str, max_results: int) -> List[Dict]:
    from ddgs import DDGS
    try:
        return await asyncio.to_thread(DDGS().text, query, max_results=max_results, backend=backend)
    except Exception as e:
        # ddgs raises when an engine returns nothing, which is usually a block
        log.warning("Error searching %s for %r: %s", backend, query, e)
        await ctx.warning(f"{backend} returned no results for {query!r} ({e})")
        return []

async def _fetch(ctx: Context, results: List[Dict], include_urls: bool) -> List[Dict]:
    from mcpsurfr.utils.fetch import fetch_all_content
    content = await asyncio.to_thread(fetch_all_content, results, include_urls)
    missing = len([r for r in results if r.get('href')]) - len(content)
    if missing:
        await ctx.info(f"{missing} of {len(results)} pages couldn't be fetched (blocked, not HTML, or timed out)")
    return content

async def _rag_search(ctx: Context, query: str, backend: str, num_results: int, top_k: int, include_urls: bool) -> Dict:
    from mcpsurfr.utils.tools import sort_by_score

    await ctx.report_progress(0, 3, f"Searching {backend} for {query!r}")
    results = await _search(ctx, query, backend, num_results)
    if not results and backend != "auto":
        await ctx.warning(f"Retrying {query!r} with auto, since {backend} returned nothing")
        results = await _search(ctx, query, "auto", num_results)
    if not results:
        return {"content": []}

    await ctx.report_progress(1, 3, f"Ranking {len(results)} results")
    scored_results = sort_by_score(await asyncio.to_thread(add_score_to_dict, query, results))
    top_results = scored_results[0:top_k]

    await ctx.report_progress(2, 3, f"Fetching {len(top_results)} pages")
    md_content = await _fetch(ctx, top_results, include_urls)
    await ctx.report_progress(3, 3, "Done")
    return {
        "content": md_content
            }

@mcp.tool(title="Web search", annotations=_READ_ONLY, icons=[_ICON])
async def rag_search_ddgs(ctx: Context, query: str, num_results:int=10, top_k:int=5, include_urls:bool=True) -> Dict:
    """
    Search the web and return the most relevant pages as text. Default choice for lookups.
    Uses ddgs "auto" metasearch, which queries several engines (DuckDuckGo, Brave,
    Wikipedia, ...) and skips any that are blocked. Results are re-ranked locally
    by semantic similarity to the query before the top pages are fetched.

    Args:
        query (str): The search query. Use natural language questions or keywords.
                    Example: "latest developments in quantum computing"
        num_results (int): Number of initial search results to rank.
                          More results provide better coverage but increase processing time.
                          Default: 10
        top_k (int): Number of top-ranked pages to fetch and return.
                    Default: 5
        include_urls (bool): Whether to include each page's source URL for citation.
                            Default: True

    Returns:
        Dict: {"content": [{"type": "text", "text": <page text, up to 10k chars>, "url": <source>}, ...]}
              ordered by relevance. Pages that couldn't be fetched are left out.
    """
    return await _rag_search(ctx, query, "auto", num_results, top_k, include_urls)

@mcp.tool(title="Google search", annotations=_READ_ONLY, icons=[_ICON])
async def rag_search_google(ctx: Context, query: str, num_results:int=10, top_k:int=5, include_urls:bool=True) -> Dict:
    """
    Search Google and return the most relevant pages as text, re-ranked locally by
    semantic similarity. Google often blocks scrapers. When it returns nothing, this
    retries with ddgs "auto" metasearch and sends a warning saying so.

    Args:
        query (str): The query to search for.
        num_results (int): Number of initial search results to rank.
        top_k (int): Number of top-ranked pages to fetch and return.
        include_urls (bool): Whether to include each page's source URL.

    Returns:
        Dict: {"content": [{"type": "text", "text": <page text, up to 10k chars>, "url": <source>}, ...]}
    """
    return await _rag_search(ctx, query, "google", num_results, top_k, include_urls)

async def _deep_research_internal(ctx: Context, search_terms:List[str], backends:List[str], num_results_per_term:int=5,top_k_per_term:int=3, include_urls:bool=True)->Dict:
    """
    Internal function to perform deep research across multiple search term with the given backend engine in ddgs.

    Args:
        search_terms (List[str]): List of search terms to perform deep research on.
        backends (List[str]): List of search backends to use.
        num_results (int): Num of results to fetch per search term per engine.
        top_k (int): Number of top score to keep per search term per engine.
        include_urls (bool): whether to include urls in the results.

    Returns:
        Dict containing aggregated research results from all search terms and engines.
    """
    from mcpsurfr.utils.tools import sort_by_score

    # ddgs would silently swap an unknown name for "auto", so say so instead
    unknown = [b for b in backends if b not in BACKENDS]
    if unknown:
        await ctx.warning(f"Unknown backends {unknown} skipped. Available: {', '.join(BACKENDS)}")
    backends = [b for b in backends if b in BACKENDS] or ["auto"]

    all_results = []
    search_summary = {}
    total = len(search_terms) * len(backends) + 1
    step = 0

    # search each term on all specified backends
    for term in search_terms:
        search_summary[term] = {backend: 0 for backend in backends}

        for backend in backends:
            await ctx.report_progress(step, total, f"Searching {backend} for {term!r}")
            step += 1
            results = await _search(ctx, term, backend, num_results_per_term)
            if results:
                scored_results = sort_by_score(await asyncio.to_thread(add_score_to_dict, term, results))
                top_results = scored_results[0:top_k_per_term]
                all_results.extend(top_results)
                search_summary[term][backend] = len(top_results)

    # every chosen engine came back empty (Google blocking, usually): fall back to auto
    if not all_results and backends != ["auto"]:
        await ctx.warning(f"{', '.join(backends)} returned nothing, retrying every term with auto")
        for term in search_terms:
            results = await _search(ctx, term, "auto", num_results_per_term)
            if results:
                scored_results = sort_by_score(await asyncio.to_thread(add_score_to_dict, term, results))
                all_results.extend(scored_results[0:top_k_per_term])
                search_summary[term]["auto"] = len(scored_results[0:top_k_per_term])

    # remove duplicates and keep high scores
    seen_urls = {}
    unique_results = []
    for result in all_results:
        url = result.get('href', '')
        if url:
            # Keep the result with the highest score for duplicate URLs
            if url not in seen_urls or result.get('score', 0) > seen_urls[url].get('score', 0):
                if url in seen_urls:
                    # Replace lower scored duplicate
                    unique_results.remove(seen_urls[url])
                seen_urls[url] = result
                unique_results.append(result)

    # fetch content from final list of results
    await ctx.report_progress(step, total, f"Fetching {len(unique_results)} pages")
    md_content = await _fetch(ctx, unique_results, include_urls)
    await ctx.report_progress(total, total, "Done")

    return {
        "search_terms": search_terms,
        "backends": backends,
        "search_summary": search_summary,
        "total_unique_results": len(unique_results),
        "content": md_content
    }

@mcp.tool(title="Deep research", annotations=_READ_ONLY, icons=[_ICON])
async def deep_research(
    ctx: Context,
    search_terms: List[str],
    backends: List[str] | None = None,
    num_results_per_term: int = 10,
    top_k_per_term: int = 3,
    include_urls: bool = True
) -> Dict:
    """
    Research a topic across several search terms and engines. Each term is searched on
    each backend, results are re-ranked locally by relevance, duplicates are removed,
    and the best pages are fetched as text.

    Backends: auto, brave, duckduckgo, google, grokipedia, mojeek, startpage, wikipedia, yahoo.
    - "auto" (default): ddgs metasearch over several engines, skipping blocked ones. Most reliable.
    - "brave": fast and usually available.
    - "wikipedia": exact article lookups, best with title-like terms.
    - "google", "startpage", "yahoo", "mojeek": often blocked. Empty engines are reported
      as warnings, and if every chosen engine is empty the terms are retried with "auto".

    Args:
        search_terms (List[str]): 2-5 specific, related search queries covering different angles.
                                  Example: ["postgres query planner", "postgres index types", "EXPLAIN ANALYZE tutorial"]
        backends (List[str] | None): Backends to use. Defaults to ["auto"]. Unknown names are skipped with a warning.
        num_results_per_term (int): Number of results to rank per search term per backend.
        top_k_per_term (int): Number of top-ranked results to keep per search term per backend.
        include_urls (bool): Whether to include each page's source URL.

    Returns:
        Dict with search_terms, backends, search_summary (results kept per term and backend),
        total_unique_results, and content: [{"type": "text", "text": ..., "url": ...}, ...].
    """

    # safe default if none is given
    if backends is None:
        backends = ["auto"]

    return await _deep_research_internal(
        ctx,
        search_terms=search_terms,
        backends=backends,
        num_results_per_term=num_results_per_term,
        top_k_per_term=top_k_per_term,
        include_urls=include_urls
    )


@mcp.tool(title="Deep research (Google)", annotations=_READ_ONLY, icons=[_ICON])
async def deep_research_google(ctx: Context, search_terms: List[str], num_results_per_term:int=10, top_k_per_term:int=3, include_urls:bool=True) -> Dict:
    """
    Deep research using only Google: each term is searched, re-ranked locally, de-duplicated
    and the best pages fetched as text. Google often blocks scrapers. If it returns
    nothing, the terms are retried with ddgs "auto" metasearch and a warning is sent.

    Args:
        search_terms (List[str]): 2-5 specific, related search queries.
        num_results_per_term (int): Number of results to rank per search term.
        top_k_per_term (int): Number of top-ranked results to keep per search term.
        include_urls (bool): Whether to include each page's source URL.

    Returns:
        Same shape as deep_research.
    """
    return await _deep_research_internal(
        ctx,
        search_terms=search_terms,
        backends=["google"],
        num_results_per_term=num_results_per_term,
        top_k_per_term=top_k_per_term,
        include_urls=include_urls
    )


@mcp.tool(title="Deep research (ddgs auto)", annotations=_READ_ONLY, icons=[_ICON])
async def deep_research_ddgs(ctx: Context, search_terms: List[str], num_results_per_term:int=10, top_k_per_term:int=3, include_urls:bool=True) -> Dict:
    """
    Deep research using ddgs "auto" metasearch, which queries several engines per term
    and skips blocked ones. Results are re-ranked locally, de-duplicated and the best
    pages fetched as text. Same as deep_research with its default backend.

    Args:
        search_terms (List[str]): 2-5 specific, related search queries.
        num_results_per_term (int): Number of results to rank per search term.
        top_k_per_term (int): Number of top-ranked results to keep per search term.
        include_urls (bool): Whether to include each page's source URL.

    Returns:
        Same shape as deep_research.
    """
    return await _deep_research_internal(
        ctx,
        search_terms=search_terms,
        backends=["auto"],
        num_results_per_term=num_results_per_term,
        top_k_per_term=top_k_per_term,
        include_urls=include_urls
    )


@mcp.prompt(title="Research a topic", icons=[_ICON])
def research(topic: str) -> str:
    """Research a topic with deep_research and write a cited summary."""
    return (
        f"Research this topic: {topic}\n\n"
        "1. Come up with 3-5 specific search terms that cover different angles of it.\n"
        "2. Call deep_research with those terms (the default backend is fine).\n"
        "3. Write a concise summary. Cite the source URL for each claim, and point out "
        "where sources disagree or look out of date."
    )

if __name__ == "__main__":
    mcp.run()
