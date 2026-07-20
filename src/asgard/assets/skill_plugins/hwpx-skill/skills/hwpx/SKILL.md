---
name: hwpx
description: HWPX 문서를 읽고 생성·편집·검증하며, 사용자가 명시한 경우 HWP를 HWPX로 변환한다.
---

# HWPX

Use the bundled commands; do not install packages or locate the skill directory yourself.

```bash
# HWPX or HWP text extraction. HWP is converted only in a temporary directory;
# the original is never changed and no converted document is retained.
asgard skills run hwpx -- extract document.hwpx --format markdown
asgard skills run hwpx -- extract document.hwp --format markdown

# Persistent HWP -> HWPX conversion: only when the user explicitly requests it.
asgard skills run hwpx -- convert input.hwp -o output.hwpx

# Other bundled utilities (examples)
asgard skills run hwpx -- script validate output.hwpx --layout
asgard skills run hwpx -- script fill_hwpx analyze form.hwpx
asgard skills run hwpx -- script fill_hwpx fill form.hwpx output.hwpx --values values.json
```

Rules:

1. Preserve the source file. Never replace an `.hwp` in place.
2. Do not persistently convert `.hwp` unless the user explicitly asks for `.hwpx` output.
3. After creating or XML-editing HWPX, run `fix_namespaces`, `finalize_hwpx --strip-linesegarray --layout`, then `validate --layout`.
4. Prefer `fill_hwpx analyze -> fill -> verify -> check --strict` for forms; do not rewrite their XML tree.
5. Visual fidelity still needs Hancom inspection for important documents.

Load `UPSTREAM.md` only for the full decision tree, and load the specific file under `references/` only when its topic is needed.
