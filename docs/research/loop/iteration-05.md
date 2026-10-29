# Iteration 05: ungrounded synthesis path, evidence acquisition on non-CS topics

Runs analysed: BST 11, Photosynthesis 1.

## Classification and fixes
| ID | Class | Cause in code | Research | Fix |
|---|---|---|---|---|
| E14 | A whole answer path skipped grounding | Budget-exhausted branch returned `synthesize_answer` text directly (`ground_agent.py`) | Open Deep Research: final synthesis from sub-agents' cited findings | One `GroundAgent._ground()` used by BOTH answer paths; the synthesis path grounds on descendants' claims + gap re-queries |
| E15 | Pages never read in full on new topics | Fetch candidates needed ⅓ term coverage on a 2-sentence summary | (design) retrieval recall vs precision: read generously, filter what reaches the LLM | `FETCH_GATE = 0.15` for choosing pages to read; passages still pass `RELEVANCE_GATE` |
| E16 | Term matching failed on plurals ("reactions" ≠ "reaction") | `content_terms` had no stemming | standard IR normalisation | Plural stemming in `content_terms` (same rule as entity canonicalisation) |
| obs | "0 claims" runs couldn't be diagnosed from the log | evidence step printed nothing on success paths | — | One `[evidence]` summary line per step: source, passages, non-answers, synthesis failures, unfaithful, claims, per-provider reports |

Tests: `verify_dewey_fetch` 12/12 (#11 plurals, #12 low-coverage summary still read); 27 suites green.

## Re-run results (5a)
| Run | Grounded | Notes |
|---|---|---|
| Photosynthesis 2 | **2/3** (was 0/3); root support 0.862 with 6 verified citations; 1 honestly "only weak evidence" | full Wikipedia article now read |
| BST 12 | 2/2 (root support 0.75 with 5 verified citations, child 1.0) | root grounded through gap re-queries ("definition", "how it works") |

## Found by the new evidence log (5b)
| ID | Class | Cause | Fix |
|---|---|---|---|
| E17 | ~30 Groq calls per run rejected ("tool call validation failed: missing properties 'item' / 'origin' / 'predicate'"), each falling through to unstable Gemma 31B → 9-minute runs | Groq validates tool calls **server-side** against the JSON schema; the model used different key names (`status` for `origin`, `relation` for `predicate`). **instructor maps every Groq mode to TOOLS** (`JSON_SCHEMA → Mode.TOOLS`), so the earlier "use JSON_SCHEMA" relation fix in this repo never took effect | Tolerant schemas: optional fields with **conservative defaults** (`origin` → "uninvestigated", untyped relations dropped, verdict item → list position) and client-side alias mapping. Live probe: audit and faithfulness both succeed on Groq 20b/120b in 2–3.5 s with correct verdicts |
| E18 (open) | 3 of 4 passages sent to synthesis are judged non-answers | lexical BM25 over long chunks; one LLM call per passage | candidate: batched synthesis (1 call for N passages) and/or section-aware passages; measure first |

## 5c: retrieval quality (found through the live `ask` and Mitosis runs)
| ID | Class | Cause | Research | Fix | Measured |
|---|---|---|---|---|---|
| E19 | The passage explaining a sub-topic never reached the LLM ("Section: Insertion" ranked 19/170) | (a) chunking split headings from their text; (b) BM25 OR-query let common terms ("binary search tree") dominate; (c) my own derivational stemming pre-stemmed FTS input ("travers") so `query("traversal")` returned nothing | Contextual chunk headers (Anthropic "Contextual Retrieval", 2024); retrieve-then-rerank; IDF weighting | Section-aware chunker v2 (every passage carries "Section: X."; new passage per section), `CHUNKER_VERSION` + re-split on re-ingest + `scripts/dewey_refresh_outdated.py`; per-term pool expansion; archive-level IDF rerank with heading/title/lead-section bonuses; FTS gets ORIGINAL words (`query_words`) | **New benchmark `scripts/evaluate_dewey_retrieval.py` (13 hand-labelled cases, 3 topics): BM25 baseline hit@4 0.69 / MRR 0.62 → 1.00 / 0.85-0.88** (parameters chosen by grid search, not by eye) |
| E20 | Wrong pages fetched/searched: Mitosis got Protist/Chemotherapy/Animal from Wikipedia; both full-page reads spent on arXiv abstract pages | outgoing `keyword_query` used stemmed terms ("phas") and question filler ("happen each important"); abstracts were fetch candidates | query reformulation (keyword extraction) | `keyword_query` = original words minus stopwords and question filler, ≤6 words ("mitosis phases"); abstracts are never fetched | Wikipedia now returns Mitosis / Interphase / Cell cycle |
| obs | ask note said "no evidence" when a weak claim existed; `【1】`/`[1]` writer markers in answers point at the wrong source list | note ignored gap-search weak claims; markers number the writer's evidence | — | weak gap claims counted in the note; inline markers stripped | tests #21-22 |
| bug | a regex `` silently became a backspace byte (shell heredoc unescaping) | tooling | — | fixed; repo scanned (no other control bytes); memory note saved | — |

Live `ask` after 5c: BST insertion **grounded 1.0** (was ungrounded), Calvin cycle inputs/outputs **grounded 1.0** with 3 full-text citations and correct stoichiometry.

## 5d: first end-to-end chat (`.scuba/logs/chat_live_run1.log`) + Mitosis 2
Scorecard: conversation → brief → "yes" → real research job (424 s) → grounded findings with
Wikipedia sources, 4 statements honestly "not confirmed", gaps listed. Mitosis 1/2 grounded (was 0/2).

| ID | Seen in | Class | Cause | Research | Fix |
|---|---|---|---|---|---|
| E21 | chat | Discovery put "chemistry" and "about 4 hours a week for 6 weeks" into the SYLLABUS | the pending-question slot swallowed any reply; "and" split + "I know" filter kept "chemistry" | (slot filling) | a reply that answers another slot (background / time) is never read as syllabus |
| E22 | chat ask | the one good light-dependent claim was dropped by the faithfulness check; kept on a re-run | LLM judge variance | LLM-as-judge variance (reliable-scaffolding paper); NLI checkers' known paraphrase false negatives | **not loosened** — logged for measurement (a judge-agreement benchmark like the coverage one is the right next step) |
| E23 | Mitosis | every Mitosis section judged a non-answer: "only describes prometaphase, so it does not cover all phases" | per-passage synthesis judged each passage against the WHOLE multi-part question | Fusion-in-Decoder-style multi-passage QA: each passage contributes partial evidence | synthesis prompt: a passage fully answering ONE part is evidence for that part (0.5–0.9) |
| E24 | chat | research spent a sub-question on "a 6-week lesson plan"; placeholder topics in the research question | discovery's inferred placeholder syllabus was passed as research focus | — | only learner-supplied topics steer the research question |
| cos | chat | "(photosynthesis) (photosynthesis)" in gap searches | topic re-appended | — | append the topic only when absent |

Tests: `verify_chat` 15/15; regression green.

## 5e: re-runs after 5d
| Run | Result |
|---|---|
| Mitosis 3 (`discovery_live_mitosis_run3_iter05d.log`) | **4/4 grounded** (support 1.0 / 1.0 / 1.0 / 0.944; was 0/2 → 1/2): the partial-evidence fix (E23) let each phase's section answer its own sub-question. Reviewed afterwards: the metaphase answer ("…pull chromosomes toward opposite poles, aligning them at the metaphase plate") matches the Wikipedia passage ("centrosomes begin pulling the chromosomes towards opposite ends… the resulting tension causes the chromosomes to align along the metaphase plate"). **Correct; my flag was a false alarm from a truncated preview.** |
| Chat 2 (`chat_live_run2.log`) | mid-chat question **grounded** with a correct light-dependent explanation (run 1: "won't guess"); "I know basic biology and chemistry" no longer a syllabus topic; research focus no longer "lesson plan" (asked about chloroplast structure). Still: 2 of 3 sub-findings not grounded; Gemma sometimes wraps JSON in code fences (fallback absorbs it). |
| ask(anaphase), after the restructure | grounded 1.0 from the existing Archive (paths intact), correct (cohesin cleavage, anaphase A/B). |

## 5f: main-block restructure (owner request)
`backend/main_block/{interface.py, door, reasoning_engine/, research_engine/}` + `backend/llm`,
clients outside. `scripts/restructure_main_block.py` (git mv + 156 import rewrites, old paths deleted),
`backend/paths.py` (REPO_ROOT instead of folder-depth counting), `RetrievedResource` moved into the
research engine, model chains moved into the reasoning engine, two engine interfaces + the main-block
interface, boundary checker rewritten for 4 rules (negative-tested). Result: 0 failing modules,
0 leftover old paths, 0 missing imported names, **30/30 suites**, retrieval benchmark hit@4 1.00.
