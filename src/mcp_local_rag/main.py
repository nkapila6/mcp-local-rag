from ddgs import DDGS
from mediapipe.tasks.python import text

from typing import List, Dict
from importlib.resources import files

from .utils.fetch import fetch_embedder, fetch_all_content, get_path_str
from .utils.tools import sort_by_score

from fastmcp import FastMCP

mcp = FastMCP("RAG Web Search. Can perform Web Searches.")

@mcp.tool()
def rag_search(query: str, num_results:int=10, top_k:int=5) -> Dict:
    """
    Search the web for a given query. Give back context to the LLM
    with a RAG-like similarity sort.

    Args:
        query (str): The query to search for.
        num_results (int): Number of results to return.
        top_k (int): Use top "k" results for content.

    Returns:
        Dict of strings containing best search based on input query. Formatted in markdown.
    """
    ddgs = DDGS()
    results = ddgs.text(query, max_results=num_results) 
    scored_results = sort_by_score(add_score_to_dict(query, results))
    top_results = scored_results[0:top_k]

    # fetch content using thread pool
    md_content = fetch_all_content(top_results)

    # formatted as dict
    return {
        "content": md_content
            }
    
def add_score_to_dict(query: str, results: List[Dict]) -> List[Dict]:
    """Add similarity scores to search results."""

    path = get_path_str(files('mcp_local_rag.embedder').joinpath('embedder.tflite'))
    embedder = fetch_embedder(path)
    query_embedding = embedder.embed(query)

    for i in results:
        i['score'] = text.TextEmbedder.cosine_similarity(
                        embedder.embed(i['body']).embeddings[0],
                        query_embedding.embeddings[0])

    return results

if __name__ == "__main__":
    mcp.run()