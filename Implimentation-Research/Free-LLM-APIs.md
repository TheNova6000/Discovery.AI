# Free-Tier LLM APIs (verified 2026)

The original Architecture.md picked Claude API, tiered by agent level. **That assumes a budget.** Anthropic and OpenAI do not have a standing free API tier — Anthropic gives a one-time ~$5 credit that expires, and any "student" program (Claude Campus, OpenAI's $100 Codex credit) is either a closed cohort or restricted to US/Canada university students. **Not usable as ongoing $0 infrastructure for an Indian undergrad.** HuggingFace's free tier is also effectively dead (~$0.10/month in credits — unusable).

## What's actually real and free (no credit card required)

| Provider | Free limits | Structured/JSON output? | Best for |
|---|---|---|---|
| **Google Gemini API** (AI Studio) | Flash-Lite ~1,000 requests/day, Flash ~250/day, 250K tokens/min shared | Yes — `responseSchema`/JSON mode, function calling. Best reliability of any free option. | **Primary** — high-volume ground-level calls |
| **Groq** | Per-model, e.g. Llama-3.1-8B-instant ~30 RPM / 14,400 RPD; GPT-OSS-120B/Qwen ~30 RPM / 1,000 RPD | Yes — `response_format: json_schema` with `strict: true` (constrained decoding, guaranteed schema match). Extremely fast inference. | **Secondary** — ground-level calls / fallback |
| **Cerebras** | ~1M tokens/day, ~30 RPM, 8K context cap, limited free model set | Some models | **Tertiary fallback** — ground-level calls when Groq/Gemini are exhausted |
| **OpenRouter** | `:free` models: 20 RPM always; 50 RPD at $0 spent, 1,000 RPD if $10 ever added | Varies by underlying model, not guaranteed | **Overflow pool**, not primary — free models get congested/deprecated |
| **Cohere trial key** | 1,000 calls/month, 20 RPM chat | Yes | Low-volume — good fit for rare **master-level synthesis** calls |
| **Mistral "Experiment" plan** | ~1B tokens/month but only ~2 RPM | Yes | Only for sparse, big-context synthesis calls — too slow for volume |
| **GitHub Models** | ~50 RPD / 10 RPM for flagship models, ~150 RPD for mini models, 8K in / 4K out tokens/request | Varies | Last-resort overflow (free to any GitHub account, not just Student Pack) |
| **SambaNova Cloud** | Free tier exists but stingy (10-30 RPM, low RPD) | Yes | Minor fallback only |

Note: the **GitHub Student Developer Pack itself does not currently include direct LLM API credits** (that changed — it's mainly Azure $100, Copilot, JetBrains now).

## Recommended free LLM strategy

Replace Architecture.md's "Claude Haiku/Sonnet/Opus tiered by level" with:

- **Ground-level (high-volume, structured JSON) calls**: round-robin **Gemini Flash-Lite → Groq → Cerebras**. Three independent free daily pools, all with real JSON-schema enforcement — this directly serves the Question Engine's typed `Question`/`Claim` outputs (Instructor already supports OpenAI-compatible and Gemini backends, so the existing Instructor-based design doesn't need to change, just the underlying client).
- **Master-level (rare, larger synthesis/structural-decision) calls**: **Gemini 2.5 Flash** (same free key, better reasoning) or **Cohere trial** (1,000/month is plenty since these calls are rare by design — see Rules.md rule 10's spawn-budget rule, which keeps master-level calls infrequent anyway).
- **Fallback chain when rate-limited**: OpenRouter free models → GitHub Models → Mistral Experiment.
- **Implementation note**: since litellm (already the chosen adapter in Architecture.md) supports all of these providers through one interface, build automatic fallback on HTTP 429 into the LLM adapter from day one — every one of these free tiers is capped low enough that a real multi-agent run will hit limits during normal use, not as an edge case.
