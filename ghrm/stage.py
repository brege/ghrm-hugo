#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from markdown_it import MarkdownIt
from mdit_py_hugo._shortcode_parsing import ParseError, parse as parse_shortcode

from .common import markdown_files


PREFIX = "<!-- ghrm -->\n"
MD = MarkdownIt()


@dataclass(frozen=True)
class Tag:
    start: int
    end: int
    name: str
    markup: str
    closing: bool


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
            if name in {"href", "src"} and value:
                self.refs.add(value)


class HtmlRewrite(HTMLParser):
    def __init__(self, builder: "StageBuilder", src: Path) -> None:
        super().__init__(convert_charrefs=False)
        self.builder = builder
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

    def rendered(self) -> str:
        return "".join(self.out)

    def _tag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
        self_closing: bool,
    ) -> str:
        parts = [f"<{tag}"]
        for name, value in attrs:
            if value is None:
                parts.append(f" {name}")
                continue
            if name in {"href", "src"}:
                value = self.builder.local_url(self.src, value)
            escaped = value.replace("&", "&amp;").replace('"', "&quot;")
            parts.append(f' {name}="{escaped}"')
        parts.append(" />" if self_closing else ">")
        return "".join(parts)


class StageBuilder:
    def __init__(
        self,
        mode: str,
        target: Path,
        content_dir: Path,
        shortcodes_dir: Path,
        static_dir: Path,
    ) -> None:
        self.mode = mode
        self.target = target
        self.content_dir = content_dir
        self.shortcodes_dir = shortcodes_dir
        self.static_dir = static_dir

    def run(self) -> int:
        self.reset_dir(self.content_dir)
        self.reset_dir(self.shortcodes_dir)
        if self.mode == "dir":
            self.reset_dir(self.static_dir)

        names: set[str] = set()
        if self.mode == "file":
            names.update(self.stage_file_mode())
        else:
            names.update(self.stage_dir_mode())

        for name in sorted(names):
            path = self.shortcodes_dir / f"{name}.html"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{{ .Inner }}\n", encoding="utf-8")
        return 0

    def stage_file_mode(self) -> set[str]:
        root = self.target.parent
        root_rel = self.target.relative_to(root)
        staged: set[Path] = set()
        pending = [root_rel]
        names: set[str] = set()

        while pending:
            rel = pending.pop()
            if rel in staged:
                continue
            src = root / rel
            source_dir = "" if rel.parent == Path(".") else rel.parent.as_posix()
            dst = self.content_dir / ("_index.md" if rel == root_rel else rel)
            text, file_names = self.stage_markdown(root, src, dst, source_dir)
            names.update(file_names)
            staged.add(rel)
            for ref in sorted(self.markdown_refs(root, src, text), reverse=True):
                if ref not in staged:
                    pending.append(ref)
        return names

    def stage_dir_mode(self) -> set[str]:
        names: set[str] = set()
        assets: set[Path] = set()
        sections: set[Path] = set()
        for src in markdown_files(self.target):
            rel = src.relative_to(self.target)
            sections.update(self.parent_dirs(rel))
            source_dir = "" if rel.parent == Path(".") else rel.parent.as_posix()
            text, file_names = self.stage_markdown(
                self.target,
                src,
                self.content_dir / rel,
                source_dir,
            )
            names.update(file_names)
            assets.update(self.asset_refs(self.target, src, text))

        for rel in sorted(sections):
            self.stage_section(rel)

        for rel in sorted(assets):
            self.copy_asset(self.target, rel)
        return names

    def parent_dirs(self, rel: Path) -> set[Path]:
        dirs: set[Path] = set()
        parent = rel.parent
        while parent != Path("."):
            dirs.add(parent)
            parent = parent.parent
        return dirs

    def stage_section(self, rel: Path) -> None:
        title = rel.name.replace("\\", "\\\\").replace('"', '\\"')
        source_dir = rel.as_posix().replace("\\", "\\\\").replace('"', '\\"')
        dst = self.content_dir / rel / "_index.md"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(
            (
                "---\n"
                f'title: "{title}"\n'
                "params:\n"
                f'  sourceDir: "{source_dir}"\n'
                "---\n"
            ),
            encoding="utf-8",
        )

    def reset_dir(self, path: Path) -> None:
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)

    def stage_markdown(
        self,
        root: Path,
        src: Path,
        dst: Path,
        source_dir: str | None,
    ) -> tuple[str, set[str]]:
        raw = src.read_text(encoding="utf-8")
        text = self.rewrite_html(root, src, raw)
        staged, names = self.stage_text(text, source_dir)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(staged, encoding="utf-8")
        return raw, names

    def stage_text(self, text: str, source_dir: str | None) -> tuple[str, set[str]]:
        tags = self.find_tags(text)
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
            raw = text[tag.start:tag.end]
            if tag.closing and idx in unmatched_closings:
                replacements[idx] = ""
                continue
            if not tag.closing and idx not in paired_openings:
                replacements[idx] = self.self_close(raw, tag.markup)
                continue
            replacements[idx] = raw

        out: list[str] = []
        cursor = 0
        for idx, tag in enumerate(tags):
            out.append(text[cursor:tag.start])
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

    def find_tags(self, text: str) -> list[Tag]:
        tags: list[Tag] = []
        cursor = 0
        while True:
            starts = [pos for pos in (text.find("{{<", cursor), text.find("{{%", cursor)) if pos != -1]
            if not starts:
                return tags
            start = min(starts)
            tag = self.parse_tag(text, start)
            if tag is None:
                cursor = start + 2
                continue
            tags.append(tag)
            cursor = tag.end

    def parse_tag(self, text: str, start: int) -> Tag | None:
        if start > 0 and text[start - 1] == "\\":
            return None
        try:
            consumed, props = parse_shortcode(text[start:])
        except ParseError:
            return None
        if props is None:
            return None
        end = start + consumed + 3
        name = props.name[1:] if props.name.startswith("/") else props.name
        return Tag(
            start=start,
            end=end,
            name=name,
            markup=props.markup,
            closing=props.name.startswith("/"),
        )

    def self_close(self, raw: str, markup: str) -> str:
        close = ">}}" if markup == "<" else "%}}"
        stripped = raw.rstrip()
        if stripped.endswith(f"/{close}"):
            return raw
        body = stripped[: -len(close)].rstrip()
        suffix = raw[len(stripped):]
        return f"{body} /{close}{suffix}"

    def token_attr(self, token, name: str) -> str | None:
        if hasattr(token, "attrGet"):
            return token.attrGet(name)
        attrs = getattr(token, "attrs", None)
        if not attrs:
            return None
        return attrs.get(name)

    def inline_tokens(self, tokens) -> list:
        out = []
        for token in tokens:
            children = getattr(token, "children", None)
            if children:
                out.extend(children)
        return out

    def relative_target(self, root: Path, src: Path, dest: str) -> Path | None:
        parts = urlsplit(dest)
        if parts.scheme or parts.netloc or not parts.path or parts.path.startswith("/"):
            return None
        resolved = (src.parent / parts.path).resolve(strict=False)
        try:
            return resolved.relative_to(root.resolve())
        except ValueError:
            return None

    def page_url(self, root: Path, rel: Path) -> str | None:
        path = root / rel
        if path.is_dir():
            for name in ("README.md", "README.MD", "readme.md", "readme.MD", "index.md", "index.MD"):
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
            return "/readme/" if stem.parent == Path(".") else f"/{stem.parent.as_posix()}/readme/"
        return f"/{stem.as_posix()}/"

    def local_url(self, src: Path, dest: str) -> str:
        root = self.target if self.mode == "dir" else self.target.parent
        parts = urlsplit(dest)
        if parts.scheme or parts.netloc or not parts.path or parts.path.startswith("/"):
            return dest
        rel = self.relative_target(root, src, dest)
        if rel is None:
            return dest
        suffix = ""
        if parts.query:
            suffix = f"{suffix}?{parts.query}"
        if parts.fragment:
            suffix = f"{suffix}#{parts.fragment}"
        page = self.page_url(root, rel)
        if page is not None:
            return f"{page}{suffix}"
        return f"/{rel.as_posix()}{suffix}"

    def rewrite_html(self, root: Path, src: Path, text: str) -> str:
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
            parser = HtmlRewrite(self, src)
            parser.feed(fragment)
            parser.close()
            out.append(text[cursor:start])
            out.append(parser.rendered())
            cursor = start + len(fragment)
        out.append(text[cursor:])
        return "".join(out)

    def asset_refs(self, root: Path, src: Path, text: str) -> set[Path]:
        refs: set[Path] = set()
        tokens = MD.parse(text)
        for token in self.inline_tokens(tokens):
            if token.type == "image":
                dest = self.token_attr(token, "src")
            elif token.type == "link_open":
                dest = self.token_attr(token, "href")
            else:
                continue
            if not dest:
                continue
            rel = self.relative_target(root, src, dest)
            if rel is None or rel.suffix.lower() == ".md":
                continue
            refs.add(rel)

        for token in tokens:
            if token.type not in {"html_block", "inline"}:
                continue
            html_tokens = [token] if token.type == "html_block" else [
                child for child in token.children or [] if child.type == "html_inline"
            ]
            for html_token in html_tokens:
                parser = HtmlRefs()
                parser.feed(html_token.content)
                parser.close()
                for dest in parser.refs:
                    rel = self.relative_target(root, src, dest)
                    if rel is None or rel.suffix.lower() == ".md":
                        continue
                    refs.add(rel)
        return refs

    def markdown_refs(self, root: Path, src: Path, text: str) -> set[Path]:
        refs: set[Path] = set()
        for token in self.inline_tokens(MD.parse(text)):
            if token.type != "link_open":
                continue
            dest = self.token_attr(token, "href")
            if not dest:
                continue
            rel = self.relative_target(root, src, dest)
            if rel is not None and rel.suffix.lower() == ".md":
                refs.add(rel)
        return refs

    def copy_asset(self, root: Path, rel: Path) -> None:
        src = root / rel
        if not src.is_file():
            return
        dst = self.static_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("file", "dir"), required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--content-dir", required=True)
    parser.add_argument("--shortcodes-dir", required=True)
    parser.add_argument("--static-dir", required=True)
    args = parser.parse_args(argv)
    builder = StageBuilder(
        mode=args.mode,
        target=Path(args.target).resolve(),
        content_dir=Path(args.content_dir),
        shortcodes_dir=Path(args.shortcodes_dir),
        static_dir=Path(args.static_dir),
    )
    return builder.run()
