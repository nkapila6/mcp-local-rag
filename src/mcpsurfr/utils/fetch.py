#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on 2025-06-04 22:55:29 Wednesday

@author: Nikhil Kapila
"""

import logging, re, time

from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import primp

from importlib.resources import as_file

from .extract import extract_main_text

# stdout is the MCP protocol channel in stdio mode, so never print(); log to stderr
log = logging.getLogger(__name__)

# primp's text_plain (the fallback) draws HTML tables with box characters,
# which eat the 10k budget on table-heavy pages
_BOX_CHARS = re.compile(r"[─-╿]+")
_TEXT_TYPES = ("text/html", "application/xhtml", "text/plain")

def get_path_str(resource)->str:
    with as_file(resource) as path:
        return str(path)
    
# cached: loading takes ~50ms, and the embedder keeps per-shape plans warm across searches
@lru_cache(maxsize=1)
def fetch_embedder(path:str, l2_normalize:bool=True):
    from .embedder import TextEmbedder
    return TextEmbedder(path, l2_normalize=l2_normalize)

def fetch_content(url: str, timeout: int = 5) -> Optional[str]:
    """Fetch content from a URL with timeout."""
    try:
        start_time = time.time()
        # impersonating a real browser gets past "set a user agent" walls (Wikipedia,
        # GitHub) that served plain requests a stub page
        client = primp.Client(impersonate="random", timeout=timeout, follow_redirects=True)
        response = client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "text/html").lower()
        if not content_type.startswith(_TEXT_TYPES):
            log.info("Skipping %s: %s", url, content_type)
            return None
        # primp decodes the charset (header or <meta>); extraction drops nav menus,
        # banners and footers. primp's own html->text is the fallback.
        content = None
        if not content_type.startswith("text/plain"):
            content = extract_main_text(response.text)
        if not content:
            content = " ".join(_BOX_CHARS.sub(" ", response.text_plain).split())
        log.debug("Fetched %s in %.2fs", url, time.time() - start_time)
        return content[:10000]  # limitting content to 10k
    except primp.PrimpError as e:
        log.warning("Error fetching %s: %s - %s", url, type(e).__name__, e)
        return None

def fetch_all_content(results: List[Dict], include_urls:bool=True) -> List[str]:
    """Fetch content from all URLs using a thread pool."""
    urls = [site['href'] for site in results if site.get('href')]
    
    # parallelize requests
    with ThreadPoolExecutor(max_workers=5) as executor:
        # submit fetch tasks to executor
        future_to_url = {executor.submit(fetch_content, url): url for url in urls}
        
        content_list = []
        for future, url in future_to_url.items():
            try:
                content = future.result()
                if content:
                    result = {
                        "type": "text",
                        "text": content,
                    }
                    if include_urls:
                        result["url"] = url
                    content_list.append(result)
            except Exception as e:
                log.warning("Request failed with exception: %s", e)
        
    return content_list