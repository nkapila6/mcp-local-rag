# mcp-local-rag
"primitive" RAG-like web search model context protocol server that runs locally. ✨ no APIs ✨ 

![Flow diagram](images/flowchart.png)

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
        "<path where this repo is located>/mcp-local-rag/",
        "run",
        "src/mcp-local-rag/rag-search.py"
      ]
    }
  }
}
```
