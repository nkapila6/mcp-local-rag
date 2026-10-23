import asyncio, base64, logging
from collections import OrderedDict
from pathlib import Path
from typing import List, Dict

from fastmcp import FastMCP, Context
from fastmcp.server.providers.skills import SkillsDirectoryProvider
from mcp.types import ElicitRequest, ElicitRequestFormParams, Icon, InputRequiredResult, ToolAnnotations

_HERE = Path(__file__).parent

# ddgs text backends. "auto" is ddgs's metasearch: it queries several engines in
# parallel and moves on when one is blocked, so it's the dependable default.
BACKENDS = ("auto", "brave", "duckduckgo", "google", "grokipedia", "mojeek", "startpage", "wikipedia", "yahoo")

INSTRUCTIONS = """\
Local web search with on-device re-ranking, no API keys.

- search: use this first. Returns only the passages that answer the query (about a tenth of the
  tokens of full pages). Pass `keywords` with terms and synonyms a good answer would contain.
- rag_search_ddgs: full pages as text, for when the user wants whole pages.
- deep_research: broader topics. Give it 2-5 specific, related search_terms. Default backend is "auto".
- Google often blocks scrapers. When it returns nothing, the server retries with "auto" and says so.
- Cite the source URLs.

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

# last few search() results, so answering the "full pages?" question doesn't search
# and fetch again (on the 2026-07-28 protocol the tool re-runs with the answer)
_recent: "OrderedDict[tuple, Dict]" = OrderedDict()

def _can_ask(ctx: Context) -> bool:
    caps = getattr(ctx.session, "client_capabilities", None)
    return bool(caps and getattr(caps, "elicitation", None))

def _ask_full_pages(message: str) -> InputRequiredResult:
    params = ElicitRequestFormParams(
        message=message,
        requested_schema={
            "type": "object",
            "properties": {"full_pages": {"type": "boolean", "title": "Return full pages instead"}},
            "required": ["full_pages"],
        },
    )
    return InputRequiredResult(
        result_type="input_required",
        input_requests={"full_pages": ElicitRequest(method="elicitation/create", params=params)},
    )

@mcp.tool(title="Search (passages)", annotations=_READ_ONLY, icons=[_ICON])
async def search(
    ctx: Context,
    query: str,
    keywords: List[str] | None = None,
    num_results: int = 10,
    top_pages: int = 5,
    max_passages: int = 8,
    backend: str = "auto",
) -> Dict | InputRequiredResult:
    """
    Search the web and return only the passages that answer the query, not whole
    pages: usually about a tenth of the text of rag_search_ddgs. Use this first.

    Tiers, cheapest first:
    1. Search, then keep the top_pages results whose title/snippet match best.
    2. Fetch those pages, split them into ~600-char passages, keyword-match them (BM25)
       against the query plus `keywords`.
    3. Only if that leaves too many candidates, or matches nothing (a paraphrase),
       the local embedder ranks them by meaning.
    If nothing matched the keywords and the client can show questions, the user is
    asked whether they want the full pages instead.

    Args:
        query (str): The question or topic, in natural language.
        keywords (List[str] | None): Terms a good answer would contain, including
            synonyms and exact phrases. Example for "how do I make postgres faster":
            ["index", "EXPLAIN ANALYZE", "query planner", "vacuum"]. Strongly improves results.
        num_results (int): Search results to consider. Default 10.
        top_pages (int): Pages to fetch and split. Default 5.
        max_passages (int): Passages to return. Default 8.
        backend (str): Search backend, same names as deep_research. Default "auto".

    Returns:
        Dict with "passages": [{"url", "heading", "text", "score"}, ...] best first, and
        "tier" ("keywords", "keywords+semantic" or "semantic") saying what picked them.
        If the user asked for full pages: "content": [{"type", "text", "url"}, ...] instead.
    """
    keywords = keywords or []
    key = (query, tuple(keywords), num_results, top_pages, max_passages, backend)
    found = _recent.get(key) or await _find_passages(ctx, *key[:1], keywords, *key[2:])
    _recent[key] = found
    _recent.move_to_end(key)
    while len(_recent) > 8:
        _recent.popitem(last=False)

    result = {k: found[k] for k in ("query", "passages", "tier", "pages_fetched", "passages_considered")}
    if found["tier"] != "semantic" or not found["pages"]:
        return result

    # low confidence: no passage matched the keywords. Offer the old full-page dump.
    message = (f"No passage matched the keywords for {query!r}, so these were picked by "
               "meaning alone and may be off. Return the full pages instead? (about 10x more text)")
    if not _can_ask(ctx):
        result["note"] = "Low confidence: nothing matched the keywords. rag_search_ddgs returns full pages."
        return result
    if ctx._is_modern_protocol():
        if ctx.input_responses is None:
            return _ask_full_pages(message)
        answer = ctx.input_responses.get("full_pages")
        wants_pages = bool(answer and answer.action == "accept" and answer.content.get("full_pages"))
    else:
        try:
            answer = await ctx.elicit(message, response_type=bool)
            wants_pages = answer.action == "accept" and bool(answer.data)
        except Exception as e:
            log.warning("Couldn't ask about full pages: %s", e)
            wants_pages = False
    if not wants_pages:
        return result
    return {"query": query, "content": [
        {"type": "text", "text": " ".join(t for _, t in blocks)[:10000], "url": url}
        for url, blocks in found["pages"].items()
    ]}

async def _find_passages(ctx: Context, query: str, keywords: List[str], num_results: int,
                         top_pages: int, max_passages: int, backend: str) -> Dict:
    from mcpsurfr.utils.fetch import fetch_all_blocks
    from mcpsurfr.utils.passages import build_passages, keyword_scores, select

    empty = {"query": query, "passages": [], "tier": None, "pages_fetched": 0, "passages_considered": 0, "pages": {}}
    if backend not in BACKENDS:
        await ctx.warning(f"Unknown backend {backend!r}, using auto. Available: {', '.join(BACKENDS)}")
        backend = "auto"
    await ctx.report_progress(0, 4, f"Searching {backend} for {query!r}")
    results = await _search(ctx, query, backend, num_results)
    if not results and backend != "auto":
        await ctx.warning(f"Retrying {query!r} with auto, since {backend} returned nothing")
        results = await _search(ctx, query, "auto", num_results)
    results = [r for r in results if r.get("href")]
    if not results:
        return empty

    # tier 1: pick pages by their search snippets, keyword hits first, then meaning
    await ctx.report_progress(1, 4, f"Picking {top_pages} of {len(results)} pages")
    results = await asyncio.to_thread(add_score_to_dict, query, results)
    snippets = [{"heading": r.get("title", ""), "text": r.get("body", "")} for r in results]
    hits = keyword_scores(query, keywords, snippets)
    ranked = sorted(zip(results, hits), key=lambda x: (x[1] > 0, x[1] + x[0]["score"]), reverse=True)
    urls = [r["href"] for r, _ in ranked[:top_pages]]

    await ctx.report_progress(2, 4, f"Fetching {len(urls)} pages")
    pages = await asyncio.to_thread(fetch_all_blocks, urls)
    if len(pages) < len(urls):
        await ctx.info(f"{len(urls) - len(pages)} of {len(urls)} pages couldn't be fetched (blocked, not HTML, or timed out)")
    passages, seen = [], set()
    for url in urls:
        for p in build_passages(url, pages.get(url, [])):
            # mirrors and syndicated copies repeat the same text across pages
            key = " ".join(p["text"].lower().split())[:200]
            if key not in seen:
                seen.add(key)
                passages.append(p)

    # tiers 2 and 3: keywords, then the embedder only if it's needed
    await ctx.report_progress(3, 4, f"Scoring {len(passages)} passages")
    scores = keyword_scores(query, keywords, passages)
    embedder = await asyncio.to_thread(_embedder)
    chosen, tier = await asyncio.to_thread(select, query, passages, scores, max_passages, embedder.embed_batch)
    await ctx.report_progress(4, 4, "Done")
    return {"query": query, "passages": chosen, "tier": tier, "pages_fetched": len(pages),
            "passages_considered": len(passages), "pages": {u: pages[u] for u in urls if u in pages}}

def _embedder():
    from importlib.resources import files
    from mcpsurfr.utils.fetch import fetch_embedder, get_path_str
    return fetch_embedder(get_path_str(files('mcpsurfr.embedder').joinpath('embedder.tflite')))

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
