#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on 2025-06-04 22:55:29 Wednesday

@author: Nikhil Kapila
"""

import requests, time

from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup

from mediapipe.tasks import python
from mediapipe.tasks.python import text

from importlib.resources import as_file

def get_path_str(resource)->str:
    with as_file(resource) as path:
        return str(path)
    
def fetch_embedder(path:str, l2_normalize:bool=True, quantize:bool=False):# ->text.text_embedder.TextEmbedder:
    base_options = python.BaseOptions(model_asset_path=path)
    options = text.TextEmbedderOptions(
                            base_options=base_options, 
                            l2_normalize=l2_normalize, 
                            quantize=quantize)
    embedder = text.TextEmbedder.create_from_options(options)
    return embedder

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