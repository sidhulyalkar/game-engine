# A measurable game-design research program

## Question and scope

Estimate how specific design choices change behavior **for a named game, player
population, task, and objective**. There is no single universal optimum to infer
from bot completion rates. Reliability, mastery, accessibility, challenge,
exploration and enjoyment are separate outcomes, sometimes in conflict.

The implementation now provides paired source-variant plans, bounded execution,
trace-verified measurements, seed-cluster uncertainty, and target-free feature
exchange with `sidhulyalkar/algonaut-a-mario`. Browser presentation, human data
collection and neural response modeling are later gates, not implied capabilities.

## Decomposition

| Manipulated factor | First measurable response | Human outcome | Key confound |
| --- | --- | --- | --- |
| Jump buffer / coyote time | Success under input-timing perturbation | Perceived responsiveness; retries | Controller competence |
| Movement speed | Route progress and overshoot | Control preference | Camera behavior and collision changes |
| Hazard timing / spacing | Failure location and recovery | Fairness; challenge | Skill and learning order |
| State feedback | Accurate state identification | Comprehension; confidence | Hidden-state bots cannot test readability |
| Route choice | Distinct paths taken | Agency; exploration | Number of genuinely viable paths |
| Reward timing | Action repetition and switching | Motivation; enjoyment | Score is not enjoyment |

Start with one factor and a two-arm comparison. Later factorial experiments can
test interactions such as jump buffering × hazard speed. Do not add many factors
before establishing sensitivity and measurement reliability.

## Executable paired experiment

Prepare two reviewed checkouts with one explicit intervention. Record the diff.
The planner fingerprints runtime files and fixes its endpoint, hypotheses,
controller seeds, world blocks, and execution order **before** running either arm.

```bash
game-engine study-plan unicorn-stampede ../unicorn-stampede ../unicorn-variant \
  --hypothesis 'Changing only Bolt speed changes structural progress under this controller.' \
  --seeds 11 23 37 51 67 --ticks 720 --endpoint final_progress --out runs/speed-plan.json
game-engine study-run runs/speed-plan.json ../unicorn-stampede ../unicorn-variant --out runs/speed-study
game-engine study-analyze runs/speed-study
```

For Puma, use `puma-platformer` with .NET 8 and reviewed edits to `MovementTuning`.
No Unity simulation is reimplemented. Twelve seconds in Unicorn is 720 ticks;
twelve seconds in Puma is 1440 ticks. Match time budgets when comparing methods.

Each seed supplies the same input script to both arms in each of three worlds.
Execution order is shuffled deterministically. The software experiment is a
controlled source intervention, not random assignment of people. A controller
that reacts to hidden state would need separate policy/observation provenance;
the current controller is open-loop seeded input stress.

Analysis computes candidate-minus-baseline per block, averages the three worlds
within each seed, then bootstraps seed means. Thus 30 runs in a two-arm × three-
world × five-seed experiment yield **five clusters**, not millions of independent
frames or thirty independent participants. A percentile interval is exploratory;
with fewer than five seeds it is withheld. No p-value or automatic winner is
reported. The worlds are fixed, so the interval concerns controller-seed variation,
not all possible games or players. Five seeds are a smoke/pilot budget, not a
powered confirmatory study.

Runtime errors make the study incomplete and suppress effect estimation.
Declared contract failures remain visible and are never silently removed from
the endpoint calculation. Source drift, duplicate schedules, missing pairs,
different adapters and forged report measurements are rejected.

A content hash detects changes; it does not establish an externally timestamped
preregistration. Commit the frozen plan before collecting confirmatory data.
Plans made after inspecting outcomes must be labeled exploratory. Retain all
attempts, and use fresh held-out seeds for a confirmatory follow-up.

## Exploratory pilot

The first exploratory local pilot completed 30 runs (five seeds × three worlds ×
two arms) for Bolt's speed multiplier, 1.14 versus 1.00. Candidate-minus-baseline
structural progress averaged +0.02865, with a seed-bootstrap interval of
[-0.03950, +0.09679]. This does not establish a directional benefit and says
nothing about enjoyment. The plan and detailed result are retained in
[`examples/studies/bolt-speed-plan.json`](../examples/studies/bolt-speed-plan.json)
and [`bolt-speed-pilot.json`](evidence/bolt-speed-pilot.json). Reproduce using
`python scripts/qualify_game_design.py --unicorn ../unicorn-stampede --out pilot`.
CI uploads all run traces instead of checking that an intervention must win.

## Human study design

Before optimizing enjoyment, introduce a rendered session recorder and conduct
a small usability pilot. Then preregister a single primary outcome, such as
within-participant preference or control-clarity rating. Use anonymous IDs,
balanced AB/BA order, matched instructions, a fixed play budget, and a practice
stage. Record prior familiarity and self-rated skill before exposure. Counterbalance
world order; model or report learning/order effects. Treat participant as the
uncertainty unit and retain dropouts, crashes and missing answers explicitly.

Do not call seed clusters participants. Do not infer confusion from stationary
position alone. Do not use long session duration as a synonym for enjoyment.
Use the pilot variance/effect size to plan recruitment; an initial 12–20-player
pilot is for feasibility and measurement design, not a universal conclusion.

## Connection to Algonauts

The official [Algonauts 2027 page](https://algonautsproject.com/2027/index.html),
checked 2026-09-11, announces video games, a late-2026 launch and CNeuroMod
collaboration. It does not yet specify detailed datasets, scoring or permitted
external data/models. Our generated games are preparation material, not assumed
competition stimuli or a submission format.

The projects have complementary roles:

| Project | Responsibility | Evidence it can produce |
| --- | --- | --- |
| game-engine | Controlled game interventions and repeatable behavior | Source changes → controller trajectories; later human preferences |
| algonaut-a-mario | Held-out representation and brain-encoding evaluation | Features → authorized neural responses under fixed source/split authority |

The reusable scientific question is whether representations capture controllable
structure—actions, movement, task state, prediction errors—and generalize beyond
appearance and game identity. Generated games can supply privileged labels for
representation diagnostics or training, subject to eventual competition rules.
They supply **no human brain targets** by themselves.

Export one completed run:

```bash
game-engine playtest-features runs/tutorial --family unicorn-v037-lineage --out runs/tutorial-features.json
PYTHONPATH=../algonaut-a-mario/src python -m algonaut_mario.gameplay_bridge runs/tutorial-features.json
```

`gameplay-features-v1` contains ten causal action/state columns, explicit units and
availability, simulation times, source/scenario/adapter fingerprints and a lineage
ID. Six controller columns can be selected separately from privileged state.
Speed uses native world units; progress has template-specific meaning. Dash also
has different mechanics across these games. Do not pool these quantities as
physically equivalent or treat state progress as a game-independent latent.

Times are end-of-step simulation seconds, **not** measured display times, neural
onsets, or TR centers. No HRF convolution, fake BOLD, EncodingDataset construction,
competition scoring or model selection occurs in the bridge. The independent
consumer validates the schema and creates read-only feature arrays. It rejects
neural target fields and claimed brain alignment. Related source variants and
identical recordings must not cross held-out lineage partitions; the caller is
responsible for assigning the same family ID to related variants.

## Ten-week sequence and stopping criteria

| Weeks | Work | Advancement gate |
| --- | --- | --- |
| 1–2 | Current paired study and bridge; identity and fault controls | Exact replay; zero identity effect; corruption rejection |
| 3–4 | Real rendered recordings and controller timing perturbations | Video/action alignment measured; a known mechanical manipulation detected |
| 5–6 | Human usability pilot, then frozen preference protocol | Users understand the task; questionnaires and dropout handling work |
| 7–8 | Representation diagnostics: action-only, state-only, frozen video | Held-out level and held-out game results; training-only preprocessing |
| 9–10 | Authorized Mario/Shinobi feature ablations in the existing referee | Neural metrics improve on held-out data with negative controls |

Keep the real-data V-JEPA baseline as a parallel priority in Algonaut-a-Mario.
Do not let this synthetic testbed replace the first authorized brain-encoding
experiment. Stop expanding the generator if it fails to detect known manipulations,
if human judgments disagree with its surrogate score, or if synthetic feature
benefits fail to transfer. Those are useful negative results, not reasons to tune
the held-out data. The larger modeling question should follow the evidence.
