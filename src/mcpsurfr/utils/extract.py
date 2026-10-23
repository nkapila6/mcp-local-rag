#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Main-content extraction: pull the article out of a page and leave the nav menus,
cookie banners and footers behind, so the 10k budget goes to actual content.
Uses lxml, which ddgs already depends on.
"""

import re
from typing import Optional

from lxml import html as lxml_html
from lxml.etree import ParserError

_DROP = ("//script|//style|//noscript|//template|//svg|//canvas|//iframe|//form|//button"
         "|//select|//nav|//header|//footer|//aside|//dialog")
_DROP_ROLES = ('//*[@role="navigation" or @role="banner" or @role="contentinfo"'
               ' or @role="search" or @aria-hidden="true" or @hidden]')
# class/id words that mark page chrome rather than content
_CHROME = re.compile(
    r"(^|[\s_-])(nav|navbar|navigation|menu|masthead|footer|sidebar|breadcrumbs?|cookie|consent"
    r"|banner|social|share|sharing|related|comments?|advert|ads|promo|newsletter|subscribe"
    r"|skip|toolbar|popup|modal)([\s_-]|$)", re.I)
# below this a <main>/<article> is probably a teaser, not the page's content
_MIN_CONTENT = 500


def _text(el) -> str:
    # itertext + join keeps block elements from gluing words together ("CopilotWrite")
    return " ".join(" ".join(el.itertext()).split())


def extract_main_text(page: str) -> Optional[str]:
    try:
        doc = lxml_html.fromstring(page)
    except (ParserError, ValueError):
        return None

    for el in doc.xpath(_DROP) + doc.xpath(_DROP_ROLES):
        if el.getparent() is not None:
            el.drop_tree()

    containers = doc.xpath('//main|//article|//*[@role="main"]')
    for el in doc.xpath("//*[@class or @id]"):
        if el.tag in ("html", "body") or el in containers:
            continue
        if _CHROME.search(f"{el.get('class', '')} {el.get('id', '')}") and el.getparent() is not None:
            el.drop_tree()

    # a single real <article> is the content (a GitHub README inside <main>).
    # Many of them is a listing (a news front page), so use the whole <main> there.
    articles = [a for a in doc.xpath("//article") if len(_text(a)) >= _MIN_CONTENT]
    if len(articles) == 1:
        root = articles[0]
    else:
        sized = [(len(_text(c)), c) for c in doc.xpath('//main|//*[@role="main"]|//article')]
        sized = [(n, c) for n, c in sized if n >= _MIN_CONTENT]
        root = max(sized, key=lambda x: x[0])[1] if sized else doc.find("body")
        if root is None:
            root = doc
    return _text(root) or None
