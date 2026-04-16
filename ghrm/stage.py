from __future__ import annotations

import html
import json
import shutil
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from markdown_it import MarkdownIt
from mdit_py_hugo._shortcode_parsing import ParseError, parse as parse_shortcode

from . import __version__
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


PageState = dict[str, int | list[str]]


class HtmlRewrite(HTMLParser):
    def __init__(self, builder: "StageBuilder", src: Path) -> None:
        super().__init__(convert_charrefs=False)
        self.builder = builder
        self.src = src
        self.out: list[str] = []
        self.refs: set[str] = set()

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
                self.refs.add(value)
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
        site_dir: Path,
    ) -> None:
        self.mode = mode
        self.target = target
        self.site_dir = site_dir

    @property
    def content_dir(self) -> Path:
        return self.site_dir / "content"

    @property
    def shortcodes_dir(self) -> Path:
        return self.site_dir / "layouts" / "shortcodes"

    @property
    def static_dir(self) -> Path:
        return self.site_dir / "static"

    @property
    def data_dir(self) -> Path:
        return self.site_dir / "data"

    @property
    def state_path(self) -> Path:
        return self.site_dir / "_ghrm" / "state.json"

    def run(self) -> int:
        state = self.load_state()
        if state is None and self.state_path.exists():
            self.clear_cache()
        if state is not None and state["version"] != __version__:
            self.clear_cache()
            state = None

        if self.mode == "file":
            names: set[str] = set()
            self.reset_dir(self.content_dir)
            self.reset_dir(self.shortcodes_dir)
            names.update(self.stage_file_mode())
        else:
            files = [path.relative_to(self.target) for path in markdown_files(self.target)]
            current = self.markdown_mtimes(files)
            if state is not None and self.cached_ready(state, current):
                return 0
            for path in (
                self.content_dir,
                self.shortcodes_dir,
                self.static_dir,
                self.data_dir,
            ):
                path.mkdir(parents=True, exist_ok=True)
            prev_pages = state["pages"] if state is not None else {}
            names, pages = self.stage_dir_mode(files, current, prev_pages)
            if prev_pages.keys() != current.keys() or not (self.data_dir / "nav.json").is_file():
                self.write_nav(files)
            self.prune_shortcodes(self.page_names(prev_pages), names)
            self.write_state(pages)

        for name in sorted(names):
            path = self.shortcodes_dir / f"{name}.html"
            if path.is_file():
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{{ .Inner }}\n", encoding="utf-8")
        return 0

    def cached_ready(self, state: dict, current: dict[str, int]) -> bool:
        if not self.content_dir.is_dir() or not self.shortcodes_dir.is_dir():
            return False
        if not self.static_dir.is_dir() or not self.data_dir.is_dir():
            return False
        if not (self.data_dir / "nav.json").is_file():
            return False
        if state["pages"].keys() != current.keys():
            return False
        for key, page in state["pages"].items():
            if page["mtime"] != current[key]:
                return False
            if not self.page_dst(Path(key)).is_file():
                return False
        for name in self.page_names(state["pages"]):
            if not (self.shortcodes_dir / f"{name}.html").is_file():
                return False
        for rel in self.page_assets(state["pages"]):
            if not (self.static_dir / rel).is_file():
                return False
        return True

    def clear_cache(self) -> None:
        for path in (
            self.content_dir,
            self.static_dir,
            self.data_dir,
            self.shortcodes_dir,
            self.state_path.parent,
        ):
            if path.exists():
                shutil.rmtree(path)

    def load_state(self) -> dict | None:
        try:
            raw = self.state_path.read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        version = data.get("version")
        pages = data.get("pages")
        if not isinstance(version, str):
            return None
        if not isinstance(pages, dict):
            return None
        cleaned_pages: dict[str, PageState] = {}
        for key, value in pages.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                return None
            mtime = value.get("mtime")
            page_names = value.get("names")
            assets = value.get("assets")
            if not isinstance(mtime, int):
                return None
            if not isinstance(page_names, list) or not all(isinstance(item, str) for item in page_names):
                return None
            if not isinstance(assets, list) or not all(isinstance(item, str) for item in assets):
                return None
            cleaned_pages[key] = {"mtime": mtime, "names": page_names, "assets": assets}
        return {
            "version": version,
            "pages": cleaned_pages,
        }

    def write_state(self, pages: dict[str, PageState]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": __version__,
            "pages": pages,
        }
        self.state_path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def markdown_mtimes(self, files: list[Path]) -> dict[str, int]:
        items: dict[str, int] = {}
        for rel in files:
            items[rel.as_posix()] = int((self.target / rel).stat().st_mtime_ns)
        return items

    def page_assets(self, pages: dict[str, PageState]) -> list[str]:
        assets = {
            path
            for page in pages.values()
            for path in page["assets"]
        }
        return sorted(assets)

    def page_names(self, pages: dict[str, PageState]) -> set[str]:
        return {
            name
            for page in pages.values()
            for name in page["names"]
        }

    def fresh(self, src: Path, dst: Path) -> bool:
        try:
            return dst.stat().st_mtime_ns >= src.stat().st_mtime_ns
        except OSError:
            return False

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
            file_names, tokens, _ = self.stage_markdown(root, src, dst, source_dir, rel.as_posix())
            names.update(file_names)
            staged.add(rel)
            for ref in sorted(self.markdown_refs(root, src, tokens), reverse=True):
                if ref not in staged:
                    pending.append(ref)
        return names

    def stage_dir_mode(
        self,
        files: list[Path],
        current: dict[str, int],
        prev_pages: dict[str, PageState],
    ) -> tuple[set[str], dict[str, PageState]]:
        names: set[str] = set()
        assets: set[Path] = set()
        sections: set[Path] = set()
        expected_pages: set[Path] = set()
        pages: dict[str, PageState] = {}
        for rel in files:
            src = self.target / rel
            sections.update(self.parent_dirs(rel))
            dst = self.page_dst(rel)
            expected_pages.add(dst)
            key = rel.as_posix()
            cached = prev_pages.get(key)
            if cached is not None and cached["mtime"] == current[key] and dst.is_file():
                page_names = set(cached["names"])
                page_assets = {
                    Path(path)
                    for path in cached["assets"]
                    if (self.target / path).is_file()
                }
                names.update(page_names)
                assets.update(page_assets)
                pages[key] = {
                    "mtime": current[key],
                    "names": sorted(page_names),
                    "assets": sorted(path.as_posix() for path in page_assets),
                }
                continue
            source_dir = "" if rel.parent == Path(".") else rel.parent.as_posix()
            page_names, tokens, html_refs = self.stage_markdown(
                self.target,
                src,
                dst,
                source_dir,
                key,
            )
            page_assets = self.asset_refs(self.target, src, tokens, html_refs)
            names.update(page_names)
            assets.update(page_assets)
            pages[key] = {
                "mtime": current[key],
                "names": sorted(page_names),
                "assets": sorted(path.as_posix() for path in page_assets),
            }

        for rel in sorted(sections):
            self.stage_section(rel)

        for rel in sorted(assets):
            self.copy_asset(self.target, rel)

        self.prune_content(expected_pages, sections, prev_pages)
        self.prune_assets(prev_pages, pages)
        return names, pages

    def prune_content(
        self,
        expected_pages: set[Path],
        sections: set[Path],
        prev_pages: dict[str, PageState],
    ) -> None:
        for key in prev_pages:
            page = self.page_dst(Path(key))
            if page in expected_pages:
                continue
            shutil.rmtree(page.parent, ignore_errors=True)

        prev_sections: set[Path] = set()
        for key in prev_pages:
            prev_sections.update(self.parent_dirs(Path(key)))
        for rel in prev_sections - sections:
            idx = self.content_dir / rel / "_index.md"
            idx.unlink(missing_ok=True)

    def prune_assets(
        self,
        prev_pages: dict[str, PageState],
        pages: dict[str, PageState],
    ) -> None:
        previous = {
            Path(path)
            for page in prev_pages.values()
            for path in page["assets"]
        }
        current = {
            Path(path)
            for page in pages.values()
            for path in page["assets"]
        }
        for rel in previous - current:
            path = self.static_dir / rel
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
                continue
            path.unlink(missing_ok=True)

    def prune_shortcodes(self, previous: set[str], current: set[str]) -> None:
        for name in previous - current:
            (self.shortcodes_dir / f"{name}.html").unlink(missing_ok=True)

    def page_dst(self, rel: Path) -> Path:
        stem = rel.with_suffix("")
        return self.content_dir / "__ghrm" / stem / "page.md"

    def parent_dirs(self, rel: Path) -> set[Path]:
        dirs: set[Path] = set()
        parent = rel.parent
        while parent != Path("."):
            dirs.add(parent)
            parent = parent.parent
        return dirs

    def stage_section(self, rel: Path) -> None:
        dst = self.content_dir / rel / "_index.md"
        if dst.is_file():
            return
        title = self.escape_yaml(rel.name)
        source_dir = self.escape_yaml(rel.as_posix())
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
        source_path: str | None,
    ) -> tuple[set[str], list, set[str]]:
        raw = src.read_text(encoding="utf-8")
        tokens = MD.parse(raw)
        text, html_refs = self.rewrite_html(root, src, raw, tokens)
        page_url = None
        if self.mode == "dir" and source_path is not None:
            page_url = self.page_url(root, Path(source_path))
        staged, names = self.stage_text(text, source_dir, source_path, page_url)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(staged, encoding="utf-8")
        return names, tokens, html_refs

    def stage_text(
        self,
        text: str,
        source_dir: str | None,
        source_path: str | None,
        page_url: str | None,
    ) -> tuple[str, set[str]]:
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
        body = self.neutralize_invalid_shortcodes("".join(out))

        staged: list[str] = []
        if source_dir is not None or source_path is not None or page_url is not None:
            staged.append("---\n")
            if source_dir is not None or source_path is not None:
                staged.append("params:\n")
                if source_dir is not None:
                    staged.append(f'  sourceDir: "{self.escape_yaml(source_dir)}"\n')
                if source_path is not None:
                    staged.append(f'  sourcePath: "{self.escape_yaml(source_path)}"\n')
            if page_url is not None:
                staged.append(f'url: "{self.escape_yaml(page_url)}"\n')
            staged.append("---\n")
        staged.append(PREFIX)
        staged.append(body)
        return "".join(staged), names

    def write_nav(self, files: list[Path]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        path = self.data_dir / "nav.json"
        payload = {"dirs": self.nav_dirs(files)}
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def nav_dirs(self, files: list[Path]) -> dict[str, dict[str, object]]:
        direct_files: dict[Path, list[Path]] = {}
        dirs = {Path(".")}

        for rel in files:
            direct_files.setdefault(rel.parent, []).append(rel)
            parent = rel.parent
            while True:
                dirs.add(parent)
                if parent == Path("."):
                    break
                parent = parent.parent

        child_dirs: dict[Path, list[Path]] = {}
        for dir_rel in dirs:
            if dir_rel == Path("."):
                continue
            child_dirs.setdefault(dir_rel.parent, []).append(dir_rel)

        nav: dict[str, dict[str, object]] = {}
        for dir_rel in sorted(dirs):
            entries: list[dict[str, str]] = []
            readme = None

            for child_dir in sorted(child_dirs.get(dir_rel, []), key=lambda path: path.name.lower()):
                entries.append(
                    {
                        "kind": "dir",
                        "href": self.dir_url(child_dir),
                        "name": child_dir.name,
                    }
                )

            for file_rel in sorted(direct_files.get(dir_rel, []), key=lambda path: path.name.lower()):
                if file_rel.name.lower() == "readme.md":
                    readme = file_rel.as_posix()
                href = self.page_url(self.target, file_rel)
                if href is None:
                    continue
                entries.append(
                    {
                        "kind": "file",
                        "href": href,
                        "name": file_rel.name,
                        "sourcePath": file_rel.as_posix(),
                    }
                )

            item: dict[str, object] = {"entries": entries}
            if readme is not None:
                item["readme"] = readme
            nav[self.rel_key(dir_rel)] = item

        return nav

    def dir_url(self, rel: Path) -> str:
        if rel == Path("."):
            return "/"
        return f"/{rel.as_posix()}/"

    def rel_key(self, rel: Path) -> str:
        if rel == Path("."):
            return ""
        return rel.as_posix()

    def escape_yaml(self, text: str) -> str:
        return text.replace("\\", "\\\\").replace('"', '\\"')

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

    def neutralize_invalid_shortcodes(self, text: str) -> str:
        out: list[str] = []
        cursor = 0
        while True:
            starts = [pos for pos in (text.find("{{<", cursor), text.find("{{%", cursor)) if pos != -1]
            if not starts:
                out.append(text[cursor:])
                return "".join(out)
            start = min(starts)
            out.append(text[cursor:start])

            end = self.shortcode_end(text, start)
            if end is None:
                out.append(text[start:])
                return "".join(out)
            raw = text[start:end]
            tag = self.parse_tag(text, start)
            if tag is not None or (start > 0 and text[start - 1] == "\\"):
                out.append(raw)
            else:
                out.append(self.escape_shortcode(raw))
            cursor = end

    def shortcode_end(self, text: str, start: int) -> int | None:
        close = ">}}" if text[start + 2] == "<" else "%}}"
        end = text.find(close, start + 3)
        if end == -1:
            return None
        return end + len(close)

    def escape_shortcode(self, raw: str) -> str:
        escaped = html.escape(raw, quote=False)
        return escaped.replace("{", "&#123;").replace("}", "&#125;")

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
            return resolved.relative_to(root)
        except ValueError:
            return None

    def page_url(self, root: Path, rel: Path) -> str | None:
        path = root / rel
        if path.is_dir():
            return self.dir_url(rel)
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

    def rewrite_html(self, root: Path, src: Path, text: str, tokens: list) -> tuple[str, set[str]]:
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
        html_refs: set[str] = set()
        cursor = 0
        for fragment in fragments:
            start = text.find(fragment, cursor)
            if start == -1:
                continue
            parser = HtmlRewrite(self, src)
            parser.feed(fragment)
            parser.close()
            html_refs.update(parser.refs)
            out.append(text[cursor:start])
            out.append(parser.rendered())
            cursor = start + len(fragment)
        out.append(text[cursor:])
        return "".join(out), html_refs

    def asset_refs(
        self,
        root: Path,
        src: Path,
        tokens: list,
        html_refs: set[str],
    ) -> set[Path]:
        refs: set[Path] = set()
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
            if not (root / rel).is_file():
                continue
            refs.add(rel)

        for dest in html_refs:
            rel = self.relative_target(root, src, dest)
            if rel is None or rel.suffix.lower() == ".md":
                continue
            if not (root / rel).is_file():
                continue
            refs.add(rel)
        return refs

    def markdown_refs(self, root: Path, src: Path, tokens: list) -> set[Path]:
        refs: set[Path] = set()
        for token in self.inline_tokens(tokens):
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
        if self.fresh(src, dst):
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
