# Recursive Knowledge Graph — System Design

This is the original foundational spec for the knowledge-graph half of the system, authored by the project owner. It's saved here verbatim because everything in PRD.md/Architecture.md/Rules.md references it by section number, and until now it only existed in conversation history, not in the repo. Treat it as a source document — PRD.md is where the operational, implementation-facing version lives (including the concrete worked example and the real-world-precedent findings in Architecture.md §0).

## 1. Core Idea

The system is a **recursive, question-driven map of knowledge and real-world systems**.

It is not a static taxonomy of subjects.

It represents:

> **Domains → Networks → Abstractions → Entities → Dimensions → Questions → Resources → Knowledge → New Questions**

The system is designed to let us **navigate knowledge by zooming, changing perspectives, changing scale, and following relationships between systems.**

---

## 2. Knowledge Network

The foundation is a network:

$$
G=(V,E)
$$

where:

* \(V\) = nodes
* \(E\) = relationships between nodes

### Node

Every node represents a **domain of knowledge/system** at the current level of abstraction.

Examples: Physics, Mathematics, Psychology, Economics, Law, Technology, Money, Insurance, Advertising, Payment Systems, Artificial Intelligence.

Nodes are connected rather than arranged only in a rigid hierarchy.

```text
Psychology ─── Economics
    │              │
    │              │
 Advertising ─── Business
    │              │
    └──── Technology
           │
          Law
```

A domain can therefore participate in many different networks.

---

## 3. Abstraction

An **abstraction is not a dimension**.

It is a **boundary placed around part of the network that we currently choose to study**.

The complete network may be enormous or effectively unbounded.

An abstraction says: "For this investigation, this is the portion of the network we are considering."

Mathematically:

$$
A \subseteq G
$$

An abstraction is therefore a **selected region/boundary of the network**. The name we give that boundary defines what we are currently studying.

---

## 4. 2D Abstraction — Subject

A **2D abstraction** is a bounded region of the domain network that we call a subject.

For example, **Quantum Computing**'s boundary may contain:

```text
Physics
   │
Quantum Mechanics
   │
Mathematics ─── Information Theory
   │                 │
   └──── Computer Science
             │
         Algorithms
             │
      Quantum Computing
```

Quantum computing is therefore not required to be a single isolated domain — it can be a **boundary over several interconnected domains**. The subject answers: **What region of the knowledge network are we studying?**

---

## 5. 3D Abstraction — Entity

An entity is a **concrete system/object/person/organization existing inside a bounded network**.

Examples: PayPal, Mastercard, Stripe, DeepMind, Google, an insurance company, a government institution, an individual.

An entity exists within: (1) a network of domains, (2) a selected boundary, (3) multiple dimensions, (4) a set of questions/problems, (5) a temporal history.

An entity can be understood as a concrete realization of solutions to questions/problems inside a particular region of the network.

---

## 6. Entities as Solutions

An entity can be understood through the **questions/problems it attempts to solve**.

**PayPal** — underlying question: *"How can people conduct transactions over the Internet without relying on physical exchange?"* PayPal operates within a network involving Finance, Technology, Economics, Business, Law, Security, Psychology, Networks.

**Mastercard** — a related but distinct coordination problem: connecting consumers, merchants and financial institutions through a standardized payment network.

**Stripe** — a different problem: *"How can businesses integrate payment infrastructure into software?"*

The same broad network can therefore produce **different entities solving different questions**.

---

## 7. Zoom

$$
\boxed{\text{Zoom = changing the abstraction}}
$$

Zooming does not mean physically moving toward or away from an object. It means: **changing the boundary and therefore changing what part of the network is currently being treated as the object of study.**

### Zoom In

A larger entity/network unfolds into smaller components:

```text
PayPal → Payment Processing → Transaction Processing → Authorization → Fraud Detection → Algorithm → Computation
```

What was one entity at a previous abstraction becomes a network of smaller nodes/entities.

### Zoom Out

Entities become nodes in a larger network: `PayPal, Mastercard, Visa, Stripe, Adyen, Wise, Banks, Merchants` → boundary named **Payment Platforms / Payment Ecosystem** → zoom out again → `Payment Platforms, Banking, Insurance, Investment, Credit, Capital Markets` → boundary **Financial Technology / Financial System** → zoom out again → **Society**.

$$
\boxed{\text{Zoom Out: Entity} \rightarrow \text{Node}} \qquad \boxed{\text{Zoom In: Node} \rightarrow \text{Network}}
$$

The underlying network can remain the same while our **representation/boundary changes**.

---

## 8. Recursive Structure

An entity can itself contain a network:

```text
PayPal
│
├── People
├── Teams
├── Software
├── Databases
├── Infrastructure
├── Security
├── Payment Processing
├── Financial Relationships
└── Legal Structures
```

At another abstraction, PayPal becomes a node under **Payment Platforms**, which itself becomes a node under **Financial Technology**.

> An entity can become a node when we zoom out, and a node can unfold into an entity/network when we zoom in.

---

## 9. Dimensions

Dimensions are **not nodes** and are **not abstractions** — they are ways of interrogating whatever abstraction we are studying.

**Scale** — At what level are we observing the system? (physical/individual/interpersonal/group/organization/institution/society/global/planetary — not a fixed universal hierarchy; the meaningful scale depends on the abstraction.)

**Perspective** — From what viewpoint? (physical/biological/psychological/social/economic/computational/systemic/legal/political/historical/philosophical.)

**Time** — When, and how does it change? (origin/development/evolution/current state/future/transformation/failure/adaptation.)

---

## 10. Dimension Hierarchies

Hierarchy is **dimension-relative** — entities do not possess one universal hierarchy. A hierarchy emerges when we select a dimension. Under Scale: Individual → Local → Regional → National → Global. Under a different dimension (Revenue, Organizational complexity, Influence, Technical dependency) the same entities order differently.

> Hierarchy is an emergent structure produced by applying a dimension.

---

## 11. Custom Dimensions

**Universal dimensions** (useful across many abstractions): Scale, Perspective, Time.

**Abstraction-specific dimensions** (meaningful only within particular systems):
- Payment Systems: Transaction flow, Risk, Settlement, Trust, Interoperability
- Organizations: Hierarchy, Control, Capital, Information flow, Decision-making
- Technology: Architecture, Performance, Reliability, Scalability, Energy
- Law: Jurisdiction, Authority, Rights, Enforcement, Precedent

The system should allow custom dimensions to emerge at the appropriate abstraction level.

---

## 12. Dimension → Question

A dimension does not directly represent knowledge — it generates a **question about the current abstraction**.

$$
\boxed{\text{Abstraction}+\text{Dimension} \rightarrow \text{Question}}
$$

More precisely: \(Q=f(A,N,E,D,L,C)\) where \(A\)=abstraction, \(N\)=network context, \(E\)=entity/node, \(D\)=dimension, \(L\)=abstraction level, \(C\)=contextual constraints.

---

## 13. Same Dimension, Different Abstraction

Take **Scale**: at the individual level, *"How does one person make a payment?"*; at the organization level, *"How does a payment company process payments?"*; at the network level, *"How do banks, merchants and payment companies coordinate?"*; at the global level, *"How does the global payment system coordinate financial exchange?"*

The dimension remains the same. The **abstraction/level changes**, therefore the question changes.

---

## 14. Same Entity, Different Dimensions

Take **PayPal**:
- Economic — How does PayPal create and capture value?
- Computational — How does PayPal process transactions?
- Psychological — Why do users trust PayPal?
- Social — How does trust propagate through the payment network?
- Legal — What legal structures govern its operations?
- Systemic — How does money flow from sender to recipient through the system?
- Historical — Why did PayPal emerge when it did?
- Philosophical — What does digital money actually mean?

$$
\boxed{\text{Entity}+\text{Dimension} \rightarrow \text{Question}}
$$

---

## 15. Question Engine

The **Question Engine** converts the structure into learning. It does not contain a giant static list of questions — it contains **rules for generating appropriate questions**.

Input: Abstraction + Network + Node/Entity + Dimension + Level + Context. Output: Questions.

---

## 16. The Question Engine Must Be Level-Aware

The same dimension should generate different questions depending on the abstraction level.

**Economic dimension + Individual** — income, consumption, incentives, constraints, risk, resource allocation.
**Economic dimension + Organization** — revenue, costs, capital, incentives, value creation, value capture, competition.
**Economic dimension + Society** — markets, distribution, productivity, inequality, trade, resource allocation.

> The Question Engine is not simply dimension → question. It is: Dimension + Abstraction Level + Context → Question Generator.

---

## 17. Questions Form Their Own Graph

A question does not have to be an endpoint — one question can generate subquestions:

*"How does Mastercard process a transaction?"* → What entities participate? (Merchant, Acquirer, Payment Network, Issuer) → How does authorization work? → How is fraud detected? → How is risk calculated? → How does settlement occur?

$$
\boxed{Question \rightarrow Subquestions \rightarrow Answers \rightarrow New Questions}
$$

Learning becomes recursive as well.

---

## 18. Resources

Every question can be answered by one or more resources: Documentary, Book, Research paper, Lecture, Course, Technical documentation, Primary source, Dataset, Experiment, Interview, Historical archive, Law/regulation, Financial report.

The resource is attached to the **question**, rather than merely to a topic. *"How did PayPal emerge?"* → history/documentary/interviews. *"How does PayPal process transactions?"* → technical documentation/engineering material. *"How does PayPal make money?"* → financial reports/economic analysis. *"How did regulation shape PayPal?"* → laws/regulatory documents/legal analysis.

This makes recommendations **question-driven rather than topic-driven**.

---

## 19. The Learning Loop

```text
USER CHOOSES / DISCOVERS ABSTRACTION → BOUNDED NETWORK → IDENTIFY NODES/ENTITIES
  → SELECT DIMENSION → QUESTION ENGINE → GENERATE QUESTIONS → RANK QUESTIONS
  → FIND RESOURCES (Documentary / Book / Paper) → ANSWER → NEW QUESTIONS → LOOP
```

---

## 20. Four Fundamental Operations

**Navigate** — move between connected nodes. *PayPal → Stripe → Banks → Regulators*
**Zoom** — change the abstraction boundary. *PayPal → Payment Platforms → Financial System*
**Interrogate** — apply a dimension. *PayPal + Economic perspective*
**Learn** — attach resources to the generated question. *Question → Documentary / Book / Paper / Primary Source*

---

## 21. Core Mathematical Model

Knowledge network: \(G=(V,E)\). Abstraction: \(A \subseteq G\). Entity: \(E_n=(N,B,D,Q,S,T)\) where \(N\)=network region, \(B\)=boundary, \(D\)=dimensions, \(Q\)=questions, \(S\)=internal structure, \(T\)=temporal evolution. Question generation: \(Q=f(A,N,E,D,L,C)\).

$$
\boxed{\text{Network} \rightarrow \text{Abstraction} \rightarrow \text{Dimension} \rightarrow \text{Question} \rightarrow \text{Resource} \rightarrow \text{Knowledge} \rightarrow \text{New Question}}
$$

---

## 22. Complete Conceptual Architecture

```text
                         KNOWLEDGE / REALITY
                                  │
                                  ▼
                         ┌─────────────────┐
                         │     NETWORK     │
                         │ Domains + Edges │
                         └────────┬────────┘
                                  │ choose boundary
                                  ▼
                         ┌─────────────────┐
                         │   ABSTRACTION   │
                         │ selected region │
                         │ of the network  │
                         └────────┬────────┘
                       ┌──────────┴──────────┐
                     SUBJECT               ENTITY
                      (2D)                  (3D)
                       └──────────┬──────────┘
                                  ▼
                             DIMENSIONS
                    ┌─────────────┼─────────────┐
                  SCALE      PERSPECTIVE       TIME
                    └─────────────┼─────────────┘
                         custom dimensions
                                  ▼
                           QUESTION ENGINE
                                  ▼
                              QUESTIONS
                         ┌────────┴────────┐
                    Subquestions       Resources
                                    ┌────────┼────────┐
                              Documentary   Book     Paper
                                           ▼
                                       KNOWLEDGE
                                           ▼
                                    NEW QUESTIONS ──────► LOOP
```

---

## 23. The Recursive Zoom Structure

```text
Civilization → Society → Financial System → FinTech → Payment Platforms → PayPal
  → Payment Processing → Transaction → Authorization → Algorithm → Computation
  → Hardware → Transistor → Physics
```

And sideways navigation simultaneously: `PayPal ── Mastercard / Visa / Stripe / Banks / Regulators / Merchants / Consumers / Technology`.

The system supports both **vertical movement through abstraction/zoom** and **horizontal movement through network relationships**.

---

## 24. Final Definition

The system is a **recursive knowledge graph in which domains form interconnected networks; abstractions define boundaries over those networks; entities exist within those bounded regions and across dimensions; dimensions generate level-appropriate questions; and resources answer those questions.**

$$
\boxed{\text{Nodes} \rightarrow \text{Network}} \quad
\boxed{\text{Network} \rightarrow \text{Abstraction}} \quad
\boxed{\text{Abstraction}+\text{Dimension} \rightarrow \text{Question}}
$$
$$
\boxed{\text{Question} \rightarrow \text{Resource}} \quad
\boxed{\text{Resource} \rightarrow \text{Knowledge}} \quad
\boxed{\text{Knowledge} \rightarrow \text{New Questions}}
$$
$$
\boxed{\text{Zoom}=\text{Changing the Abstraction}} \qquad
\boxed{\text{Hierarchy}=\text{Structure produced by a chosen dimension}}
$$

The goal is not merely to **store knowledge**. It is to create a system that can continuously answer: What exists? How is it connected? What boundary are we studying? At what scale? From what perspective? Across what period of time? What questions do those choices generate? What resources can answer them? What new questions emerge from those answers?
