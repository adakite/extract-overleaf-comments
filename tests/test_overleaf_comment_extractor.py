from overleaf_comment_extractor import extract_comments, map_rows_to_tex, write_annotated_tex


def test_extract_comments_with_reply_and_mapping():
    html = """
    <div class="review-panel-entry-comment" data-pos="14" data-top="120">
      <div class="review-panel-entry-user">Alice</div>
      <div class="review-panel-entry-time">2026-05-23</div>
      <div class="review-panel-comment-body">Clarify the opening sentence.</div>
      <div class="review-panel-entry-user">Bob</div>
      <div class="review-panel-entry-time">2026-05-24</div>
      <div class="review-panel-comment-body">Done in the next revision.</div>
    </div>
    """
    rows = extract_comments(html)

    assert len(rows) == 2
    assert rows[0]["thread"] == "T001"
    assert rows[0]["author"] == "Alice"
    assert rows[1]["message"] == 2
    assert rows[1]["comment"] == "Done in the next revision."

    mapped = map_rows_to_tex(rows, "First line.\nSecond line has text.\n")
    assert mapped[0]["line"] == 2
    assert mapped[0]["latex_context"] == "Second line has text."
    assert "[[POS]]cond line" in mapped[0]["latex_offset_context"]


def test_write_annotated_tex(tmp_path):
    tex_path = tmp_path / "paper.tex"
    tex = "\\documentclass{article}\n\\begin{document}\nHello world.\n\\end{document}\n"
    tex_path.write_text(tex, encoding="utf-8")
    rows = [
        {
            "thread": "T001",
            "message": 1,
            "data_pos": tex.index("world"),
            "line": 3,
            "column": 7,
            "author": "Alice",
            "time": "today",
            "possibly_truncated": False,
            "comment": "Clarify & expand.",
        }
    ]

    out = write_annotated_tex(tex, rows, tex_path)
    annotated = out.read_text(encoding="utf-8")

    assert "\\olcommentmarker{T001}" in annotated
    assert "\\section*{Extracted Overleaf Comments}" in annotated
    assert "Clarify \\& expand." in annotated


def test_write_margin_annotated_tex(tmp_path):
    tex_path = tmp_path / "paper.tex"
    tex = "\\documentclass{article}\n\\begin{document}\nHello world.\n\\end{document}\n"
    tex_path.write_text(tex, encoding="utf-8")
    rows = [
        {
            "thread": "T001",
            "message": 1,
            "data_pos": tex.index("world"),
            "line": 3,
            "column": 7,
            "author": "Alice",
            "time": "today",
            "possibly_truncated": False,
            "comment": "Clarify & expand.",
        }
    ]

    out = write_annotated_tex(tex, rows, tex_path, comment_placement="margin")
    annotated = out.read_text(encoding="utf-8")

    assert "\\olcommentmargin{T001}" in annotated
    assert "\\section*{Extracted Overleaf Comments}" not in annotated
    assert "Clarify \\& expand." in annotated
