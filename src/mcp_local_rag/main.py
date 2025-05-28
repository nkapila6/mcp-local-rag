#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import asyncio
import logging
from typing import List, Dict, Optional
from importlib.resources import files

from mediapipe.tasks import python
from mediapipe.tasks.python import text
from duckduckgo_search import DDGS
from lxml import html
import httpx

# https://modelcontextprotocol.io/quickstart/server
from mcp.server.fastmcp import FastMCP

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

mcp = FastMCP("RAG Web Search", dependencies=[
    "mediapipe", "duckduckgo-search", "httpx"])

# Global constant for content length limit
CONTENT_MAX_LENGTH = 16_000
CONTENT_FETCH_TIMEOUT = 30

# Dynamically locate embedder.tflite within the installed package
# PATH = "src/mcp_local_rag/embedder/embedder.tflite"
PATH = files('mcp_local_rag').joinpath('embedder/embedder.tflite')

# Initialize TextEmbedder globally for efficiency
try:
    BASE_OPTIONS = python.BaseOptions(model_asset_path=PATH)
    L2_NORMALIZE, QUANTIZE = True, False
    OPTIONS = text.TextEmbedderOptions(
        base_options=BASE_OPTIONS, l2_normalize=L2_NORMALIZE, quantize=QUANTIZE)
    EMBEDDER = text.TextEmbedder.create_from_options(OPTIONS)
except Exception as e:
    logging.error(f"Error initializing TextEmbedder: {e}")
    EMBEDDER = None # Handle potential initialization errors


@mcp.tool()
async def fetch_urls(urls: List[str]) -> List:
    """
    Fetches content from a list of URLs concurrently.

    Args:
        urls (List[str]): A list of URLs to fetch content from.

    Returns:
        List: A list of dictionaries containing the fetched content.
    """
    content_list = []
    # Create a single client session for all requests
    async with httpx.AsyncClient(follow_redirects=True) as client:
        tasks = [fetch_content(url, client) for url in urls]
        fetched_contents = await asyncio.gather(*tasks, return_exceptions=True) # Use asyncio.gather

    for url, content_or_exc in zip(urls, fetched_contents):
        if isinstance(content_or_exc, Exception):
            logging.warning(f"Request for {url} failed with exception: {content_or_exc}")
        elif content_or_exc:
            content_list.append({
                "type": "text",
                "url": url,
                "text": content_or_exc
            })
        # else: content was None (handled inside fetch_content) or empty string

    return content_list

@mcp.tool()
async def rag_search(query: str, num_results:int=10, top_k:int=5) -> Dict:
    """
    Search the web for a given query. Give back context to the LLM
    with a RAG-like similarity sort.

    Args:
        query (str): The query to search for.
        num_results (int): Number of results to return.
        top_k (int): Use top "k" results for content.

    Returns:
        List[Dict]: A list of dictionaries containing the fetched content.
    """
    ddgs = DDGS()
    loop = asyncio.get_running_loop()
    # Run synchronous ddgs.text in an executor to avoid blocking
    results = await loop.run_in_executor(None, ddgs.text, query, min(num_results, 20))
    if not EMBEDDER:
         return {"error": "TextEmbedder not initialized."}

    # Embedding might be CPU-bound, run in executor
    scored_results = await add_score_to_dict(query, results) # Await the async function
    sorted_scored_results = sort_by_score(scored_results) # Sorting is likely fast enough
    top_results = sorted_scored_results[0:top_k]
    top_urls = [site['href'] for site in top_results if site.get('href')]

    # fetch content using the new tool
    return await fetch_urls(top_urls)

async def add_score_to_dict(query: str, results: List[Dict]) -> List[Dict]:
    """
    Calculates similarity scores for search results against the query and adds them
    to the result dictionaries. Embeddings are computed concurrently.

    Args:
        query (str): The search query string.
        results (List[Dict]): A list of result dictionaries from the search provider.
                               Each dictionary is expected to have a 'body' key for embedding.
                               This list is modified in-place by adding a 'score' key.

    Returns:
        List[Dict]: The original list of result dictionaries, modified in-place
                    to include a 'score' key for each result. Results without a 'body',
                    or those encountering errors during embedding/similarity calculation,
                    will have a score of 0.0.
    """
    # EMBEDDER check is handled by the caller (rag_search)
    loop = asyncio.get_running_loop()
    # Run potentially CPU-bound embedding in an executor
    try:
        query_embedding = await loop.run_in_executor(None, EMBEDDER.embed, query)
    except Exception as e:
        logging.error(f"Error embedding query '{query}': {e}")
        # If query embedding fails, cannot score anything, return results with 0 score
        for result in results:
            result['score'] = 0.0
        return results

    embedding_tasks = []
    results_to_process = [] # Keep track of results that will have embeddings

    for result in results:
        if 'body' in result and result['body']:
            # Schedule embedding task in executor
            task = loop.run_in_executor(None, EMBEDDER.embed, result['body'])
            embedding_tasks.append(task)
            results_to_process.append(result)
        else:
            result['score'] = 0.0 # Assign default score if body is missing/empty

    # Wait for all embedding tasks to complete
    result_embeddings = await asyncio.gather(*embedding_tasks, return_exceptions=True)

    # Process results and calculate scores
    for i, result in enumerate(results_to_process):
        embedding_or_exc = result_embeddings[i]
        if isinstance(embedding_or_exc, Exception):
            logging.warning(f"Error embedding body for result {result.get('href', 'N/A')}: {embedding_or_exc}")
            result['score'] = 0.0 # Assign default score on embedding error
        else:
            try:
                result['score'] = text.TextEmbedder.cosine_similarity(
                                    embedding_or_exc.embeddings[0],
                                    query_embedding.embeddings[0])
            except Exception as e:
                logging.warning(f"Error calculating similarity for result {result.get('href', 'N/A')}: {e}")
                result['score'] = 0.0 # Assign default score on similarity calculation error

    return results # Return the original list with scores updated

def sort_by_score(results: List[Dict]) -> List[Dict]:
    """Sort results by similarity score."""
    return sorted(results, key=lambda x: x['score'], reverse=True)


async def fetch_content(url: str, client: httpx.AsyncClient, timeout: int = CONTENT_FETCH_TIMEOUT, max_length: int = CONTENT_MAX_LENGTH) -> Optional[str]:
    """Fetch content from a URL with timeout using an httpx.AsyncClient instance."""
    try:
        start_time = time.time()
        # Use the passed httpx client
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        }
        response = await client.get(url, timeout=timeout, headers=headers) # Await the get call
        response.raise_for_status() # Check for HTTP errors
        # response.text is a property, accessing it might implicitly await reading the body if not already done.
        # For explicit control or large files, use await response.aread()
        # content = BeautifulSoup(response.text, "html.parser").get_text(separator=' ', strip=True) # Old line
        parsed_html = html.fromstring(response.text)
        # Extract text nodes, excluding those within script and style tags
        text_nodes = parsed_html.xpath("//text()[not(ancestor::script or ancestor::style)]")
        # Join stripped text nodes with a single space, and strip overall result
        content = " ".join(t.strip() for t in text_nodes if t.strip()).strip()
        # Limit content length to max_length
        content = content[:max_length]
        if "ENABLE_SUMMARY" in os.environ:
            # summarize content (if possible please summarize the content)
            data = {
                "messages": [
                    {
                        "role": "system",
                        "content": \
    """
    ### Summary Rules:

    Please follow these guidelines to create a structured summary of the provided "Web Content", aiming for generality and effectiveness:

    1.  Core Extraction: Read the entire text to identify the core theme, main viewpoints, and key information points. Condense these into several summary dimensions (typically 3-5, adjustable based on content complexity).

    2.  Completeness and Accuracy: Strive for a comprehensive and accurate summary of the main content, retaining core arguments, important facts, and key details. Avoid oversimplification or omission of important information. Ensure accuracy for specific information like data, percentages, and times.

    3.  Hierarchical Structure: It is recommended to use a "General-Specific-General" structure:
        *   Overall Overview: Briefly explain the webpage's theme, core content, or main function/purpose.
        *   Detailed Points: Clearly list key information and main viewpoints around the core theme or different aspects/modules. For example: "Core Theme 1: [Relevant information and viewpoints]".
        *   Overall Induction: Summarize the overall situation of the webpage content, main conclusions, or potential trends.

    4.  Emphasis on Key Information: Pay special attention to retaining definitions, key terms, important data (if applicable), examples, and conclusions from the original text. If the content is time-sensitive and explicitly mentioned in the original text, it should be reflected.

    5.  Balance and Readability: While maintaining information density, ensure the summary is concise, well-organized, and easy to read. Key information and core viewpoints should be adequately represented.

    6.  Language Style: Use neutral, objective, concise, and professional language. Avoid redundant expressions and unnecessary complex terminology to ensure clear communication of information.
    """
                    },
                    {
                        "role": "user",
                        "content": content
                    }
                ],
                "model": "deepseek/deepseek-v3-base:free",
                "temperature": 1.0,
                "stream": False
            }
            # Make a POST request to the summarization API
            response = await httpx.AsyncClient(timeout=CONTENT_FETCH_TIMEOUT, follow_redirects=True).post(
                "https://proxy-ai.doocs.org/v1/chat/completions", json=data)
            response.raise_for_status()  # Check for HTTP errors
            # Extract the summary from the response
            summary = response.json().get('choices', [{}])[0].get('message', {}).get('content', '')
            if summary: content = summary
        logging.info(f"Fetched {url} in {time.time() - start_time:.2f}s")
        return content
    # Catch httpx specific exceptions and general exceptions
    except httpx.RequestError as e:
        logging.warning(f"Error fetching {url} with httpx: {type(e).__name__} - {str(e)}")
        return None
    except Exception as e: # Catch other potential errors (e.g., lxml parsing)
        logging.warning(f"An unexpected error occurred for {url}: {type(e).__name__} - {str(e)}")
        return None