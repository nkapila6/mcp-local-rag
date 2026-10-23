#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on 2025-06-04 23:01:38 Wednesday

@author: Nikhil Kapila
"""

from typing import List, Dict

def sort_by_score(results: List[Dict]) -> List[Dict]:
    """Sort results by similarity score."""
    return sorted(results, key=lambda x: x['score'], reverse=True)