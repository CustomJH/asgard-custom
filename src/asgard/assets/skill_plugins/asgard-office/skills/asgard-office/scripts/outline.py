#!/usr/bin/env python3
"""Genre skeletons — the shape a document of a given kind is expected to have.

    asgard skills run asgard-office -- outline                 # list every genre
    asgard skills run asgard-office -- outline adr             # print one skeleton
    asgard skills run asgard-office -- outline proposal --language ko -o spec.md

A skeleton is a build-ready spec: front matter, headings in the order the genre
reads best, and one `<!-- … -->` line per section saying what belongs there.
Those comment lines never reach the rendered document — the builders drop them —
so the guidance can be blunt without leaking into the deliverable.

The structures are conventional on purpose. A decision record that hides the
alternatives, or an incident review with no timeline, fails as that genre no
matter how well it is written.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# (english, korean) heading pair, then the guidance line for that section.
Section = tuple[tuple[str, str], str]

GENRES: dict[str, dict] = {
    # ------------------------------------------------------------- business
    "report": {
        "kind": "docx",
        "title": ("Status report", "보고서"),
        "meta": {"toc": True, "number_headings": True},
        "sections": [
            (("Summary", "요약"), "The finding first, in three sentences. A reader who stops here must still be correctly informed."),
            (("What we measured", "측정 대상"), "Scope, period, and method. Name what was excluded."),
            (("Findings", "결과"), "One subsection per axis. Every number carries its source."),
            (("Risks", "위험"), "What could still go wrong, with the leading indicator for each."),
            (("Next", "다음 조치"), "Owner, action, date. No item without all three."),
        ],
    },
    "memo": {
        "kind": "docx",
        "title": ("Decision memo", "결정 메모"),
        "meta": {},
        "sections": [
            (("Recommendation", "권고"), "The ask, in one sentence, at the top. This is a decision memo, not a mystery."),
            (("Background", "배경"), "Only what the decider does not already know."),
            (("Options", "선택지"), "Two or three, each with its cost and what it forecloses."),
            (("Rationale", "근거"), "Why the recommendation beats the alternatives on the stated criteria."),
            (("Decision requested", "요청 사항"), "Who decides, by when, and what happens if they do not."),
        ],
    },
    "proposal": {
        "kind": "docx",
        "title": ("Proposal", "제안서"),
        "meta": {"toc": True, "cover": True, "number_headings": True},
        "sections": [
            (("Understanding the need", "과업 이해"), "Restate the client's problem in their words before offering anything."),
            (("Proposed approach", "제안 방식"), "Method and why it fits this problem rather than being your usual one."),
            (("Scope", "과업 범위"), "In scope, and — the part that prevents the dispute — explicitly out of scope."),
            (("Deliverables", "산출물"), "A table: artefact, format, acceptance criterion."),
            (("Schedule", "일정"), "Phases with dates and the dependency that could move each one."),
            (("Team", "수행 조직"), "Who does the work, not who signs the contract."),
            (("Pricing", "비용"), "Line items with units. State what is excluded (travel, licences, third-party fees)."),
            (("Assumptions and terms", "가정 및 조건"), "Every assumption whose failure changes the price."),
        ],
    },
    "sow": {
        "kind": "docx",
        "title": ("Statement of work", "과업 지시서"),
        "meta": {"toc": True, "number_headings": True},
        "sections": [
            (("Purpose", "목적"), "What the engagement is for, in the contract's language."),
            (("Scope of work", "과업 범위"), "Numbered, so a change request can cite a clause."),
            (("Deliverables and acceptance", "산출물 및 검수"), "Acceptance criteria must be testable by someone who was not there."),
            (("Schedule and milestones", "일정 및 마일스톤"), "Milestone, date, payment trigger."),
            (("Responsibilities", "책임 분담"), "Both sides. Client obligations are where schedules actually slip."),
            (("Change control", "변경 관리"), "How a change is requested, priced, and approved."),
            (("Assumptions", "전제"), ""),
        ],
    },
    "minutes": {
        "kind": "docx",
        "title": ("Meeting minutes", "회의록"),
        "meta": {},
        "sections": [
            (("Attendees", "참석자"), "Present, absent, and who represented whom."),
            (("Agenda", "안건"), ""),
            (("Discussion", "논의"), "Positions and the reasoning, not a transcript."),
            (("Decisions", "결정 사항"), "What was decided and by whom. If nothing was decided, say so."),
            (("Actions", "조치 사항"), "A table: action, owner, due date."),
            (("Open questions", "미결"), "Carried into the next meeting."),
        ],
    },
    "one-pager": {
        "kind": "docx",
        "title": ("One-pager", "요약서"),
        "meta": {},
        "sections": [
            (("The problem", "문제"), "One paragraph. Whose problem, and what it costs them."),
            (("What we are doing", "해결 방안"), ""),
            (("Why now", "지금인 이유"), ""),
            (("What we need", "필요 사항"), "The ask, quantified."),
        ],
    },
    # ------------------------------------------------------------ technical
    "prd": {
        "kind": "docx",
        "title": ("Product requirements", "제품 요구사항"),
        "meta": {"toc": True, "number_headings": True},
        "sections": [
            (("Problem", "문제"), "The user's problem, with evidence it exists. Not the feature."),
            (("Goals and non-goals", "목표 및 비목표"), "Non-goals are the load-bearing half — they stop scope drift later."),
            (("Users", "사용자"), "Segments and the job each is hiring this for."),
            (("Requirements", "요구사항"), "Numbered and testable. 'Fast' is not a requirement; a latency budget is."),
            (("Success metrics", "성공 지표"), "Baseline, target, and how it is measured."),
            (("Open questions", "미결 사항"), ""),
        ],
    },
    "design-doc": {
        "kind": "docx",
        "title": ("Design document", "설계 문서"),
        "meta": {"toc": True, "number_headings": True},
        "sections": [
            (("Context", "배경"), "What exists today and why it no longer suffices."),
            (("Goals and non-goals", "목표 및 비목표"), ""),
            (("Design", "설계"), "The chosen approach, with a diagram if the shape matters."),
            (("Alternatives considered", "검토한 대안"), "At least two, each with the reason it lost. A design doc with no rejected alternatives was not a design process."),
            (("Failure modes", "실패 양상"), "What breaks, how it is detected, and what the blast radius is."),
            (("Rollout", "적용 계획"), "Migration, backward compatibility, and the rollback path."),
            (("Open questions", "미결 사항"), ""),
        ],
    },
    "adr": {
        "kind": "docx",
        "title": ("Architecture decision record", "아키텍처 결정 기록"),
        "meta": {},
        "sections": [
            (("Status", "상태"), "Proposed / accepted / superseded by ADR-NNN. One line."),
            (("Context", "배경"), "The forces in play. Write it so it still reads correctly after the decision is reversed."),
            (("Decision", "결정"), "Active voice: 'We will …'."),
            (("Consequences", "결과"), "Good and bad. A record with only upsides is marketing."),
            (("Alternatives", "대안"), "What else was on the table and why it lost."),
        ],
    },
    "postmortem": {
        "kind": "docx",
        "title": ("Incident review", "장애 리뷰"),
        "meta": {"toc": True},
        "sections": [
            (("Summary", "요약"), "What broke, for whom, for how long."),
            (("Impact", "영향"), "Users affected, requests lost, money or trust cost. Numbers."),
            (("Timeline", "타임라인"), "A table: time (with timezone), event, who observed it. Detection time and mitigation time are the two that matter."),
            (("Root cause", "근본 원인"), "The chain, not the last link. Stop at the point a change would have prevented it."),
            (("What went well", "잘 된 점"), "Keep it — this is where the next incident's detection comes from."),
            (("Action items", "조치 항목"), "Owner and date on every one. Split prevention from detection."),
            (("Lessons", "교훈"), "Blameless: name systems and gaps, not people."),
        ],
    },
    "runbook": {
        "kind": "docx",
        "title": ("Runbook", "운영 절차서"),
        "meta": {"toc": True, "number_headings": True},
        "sections": [
            (("When to use this", "적용 시점"), "The alert or symptom that brings someone here at 03:00."),
            (("Preconditions", "전제 조건"), "Access, tools, and what must be true before starting."),
            (("Procedure", "절차"), "Numbered commands with expected output. A step whose success cannot be checked is not a step."),
            (("Verification", "검증"), "How to know it worked."),
            (("Rollback", "롤백"), "Always present. A procedure with no way back is a gamble."),
            (("Escalation", "에스컬레이션"), "Who to wake, and after how long."),
        ],
    },
    "test-plan": {
        "kind": "docx",
        "title": ("Test plan", "시험 계획"),
        "meta": {"toc": True, "number_headings": True},
        "sections": [
            (("Scope", "범위"), "What is under test and what is explicitly not."),
            (("Environment", "환경"), "Versions, data, and how the environment is reset between runs."),
            (("Cases", "시험 항목"), "A table: id, precondition, steps, expected result."),
            (("Entry and exit criteria", "착수 및 종료 기준"), "What must hold to start, and what must hold to call it done."),
            (("Risks", "위험"), ""),
        ],
    },
    "release-notes": {
        "kind": "docx",
        "title": ("Release notes", "릴리스 노트"),
        "meta": {},
        "sections": [
            (("Highlights", "주요 변경"), "What a user will notice, in their language."),
            (("Added", "추가"), ""),
            (("Changed", "변경"), ""),
            (("Fixed", "수정"), ""),
            (("Breaking changes", "호환성 변경"), "With the migration step for each. Never leave this to the reader."),
        ],
    },
    "user-manual": {
        "kind": "docx",
        "title": ("User manual", "사용 설명서"),
        "meta": {"toc": True, "number_headings": True},
        "sections": [
            (("Before you start", "시작하기 전에"), "Prerequisites and what the reader is assumed to know."),
            (("Getting started", "시작하기"), "The shortest path to one successful outcome."),
            (("Tasks", "작업"), "One subsection per task, named by what the user wants, not by the feature."),
            (("Reference", "참조"), "Options, fields, limits."),
            (("Troubleshooting", "문제 해결"), "Symptom, cause, fix. Written from the symptom the user sees."),
        ],
    },
    # ------------------------------------------------------------- academic
    "paper": {
        "kind": "docx",
        "title": ("Research paper", "연구 논문"),
        "meta": {"toc": True, "number_headings": True},
        "sections": [
            (("Abstract", "초록"), "Problem, method, result, significance — one sentence each."),
            (("Introduction", "서론"), "The gap this fills, ending in the contribution claim."),
            (("Related work", "선행 연구"), "Grouped by approach, not listed by author."),
            (("Method", "방법"), "Reproducible by a competent reader with no further correspondence."),
            (("Results", "결과"), "Findings without interpretation. Effect sizes, not only significance."),
            (("Discussion", "논의"), "Interpretation, and the limitations you would raise as a reviewer."),
            (("Conclusion", "결론"), ""),
            (("References", "참고문헌"), ""),
        ],
    },
    "lit-review": {
        "kind": "docx",
        "title": ("Literature review", "문헌 검토"),
        "meta": {"toc": True, "number_headings": True},
        "sections": [
            (("Question", "검토 질문"), "Stated so a reader can judge whether a source is in or out."),
            (("Search strategy", "검색 전략"), "Databases, terms, inclusion and exclusion criteria, dates."),
            (("Themes", "주제별 정리"), "One subsection per theme, synthesising across sources."),
            (("Gaps", "연구 공백"), "What the literature does not answer."),
            (("References", "참고문헌"), ""),
        ],
    },
    # ----------------------------------------------------------- individual
    "resume": {
        "kind": "docx",
        "title": ("Resume", "이력서"),
        "meta": {"page": {"margins": "16mm"}},
        "sections": [
            (("Summary", "요약"), "Three lines. What you do, at what scale, with what result."),
            (("Experience", "경력"), "Per role: scope, then outcomes with numbers. Verb, object, measured result."),
            (("Skills", "역량"), "Grouped, and honest about depth."),
            (("Education", "학력"), ""),
        ],
    },
    "cover-letter": {
        "kind": "docx",
        "title": ("Cover letter", "자기소개서"),
        "meta": {},
        "sections": [
            (("Opening", "지원 동기"), "Why this role at this organisation — specific enough that it could not be sent elsewhere."),
            (("Evidence", "근거"), "Two examples that match the posting's stated needs."),
            (("Close", "맺음"), "What you are asking for."),
        ],
    },
    # ----------------------------------------------------------------- deck
    "deck": {
        "kind": "pptx",
        "title": ("Presentation", "발표"),
        "meta": {"size": "16x9"},
        "slides": [
            ("title", ("Title", "제목"), "One line that states the conclusion, not the topic."),
            ("stat", ("The numbers", "핵심 수치"), "Three at most, each `value :: label`."),
            ("bullets", ("What is happening", "현황"), "Four bullets. If you need six, you need two slides."),
            ("two-col", ("Before and after", "대비"), "Split the list with a `|||` item."),
            ("table", ("Detail", "세부"), ""),
            ("section", ("What we are asking for", "요청"), "End on the ask, not on a thank-you slide."),
        ],
    },
    "pitch": {
        "kind": "pptx",
        "title": ("Pitch", "투자 제안"),
        "meta": {"size": "16x9"},
        "slides": [
            ("title", ("Company purpose", "회사 소개"), "One declarative sentence. Not a tagline."),
            ("bullets", ("Problem", "문제"), "Whose pain, how they solve it today, what that costs."),
            ("bullets", ("Solution", "해결"), "Show the thing. Describe it second."),
            ("stat", ("Why now", "지금인 이유"), "The change that made this possible or necessary."),
            ("stat", ("Market", "시장"), "Bottom-up. A top-down number invites the wrong argument."),
            ("bullets", ("Competition", "경쟁"), "Name the real alternatives, including doing nothing."),
            ("bullets", ("Business model", "수익 모델"), "Unit economics, not just the pricing page."),
            ("bullets", ("Team", "팀"), "Why this team for this problem."),
            ("table", ("Traction", "성과"), "The metric that compounds, over time."),
            ("section", ("The ask", "요청"), "Amount, use of funds, and what it buys in milestones."),
        ],
    },
    "qbr": {
        "kind": "pptx",
        "title": ("Quarterly review", "분기 리뷰"),
        "meta": {"size": "16x9"},
        "slides": [
            ("title", ("Quarter in one line", "한 줄 요약"), ""),
            ("stat", ("Against plan", "계획 대비"), "Three headline numbers with their targets."),
            ("bullets", ("What worked", "성과"), ""),
            ("bullets", ("What did not", "미달"), "Lead with these if the quarter missed. Hiding them costs the room's attention."),
            ("table", ("Metrics", "지표"), ""),
            ("bullets", ("Next quarter", "다음 분기"), "Commitments with owners."),
        ],
    },
    "readout": {
        "kind": "pptx",
        "title": ("Findings readout", "결과 보고"),
        "meta": {"size": "16x9"},
        "slides": [
            ("title", ("What we found", "결론"), "The conclusion on slide one."),
            ("bullets", ("How we looked", "방법"), "Method and sample, briefly. Enough to judge the finding."),
            ("stat", ("Evidence", "근거"), ""),
            ("bullets", ("What it means", "해석"), ""),
            ("section", ("Recommendation", "권고"), ""),
        ],
    },
    # ------------------------------------------------------------ workbooks
    "model": {
        "kind": "xlsx",
        "title": ("Financial model", "재무 모형"),
        "meta": {},
        "sections": [],
    },
}

SKELETONS = GENRES  # the name `template.py` imports


def _front(genre: str, spec: dict, language: str) -> list[str]:
    title = spec["title"][1 if language == "ko" else 0]
    lines = [
        "---",
        'title: "{{title}}"',
        f"subtitle: {title}",
        'author: "{{author}}"',
        'date: "{{date}}"',
    ]
    for key, value in spec.get("meta", {}).items():
        if isinstance(value, dict):
            lines.append(f"{key}:")
            lines += [f"  {inner}: {item}" for inner, item in value.items()]
        else:
            lines.append(f"{key}: {str(value).lower() if isinstance(value, bool) else value}")
    lines.append("---")
    return lines


def _doc_skeleton(genre: str, spec: dict, language: str) -> str:
    lines = _front(genre, spec, language)
    for heading, guidance in spec["sections"]:
        lines += ["", f"# {heading[1 if language == 'ko' else 0]}"]
        if guidance:
            lines.append(f"<!-- {guidance} -->")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _deck_skeleton(genre: str, spec: dict, language: str) -> str:
    lines = _front(genre, spec, language)
    for index, (layout, heading, guidance) in enumerate(spec["slides"]):
        if index:
            lines += ["", "---"]
        lines += ["", f"## {heading[1 if language == 'ko' else 0]}", f"<!-- layout: {layout} -->"]
        if guidance:
            lines.append(f"<!-- {guidance} -->")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


_MODEL_SKELETON = """\
title: "{{title}}"
author: "{{author}}"

# A model is inputs, then logic, then output — in that order, on separate sheets.
# Blue text on yellow marks a cell a human fills in; everything else is a formula.
sheets:
  - name: Assumptions
    title: Assumptions
    columns:
      - {header: Item, width: 34}
      - {header: Value, width: 14}
      - {header: Source, width: 44}
    rows:
      - ["<assumption>", 0.0, "<where this number came from>"]
    inputs: [B4]
    legend: true

  - name: Model
    columns:
      - {header: Period, width: 12}
      - {header: Driver, width: 16, format: "$#,##0"}
      - {header: Result, width: 16, format: "$#,##0"}
    rows:
      - ["P1", 0, 0]
    cells:
      C2: "=B2*(1+Assumptions!$B$4)"

  - name: Output
    title: Summary
    columns:
      - {header: Metric, width: 28}
      - {header: Value, width: 18, format: "$#,##0"}
    cells:
      B2: "=SUM(Model!C2:C13)"
"""


def skeleton(genre: str, kind: str = "", language: str = "en") -> str:
    spec = GENRES.get(genre)
    if spec is None:
        raise ValueError(f"unknown genre {genre!r} — try one of: {', '.join(sorted(GENRES))}")
    resolved = kind or spec["kind"]
    if resolved == "xlsx" or spec["kind"] == "xlsx":
        return _MODEL_SKELETON
    if resolved == "pptx" or "slides" in spec:
        if "slides" not in spec:
            raise ValueError(f"genre {genre!r} has no deck form — pick a deck genre, or build it as a document")
        return _deck_skeleton(genre, spec, language)
    return _doc_skeleton(genre, spec, language)


def catalogue() -> list[dict]:
    return [
        {
            "genre": name,
            "kind": spec["kind"],
            "title": spec["title"][0],
            "sections": len(spec.get("sections") or spec.get("slides") or []),
        }
        for name, spec in sorted(GENRES.items(), key=lambda item: (item[1]["kind"], item[0]))
    ]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="outline", description="Document genre skeletons")
    parser.add_argument("genre", nargs="?", default="")
    parser.add_argument("--language", default="en", choices=("en", "ko"))
    parser.add_argument("--kind", default="", choices=("", "docx", "pptx", "xlsx", "md"))
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not args.genre:
        rows = catalogue()
        if args.json:
            import json

            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            for row in rows:
                print(f"{row['genre']:<16} {row['kind']:<5} {row['sections']:>2} sections   {row['title']}")
        return 0
    try:
        body = skeleton(args.genre, args.kind, args.language)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(body, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
