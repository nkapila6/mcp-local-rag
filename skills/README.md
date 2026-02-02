# Agent Skills for mcp-local-rag

This folder contains Agent Skills that teach Claude how to effectively use the mcp-local-rag MCP server.

## What are Agent Skills?

Agent Skills are folders of instructions that Claude loads dynamically to improve performance on specialized tasks. Each skill contains a `SKILL.md` file with:

- **Metadata** (name, description) in YAML frontmatter
- **Instructions** that Claude follows when the skill is active
- **Examples** and **Guidelines** for best practices

Learn more at: https://github.com/anthropics/skills

## Available Skills

### local-rag-search

Teaches Claude how to effectively use the mcp-local-rag web search tools with semantic similarity ranking.

**Use this skill when you need to:**
- Search the web for current information
- Research topics across multiple sources
- Perform deep research with multiple search engines
- Get semantically relevant results without external APIs

## How to Use These Skills

### In Claude Desktop

1. Navigate to **Settings** → **Skills**
2. Click **Add Skill** → **Add from folder**
3. Select the skill folder (e.g., `skills/local-rag-search/`)
4. The skill will now be available in your conversations

### In Claude Code (via Plugin Marketplace)

Skills can be packaged as plugins for Claude Code. To create a plugin from these skills:

1. Create a `.claude-plugin` folder in this repository
2. Add a `plugin.json` manifest
3. Reference the skill folders

### In Claude API

You can upload skills via the API using the Skills API. See [Skills API Quickstart](https://docs.anthropic.com/claude/docs/skills-api-quickstart).

### Direct Usage

When the MCP server is configured and the skill is loaded, simply mention the task:

```
"Search the web for the latest Python 3.13 features"
"Do deep research on sustainable energy solutions"
"Find information about quantum computing breakthroughs"
```

Claude will automatically use the skill to guide its use of the mcp-local-rag tools.