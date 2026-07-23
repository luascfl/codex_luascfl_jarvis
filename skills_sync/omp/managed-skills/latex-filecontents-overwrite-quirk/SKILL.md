---
name: latex-filecontents-overwrite-quirk
description: How to handle LaTeX filecontents* not overwriting existing .bib/.toc files and avoiding malformed .toc crashes
---

## Origem
Criada a partir do contexto: `/home/lucas/Downloads/codex_latex_abnt`

# Latex Filecontents Overwrite Quirk

When modifying a LaTeX project that uses `\begin{filecontents*}{\jobname.bib}` or `\begin{filecontents*}{\jobname.toc}` to embed bibliography or table of contents placeholders:

1. **`filecontents*` does not overwrite existing files by default.** If you copied a base `template.bib` into your working directory or previously compiled the document, the embedded `filecontents*` block will be ignored with a warning like: `LaTeX Info: File 'template.bib' already exists on the system. Not generating it from this source.`
2. **Delete the old files first.** Before compiling, explicitly remove the `.bib` or `.toc` files from the directory so `filecontents*` can generate the updated versions.
3. **Avoid malformed dummy `.toc` entries.** If you use a dummy `.toc` inside `filecontents*` to prevent first-pass compilation crashes (common with `memoir` and `abntex2`), avoid manually typing `\contentsline` entries unless you match hyperref's exact argument count (which is often 4 or 5, not 3). It is much safer to leave the `.toc` dummy block empty or minimal (e.g., `\changetocdepth {4}` and `\babel@toc {brazil}{}\relax`) and let LaTeX regenerate the actual table of contents natively.
4. **Force recompilation.** Use `latexmk -g -xelatex -interaction=nonstopmode <file.tex>` to ensure LaTeX rebuilds everything, bypassing its internal up-to-date checks when you have only removed auxiliary files.
