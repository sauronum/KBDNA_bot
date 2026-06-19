from __future__ import annotations

import hashlib
import json
import re
import socket
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen

from app.storage_io import write_json_atomic


YFULL_BASE_URL = "https://www.yfull.com"
_CACHE_SCHEMA_VERSION = 2
_DEFAULT_CACHE_TTL_SECONDS = 24 * 60 * 60
_MAX_HTML_BYTES = 3 * 1024 * 1024
_BRANCH_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9*._-]{0,79}")
_MACRO_BRANCHES = set("ABCDEFGHIJKLMNOPQRST")
TREE_YDNA = "ytree"
TREE_MTDNA = "mtree"
_TREE_CONFIG = {
    TREE_YDNA: ("tree", "YTree"),
    TREE_MTDNA: ("mtree", "MTree"),
}


def _tree_config(tree_type: str) -> tuple[str, str]:
    try:
        return _TREE_CONFIG[tree_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported YFull tree type: {tree_type}") from exc


class YFullLookupError(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class YFullChildBranch:
    name: str
    snps: tuple[str, ...]
    formed_ybp: int | None
    tmrca_ybp: int | None
    formed_ci_ybp: tuple[int, int] | None
    tmrca_ci_ybp: tuple[int, int] | None
    public_sample_count: int


@dataclass(frozen=True)
class YFullGeography:
    label: str
    count: int


@dataclass(frozen=True)
class YFullBranch:
    name: str
    parent: str
    path: tuple[str, ...]
    snps: tuple[str, ...]
    formed_ybp: int | None
    tmrca_ybp: int | None
    formed_ci_ybp: tuple[int, int] | None
    tmrca_ci_ybp: tuple[int, int] | None
    children: tuple[YFullChildBranch, ...]
    public_sample_count: int
    geographies: tuple[YFullGeography, ...]
    tree_version: str
    release_date: str
    source_url: str
    fetched_at: str


@dataclass(frozen=True)
class YFullLookupResult:
    branch: YFullBranch
    cache_status: str


@dataclass
class _ParsedNode:
    branch_id: str
    parent_id: str
    name: str = ""
    snp_text: str = ""
    extra_snp_text: str = ""
    age_text: str = ""
    age_title: str = ""
    public_sample_count: int = 0


@dataclass
class _LiContext:
    branch_id: str = ""


class _YFullTreeParser(HTMLParser):
    def __init__(self, *, path_segment: str = "tree") -> None:
        super().__init__(convert_charrefs=True)
        self.path_segment = path_segment
        self.breadcrumbs: list[str] = []
        self.nodes: list[_ParsedNode] = []
        self.public_sample_count = 0
        self.geography_counts: dict[str, int] = {}
        self.all_text: list[str] = []
        self._node_by_id: dict[str, _ParsedNode] = {}
        self._li_stack: list[_LiContext] = []
        self._tree_ul_depth = 0
        self._breadcrumb_div_depth = 0
        self._capture_tag = ""
        self._capture_kind = ""
        self._capture_node: _ParsedNode | None = None
        self._capture_text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        classes = set(str(attributes.get("class") or "").split())

        if tag == "div":
            if attributes.get("id") == "bc":
                self._breadcrumb_div_depth = 1
            elif self._breadcrumb_div_depth:
                self._breadcrumb_div_depth += 1

        if tag == "ul":
            if attributes.get("id") == "tree":
                self._tree_ul_depth = 1
            elif self._tree_ul_depth:
                self._tree_ul_depth += 1

        if self._breadcrumb_div_depth and tag == "a":
            self._start_capture(tag, "breadcrumb")

        if not self._tree_ul_depth:
            return

        if tag == "li":
            raw_id = str(attributes.get("id") or "")
            branch_id = raw_id[1:] if raw_id.startswith("l") else ""
            parent_id = next((item.branch_id for item in reversed(self._li_stack) if item.branch_id), "")
            self._li_stack.append(_LiContext(branch_id=branch_id))
            if branch_id:
                node = _ParsedNode(branch_id=branch_id, parent_id=parent_id)
                self.nodes.append(node)
                self._node_by_id[branch_id] = node
            if attributes.get("valsampleid") or attributes.get("valSampleID"):
                self.public_sample_count += 1
                for context in self._li_stack:
                    node = self._node_by_id.get(context.branch_id)
                    if node is not None:
                        node.public_sample_count += 1
            return

        node = self._current_node()
        if node is None:
            return
        if tag == "a" and ("yf-root" in classes or f"/{self.path_segment}/" in str(attributes.get("href") or "")):
            self._start_capture(tag, "name", node)
        elif tag == "span" and "yf-snpforhg" in classes:
            self._start_capture(tag, "snps", node)
        elif tag == "span" and "yf-plus-snps" in classes:
            node.extra_snp_text = str(attributes.get("title") or "").strip()
        elif tag == "span" and "yf-age" in classes:
            node.age_title = str(attributes.get("title") or "").strip()
            self._start_capture(tag, "age", node)
        elif tag == "b" and "yf-geo" in classes:
            geography = _geography_group_label(str(attributes.get("title") or ""))
            if geography:
                self.geography_counts[geography] = self.geography_counts.get(geography, 0) + 1

    def handle_endtag(self, tag: str) -> None:
        if self._capture_tag == tag:
            self._finish_capture()

        if tag == "li" and self._tree_ul_depth and self._li_stack:
            self._li_stack.pop()
        if tag == "ul" and self._tree_ul_depth:
            self._tree_ul_depth -= 1
        if tag == "div" and self._breadcrumb_div_depth:
            self._breadcrumb_div_depth -= 1

    def handle_data(self, data: str) -> None:
        clean = data.strip()
        if clean:
            self.all_text.append(clean)
        if self._capture_tag:
            self._capture_text.append(data)

    def _current_node(self) -> _ParsedNode | None:
        branch_id = next((item.branch_id for item in reversed(self._li_stack) if item.branch_id), "")
        return self._node_by_id.get(branch_id)

    def _start_capture(self, tag: str, kind: str, node: _ParsedNode | None = None) -> None:
        self._capture_tag = tag
        self._capture_kind = kind
        self._capture_node = node
        self._capture_text = []

    def _finish_capture(self) -> None:
        value = " ".join("".join(self._capture_text).split())
        if self._capture_kind == "breadcrumb" and value and value.lower() != "home":
            self.breadcrumbs.append(value)
        elif self._capture_node is not None:
            if self._capture_kind == "name" and not self._capture_node.name:
                self._capture_node.name = value
            elif self._capture_kind == "snps":
                self._capture_node.snp_text = value
            elif self._capture_kind == "age":
                self._capture_node.age_text = value
        self._capture_tag = ""
        self._capture_kind = ""
        self._capture_node = None
        self._capture_text = []


def normalize_yfull_branch_query(value: str, *, tree_type: str = TREE_YDNA) -> str:
    path_segment, _ = _tree_config(tree_type)
    clean = value.strip().strip("<>")
    if not clean:
        raise YFullLookupError("invalid_query")

    if "://" in clean:
        parsed = urlparse(clean)
        host = (parsed.hostname or "").lower()
        if host not in {"yfull.com", "www.yfull.com"}:
            raise YFullLookupError("invalid_query")
        tree_path_re = re.compile(rf"/(?:live/|sc/|chart/)?{re.escape(path_segment)}/([^/?#]+)/?", re.IGNORECASE)
        match = tree_path_re.search(parsed.path)
        if match is None:
            raise YFullLookupError("invalid_query")
        clean = unquote(match.group(1))

    clean = clean.strip().strip("/")
    if _BRANCH_RE.fullmatch(clean) is None or ".." in clean:
        raise YFullLookupError("invalid_query")
    if tree_type == TREE_YDNA and not any(character.isdigit() for character in clean) and clean.upper() not in _MACRO_BRANCHES:
        raise YFullLookupError("invalid_query")
    if "-" in clean:
        prefix, suffix = clean.split("-", 1)
        return f"{prefix.upper()}-{suffix.upper()}"
    return clean[:1].upper() + clean[1:]


def parse_yfull_branch_html(html_text: str, *, source_url: str, tree_type: str = TREE_YDNA) -> YFullBranch:
    path_segment, tree_label = _tree_config(tree_type)
    parser = _YFullTreeParser(path_segment=path_segment)
    try:
        parser.feed(html_text)
        parser.close()
    except Exception as exc:
        raise YFullLookupError("parse_error") from exc

    root = next((node for node in parser.nodes if not node.parent_id and node.name), None)
    if root is None:
        raise YFullLookupError("not_found" if tree_label in html_text else "parse_error")

    text = " ".join(parser.all_text)
    version_match = re.search(rf"{re.escape(tree_label)}\s+v([0-9.]+)", text, flags=re.IGNORECASE)
    release_match = re.search(rf"(?:Haplogroup\s+)?{re.escape(tree_label)}\s+v?([0-9.]+)\s*\(([^)]+)\)", text, flags=re.IGNORECASE)
    children = tuple(
        YFullChildBranch(
            name=node.name or node.branch_id,
            snps=_split_snps(node.snp_text, node.extra_snp_text),
            formed_ybp=_age_value(node.age_text, "formed"),
            tmrca_ybp=_age_value(node.age_text, "TMRCA"),
            formed_ci_ybp=_age_interval(node.age_title, "formed"),
            tmrca_ci_ybp=_age_interval(node.age_title, "TMRCA"),
            public_sample_count=node.public_sample_count,
        )
        for node in parser.nodes
        if node.parent_id == root.branch_id and (node.name or node.branch_id)
    )
    path = tuple(parser.breadcrumbs) + (root.name,)
    canonical_url = f"{YFULL_BASE_URL}/{path_segment}/{quote(root.name, safe='-*._')}/"
    return YFullBranch(
        name=root.name,
        parent=parser.breadcrumbs[-1] if parser.breadcrumbs else "",
        path=path,
        snps=_split_snps(root.snp_text, root.extra_snp_text),
        formed_ybp=_age_value(root.age_text, "formed"),
        tmrca_ybp=_age_value(root.age_text, "TMRCA"),
        formed_ci_ybp=_age_interval(root.age_title, "formed"),
        tmrca_ci_ybp=_age_interval(root.age_title, "TMRCA"),
        children=children,
        public_sample_count=root.public_sample_count or parser.public_sample_count,
        geographies=tuple(
            YFullGeography(label=label, count=count)
            for label, count in sorted(parser.geography_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
        tree_version=version_match.group(1) if version_match else "",
        release_date=release_match.group(2).strip() if release_match else "",
        source_url=canonical_url or source_url,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def fetch_yfull_html(url: str, *, timeout_seconds: float = 20.0) -> str:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "KBDNAbot/1.0 (public YFull branch lookup)",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            data = response.read(_MAX_HTML_BYTES + 1)
    except HTTPError as exc:
        if exc.code == 404:
            raise YFullLookupError("not_found") from exc
        raise YFullLookupError("unavailable") from exc
    except (URLError, TimeoutError, socket.timeout, OSError) as exc:
        raise YFullLookupError("unavailable") from exc
    if len(data) > _MAX_HTML_BYTES:
        raise YFullLookupError("response_too_large")
    return data.decode("utf-8", errors="replace")


class YFullBranchService:
    def __init__(
        self,
        cache_dir: Path,
        *,
        cache_ttl_seconds: int = _DEFAULT_CACHE_TTL_SECONDS,
        fetch_html: Callable[[str], str] = fetch_yfull_html,
        tree_type: str = TREE_YDNA,
    ) -> None:
        self.path_segment, self.tree_label = _tree_config(tree_type)
        self.tree_type = tree_type
        self.cache_dir = cache_dir
        self.cache_ttl_seconds = max(0, int(cache_ttl_seconds))
        self.fetch_html = fetch_html
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def lookup(self, query: str, *, force_refresh: bool = False) -> YFullLookupResult:
        branch_name = normalize_yfull_branch_query(query, tree_type=self.tree_type)
        cache_path = self._cache_path(branch_name)
        cached = self._read_cache(cache_path)
        if cached is not None and not force_refresh and self._is_fresh(cache_path):
            return YFullLookupResult(branch=cached, cache_status="cache")

        source_url = f"{YFULL_BASE_URL}/{self.path_segment}/{quote(branch_name, safe='-*._')}/"
        try:
            html_text = self.fetch_html(source_url)
            branch = parse_yfull_branch_html(html_text, source_url=source_url, tree_type=self.tree_type)
            if not _branch_matches_query(branch_name, branch):
                raise YFullLookupError("parse_error")
        except YFullLookupError as exc:
            if cached is not None and exc.reason in {"unavailable", "parse_error", "response_too_large"}:
                return YFullLookupResult(branch=cached, cache_status="stale")
            raise
        self._write_cache(cache_path, branch)
        return YFullLookupResult(branch=branch, cache_status="live")

    def _cache_path(self, branch_name: str) -> Path:
        identity = branch_name if self.tree_type == TREE_YDNA else f"{self.tree_type}:{branch_name}"
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        return self.cache_dir / f"{digest}.json"

    def _is_fresh(self, path: Path) -> bool:
        try:
            return time.time() - path.stat().st_mtime <= self.cache_ttl_seconds
        except OSError:
            return False

    @staticmethod
    def _read_cache(path: Path) -> YFullBranch | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or payload.get("schema_version") != _CACHE_SCHEMA_VERSION:
            return None
        branch = payload.get("branch")
        if not isinstance(branch, dict):
            return None
        try:
            children = tuple(
                YFullChildBranch(
                    name=str(item.get("name") or ""),
                    snps=tuple(str(snp) for snp in item.get("snps", [])),
                    formed_ybp=_optional_int(item.get("formed_ybp")),
                    tmrca_ybp=_optional_int(item.get("tmrca_ybp")),
                    formed_ci_ybp=_optional_interval(item.get("formed_ci_ybp")),
                    tmrca_ci_ybp=_optional_interval(item.get("tmrca_ci_ybp")),
                    public_sample_count=int(item.get("public_sample_count") or 0),
                )
                for item in branch.get("children", [])
                if isinstance(item, dict)
            )
            return YFullBranch(
                name=str(branch.get("name") or ""),
                parent=str(branch.get("parent") or ""),
                path=tuple(str(item) for item in branch.get("path", [])),
                snps=tuple(str(item) for item in branch.get("snps", [])),
                formed_ybp=_optional_int(branch.get("formed_ybp")),
                tmrca_ybp=_optional_int(branch.get("tmrca_ybp")),
                formed_ci_ybp=_optional_interval(branch.get("formed_ci_ybp")),
                tmrca_ci_ybp=_optional_interval(branch.get("tmrca_ci_ybp")),
                children=children,
                public_sample_count=int(branch.get("public_sample_count") or 0),
                geographies=tuple(
                    YFullGeography(label=str(item.get("label") or ""), count=int(item.get("count") or 0))
                    for item in branch.get("geographies", [])
                    if isinstance(item, dict)
                ),
                tree_version=str(branch.get("tree_version") or ""),
                release_date=str(branch.get("release_date") or ""),
                source_url=str(branch.get("source_url") or ""),
                fetched_at=str(branch.get("fetched_at") or ""),
            )
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _write_cache(path: Path, branch: YFullBranch) -> None:
        write_json_atomic(path, {"schema_version": _CACHE_SCHEMA_VERSION, "branch": asdict(branch)})


def _split_snps(primary: str, extra: str = "") -> tuple[str, ...]:
    values = []
    for item in re.split(r"\s*\*\s*", " * ".join(value for value in (primary, extra) if value)):
        clean = unescape(item).strip()
        if clean and clean not in values:
            values.append(clean)
    return tuple(values)


def _branch_matches_query(query: str, branch: YFullBranch) -> bool:
    query_aliases = _branch_identity_aliases(query)
    branch_aliases: set[str] = set()
    for value in (branch.name, *branch.snps):
        branch_aliases.update(_branch_identity_aliases(value))
    return bool(query_aliases & branch_aliases)


def _branch_identity_aliases(value: str) -> set[str]:
    clean = value.strip().upper()
    aliases = {re.sub(r"[^A-Z0-9]+", "", clean)}
    if "-" in clean:
        aliases.add(re.sub(r"[^A-Z0-9]+", "", clean.split("-", 1)[1]))
    aliases.update(re.findall(r"[A-Z]+[0-9][A-Z0-9]*", clean))
    return {alias for alias in aliases if alias}


def _age_value(value: str, label: str) -> int | None:
    match = re.search(rf"\b{re.escape(label)}\s+([0-9][0-9,]*)\s+ybp\b", value, flags=re.IGNORECASE)
    if match is None:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _age_interval(value: str, label: str) -> tuple[int, int] | None:
    match = re.search(
        rf"\b{re.escape(label)}\s+CI\s+95%\s+([0-9][0-9,]*)\s*<->\s*([0-9][0-9,]*)\s+ybp\b",
        value,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    try:
        values = (int(match.group(1).replace(",", "")), int(match.group(2).replace(",", "")))
    except ValueError:
        return None
    return min(values), max(values)


def _geography_group_label(value: str) -> str:
    clean = unescape(value).strip()
    return clean.split(" (", 1)[0].strip()


def _optional_int(value) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _optional_interval(value) -> tuple[int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    values = int(value[0]), int(value[1])
    return min(values), max(values)
