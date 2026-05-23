#!/usr/bin/env python3
"""Extract visible Overleaf review-panel comments from saved HTML archives."""

from __future__ import annotations

import argparse
import csv
import re
import zipfile
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from pathlib import Path


VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


@dataclass
class Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["Node"] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)

    def has_class(self, class_name: str) -> bool:
        return class_name in self.attrs.get("class", "").split()

    def text(self) -> str:
        parts = list(self.text_parts)
        for child in self.children:
            parts.append(child.text())
        return clean(unescape(" ".join(parts)))

    def find_all_by_class(self, class_name: str) -> list["Node"]:
        matches = []
        if self.has_class(class_name):
            matches.append(self)
        for child in self.children:
            matches.extend(child.find_all_by_class(class_name))
        return matches


class ReviewPanelHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        node = Node(tag, attr_map)
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.stack[-1].text_parts.append(data)


def parse_html(html_text: str) -> Node:
    parser = ReviewPanelHTMLParser()
    parser.feed(html_text)
    return parser.root


def read_html_from_zip(zip_path: str | Path) -> str:
    with zipfile.ZipFile(zip_path) as archive:
        html_files = [
            name
            for name in archive.namelist()
            if name.lower().endswith((".html", ".htm"))
            and not name.startswith("__MACOSX/")
            and not Path(name).name.startswith("._")
        ]
        if not html_files:
            raise RuntimeError("No HTML file found in archive.")

        html_files.sort(key=lambda name: archive.getinfo(name).file_size, reverse=True)
        return archive.read(html_files[0]).decode("utf-8", errors="replace")


def offset_to_line_col_and_context(tex: str, pos: str | int) -> tuple[int, int, str]:
    position = max(0, min(int(pos), len(tex)))

    line = tex.count("\n", 0, position) + 1
    last_newline = tex.rfind("\n", 0, position)
    column = position + 1 if last_newline == -1 else position - last_newline

    start = tex.rfind("\n", 0, position) + 1
    end = tex.find("\n", position)
    if end == -1:
        end = len(tex)

    return line, column, tex[start:end].strip()


def offset_snippet(tex: str, pos: str | int, radius: int = 90) -> str:
    position = max(0, min(int(pos), len(tex)))
    start = max(0, position - radius)
    end = min(len(tex), position + radius)
    snippet = tex[start:position] + "[[POS]]" + tex[position:end]
    return clean(snippet)


def escape_latex_text(text: object) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in str(text))


def extract_comments(html_text: str) -> list[dict[str, object]]:
    root = parse_html(html_text)
    entries = root.find_all_by_class("review-panel-entry-comment")

    rows: list[dict[str, object]] = []
    for thread_index, entry in enumerate(entries, 1):
        pos = entry.attrs.get("data-pos", "")
        top = entry.attrs.get("data-top", "")

        bodies = entry.find_all_by_class("review-panel-comment-body")
        users = entry.find_all_by_class("review-panel-entry-user")
        times = entry.find_all_by_class("review-panel-entry-time")

        for message_index, body_node in enumerate(bodies, 1):
            body = body_node.text()
            if not body:
                continue

            author = users[message_index - 1].text() if message_index - 1 < len(users) else ""
            time = times[message_index - 1].text() if message_index - 1 < len(times) else ""

            rows.append(
                {
                    "thread": f"T{thread_index:03d}",
                    "message": message_index,
                    "data_pos": pos,
                    "data_top": top,
                    "author": author,
                    "time": time,
                    "possibly_truncated": body.endswith(("...", "...", "…")),
                    "comment": body,
                }
            )

    return rows


def map_rows_to_tex(
    rows: list[dict[str, object]], tex_text: str | None
) -> list[dict[str, object]]:
    mapped_rows = []
    for row in rows:
        mapped = dict(row)
        mapped["line"] = ""
        mapped["column"] = ""
        mapped["latex_context"] = ""
        mapped["latex_offset_context"] = ""

        data_pos = str(mapped.get("data_pos", ""))
        if tex_text is not None and data_pos.isdigit():
            line, column, context = offset_to_line_col_and_context(tex_text, data_pos)
            mapped["line"] = line
            mapped["column"] = column
            mapped["latex_context"] = context
            mapped["latex_offset_context"] = offset_snippet(tex_text, data_pos)

        mapped_rows.append(mapped)
    return mapped_rows


def group_threads_for_latex(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    threads: dict[str, dict[str, object]] = {}
    for row in rows:
        thread = str(row["thread"])
        if thread not in threads:
            threads[thread] = {
                "thread": thread,
                "data_pos": str(row.get("data_pos", "")),
                "line": row.get("line", ""),
                "column": row.get("column", ""),
                "messages": [],
            }
        threads[thread]["messages"].append(row)

    sortable = []
    for thread in threads.values():
        data_pos = str(thread["data_pos"])
        position = int(data_pos) if data_pos.isdigit() else 0
        sortable.append((position, str(thread["thread"]), thread))
    return [thread for _, _, thread in sorted(sortable)]


def latex_preamble_injection() -> str:
    return r"""

% Overleaf comment annotations inserted by extract-overleaf-comments.
\usepackage{xcolor}
\usepackage{graphicx}
\DeclareRobustCommand{\olcommentmarker}[1]{\textcolor{red}{\textbf{[#1]}}}
\DeclareRobustCommand{\olcommententry}[4]{%
  \par\noindent\textcolor{red}{\textbf{#1.#2 -- #3:} #4}\par
}
\DeclareRobustCommand{\olcommentmargin}[2]{%
  \olcommentmarker{#1}%
  \marginpar{\raggedright\footnotesize\textcolor{red}{\textbf{#1}}\par #2}%
}
\let\olcommentoriginalincludegraphics\includegraphics
\renewcommand{\includegraphics}[2][]{%
  \IfFileExists{#2}{%
    \olcommentoriginalincludegraphics[#1]{#2}%
  }{%
    \fbox{\begin{minipage}{0.72\linewidth}\centering
    Missing figure placeholder:\\\texttt{\detokenize{#2}}
    \end{minipage}}%
  }%
}
"""


def standalone_preamble() -> str:
    return r"""

% Standalone fallback preamble inserted by extract-overleaf-comments.
% It is intentionally minimal and aimed at compiling a comment-review PDF.
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{xcolor}
\usepackage{graphicx}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{booktabs}
\usepackage{multirow}
\usepackage{rotating}
\usepackage{hyperref}
\setlength{\marginparwidth}{4cm}
\setlength{\marginparsep}{0.5cm}
\definecolor{lightgray}{gray}{0.95}
\makeatletter
\def\@author{}
\renewcommand{\author}[2][]{\g@addto@macro\@author{#2\par}}
\let\ps@firstpage\ps@plain
\makeatother
\newcommand{\orcidlink}[1]{}
\newcommand{\affil}[2][]{}
\newcommand{\submissiondate}[1]{}
\newcommand{\revisiondate}[1]{}
\newcommand{\accepteddate}[1]{}
\newcommand{\mstype}[1]{}
\newcommand{\summary}[1]{\section*{Summary}#1}
\newcommand{\license}[1][]{}
\newcommand{\addbibresource}[1]{}
\newcommand{\printbibliography}{}
\newcommand{\parencite}[1]{[cite]}
\newcommand{\parencites}[1]{[cite]}
\newcommand{\textcite}[1]{[cite]}
\newcommand{\ExecuteBibliographyOptions}[1]{}
\newcommand{\nameyeardelim}{}
\newcommand{\addcomma}{,}
\renewcommand{\includegraphics}[2][]{%
  \fbox{\begin{minipage}{0.78\linewidth}\centering
  Missing figure placeholder:\\\texttt{\detokenize{#2}}
  \end{minipage}}%
}
"""


def make_tex_standalone(tex_text: str) -> str:
    tex_text = re.sub(
        r"\\documentclass(?:\[[^\]]*\])?\{[^}]+\}",
        r"\\documentclass{article}",
        tex_text,
        count=1,
    )
    tex_text = re.sub(
        r"\\ExecuteBibliographyOptions\s*\{.*?\}\s*",
        "",
        tex_text,
        count=1,
        flags=re.DOTALL,
    )
    tex_text = re.sub(r"\\renewcommand\*?\{\\nameyeardelim\}\{[^}]*\}\s*", "", tex_text, count=1)
    tex_text = re.sub(r"\\usepackage(?:\[[^\]]*\])?\{[^}]+\}\s*", "", tex_text)
    tex_text = re.sub(r"\\definecolor\{lightgray\}\{gray\}\{0\.95\}\s*", "", tex_text)

    match = re.search(r"\\documentclass(?:\[[^\]]*\])?\{[^}]+\}", tex_text)
    if match:
        insert_at = match.end()
        tex_text = tex_text[:insert_at] + standalone_preamble() + tex_text[insert_at:]
    else:
        tex_text = r"\documentclass{article}" + standalone_preamble() + tex_text
    return tex_text


def inject_latex_preamble(tex_text: str) -> str:
    begin_document = tex_text.find(r"\begin{document}")
    if begin_document == -1:
        return latex_preamble_injection() + "\n" + tex_text
    return tex_text[:begin_document] + latex_preamble_injection() + "\n" + tex_text[begin_document:]


def build_comment_appendix(threads: list[dict[str, object]]) -> str:
    lines = [
        "",
        r"\clearpage",
        r"\section*{Extracted Overleaf Comments}",
        r"\addcontentsline{toc}{section}{Extracted Overleaf Comments}",
        "",
    ]
    for thread in threads:
        location = ""
        if thread["line"]:
            location = f" line {thread['line']}, column {thread['column']}"
        elif thread["data_pos"]:
            location = f" data-pos {thread['data_pos']}"

        lines.extend(
            [
                rf"\subsection*{{{escape_latex_text(thread['thread'])}{escape_latex_text(location)}}}",
                "",
            ]
        )
        for message in thread["messages"]:
            comment = escape_latex_text(message.get("comment", ""))
            author = escape_latex_text(message.get("author", "unknown author"))
            time = escape_latex_text(message.get("time", ""))
            msg = escape_latex_text(message.get("message", ""))
            lines.append(rf"\olcommententry{{{thread['thread']}}}{{{msg}}}{{{author}, {time}}}{{{comment}}}")
            if message.get("possibly_truncated"):
                lines.append(r"\textcolor{red}{\emph{This comment may be truncated in the saved HTML.}}\par")
            lines.append("")
    return "\n".join(lines)


def build_margin_note(thread: dict[str, object]) -> str:
    parts = []
    for message in thread["messages"]:
        msg = escape_latex_text(message.get("message", ""))
        author = escape_latex_text(message.get("author", "unknown author"))
        time = escape_latex_text(message.get("time", ""))
        comment = escape_latex_text(message.get("comment", ""))
        truncated = r" \emph{[truncated?]}" if message.get("possibly_truncated") else ""
        parts.append(rf"\textbf{{{msg}. {author}}} ({time}){truncated}: {comment}")
    return r"\par ".join(parts)


def marker_position(tex_text: str, pos: int) -> int:
    position = max(0, min(pos, len(tex_text)))
    while position > 0 and (
        tex_text[position - 1].isalnum() or tex_text[position - 1] in {"'", "-"}
    ):
        position -= 1
    return position


def find_matching_brace(text: str, open_brace: int) -> int | None:
    depth = 0
    escaped = False
    for index in range(open_brace, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def move_out_of_moving_argument(tex_text: str, position: int) -> int:
    pattern = re.compile(r"\\(?:caption|section|subsection|subsubsection)\*?(?:\[[^\]]*\])?\{")
    adjusted = position
    for match in pattern.finditer(tex_text):
        open_brace = match.end() - 1
        close_brace = find_matching_brace(tex_text, open_brace)
        if close_brace is None:
            continue
        if match.start() <= position <= close_brace:
            adjusted = max(adjusted, close_brace + 1)
    return adjusted


def move_out_of_float_environment(tex_text: str, position: int) -> int:
    adjusted = position
    for env in ("figure", "table"):
        pattern = re.compile(rf"\\begin\{{{env}\}}(?:\[[^\]]*\])?")
        for match in pattern.finditer(tex_text):
            end_match = re.search(rf"\\end\{{{env}\}}", tex_text[match.end() :])
            if end_match is None:
                continue
            end = match.end() + end_match.end()
            if match.start() <= position <= end:
                adjusted = max(adjusted, end)
    return adjusted


def safe_margin_position(tex_text: str, position: int) -> int:
    position = move_out_of_moving_argument(tex_text, position)
    position = move_out_of_float_environment(tex_text, position)
    position = move_out_of_moving_argument(tex_text, position)
    return position


def write_annotated_tex(
    tex_text: str,
    rows: list[dict[str, object]],
    tex_path: str | Path,
    out_path: str | Path | None = None,
    standalone: bool = True,
    comment_placement: str = "appendix",
) -> Path:
    tex_path = Path(tex_path)
    annotated_path = Path(out_path) if out_path else tex_path.with_name(f"{tex_path.stem}_comments.tex")
    threads = group_threads_for_latex(rows)

    insertions: list[tuple[int, str]] = []
    for thread in threads:
        data_pos = str(thread["data_pos"])
        if data_pos.isdigit():
            position = marker_position(tex_text, int(data_pos))
            thread_id = escape_latex_text(thread["thread"])
            if comment_placement == "margin":
                position = safe_margin_position(tex_text, position)
                marker = rf"\olcommentmargin{{{thread_id}}}{{{build_margin_note(thread)}}}"
            else:
                marker = rf"\olcommentmarker{{{thread_id}}}"
            insertions.append((position, marker))

    annotated = tex_text
    for position, marker in sorted(insertions, reverse=True):
        annotated = annotated[:position] + marker + annotated[position:]

    if standalone:
        annotated = make_tex_standalone(annotated)
    annotated = inject_latex_preamble(annotated)
    appendix = "" if comment_placement == "margin" else build_comment_appendix(threads)
    end_document = annotated.rfind(r"\end{document}")
    if not appendix:
        pass
    elif end_document == -1:
        annotated = annotated.rstrip() + "\n" + appendix + "\n"
    else:
        annotated = annotated[:end_document] + appendix + "\n" + annotated[end_document:]

    annotated_path.write_text(annotated, encoding="utf-8")
    return annotated_path


def write_outputs(
    rows: list[dict[str, object]], out_prefix: str | Path, tex_text: str | None = None
) -> tuple[Path, Path]:
    out_prefix = Path(out_prefix)
    csv_path = out_prefix.with_suffix(".csv")
    md_path = out_prefix.with_suffix(".md")
    mapped_rows = map_rows_to_tex(rows, tex_text)

    fields = [
        "thread",
        "message",
        "data_pos",
        "data_top",
        "line",
        "column",
        "author",
        "time",
        "possibly_truncated",
        "comment",
        "latex_offset_context",
        "latex_context",
    ]

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(mapped_rows)

    markdown = [
        "# Overleaf Comments Extraction",
        "",
        f"Extracted {len(mapped_rows)} messages including replies.",
        f"{sum(bool(row['possibly_truncated']) for row in mapped_rows)} messages appear truncated in the saved DOM.",
        "",
    ]

    for row in mapped_rows:
        title = f"## {row['thread']}.{row['message']}"
        title += f" - LaTeX line {row['line']}" if row["line"] else f" - pos {row['data_pos']}"
        if row["possibly_truncated"]:
            title += " [possibly truncated]"

        markdown.extend(
            [
                title,
                "",
                f"**Author:** {row['author']}",
                "",
                f"**Time:** {row['time']}",
                "",
                f"**data-pos:** `{row['data_pos']}`; **data-top:** `{row['data_top']}`",
                "",
                f"**Comment:** {row['comment']}",
                "",
            ]
        )

        if row["latex_offset_context"]:
            markdown.extend(
                [
                    "**LaTeX offset context:**",
                    "",
                    "```latex",
                    str(row["latex_offset_context"]),
                    "```",
                    "",
                ]
            )

        if row["latex_context"]:
            markdown.extend(["**LaTeX context:**", "", "```latex", str(row["latex_context"]), "```", ""])

    md_path.write_text("\n".join(markdown), encoding="utf-8")
    return csv_path, md_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract visible comments from a Chrome-saved Overleaf HTML archive."
    )
    parser.add_argument("archive", help="Chrome 'Save page as' Overleaf archive, usually a .zip")
    parser.add_argument("--tex", help="Corresponding .tex file; enables data-pos to line mapping")
    parser.add_argument("--out-prefix", default="overleaf_comments_extracted")
    parser.add_argument(
        "--comment-tex",
        nargs="?",
        const="",
        help="Write an annotated LaTeX copy. Defaults to '<input_stem>_comments.tex'.",
    )
    parser.add_argument(
        "--preserve-comment-tex-preamble",
        action="store_true",
        help="Keep the original document class/packages in --comment-tex output.",
    )
    parser.add_argument(
        "--comment-placement",
        choices=["appendix", "margin"],
        default="appendix",
        help="Place comments in a final appendix or directly in margin notes.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    html_text = read_html_from_zip(args.archive)
    rows = extract_comments(html_text)

    tex_text = None
    if args.tex:
        tex_text = Path(args.tex).read_text(encoding="utf-8", errors="replace")

    csv_path, md_path = write_outputs(rows, args.out_prefix, tex_text=tex_text)
    comment_tex_path = None
    if args.tex and args.comment_tex is not None:
        mapped_rows = map_rows_to_tex(rows, tex_text)
        comment_tex_path = write_annotated_tex(
            tex_text,
            mapped_rows,
            args.tex,
            out_path=args.comment_tex or None,
            standalone=not args.preserve_comment_tex_preamble,
            comment_placement=args.comment_placement,
        )

    print(f"Extracted {len(rows)} messages.")
    print(f"Wrote {csv_path}")
    print(f"Wrote {md_path}")
    if comment_tex_path:
        print(f"Wrote {comment_tex_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
