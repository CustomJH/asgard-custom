# Bragi — human-voice bench

Does the human-voice patch actually change what Asgard writes, or does it only add a gate that
feels reassuring? Three measurements, in increasing order of how much they prove.

| | what it measures | what it cannot prove |
|---|---|---|
| Part A | how faithfully the upstream tell corpora were ported | generalization — the patterns came from these same repos |
| Part B | how often the gate misfires on real human technical prose | detection strength |
| Part C | whether the prompt contract changes a live model's output | anything about models other than the one measured |

## Running

```bash
# Part A needs the upstream repos cloned side by side into one directory
git clone --depth 1 https://github.com/DaleSeo/korean-skills.git         <dir>/korean-skills
git clone --depth 1 https://github.com/blader/humanizer.git              <dir>/humanizer
git clone --depth 1 https://github.com/longhang2004/vietnamese-humanizer <dir>/vi-hum
git clone --depth 1 https://github.com/gonta223/humanizer-ja.git         <dir>/ja-hum
uv run python benchmarks/bragi-humanvoice/build_corpus.py <dir>

uv run python benchmarks/bragi-humanvoice/measure.py            # Part A + B, no LLM, seconds
uv run python benchmarks/bragi-humanvoice/live_ab.py --model qwen3:8b   # Part C, needs local ollama
```

## Part A — upstream labeled pairs

250 samples pulled from four third-party repos that publish before/after pairs. The labels are
theirs, not mine. 64 of the samples come from the Vietnamese repo's spelling and typography rules
(`sát nhập` → `sáp nhập`, space before a comma); those are scored separately because Bragi is a
voice gate, not a spell checker.

| lang | AI n | human n | recall | false positive |
|---|---|---|---|---|
| en | 32 | 29 | 43.8% | 0.0% |
| ko | 21 | 17 | 76.2% | 5.9% |
| vi | 42 | 38 | 23.8% | 0.0% |
| ja | 6 | 1 | 33.3% | 0.0% |
| **all** | **101** | **85** | **41.6%** | **1.2%** |

Recall tracks sample length, because the cluster rule needs more than one tell to fire:

| sample length | n | recall |
|---|---|---|
| under 100 chars | 59 | 27.1% |
| 100–250 chars | 38 | 57.9% |
| over 250 chars | 4 | 100% |

The gate reads whole reports, which land in the top two bands. A single 40-character sentence
carrying one mild tell is deliberately allowed through — that is the same trade that keeps Part B
near zero.

**What this does not show.** Bragi's patterns were ported from these repos, so a high number here
would mean the port is faithful, not that the detector generalizes. Read it as port fidelity.
The Vietnamese figure is genuinely low: 14 of the upstream's 43 patterns are ported.

## Part B — held-out human corpus

The number that decides whether the gate is safe to leave on. Every sample is prose the author of
this repository actually wrote, none of it connected to the pattern sources. A false positive here
costs a wasted model round trip and, in the worst case, replaces an answer with a notice.

| source | n | false positive | grades |
|---|---|---|---|
| git commit bodies | 326 | 0.0% | A:326 |
| tracked `.md` prose | 101 | 1.0% | A:100 B:1 |
| personal memory docs | 113 | 0.0% | A:113 |
| module docstrings | 137 | 0.7% | A:136 B:1 |
| **total** | **677** | **0.44%** | |

Vendored upstream skill assets and `archive/` are excluded — that text is not this author's.

Three earlier revisions of the detector were rejected against this corpus rather than by taste:

- Korean comma density at the 0.55 threshold flagged 3.7% of commit bodies. KatFishNet measured
  61% for LLM Korean against 26% for humans on news and essays, but this gate reads technical
  prose, where people enumerate with commas. Raised to 0.70 and to a minimum of 8 sentences.
- Bolded inline headers (`- **X**:`) were the single largest source of misfires on the repo's own
  specs and checklists, where the format is legitimate. Demoted from S2 to S3, so it only counts
  inside a cluster.
- Sentence-ending monotony fired 635 times on English lists, because the last three characters of
  an English sentence are not a morphological ending. Restricted to Korean and Japanese.

The em dash went the same way. Wikipedia's guidance calls it the most reliable English tell, and
`blader/humanizer` bans it outright, but this repository's human prose uses it constantly — so it
is S3, contributing to a cluster and never firing alone.

A fourth revision was rejected the same way on 2026-08-19, while porting the sentence-completion
axis that [`snflkd/fluent-korean`](https://github.com/snflkd/fluent-korean) documents. Ending a
sentence on a noun phrase (`… 갈리는 자리.`) is the defect that repository names first, and the
Bragi contract already forbids it, but no threshold made it measurable here — the author's release
notes and memory entries are written in note form and legitimately end on nouns.

**The block below is what `measure.py` prints, from one dated run (2026-08-20).** The corpus is
rebuilt from live git history, so it drifts by a commit or two between runs; read the printed line,
not this page, when the two disagree. The block is pasted from that command's output rather than
typed. Every count in this section lives in that block: the prose around it names the mechanism and
points at the printed line, and it never restates a value or cites a figure for a draft that is no
longer in the tree.

```
KO-unfinished-sentence  fires on 0 of 2004 human samples · catches 8/10 hand-written broken sentences
blind spot              4532 of 8232 Korean sentences (55.1%) carry a dash, comma, or colon and are exempt — of those 8232, 2716 carry a comma (33.0%)
noun-phrase endings     not shipped — misfire on 544 samples by threshold:
  0.20=17.3%  0.25=14.2%  0.30=12.1%  0.35=10.8%  0.40= 9.7%  0.50= 7.4%
```

The rejected detector lives in `measure.py` (`_noun_ending_ratio`) rather than in the library, so
the trade-off can be re-measured instead of taken on trust. No cut between 0.20 and 0.50 brings the
misfire rate near zero, which is what kept the noun-phrase axis in the contract and out of the judge.

What did ship is the narrow half — a sentence ending on a connective (`캐시를 지우도록.`), where the
following clause is missing rather than reordered. The ten broken sentences it is scored against are
checked in as `BROKEN_KO`. The two it misses end on `읽고` and `쓰면`, where the ending cannot be told
from the nouns `보고` and `화면` without a morphological analyser, so those two stems are left
uncovered on purpose.

Four guards earned their place by measurement, each after the rule fired on something human:

- Sentences are reassembled paragraph-first, because prose folds at the screen width and the fold
  lands on a particle, so a line read as a sentence ends on 를 or 로 and every wrapped paragraph
  looks broken. The line-splitting draft was discarded rather than tuned; `measure.py` measures the
  rule that shipped, not the one that did not.
- A tail carried after a dash, a comma, or a colon is a continuation of the sentence before it, not
  a clause that went missing (`… 판정기를 끄는 것이라서.`, `6회차, 전/후를 번갈아, 뒤집어서.`,
  `이유가 그것이다: 옛 배치를 계속 증명하지 않도록.`). **This guard is the rule's blind spot; the printed
  `blind spot` line is its size.** Putting one comma into a `BROKEN_KO` sentence puts it out of the
  rule's reach. Adding the
  colon widened the exemption further and cost no detection, because none of the sentences it newly
  exempted ended on a connective. The two shapes cannot be told apart without a morphological analyser, so the rule
  claims only what it can see.
- `까지만` ends in the same two syllables as the connective `지만` while being a particle. The rule
  refuses it by lookbehind rather than by the length floor that happened to hide it.
- `-습니까`/`-ㅂ니까` is the formal question ending, not the connective `-니까`. The verdict found this
  one, on `적용하시겠습니까?` — a complete sentence the first draft called unfinished. Questions are
  skipped outright, and the period-typo case is split by the ㅂ 종성 on the preceding syllable.

Scanned across every tracked `.md` paragraph of 40 characters or more, plus all commit bodies,
docstrings under `src/asgard`, and memory entries, the rule fires only inside vendored upstream text
under `ref/` and `assets/skill_plugins/`, and those hits are real (`… 재시도 가능하도록.`).
`measure.py` reads docstrings from `src/asgard` only; widening the scan to `tests/` is what turned
up the colon case above.

**The Part B table above is the 677-sample revision and has not been recomputed since.** The same
harness on today's corpus, about three times that size, reports misfire rates between roughly a
quarter and nearly all of each source, and `KO-josa-spacing` alone accounts for most of the hits.
Those are mostly that rule's own true positives — the author does write `PASS 를` — which is what
breaks the corpus's premise that human text must never fire. Run `measure.py` for the current
numbers, and read the per-rule counts rather than the totals until the corpus is relabeled.

## Part C — live A/B on a real model

Same task, same model, same seed; only the system prompt changes.

- **Z** — no style canon, just the reporting instruction
- **A** — Lagom canon (Asgard before this patch)
- **B** — Lagom canon + Bragi canon (Asgard after this patch)
- **C** — condition A's output pushed through the gate's real rewrite prompt

Z is measured so that the share Lagom already handles is not credited to Bragi.

Six tasks × three languages (en/ko/vi). Each task supplies fixed verified facts and asks for a
four-to-five paragraph completion report. A first attempt asked for a short summary and every
condition scored A: 130-character outputs are too short for any tell to appear, and the experiment
distinguished nothing. Prose length is a precondition for measuring prose style.

Results are written to `live_ab.json` after every row, so a killed run keeps what it measured.

### Results — qwen3:8b, 18 reports per condition

| lang | canon | gate fires | tells / 1k chars | grade A | mean chars |
|---|---|---|---|---|---|
| en | none | 50% | 4.28 | 50% | 1861 |
| en | lagom | 33% | 2.70 | 67% | 1474 |
| en | **+bragi** | **0%** | **0.00** | **100%** | 1249 |
| ko | none | 100% | 34.26 | 17% | 816 |
| ko | lagom | 83% | 23.04 | 17% | 776 |
| ko | **+bragi** | **67%** | **8.19** | **50%** | 718 |
| vi | none | 100% | 2.61 | 17% | 1730 |
| vi | lagom | 83% | 5.89 | 17% | 1493 |
| vi | **+bragi** | **67%** | **5.27** | **67%** | 1161 |
| **all** | none | 83% | 13.72 | 28% | 1469 |
| **all** | lagom | 67% | 10.54 | 33% | 1248 |
| **all** | **+bragi** | **44%** | **4.48** | **72%** | 1043 |

Against unpatched Asgard (lagom), the contract cuts tell density 57% and lifts clean reports from
33% to 72%. Against no style contract at all, density falls 67%. Reports also get shorter at each
step, 1469 → 1248 → 1043 characters, which follows from "stop at the last fact".

Per language, the picture is uneven and worth stating plainly:

- **English** is fully solved on this sample: no report tripped the gate.
- **Korean** shows the largest density drop, 34.26 → 8.19, but two thirds of reports still trip the
  gate. Korean machine writing survives an instruction better than English does, which is the same
  asymmetry KatFishNet gives as the reason language-specific detection is needed at all.
- **Vietnamese** density barely moves (5.89 → 5.27) while grade A triples (17% → 67%). The contract
  is shifting severity rather than volume: decisive S1 tells go, weaker ones remain.

One anomaly, reported rather than smoothed: for Vietnamese, Lagom alone scores *worse* than no
canon (2.61 → 5.89). With six reports per cell that is within noise, but it is in the data.

### Repair path

12 of 18 condition-A drafts tripped the gate. Pushing each through the real rewrite prompt:

- tell density 15.81 → 9.06 per 1k chars
- 50% came back fully clean; the other half kept at least one tell

So the gate's repair is a real improvement but not a guarantee at this model size. That is why the
runtime accepts a rewrite when it strictly reduces tells rather than demanding zero: refusing
anything short of perfect would hand the user a notice instead of an answer.


## Honest limits

- Part C measures one 8B local model. A larger model writes differently, and the effect size will
  differ. The direction is what is being claimed, not the magnitude.
- Recall on short text is low by design. This gate is tuned for whole reports.
- Japanese has 7 labeled samples. That figure is an indication, not a measurement.
- No claim is made that Bragi defeats any AI-text classifier, and it should not be used for that.
  It grades writing quality; it never claims a text was machine-written.
