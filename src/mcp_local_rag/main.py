from duckduckgo_search import DDGS
from mediapipe.tasks import python
from mediapipe.tasks.python import text
from bs4 import BeautifulSoup
import requests
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Optional
import time
from importlib.resources import files

# imports from mcp
# https://modelcontextprotocol.io/quickstart/server
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("RAG Web Search", dependencies=["duckduckgo-search", "mediapipe", 
                                  "beautifulsoup4", "requests"])

# Dynamically locate embedder.tflite within the installed package
# PATH = "src/mcp_local_rag/embedder/embedder.tflite"
PATH = files('mcp_local_rag').joinpath('embedder/embedder.tflite')

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
    base_options = python.BaseOptions(model_asset_path=PATH)
    l2_normalize, quantize = True, False
    options = text.TextEmbedderOptions(
        base_options=base_options, l2_normalize=l2_normalize, quantize=quantize)
    embedder = text.TextEmbedder.create_from_options(options)
    query_embedding = embedder.embed(query)

    for i in results:
        i['score'] = text.TextEmbedder.cosine_similarity(
                        embedder.embed(i['body']).embeddings[0],
                        query_embedding.embeddings[0])

    return results

def sort_by_score(results: List[Dict]) -> List[Dict]:
    """Sort results by similarity score."""
    return sorted(results, key=lambda x: x['score'], reverse=True)

def fetch_content(url: str, timeout: int = 5) -> Optional[str]:
    """Fetch content from a URL with timeout."""
    try:
        start_time = time.time()
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        content = BeautifulSoup(response.text, "html.parser").get_text(separator=" ", strip=True)
        print(f"Fetched {url} in {time.time() - start_time:.2f}s")
        return content[:10000]  # limitting content to 10k
    except requests.RequestException as e:
        print(f"Error fetching {url}: {type(e).__name__} - {str(e)}")
        return None

def fetch_all_content(results: List[Dict]) -> List[str]:
    """Fetch content from all URLs using a thread pool."""
    urls = [site['href'] for site in results if site.get('href')]
    
    # parallelize requests
    with ThreadPoolExecutor(max_workers=5) as executor:
        # submit fetch tasks to executor
        future_to_url = {executor.submit(fetch_content, url): url for url in urls}
        
        content_list = []
        for future in future_to_url:
            try:
                content = future.result()
                if content:
                    content_list.append({
                        "type": "text",
                        "text": content
                    })
            except Exception as e:
                print(f"Request failed with exception: {e}")
        
    return content_list
