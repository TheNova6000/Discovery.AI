from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .exceptions import QuestionEngineError
from backend.llm.client import structured_call
from backend.main_block.reasoning_engine.model_chains import MASTER_MODEL_CHAIN

_SYSTEM_PROMPT = """\
You are a synthesis auditor for a recursive investigation system. You are given \
two things: a final synthesized ANSWER produced by a reasoning step, and the \
KNOWN material — the actual sub-questions that were investigated and their \
answers, i.e. everything the synthesizer was actually given to work from.

Your job: decompose the ANSWER into its atomic propositions — split any sentence \
that bundles more than one factual claim into separate propositions — and \
classify EACH one as:

- "investigated": this proposition is directly stated, or a straightforward \
restatement/paraphrase, of something in KNOWN.
- "uninvestigated": you cannot trace this proposition to anything in KNOWN, even \
in paraphrase — KNOWN never actually established it.

CRITICAL: this is a TRACEABILITY judgment, not a truth judgment.
- "uninvestigated" does NOT mean false. A proposition can be completely accurate \
and still uninvestigated if KNOWN simply never covered it — mark it uninvestigated \
anyway. Do not let your own belief that something is obviously true cause you to \
mark it "investigated" when KNOWN never actually said it.
- "investigated" does NOT mean verified true. It means this specific investigation \
actually produced this specific information — nothing more.

For each "investigated" proposition, also list in `supported_by` the number(s) of the KNOWN item(s) that state it. Leave `supported_by` empty for "uninvestigated" propositions. Only use numbers that appear in KNOWN.

Keep output compact: do not quote or paraphrase KNOWN back at length anywhere in \
your response. This matters — verbose output on longer answers has already caused \
truncated, invalid responses from more than one provider.
"""


_ORIGIN_ALIASES = ("status", "classification", "label", "verdict")
_TEXT_ALIASES = ("proposition", "statement", "claim")


class AtomicClaim(BaseModel):
    text: str = Field(default="", description="One self-contained atomic proposition extracted from the answer.")
    origin: Literal["investigated", "uninvestigated"] = "uninvestigated"
    """Defaults to "uninvestigated": a statement the auditor didn't label is never
    counted as supported."""

    @model_validator(mode="before")
    @classmethod
    def _accept_aliases(cls, data):
        # Groq's tool calls used "status" for `origin` (loop iteration 05: the
        # server rejected ~30 audit calls per run for the missing key). With these
        # fields optional in the schema the call is accepted and mapped here.
        if isinstance(data, dict):
            data = dict(data)
            if "origin" not in data:
                for key in _ORIGIN_ALIASES:
                    if data.get(key) in ("investigated", "uninvestigated"):
                        data["origin"] = data[key]
                        break
            if not data.get("text"):
                for key in _TEXT_ALIASES:
                    if isinstance(data.get(key), str):
                        data["text"] = data[key]
                        break
        return data
    supported_by: list[int] = Field(
        default_factory=list,
        description="1-based numbers of the KNOWN items that state this proposition; empty if uninvestigated.",
    )


class SynthesisAudit(BaseModel):
    claims: list[AtomicClaim]


def _build_user_prompt(answer: str, known: list[str]) -> str:
    lines = ["KNOWN (what was actually investigated):"]
    for i, item in enumerate(known, start=1):
        lines.append(f"\n{i}. {item}")
    lines.append("\n\nANSWER (to audit):\n" + answer)
    return "\n".join(lines)


async def audit_synthesis(
    answer: str,
    known: list[str],
    *,
    model_chain: list[str] | None = None,
) -> SynthesisAudit:
    """One isolated experiment (docs/Memory.md's content-provenance design pass):
    decompose a synthesized ANSWER into atomic propositions and classify each as
    traceable to KNOWN or not. Deliberately a SEPARATE call from whatever produced
    ANSWER, not a self-report the generator makes about its own output — content
    provenance is designed as an audit problem, not a declared property, because
    self-attribution of "did this come from context or from my own training" is a
    documented LLM weak spot, not just an instruction-compliance risk.

    Lives in `backend/main_block/reasoning_engine/llm_steps` per Rules.md rule 2 (LLM calls confined to
    `backend/main_block/reasoning_engine/evidence` and `backend/main_block/reasoning_engine/llm_steps`).
    """
    chain = model_chain or MASTER_MODEL_CHAIN
    try:
        return await structured_call(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=_build_user_prompt(answer, known),
            response_model=SynthesisAudit,
            model_chain=chain,
        )
    except Exception as exc:  # noqa: BLE001 - collapse into this layer's typed boundary
        raise QuestionEngineError(
            f"audit_synthesis failed on every provider in {chain}: {exc}"
        ) from exc
