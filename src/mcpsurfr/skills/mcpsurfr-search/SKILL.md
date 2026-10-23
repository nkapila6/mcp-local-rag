---
name: mcpsurfr-search
description: Search the web and research topics with the mcpsurfr MCP server, which needs no API keys and re-ranks results locally. Use it when you need current information, documentation, news, or several sources on a topic.
---

# mcpsurfr search

mcpsurfr searches the web through ddgs and re-ranks the results on-device by semantic similarity to your query. It then fetches the best pages and returns their main text (navigation and page chrome stripped, up to 10k characters per page) with source URLs. No API keys are involved.

## Tools

### `rag_search_ddgs`: the default
Uses ddgs **"auto" metasearch**. It queries several engines in parallel (Wikipedia, Brave, DuckDuckGo, ...) and skips any that are blocked or empty. Despite the name, it isn't DuckDuckGo-only, and that's why it's the most reliable choice.

- `query`: natural language works best
- `num_results` (10): results to rank
- `top_k` (5): best pages to fetch and return
- `include_urls` (true): include each page's URL so you can cite it

### `rag_search_google`
Same, but searches Google. **Google often blocks scrapers.** When it returns nothing, the server retries with "auto" and sends a warning. Only pick it when the user asks for Google specifically.

### `deep_research`
For topics that need several angles. Each search term is searched on each backend, results are re-ranked, duplicates are removed, and the best pages are fetched.

- `search_terms`: 2-5 specific, related queries, each covering a different angle
- `backends` (default `["auto"]`): any of `auto`, `brave`, `duckduckgo`, `google`, `grokipedia`, `mojeek`, `startpage`, `wikipedia`, `yahoo`
- `num_results_per_term` (10), `top_k_per_term` (3)

The result includes `search_summary`, showing how many results each term and backend contributed. Use it to see which engines actually delivered.

### `deep_research_ddgs` / `deep_research_google`
Shortcuts for `deep_research` with `["auto"]` and `["google"]`.

### Prompt: `research`
`research(topic)` makes a plan: 3-5 search terms, one `deep_research` call, a cited summary. Clients that support prompts show it as a slash command.

## Picking backends

| Backend | Use it for | Reliability |
|---|---|---|
| `auto` | almost everything | best, since it falls back across engines |
| `brave` | a second, independent engine | usually available and fast |
| `wikipedia` | factual background | exact article lookups: use title-like terms ("Rust (programming language)") |
| `duckduckgo`, `yahoo` | variety | rate-limited at times (both serve Bing results) |
| `google`, `startpage`, `mojeek` | only when asked | often blocked |

Engines that return nothing come back as warnings, not errors. If every engine you chose is empty, the terms are retried with `auto` automatically. Names that aren't in the list are skipped with a warning.

## Writing queries

- Be specific: "postgres EXPLAIN ANALYZE reading the output", not "postgres".
- For `deep_research`, make the terms differ in angle, not just wording: "rust async runtime comparison", "tokio vs async-std benchmarks", "rust async pitfalls".
- Put the year in for time-sensitive topics: "kubernetes 1.34 release notes".

## Parameters

- Quick answer: `rag_search_ddgs` with `top_k=3`
- Thorough answer: `num_results=15-20`, `top_k=7`
- Research: `deep_research` with 3-5 terms, `top_k_per_term=3`, default backend. Add `["auto", "brave"]` for more engine variety.

More pages and more backends give better coverage but are slower. Each page fetch can take a few seconds, and clients show progress while it runs.

## Using the results

1. Cite the `url` of every page you draw from.
2. Check dates: pages can be stale. Say so when they are.
3. Cross-check important facts across at least two pages or terms.
4. If a page's text looks cut off or empty, it was probably blocked or JavaScript-only. Use the other results.

## When results are thin

1. Rephrase the query, more specific or with different keywords.
2. Raise `num_results`.
3. Switch to `deep_research` with several related terms.
4. Add `brave` alongside `auto`.
