---
name: mcpsurfr-search
description: Search the web and research topics with the mcpsurfr MCP server, which needs no API keys and ranks results locally. Use it when you need current information, documentation, news, or several sources on a topic. Start with the `search` tool, which returns only the relevant passages.
---

# mcpsurfr search

mcpsurfr searches the web through ddgs, ranks the results on-device, and fetches the best pages. No API keys are involved. Its main tool, `search`, returns only the passages that answer the question, not whole pages: usually about a tenth of the tokens. Prefer it.

## Which tool

| Situation | Tool |
|---|---|
| Almost any question | `search` |
| The user wants whole pages, or `search` came back thin | `rag_search_ddgs` |
| A topic that needs several angles or sources | `deep_research` |
| The user asks for Google specifically | `rag_search_google` / `deep_research_google` |

## `search` (start here)

- `query`: the question in natural language
- `keywords`: **pass these.** Terms a good answer would contain, including synonyms and exact phrases, because the first ranking pass is keyword-based (BM25). For "how do I make postgres faster", pass `["index", "EXPLAIN ANALYZE", "query planner", "vacuum"]`.
- `max_passages` (8), `top_pages` (5), `num_results` (10), `backend` ("auto")

It returns `passages`: `[{url, heading, text, score}]`, best first, plus `tier`, which says what picked them:
- `keywords` or `keywords+semantic`: confident.
- `semantic`: nothing matched your keywords, so passages were picked by meaning only. Treat them with care, and try again with better keywords or use `rag_search_ddgs`. The user may be asked whether they want full pages instead. If they say yes, you get `content` (full page text) rather than `passages`.

## `rag_search_ddgs` / `rag_search_google`

Full page text (main content only, up to 10k characters each) for the top `top_k` results. `rag_search_ddgs` uses ddgs "auto" metasearch, which covers several engines and skips blocked ones. Google often blocks scrapers. When it returns nothing, the server retries with "auto" and warns you.

## `deep_research`

- `search_terms`: 2-5 related queries, each covering a different angle (not just rewordings)
- `backends` (default `["auto"]`): `auto`, `brave`, `duckduckgo`, `google`, `grokipedia`, `mojeek`, `startpage`, `wikipedia`, `yahoo`
- `top_k_per_term` (3)

`search_summary` in the result shows which engines actually delivered. Full pages come back, so it's token-heavy: for one focused question, `search` is better.

Prompt: `research(topic)` plans the terms, runs `deep_research` and asks for a cited summary.

## Backends

`auto` (best: falls back across engines) and `brave` (fast, usually up) are dependable. `wikipedia` is an exact-title lookup. `duckduckgo` and `yahoo` get rate-limited at times. `google`, `startpage` and `mojeek` are often blocked. Empty engines come back as warnings, and unknown names are skipped with a warning.

## Using results

1. Cite the `url` of everything you use.
2. Check dates, and say when a source looks stale.
3. Cross-check important facts across two sources.
4. Thin results: add keywords and synonyms, rephrase, raise `num_results`, or switch tools as in the table above.
