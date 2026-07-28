# Genres — what each one owes its reader

```bash
asgard skills run asgard-office -- outline                       # the catalogue
asgard skills run asgard-office -- outline postmortem            # one skeleton
asgard skills run asgard-office -- outline proposal --language ko -o spec.md
```

A skeleton prints front matter, the sections in the order the genre reads best,
and one `<!-- … -->` guidance line per section. The builders drop those comments,
so the guidance never reaches the document. Headings come in English or Korean
(`--language ko`); the structure is the same either way.

23 genres. What follows is the part a skeleton cannot carry: the failure that
defines each one.

## Documents

| Genre | Fails when |
|---|---|
| `report` | the summary does not stand alone. A reader who stops after three sentences must still be correctly informed. |
| `memo` | the ask is not in the first line. A decision memo that builds to its recommendation is a mystery novel. |
| `proposal` | out-of-scope is missing. That section, not the price, is what prevents the dispute. |
| `sow` | acceptance criteria are not testable by someone who was not in the room. |
| `minutes` | it records discussion but not decisions. If nothing was decided, say so — that is also a finding. |
| `one-pager` | it is two pages. |
| `prd` | non-goals are absent. They are the load-bearing half; without them scope drifts and nobody can point at when. |
| `design-doc` | no alternatives were rejected. A design doc with only the chosen approach documents an outcome, not a design process. |
| `adr` | the context is written as though the decision were obviously right. It has to still read correctly after the decision is reversed. |
| `postmortem` | there is no timeline with detection and mitigation times, or it names a person instead of a system. |
| `runbook` | a step's success cannot be checked, or there is no rollback. A procedure with no way back is a gamble. |
| `test-plan` | entry and exit criteria are missing, so nobody can say when testing is done. |
| `release-notes` | a breaking change appears without its migration step. |
| `user-manual` | sections are named after features rather than after what the user is trying to do. |
| `paper` | the method is not reproducible without writing to the authors. |
| `lit-review` | the search strategy is unstated, so a reader cannot tell what was excluded or why. |
| `resume` | responsibilities instead of outcomes. Verb, object, measured result. |
| `cover-letter` | it could be sent to a different organisation unchanged. |

## Decks

| Genre | Fails when |
|---|---|
| `deck` | it ends on a thank-you slide instead of the ask. |
| `pitch` | the market number is top-down. A bottom-up number invites the argument you want; a top-down one invites the argument you lose. |
| `qbr` | a missed quarter leads with what worked. Lead with the miss — hiding it costs the room's attention for the rest. |
| `readout` | the conclusion is not on slide one. |

## Workbooks

| Genre | Fails when |
|---|---|
| `model` | inputs, logic, and output are not on separate sheets, or a number is typed into a formula instead of referenced from a labelled cell. |

## Using a skeleton

```bash
asgard skills run asgard-office -- outline design-doc -o spec.md
# write the content; delete each <!-- --> line as its section is done
asgard skills run asgard-office -- build docx spec.md -o design.docx
asgard skills run asgard-office -- verify design.docx --strict
```

A skeleton is a starting shape, not a form to fill. Delete a section the
document genuinely does not need — but delete it deliberately, because each one
is there for the failure named above. The two that are almost never safe to drop
are `design-doc`'s alternatives and `postmortem`'s timeline.

To reuse a shape, turn it into a template rather than copying the file:

```bash
asgard skills run asgard-office -- template new house-design-doc --genre design-doc
```
