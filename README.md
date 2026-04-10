# ghrm

Preview GitHub-flavored Markdown locally using Hugo. Renders admonitions, Mermaid diagrams, KaTeX math, GeoJSON/TopoJSON maps, and light/dark theme toggling all whilst matching GitHub's README style.

## Ethos

People who lose internet and power often: this tool is for you. It renders Markdown the exact same way as GitHub would. If you are offline and still need to make meaningful contributions, focusing on documentation is often the cromulent choice (no coding agents, no wikipedia available, etc).

The point of this tool is **offline preview**. Run install while online once, then keep working with no network connection when power, internet, or both are unreliable.

## Requirements

- [Hugo](https://gohugo.io/) (>= 0.132)
- [Node.js](https://nodejs.org/) (>= 22, only for asset refreshes)
- `inotifywait` (optional, from `inotify-tools`)

## Install

```bash
git clone https://github.com/brege/ghrm.git
cd ghrm
make install
```

This symlinks `ghrm` into `~/.local/bin` and downloads vendor assets (Mermaid, KaTeX, Leaflet). After that bootstrap step, preview runs do not need the network.

If you want to refresh the downloaded vendor files later:

```bash
make assets
```

## Usage

```bash
ghrm README.md
```

Opens a live-reloading preview in your browser. Edits to the file are reflected automatically.
`ghrm` does not fetch assets at runtime. If vendor files are missing, it exits and tells you to run `make assets` while online.

## Neovim

Add to your lazy.nvim config:

```lua
{ "brege/ghrm", ft = "markdown", config = function() require("ghrm").setup() end }
```

Commands: `:Ghrm` to start, `:GhrmStop` to stop, or just exit nvim.

## Supported Features

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
ghrm test/basics.md
ghrm test/diagrams.md
```

## Uninstall

```bash
make uninstall
make clean
```
