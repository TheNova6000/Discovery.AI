# Indian Government / Student-Specific Compute Programs (verified 2026)

Checked against official/primary sources (`.gov.in`, official program pages), not forum hearsay. Blunt verdict up front: **none of these are realistically usable by a solo 2nd-year B.Tech student this month.** They're aimed at startups, institutions, or formal research projects, not individual side projects.

| Program | What it actually is | Why it doesn't work for this case |
|---|---|---|
| **IndiaAI Compute Portal** (pmgatishakti.gov.in/IndiaAICompute) | Real and live — a **subsidized GPU rental marketplace**, ~₹65-67/hr per GPU with up to 40% subsidy. Students are a listed eligibility category. | Requires Meri Pehchaan/DigiLocker login, an APAAR ID, formal registration + document verification, a written project proposal with technical approach and "bill of materials," and approval by a Program Monitoring and Evaluation Committee. It's a grant application, not a signup — weeks of friction, no guarantee of approval, and **you still pay per GPU-hour after the subsidy**. Not free, not fast. |
| **C-DAC / PARAM / National Supercomputing Mission** | Real national HPC infrastructure | Access flows through **National Knowledge Network-connected academic institutions**, allocated via your college's HPC committee to faculty-sponsored research. **No individual-student self-signup path exists.** Only reachable via your college, and typically only for coursework/faculty-backed research. |
| **AICTE initiatives** (2025-26 "Year of AI," Perplexity Pro / ChatGPT edu licenses, IBM SkillsBuild) | Real, but these are **AI tool access and training programs**, not backend compute/GPU infrastructure. | Doesn't address hosting a backend + graph DB + agent runtime at all. |
| **NVIDIA Inception** | Startup compute/credits program | **Explicitly requires an incorporated company.** A B.Tech student without a registered entity is ineligible. |
| **NVIDIA Academic Grant Program** | Real | For **full-time faculty**, not students. |
| **NVIDIA DLI free courses** | Real, includes temporary GPU sandboxes | Scoped to the exercise duration (hours) — not usable to host a running personal project. |
| **Google for Startups / Microsoft for Startups / AWS Activate** | Real cloud-credit programs | All three **require a registered company** or accelerator affiliation — explicitly exclude individuals/students. |
| **Jio / Airtel / BSNL developer programs** | Checked — nothing relevant exists. Jio's "cloud" offerings are consumer storage (≤50GB) or enterprise dev tools that just resell Azure credits. | Not applicable. |

## The one lever that actually works: your college

Many Indian engineering colleges hold **institutional agreements for Azure for Students** ($100 credit, no card, 140+ countries including India) and historically AWS Educate / Azure Dev Tools for Teaching (mostly software, not big compute). Access is typically via your `.edu.in` college email domain, sometimes with a faculty-issued code. **Worth asking your CSE/IT department coordinator** — but this goes through your college, not a direct government scheme, and it's the same Azure for Students credit already covered in Free-Hosting-Compute.md, not something extra.

## Verdict

Skip pursuing any Indian government program for this project right now. IndiaAI Compute is real but proposal-gated and still paid (with subsidy) — wrong shape for a solo hobby project needing quick, free access. Rely on the global free tiers instead: **Oracle Cloud Free Tier** (perpetual, no student status needed) + **GitHub Student Developer Pack** (Azure $100 backup, using your `.edu.in` email) + **Gemini/Groq free API tiers** for the LLM layer. That combination is strictly faster and more reliable than any Indian scheme available today.
