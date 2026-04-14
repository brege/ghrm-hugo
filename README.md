# ghrm

Preview GitHub-flavored Markdown locally using Hugo. Renders admonitions, Mermaid diagrams, KaTeX math, GeoJSON/TopoJSON maps, and light/dark theme toggling all whilst matching GitHub's README style.

## Ethos

People who lose internet and power often: this tool is for you. It renders Markdown the exact same way as GitHub would. If you are offline and still need to make meaningful contributions, focusing on documentation is often the cromulent choice (no coding agents, no Wikipedia/GitHub available, etc).

The point of this tool is **offline preview**. Install once, then keep working with no network connection when power, internet, or both are unreliable.

## Requirements

- [Hugo](https://gohugo.io/) (>= 0.132)
- [uv](https://docs.astral.sh/uv/)

## Install

```bash
git clone https://github.com/brege/ghrm.git
cd ghrm
make install
```

## Usage

```bash
# one file
ghrm README.md

# multiple files, recursively
ghrm .
```

Opens a live-reloading preview in your browser. Edits to the file are reflected automatically.

## Neovim

Add to your lazy.nvim config:

```lua
{ "brege/ghrm", ft = "markdown", config = function() require("ghrm").setup() end }
```

Commands: `:Ghrm` to start, `:GhrmStop` to stop, or just exit nvim.

## Supported Features

- **Works offline**
- GitHub alert admonitions (`[!NOTE]`, `[!TIP]`, `[!WARNING]`, etc.)
- Collapsible `<details>` sections and normal Markdown formatting and highlighting
- Mermaid diagrams
- KaTeX math (inline, display, and fenced `math` blocks)
- GeoJSON and TopoJSON maps
- Light/dark theme toggle

### Examples

- [Basics](test/basics.md)
- [Diagrams](test/diagrams.md)

```bash
ghrm README.md
ghrm test/basics.md
ghrm test/diagrams.md
ghrm .
```

## Uninstall

```bash
make uninstall
make clean
```
