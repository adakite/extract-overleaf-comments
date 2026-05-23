# Extract Overleaf Comments

Extract visible comments from a Chrome-saved Overleaf page and optionally map
Overleaf character offsets (`data-pos`) back to line numbers in a `.tex` file.

This is useful because Overleaf review-panel comments are not included in the
downloaded LaTeX source archive.

## Install

The extractor uses only the Python standard library.

From PyPI, once released:

```bash
pip install extract-overleaf-comments
```

From a local checkout:

```bash
python3 -m pip install .
```

Then run:

```bash
extract-overleaf-comments --help
```

## Development

```bash
python3 -m pip install -e ".[test]"
python3 -m pytest tests
python3 -m build
python3 -m twine check dist/*
```

## Usage

1. Open the Overleaf project.
2. Open the review/comments panel.
3. Use the browser's "Save page as..." feature and save the complete page.
4. Zip the saved `.html` file and its companion `_files/` directory, or pass a
   zip archive created by the browser.
5. Run:

```bash
python3 src/overleaf_comment_extractor.py Archive.zip --tex main.tex --out-prefix comments
```

The command writes:

- `comments.csv`
- `comments.md`

To also create a compilable annotated LaTeX copy:

```bash
python3 src/overleaf_comment_extractor.py Archive.zip \
  --tex main.tex \
  --out-prefix comments \
  --comment-tex
```

This writes `main_comments.tex` by default. The annotated file inserts red
thread markers such as `[T001]` near the Overleaf character offsets and adds a
final `Extracted Overleaf Comments` section with the full comment text.

To put comments directly in the PDF margin instead:

```bash
python3 src/overleaf_comment_extractor.py Archive.zip \
  --tex main.tex \
  --out-prefix comments \
  --comment-tex \
  --comment-placement margin
```

The margin mode groups all replies from one thread into one `\marginpar` note in
`\footnotesize` text. The default is `--comment-placement appendix`.

By default, this annotated copy is made standalone: the original document class
and package list are replaced by a minimal `article` setup, and missing figures
are rendered as placeholders. This makes the review PDF compile even when the
full private Overleaf project is not available locally. Use
`--preserve-comment-tex-preamble` if you want to keep the original LaTeX class
and package setup.

## Example

The repository contains a fake HTML snapshot and fake `.tex` file only. It does
not contain private Overleaf projects or real manuscripts.

```bash
cd examples/fake_overleaf_save
zip -r ../fake_overleaf_save.zip .
cd ../..
python3 src/overleaf_comment_extractor.py examples/fake_overleaf_save.zip \
  --tex examples/fake_project.tex \
  --out-prefix examples/fake_comments \
  --comment-tex examples/fake_project_comments.tex
```

## Release

PyPI publishing is configured through GitHub Actions Trusted Publishing. To
publish a release:

1. Create a pending publisher on PyPI for:
   - PyPI project: `extract-overleaf-comments`
   - Owner: `adakite`
   - Repository: `extract-overleaf-comments`
   - Workflow: `publish-pypi.yml`
   - Environment: `pypi`
2. Tag a version and push the tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

## Limitations

This tool parses comments that are present in the saved browser DOM. If Overleaf
has not loaded a thread, or if a collapsed/truncated comment is not present in
the DOM, the extractor cannot recover it from the HTML snapshot. For a more
complete capture, make sure the review panel is open and the relevant comments
are loaded before saving the page.
