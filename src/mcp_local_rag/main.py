from typing import List, Dict

from fastmcp import FastMCP

mcp = FastMCP("RAG Web Search. Can perform Web Searches.")

def add_score_to_dict(query: str, results: List[Dict]) -> List[Dict]:
    """Add similarity scores to search results."""
    # Import heavy dependencies only when needed (slow import!)
    from importlib.resources import files
    from mediapipe.tasks.python import text
    from .utils.fetch import fetch_embedder, get_path_str
    
    path = get_path_str(files('mcp_local_rag.embedder').joinpath('embedder.tflite'))
    embedder = fetch_embedder(path)
    query_embedding = embedder.embed(query)

    for i in results:
        i['score'] = text.TextEmbedder.cosine_similarity(
                        embedder.embed(i['body']).embeddings[0],
                        query_embedding.embeddings[0])

    return results

@mcp.tool()
def rag_search_ddgs(query: str, num_results:int=10, top_k:int=5, include_urls:bool=True) -> Dict:
    """
    Search the web for a given query using DuckDuckGo. Returns context to the LLM
    with RAG-like similarity scoring to prioritize the most relevant results.
    
    This tool fetches web search results, scores them by semantic similarity to the query
    using text embeddings, and returns the top-ranked content as markdown text.
    
    Args:
        query (str): The search query. Use natural language questions or keywords.
                    Example: "latest developments in quantum computing"
        num_results (int): Number of initial search results to fetch from DuckDuckGo.
                          More results provide better coverage but increase processing time.
                          Default: 10
        top_k (int): Number of top-scored results to include in the final output.
                    These are the most semantically relevant results after scoring.
                    Default: 5
        include_urls (bool): Whether to include source URLs in the results.
                            If True, each result includes its URL for citation.
                            Default: True
    
    Returns:
        Dict: A dictionary with a single key "content" containing the search results.
              The content is formatted as markdown text with the most relevant information
              from the top_k web pages. If include_urls is True, each section includes
              its source URL.
              
    Example:
        {"content": "# Result 1\\n\\nContent here...\\n\\nSource: https://example.com"}
    """
    
    # Import heavy dependencies only when tool is invoked
    from ddgs import DDGS
    from .utils.fetch import fetch_all_content
    from .utils.tools import sort_by_score
    
    ddgs = DDGS()
    results = ddgs.text(query, max_results=num_results) 
    scored_results = sort_by_score(add_score_to_dict(query, results))
    top_results = scored_results[0:top_k]

    # fetch content using thread pool
    md_content = fetch_all_content(top_results, include_urls)

    # formatted as dict
    return {
        "content": md_content
            }

@mcp.tool()
def rag_search_google(query: str, num_results:int=10, top_k:int=5, include_urls:bool=True) -> Dict:
    """
    Search on Google for a given query using ddgs. Give back context to the LLM
    with a RAG-like similarity sort.

    Args:
        query (str): The query to search for.
        num_results (int): Number of results to return.
        top_k (int): Use top "k" results for content.
        include_urls (bool): Whether to include URLs in the results.
        If True, the results will be a list of dictionaries with the following keys:
            - type: "text"
            - text: The content of the result
            - url: The URL of the result
        
    Returns:
        Dict of strings containing best search based on input query. Formatted in markdown.
    """
    # Import heavy dependencies only when tool is invoked
    from ddgs import DDGS
    from .utils.fetch import fetch_all_content
    from .utils.tools import sort_by_score
    
    ddgs = DDGS()
    results = ddgs.text(query, max_results=num_results, backend="google") 
    scored_results = sort_by_score(add_score_to_dict(query, results))
    top_results = scored_results[0:top_k]

    # fetch content using thread pool
    md_content = fetch_all_content(top_results, include_urls)

    # formatted as dict
    return {
        "content": md_content
            }
    
def _deep_research_internal(search_terms:List[str], backends:List[str], num_results_per_term:int=5,top_k_per_term:int=3, include_urls:bool=True)->Dict:
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

    # lazy load
    from ddgs import DDGS
    from .utils.fetch import fetch_all_content
    from .utils.tools import sort_by_score

    ddgs = DDGS()
    all_results = []
    search_summary = {}
    
    # search each term on all specified backends
    for term in search_terms:
        search_summary[term] = {backend: 0 for backend in backends}
        
        for backend in backends:
            try:
                if backend == "duckduckgo":
                    results = ddgs.text(term, max_results=num_results_per_term)
                else:
                    results = ddgs.text(term, max_results=num_results_per_term, backend=backend)
                if results:
                    scored_results = sort_by_score(add_score_to_dict(term, results))
                    top_results = scored_results[0:top_k_per_term]
                    all_results.extend(top_results)
                    search_summary[term][backend] = len(top_results)
            except Exception as e:
                print(f"Error searching {backend} for '{term}': {e}")
    
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
    md_content = fetch_all_content(unique_results, include_urls)
    
    return {
        "search_terms": search_terms,
        "backends": backends,
        "search_summary": search_summary,
        "total_unique_results": len(unique_results),
        "content": md_content
    }

@mcp.tool()
def deep_research(
    search_terms: List[str], 
    backends: List[str] | None = None,
    num_results_per_term: int = 10, 
    top_k_per_term: int = 3, 
    include_urls: bool = True
) -> Dict:
    """
    Perform deep research across multiple search terms using specified search backends.
    This tool aggregates results from multiple searches across chosen engines, scores them 
    by relevance, and returns the most relevant content with duplicates removed.
    Perfect for comprehensive research on a topic.
    
    Available backends: bing, brave, duckduckgo, google, grokipedia, mojeek, yandex, yahoo, wikipedia
    
    USAGE GUIDANCE FOR LLM:
    1. Ask the user which backend(s) they prefer, OR
    2. Choose appropriate backend(s) based on context:
       - ["duckduckgo"] - Privacy-focused, general search
       - ["google"] - Comprehensive results, best for technical queries
       - ["duckduckgo", "google"] - Maximum coverage (default)
       - ["wikipedia"] - Factual/encyclopedia content
       - ["bing", "google"] - Balanced commercial engines
       - Multiple backends for broader research coverage
    
    3. For specific use cases, consider:
       - deep_research_google() - shortcut for Google-only
       - deep_research_ddgs() - shortcut for DuckDuckGo-only
    
    Args:
        search_terms (List[str]): List of search terms to research. Provide multiple 
                                  related search queries for comprehensive coverage.
                                  Example: ["machine learning fundamentals", "neural networks", "deep learning best practices"]
        backends (List[str] | None): List of search backends to use. Defaults to ["duckduckgo", "google"].
                             Can include: bing, brave, duckduckgo, google, grokipedia, 
                             mojeek, yandex, yahoo, wikipedia. If None, uses default.
        num_results_per_term (int): Number of results to fetch per search term per backend.
        top_k_per_term (int): Number of top scored results to keep per search term per backend.
        include_urls (bool): Whether to include URLs in the results.
    
    Returns:
        Dict containing aggregated research results from all search terms and specified backends,
        with duplicates removed.
    """

    # safe default if none is given
    if backends is None:
        backends = ["duckduckgo", "google"]

    return _deep_research_internal(
        search_terms=search_terms,
        backends=backends,
        num_results_per_term=num_results_per_term,
        top_k_per_term=top_k_per_term,
        include_urls=include_urls
    )


@mcp.tool()
def deep_research_google(search_terms: List[str], num_results_per_term:int=10, top_k_per_term:int=3, include_urls:bool=True) -> Dict:
    """
    Perform deep research across multiple search terms using ONLY Google.
    Aggregates results from multiple Google searches, scores them by relevance,
    and returns the most relevant content with duplicates removed.
    
    Args:
        search_terms (List[str]): List of search terms to research. The LLM should provide 
                                  multiple related search queries for comprehensive coverage.
        num_results_per_term (int): Number of results to fetch per search term.
        top_k_per_term (int): Number of top scored results to keep per search term.
        include_urls (bool): Whether to include URLs in the results.
    
    Returns:
        Dict containing aggregated research results from all search terms (Google only),
        with duplicates removed.
    """
    return _deep_research_internal(
        search_terms=search_terms,
        backends=["google"],
        num_results_per_term=num_results_per_term,
        top_k_per_term=top_k_per_term,
        include_urls=include_urls
    )


@mcp.tool()
def deep_research_ddgs(search_terms: List[str], num_results_per_term:int=10, top_k_per_term:int=3, include_urls:bool=True) -> Dict:
    """
    Perform deep research across multiple search terms using ONLY DuckDuckGo.
    Aggregates results from multiple DuckDuckGo searches, scores them by relevance,
    and returns the most relevant content with duplicates removed.
    
    Args:
        search_terms (List[str]): List of search terms to research. The LLM should provide 
                                  multiple related search queries for comprehensive coverage.
        num_results_per_term (int): Number of results to fetch per search term.
        top_k_per_term (int): Number of top scored results to keep per search term.
        include_urls (bool): Whether to include URLs in the results.
    
    Returns:
        Dict containing aggregated research results from all search terms (DuckDuckGo only),
        with duplicates removed.
    """
    return _deep_research_internal(
        search_terms=search_terms,
        backends=["duckduckgo"],
        num_results_per_term=num_results_per_term,
        top_k_per_term=top_k_per_term,
        include_urls=include_urls
    )

if __name__ == "__main__":
    mcp.run()