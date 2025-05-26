<a href='https://github.com/nkapila6/mcp-local-rag/'><img src='images/rag.jpeg' width='200' height='200'></a>

<!-- omit from toc -->
# mcp-local-rag
"primitive" RAG-like web search model context protocol (MCP) server that runs locally. ✨ no APIs ✨

```mermaid
flowchart TD
    A[User] -->|1.Submits LLM Query| B[Language Model]
    B -->|2.Sends Query| C[mcp-local-rag Tool]
    
    subgraph mcp-local-rag Processing
    C -->|Search DuckDuckGo| D[Fetch 10 search results]
    D -->|Fetch Embeddings| E[Embeddings from Google's MediaPipe Text Embedder]
    E -->|Compute Similarity| F[Rank Entries Against Query]
    F -->|Select top k results| G[Context Extraction from URL]
    end
    
    G -->|Returns Markdown from HTML content| B
    B -->|3.Generated response with context| H[Final LLM Output]
    H -->|5.Present result to user| A

    classDef default fill:#f9f,stroke:#333,stroke-width:2px;
    classDef process fill:#bbf,stroke:#333,stroke-width:2px;
    classDef input fill:#9f9,stroke:#333,stroke-width:2px;
    classDef output fill:#ff9,stroke:#333,stroke-width:2px;

    class A input;
    class B,C process;
    class G output;
```

---

<!-- omit from toc -->
# Table of Contents
- [Installation](#installation)
  - [Using Docker (recommended)](#using-docker-recommended)
  - [Using Python + uv](#using-python--uv)
    - [Run Directly via `uvx`](#run-directly-via-uvx)
    - [Clone and Run Locally](#clone-and-run-locally)
- [Example use](#example-use)
  - [Prompt](#prompt)
  - [Result](#result)
- [🛠️ Contributing](#️-contributing)
- [📝 License](#-license)


---

# Installation

## Using Python + uv
For this step, make sure you have [`uv`](https://docs.astral.sh/uv) installed: https://docs.astral.sh/uv/.

There are 2 ways to approach this:

1. Option 1: [Directly running via `uvx`](#directly-running-via-uvx)
2. Option 2: [Clone and Run Locally](#cloning-the-repository)

### Run Directly via `uvx`
This is the easiest and quickest method. Add the following to your MCP config:<br>

```json
{
  "mcpServers": {
    "mcp-local-rag":{
      "command": "uvx",
        "args": [
          "--python=3.10",
          "--from",
          "git+https://github.com/nkapila6/mcp-local-rag",
          "mcp-local-rag"
        ]
      }
  }
}
```

### Clone and Run Locally
1. Clone this GitHub repository

```bash
git clone https://github.com/nkapila6/mcp-local-rag
```

2. Add the following to your MCP Server configuration.

```json
{
  "mcpServers": {
    "mcp-local-rag": {
      "command": "uv",
      "args": [
        "--directory",
        "<path where this folder is located>/mcp-local-rag/",
        "run",
        "src/mcp_local_rag/main.py"
      ]
    }
  }
}
```
You can find MCP config file paths here: https://modelcontextprotocol.io/quickstart/user


## Using Docker
Ensure you have [Docker](https://www.docker.com) installed.<br>
Add this to your MCP server configuration:

```json
{
  "mcpServers": {
    "mcp-local-rag": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "--init",
        "-e",
        "DOCKER_CONTAINER=true",
        "ghcr.io/nkapila6/mcp-local-rag:latest"
      ]
    }
  }
}
```

# Security audits
<a href='https://mseep.ai/app/nkapila6-mcp-local-rag'><img src='https://mseep.net/pr/nkapila6-mcp-local-rag-badge.png' width='auto' height='200'></a>

# Examples on Claude Desktop
When an LLM (like Claude) is asked a question requiring recent web information, it will trigger `mcp-local-rag`.

When asked to fetch/lookup/search the web, the model prompts you to use MCP server for the chat.

In the example, have asked it about Google's latest Gemma models released yesterday. This is new info that Claude is not aware about.
<img src='images/mcp_prompted.png'>

## Result
`mcp-local-rag` performs a live web search, extracts context, and sends it back to the model—giving it fresh knowledge:

<img src='images/mcp_result.png'>

# Contributing
Have ideas or want to improve this project? Issues and pull requests are welcome!

# License
This project is licensed under the MIT License.