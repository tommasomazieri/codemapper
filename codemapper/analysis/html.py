"""Deterministic HTML diagnostics via tree-sitter-html.

fallow only handles framework component templates, not standalone .html, so this
small pass covers plain HTML. Rules:

  duplicate_id      (error) two elements share an id
  broken_local_ref  (warn)  href/src points at a local file not on disk
  missing_alt       (info)  <img> without an alt attribute
  missing_lang      (info)  <html> without a lang attribute
  inline_script_loc (warn)  inline <script> body exceeds INLINE_SCRIPT_LOC lines

Import is guarded: if tree-sitter wheels are absent, ``find_html_issues`` returns
an empty list (the language pass is simply skipped).
"""

from pathlib import Path

from codemapper.analysis.findings import Finding

INLINE_SCRIPT_LOC = 50

# URI schemes / anchors that are never a local file ref.
_NON_LOCAL_PREFIXES = ("http://", "https://", "//", "#", "data:", "mailto:", "tel:", "javascript:")


def _parser():
    """Return a configured tree-sitter HTML parser, or None if unavailable."""
    try:
        import tree_sitter_html as tshtml
        from tree_sitter import Language, Parser
    except ImportError:
        return None
    lang = Language(tshtml.language())
    try:
        return Parser(lang)  # tree-sitter >= 0.22
    except TypeError:  # pragma: no cover - older binding
        p = Parser()
        p.set_language(lang)
        return p


def _text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", "replace")


def _attrs(tag_node, src: bytes) -> dict[str, str]:
    """Map of attribute name -> unquoted value for a start/self-closing tag node."""
    out: dict[str, str] = {}
    for child in tag_node.children:
        if child.type != "attribute":
            continue
        name = value = None
        for sub in child.children:
            if sub.type == "attribute_name":
                name = _text(sub, src).lower()
            elif sub.type in ("quoted_attribute_value", "attribute_value"):
                value = _text(sub, src).strip("'\"")
        if name is not None:
            out[name] = value or ""
    return out


def _tag_name(tag_node, src: bytes) -> str:
    for child in tag_node.children:
        if child.type == "tag_name":
            return _text(child, src).lower()
    return ""


def _is_local_ref(value: str) -> bool:
    v = value.strip()
    if not v:
        return False
    low = v.lower()
    if any(low.startswith(p) for p in _NON_LOCAL_PREFIXES):
        return False
    # Skip templating placeholders ({{ }}, <%= %>, ${ }).
    if "{{" in v or "${" in v or "<%" in v:
        return False
    return True


def _analyze_one(root: Path, rel: str) -> list[Finding]:
    parser = _parser()
    if parser is None:
        return []
    abspath = root / rel
    try:
        src = abspath.read_bytes()
    except OSError:
        return []

    tree = parser.parse(src)
    findings: list[Finding] = []
    ids_seen: dict[str, int] = {}
    base_dir = abspath.parent

    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type in ("start_tag", "self_closing_tag"):
            line = node.start_point[0] + 1
            tag = _tag_name(node, src)
            attrs = _attrs(node, src)

            if "id" in attrs and attrs["id"]:
                val = attrs["id"]
                if val in ids_seen:
                    findings.append(Finding(
                        rule="duplicate_id", severity="error", path=rel, line=line,
                        symbol=val, language="html",
                        message=f"Duplicate id '{val}' (also line {ids_seen[val]})"))
                else:
                    ids_seen[val] = line

            for ref_attr in ("href", "src"):
                if ref_attr in attrs:
                    val = attrs[ref_attr]
                    if _is_local_ref(val):
                        target = (base_dir / val.split("?")[0].split("#")[0]).resolve()
                        if not target.exists():
                            findings.append(Finding(
                                rule="broken_local_ref", severity="warn", path=rel, line=line,
                                language="html",
                                message=f"{ref_attr} '{val}' not found on disk"))

            if tag == "img" and "alt" not in attrs:
                findings.append(Finding(
                    rule="missing_alt", severity="info", path=rel, line=line,
                    language="html", message="<img> missing alt attribute"))

            if tag == "html" and "lang" not in attrs:
                findings.append(Finding(
                    rule="missing_lang", severity="info", path=rel, line=line,
                    language="html", message="<html> missing lang attribute"))

        elif node.type == "script_element":
            # Inline only: a <script src=...> has no raw_text body.
            for child in node.children:
                if child.type == "raw_text":
                    body = _text(child, src)
                    loc = sum(1 for ln in body.splitlines() if ln.strip())
                    if loc > INLINE_SCRIPT_LOC:
                        findings.append(Finding(
                            rule="inline_script_loc", severity="warn", path=rel,
                            line=node.start_point[0] + 1, language="html",
                            message=f"Inline <script> has {loc} lines (>{INLINE_SCRIPT_LOC}); extract to a module"))

        stack.extend(node.children)

    return findings


def find_html_issues(root: Path, html_files: list[str]) -> list[Finding]:
    """Run HTML diagnostics over the given repo-relative .html files.

    Returns [] (pass skipped) if tree-sitter-html is not installed.
    """
    if _parser() is None:
        return []
    root = root.resolve()
    findings: list[Finding] = []
    for rel in html_files:
        findings.extend(_analyze_one(root, rel))
    return findings
