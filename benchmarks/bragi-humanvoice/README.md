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
