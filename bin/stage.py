#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from markdown_it import MarkdownIt
try:
    # mdit-py-hugo ships the parser Hugo syntax support is built on.
    from mdit_py_hugo._shortcode_parsing import ParseError, parse as parse_shortcode
except ImportError as exc:
    raise SystemExit(
        "error: missing Python dependency 'mdit-py-hugo'; run 'uv sync'"
    ) from exc


EXCLUDED_DIRS = {".git", ".claude", ".venv", "node_modules"}
PREFIX = "<!-- ghrm -->\n"
MD = MarkdownIt()


@dataclass(frozen=True)
class Tag:
    start: int
    end: int
    name: str
    markup: str
    closing: bool
    self_closing: bool


class HtmlRefs(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.refs: set[str] = set()

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._collect(attrs)

    def handle_startendtag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._collect(attrs)

    def _collect(self, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name not in {"href", "src"} or not value:
                continue
            self.refs.add(value)


class HtmlRewrite(HTMLParser):
    def __init__(self, root: Path, src: Path) -> None:
        super().__init__(convert_charrefs=False)
        self.root = root
        self.src = src
        self.out: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.out.append(self._tag(tag, attrs, False))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.out.append(self._tag(tag, attrs, True))

    def handle_endtag(self, tag: str) -> None:
        self.out.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.out.append(data)

    def handle_comment(self, data: str) -> None:
        self.out.append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self.out.append(f"<!{decl}>")

    def handle_entityref(self, name: str) -> None:
        self.out.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.out.append(f"&#{name};")

    def handle_pi(self, data: str) -> None:
        self.out.append(f"<?{data}>")

    def unknown_decl(self, data: str) -> None:
        self.out.append(f"<![{data}]>")

    def rewritten(self) -> str:
        return "".join(self.out)

    def _tag(self, tag: str, attrs: list[tuple[str, str | None]], self_closing: bool) -> str:
        parts = [f"<{tag}"]
        for name, value in attrs:
            if value is None:
                parts.append(f" {name}")
                continue

            if name in {"href", "src"}:
                value = local_url(self.root, self.src, value)

            escaped = value.replace("&", "&amp;").replace('"', "&quot;")
            parts.append(f' {name}="{escaped}"')

        parts.append(" />" if self_closing else ">")
        return "".join(parts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("file", "dir"), required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--content-dir", required=True)
    parser.add_argument("--shortcodes-dir", required=True)
    parser.add_argument("--static-dir", required=True)
    return parser.parse_args()


def markdown_files(target: Path) -> list[Path]:
    files: list[Path] = []
    for root, dirs, names in os.walk(target):
        dirs[:] = [name for name in dirs if name not in EXCLUDED_DIRS]
        root_path = Path(root)
        for name in names:
            if not name.endswith((".md", ".MD")):
                continue

            path = root_path / name
            if not path.is_file():
                continue

            files.append(path)
    files.sort()
    return files


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def parse_tag(text: str, start: int) -> Tag | None:
    if start > 0 and text[start - 1] == "\\":
        return None

    try:
        consumed, props = parse_shortcode(text[start:])
    except ParseError:
        return None

    if props is None:
        return None

    end = start + consumed + 3
    raw = text[start:end].rstrip()
    closing = props.name.startswith("/")
    name = props.name[1:] if closing else props.name
    close = "/>}}" if props.markup == "<" else "/%}}"
    return Tag(
        start=start,
        end=end,
        name=name,
        markup=props.markup,
        closing=closing,
        self_closing=raw.endswith(close),
    )


def find_tags(text: str) -> list[Tag]:
    tags: list[Tag] = []
    i = 0

    while True:
        next_angle = text.find("{{<", i)
        next_percent = text.find("{{%", i)
        starts = [pos for pos in (next_angle, next_percent) if pos != -1]
        if not starts:
            return tags

        start = min(starts)
        tag = parse_tag(text, start)
        if tag is None:
            i = start + 2
            continue

        tags.append(tag)
        i = tag.end


def self_close(raw: str, markup: str) -> str:
    close = ">}}" if markup == "<" else "%}}"
    stripped = raw.rstrip()
    if stripped.endswith(f"/{close}"):
        return raw

    body = stripped[: -len(close)].rstrip()
    suffix = raw[len(stripped) :]
    return f"{body} /{close}{suffix}"


def stage_text(text: str, source_dir: str | None) -> tuple[str, set[str]]:
    tags = find_tags(text)
    names = {tag.name for tag in tags}
    replacements: dict[int, str] = {}
    paired_openings: set[int] = set()
    unmatched_closings: set[int] = set()
    stack: list[tuple[int, str, str]] = []

    for idx, tag in enumerate(tags):
        key = (tag.name, tag.markup)
        if tag.closing:
            if not stack or stack[-1][1:] != key:
                unmatched_closings.add(idx)
                continue

            open_idx, _, _ = stack.pop()
            paired_openings.add(open_idx)
            continue

        stack.append((idx, tag.name, tag.markup))

    for idx, tag in enumerate(tags):
        raw = text[tag.start : tag.end]
        if tag.closing and idx in unmatched_closings:
            replacements[idx] = ""
            continue

        if not tag.closing and idx not in paired_openings:
            replacements[idx] = self_close(raw, tag.markup)
            continue

        replacements[idx] = raw

    out: list[str] = []
    cursor = 0
    for idx, tag in enumerate(tags):
        out.append(text[cursor : tag.start])
        out.append(replacements[idx])
        cursor = tag.end
    out.append(text[cursor:])

    staged: list[str] = []
    if source_dir is not None:
        staged.extend(
            [
                "---\n",
                "params:\n",
                f'  sourceDir: "{source_dir}"\n',
                "---\n",
            ]
        )
    staged.append(PREFIX)
    staged.append("".join(out))
    return "".join(staged), names


def stage_markdown(root: Path, src: Path, dst: Path, source_dir: str | None) -> tuple[str, set[str]]:
    text = src.read_text(encoding="utf-8")
    text = rewrite_html(root, src, text)
    staged, names = stage_text(text, source_dir)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(staged, encoding="utf-8")
    return text, names


def token_attr(token, name: str) -> str | None:
    if hasattr(token, "attrGet"):
        return token.attrGet(name)

    attrs = getattr(token, "attrs", None)
    if not attrs:
        return None
    return attrs.get(name)


def inline_tokens(tokens) -> list:
    out = []
    for token in tokens:
        children = getattr(token, "children", None)
        if children:
            out.extend(children)
    return out


def relative_target(root: Path, src: Path, dest: str) -> Path | None:
    parts = urlsplit(dest)
    if parts.scheme or parts.netloc or not parts.path or parts.path.startswith("/"):
        return None

    root_real = root.resolve()
    resolved = (src.parent / parts.path).resolve(strict=False)
    try:
        return resolved.relative_to(root_real)
    except ValueError:
        return None


def page_url(root: Path, rel: Path) -> str | None:
    path = root / rel
    if path.is_dir():
        for name in (
            "README.md",
            "README.MD",
            "readme.md",
            "readme.MD",
            "index.md",
            "index.MD",
        ):
            candidate = rel / name
            if (root / candidate).is_file():
                rel = candidate
                break
        else:
            return None

    if rel.suffix.lower() != ".md":
        return None

    stem = rel.with_suffix("")
    if rel.name.lower() == "readme.md":
        if stem.parent == Path("."):
            return "/readme/"
        return f"/{stem.parent.as_posix()}/readme/"

    return f"/{stem.as_posix()}/"


def local_url(root: Path, src: Path, dest: str) -> str:
    parts = urlsplit(dest)
    if parts.scheme or parts.netloc or not parts.path or parts.path.startswith("/"):
        return dest

    rel = relative_target(root, src, dest)
    if rel is None:
        return dest

    suffix = ""
    if parts.query:
        suffix = f"{suffix}?{parts.query}"
    if parts.fragment:
        suffix = f"{suffix}#{parts.fragment}"

    page = page_url(root, rel)
    if page is not None:
        return f"{page}{suffix}"

    return f"/{rel.as_posix()}{suffix}"


def rewrite_html(root: Path, src: Path, text: str) -> str:
    tokens = MD.parse(text)
    fragments: list[str] = []

    for token in tokens:
        if token.type == "html_block":
            fragments.append(token.content)
            continue

        if token.type != "inline":
            continue

        for child in token.children or []:
            if child.type == "html_inline":
                fragments.append(child.content)

    out: list[str] = []
    cursor = 0
    for fragment in fragments:
        start = text.find(fragment, cursor)
        if start == -1:
            continue

        parser = HtmlRewrite(root, src)
        parser.feed(fragment)
        parser.close()

        out.append(text[cursor:start])
        out.append(parser.rewritten())
        cursor = start + len(fragment)

    out.append(text[cursor:])
    return "".join(out)


def asset_refs(root: Path, src: Path, text: str) -> set[Path]:
    refs: set[Path] = set()
    tokens = MD.parse(text)
    for token in inline_tokens(tokens):
        if token.type == "image":
            dest = token_attr(token, "src")
        elif token.type == "link_open":
            dest = token_attr(token, "href")
        else:
            continue

        if not dest:
            continue

        rel = relative_target(root, src, dest)
        if rel is None or rel.suffix.lower() == ".md":
            continue

        refs.add(rel)

    for token in tokens:
        if token.type not in {"html_block", "inline"}:
            continue

        html_tokens = [token]
        if token.type == "inline":
            html_tokens = [
                child
                for child in token.children or []
                if child.type == "html_inline"
            ]

        for html_token in html_tokens:
            parser = HtmlRefs()
            parser.feed(html_token.content)
            parser.close()

            for dest in parser.refs:
                rel = relative_target(root, src, dest)
                if rel is None or rel.suffix.lower() == ".md":
                    continue
                refs.add(rel)

    return refs


def markdown_refs(root: Path, src: Path, text: str) -> set[Path]:
    refs: set[Path] = set()
    tokens = MD.parse(text)
    for token in inline_tokens(tokens):
        if token.type != "link_open":
            continue

        dest = token_attr(token, "href")
        if not dest:
            continue

        rel = relative_target(root, src, dest)
        if rel is None or rel.suffix.lower() != ".md":
            continue

        refs.add(rel)

    return refs


def copy_asset(root: Path, rel: Path, static_dir: Path) -> None:
    src = root / rel
    if not src.is_file():
        return

    dst = static_dir / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def write_shortcode_stub(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{{ .Inner }}\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    target = Path(args.target).resolve()
    content_dir = Path(args.content_dir)
    shortcodes_dir = Path(args.shortcodes_dir)
    static_dir = Path(args.static_dir)

    reset_dir(content_dir)
    reset_dir(shortcodes_dir)
    if args.mode == "dir":
        reset_dir(static_dir)

    names: set[str] = set()

    if args.mode == "file":
        root = target.parent
        root_rel = target.relative_to(root)
        staged: set[Path] = set()
        pending = [root_rel]

        while pending:
            rel = pending.pop()
            if rel in staged:
                continue

            src = root / rel
            source_dir = rel.parent.as_posix() if rel.parent != Path(".") else ""
            dst = content_dir / ("_index.md" if rel == root_rel else rel)
            text, file_names = stage_markdown(root, src, dst, source_dir)
            names.update(file_names)
            staged.add(rel)

            for ref in sorted(markdown_refs(root, src, text), reverse=True):
                if ref not in staged:
                    pending.append(ref)
    else:
        assets: set[Path] = set()
        for src in markdown_files(target):
            rel = src.relative_to(target)
            text, file_names = stage_markdown(
                target,
                src,
                content_dir / rel,
                rel.parent.as_posix() if rel.parent != Path(".") else "",
            )
            names.update(file_names)
            assets.update(asset_refs(target, src, text))

        for rel in sorted(assets):
            copy_asset(target, rel, static_dir)

    for name in sorted(names):
        write_shortcode_stub(shortcodes_dir / f"{name}.html")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
