<img src='images/rag.jpeg' width='200' height='200'>

# mcp-local-rag
"primitive" RAG-like web search model context protocol (MCP) server that runs locally. ✨ no APIs ✨ 

<img src='images/flowchart.png' width='1000' height='500'>

# Installation instructions
1. You would need to install ```uv```: https://docs.astral.sh/uv/

2. Clone this GitHub repository.
```terminal
git clone https://github.com/nkapila6/mcp-local-rag
```

3. Add the following to your Claude config. You can find the configuration paths here: https://modelcontextprotocol.io/quickstart/user
```json
{
  "mcpServers": {
    "mcp-local-rag": {
      "command": "uv",
      "args": [
        "--directory",
        "<path where this folder is located>/mcp-local-rag/",
        "run",
        "src/mcp-local-rag/rag-search.py"
      ]
    }
  }
}
```

# Example use

## On prompt
When asked to fetch/lookup/search the web, the model prompts you to use MCP server for the chat.

In the example, have asked it about Google's latest Gemma models released yesterday. This is new info that Claude is not aware about.
<img src='images/mcp_prompted.png'>

## Result
The result from the local `rag_search` helps the model answer with new info.
<img src='images/mcp_result.png'>
