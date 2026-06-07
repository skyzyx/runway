<!-- @config-manager:start kg-readme -->
# Kirograph

We use [Kirograph] to provide a knowledge graph for LLMs and MCP servers to leverage. Obviously, this is designed to work specifically with [Kiro].

## Prerequisites

* Node.js (use a version which still receives support)
* [Kiro]

## Installation

### Install kirograph CLI (first time)

```bash
sudo npm install -g kirograph
```

### Install kirograph into your project

```bash
npx -y kirograph install
```

Kirograph's indexing will work best when your functions and complex code sections have comments which explain _why_ the code exists.

[Kiro]: https://kiro.dev
[Kirograph]: https://github.com/davide-desio-eleva/kirograph
<!-- @config-manager:end kg-readme -->
