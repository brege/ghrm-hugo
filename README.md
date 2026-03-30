# ghrm

Preview GitHub-flavored Markdown locally using Hugo. Renders admonitions, Mermaid diagrams, KaTeX math, GeoJSON/TopoJSON maps, and light/dark theme toggling all whilst matching GitHub's README style.

## Requirements

- [Hugo](https://gohugo.io/) (>= 0.132)
- [Node.js](https://nodejs.org/) (>= 22, for vendor asset downloads)
- `inotifywait` (optional, from `inotify-tools`)

## Install

```bash
git clone https://github.com/brege/ghrm.git
cd ghrm
make install
```

This symlinks `ghrm` into `~/.local/bin` and downloads vendor assets (Mermaid, KaTeX, Leaflet, Three.js) on first run so you can use it offline.

## Usage

```bash
ghrm README.md
```

Opens a live-reloading preview in your browser. Edits to the file are reflected automatically.

## Neovim

Add to your lazy.nvim config:

```lua
{ "brege/ghrm", ft = "markdown", config = function() require("ghrm").setup() end }
```

Commands: `:Ghrm` to start, `:GhrmStop` to stop.

## Supported Features

- GitHub alert admonitions (`[!NOTE]`, `[!TIP]`, `[!WARNING]`, etc.)
- Collapsible `<details>` sections and normal Markdown formatting and highlighting
- Mermaid diagrams
- KaTeX math (inline, display, and fenced `math` blocks)
- GeoJSON and TopoJSON maps
- STL 3D model viewer (work in progress)
- Light/dark theme toggle

## Uninstall

```bash
make uninstall
make clean
```
