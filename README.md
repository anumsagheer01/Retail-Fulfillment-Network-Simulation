# Fulfillment Network Optimization + AI Sourcing Agent

**In one sentence:** this project figures out the cheapest, fastest way to ship online orders from warehouses to customers, and then wraps that engine in an AI assistant that a contractor can talk to in plain English to get an instant sourcing plan.

It has two halves that build on each other:

1. **The optimization engine** decides which warehouse should ship which product to which city. It cut shipping distance by **8.4%** while still getting **95%** of orders delivered within two days.
2. **The AI agent** lets a professional customer describe a project in their own words ("I need 120 studs and 6 rolls of wire in Atlanta"), understands it, calls the engine, and hands back a sourcing and fulfillment plan with an estimated cost.

Everything runs in Python. The engine uses mathematical optimization; the agent uses the Anthropic API for language and a FastAPI web service to expose it.

---

## Why this problem is hard

A two-day delivery promise looks simple from the customer's side. Behind it, a lot of decisions have to line up at once:

- The **closest** warehouse is the fastest, but it might be out of stock or already at capacity.
- The **cheapest** warehouse might be far away, which blows the two-day promise.
- Every warehouse has **limited inventory** and can only pack so many orders per day.

These goals fight each other. Optimization exists precisely because you cannot have all three for free. This project measures the trade and finds the best balance.

---

## The results

Four different strategies were tested against a full year of simulated demand, sampled across 24 days including the busiest days of the year (Black Friday, Cyber Monday).

![Results comparison](outputs/figures/results_comparison.png)

| Strategy | Miles per unit | vs Baseline | 2-Day Service | Cost per unit |
|---|---|---|---|---|
| Nearest FC (baseline) | 221.7 | — | 93.6% | $11.84 |
| Cost-Minimizing model | 204.9 | −7.6% | 94.4% | $10.71 |
| Service-Constrained model | 204.9 | −7.6% | 94.4% | $10.71 |
| **Forward Positioning (best)** | **203.1** | **−8.4%** | **95.1%** | **$10.63** |

**The best strategy improved all three at once** — fewer miles, better service, lower cost — because the naive "just use the nearest warehouse" baseline was genuinely wasteful.

### The most interesting finding

I expected faster delivery to cost more. It barely did.

![Lane cost insight](outputs/figures/lane_cost_insight.png)

Short shipping lanes turned out to be **both faster and cheaper**, because both speed and cost are driven by distance. So minimizing cost automatically produced good delivery speed. Testing service targets from 90% to 95% barely changed the answer. In plain terms: **the company does not actually face a cost-versus-speed tradeoff in its normal operating range.** That is a genuinely useful thing for a business to know before spending money defending a delivery target it already hits for free.

### The real bottleneck

The network has no warehouse in the Pacific Northwest, so Seattle and Portland sit more than 1,000 miles from every warehouse and can never hit two days. This caps the best-possible service level at about 95%, no matter how clever the routing is.

![FC coverage](outputs/figures/fc_coverage.png)

The lesson: the binding constraint was **where the warehouses are**, not how orders get routed. That is the kind of finding that changes a real business decision (build a new warehouse) rather than just tuning software.

---

## How the whole thing works

![Architecture](outputs/figures/architecture.png)

A contractor sends a plain-English request. The AI agent reads it, pulls out the products and quantities, and calls the sourcing tool. The sourcing tool matches each vague description to a real catalog product, checks inventory across the six warehouses, and runs the optimization engine to produce a plan. The agent reads the plan back to the customer. Everything is exposed over a web API.

A key design rule: **the AI never does the math.** Language models are unreliable at arithmetic and constraints, so the agent only handles language and decides *when* to call the optimizer. The actual optimization is done by a deterministic solver behind a clean boundary. This is the correct way to build an AI agent that has to produce trustworthy numbers.

---

## The project, part by part

The project was built in eight stages. Each stage is a file (or two) in `src/`.

### Part 1 — Generate the demand data (`generate_demand.py`)
Real order data is private, so this creates a realistic year of fake orders: 3.6 million units across 25 cities and 12 products. It builds in the patterns real demand has — busier on Mondays, huge spikes on Black Friday and Cyber Monday, bigger cities ordering more. The variability is modeled with a gamma-Poisson mixture so demand is "lumpy" the way real orders are, not artificially smooth.

### Part 2 — Map the network (`network.py`)
Calculates the real distance between every warehouse and every city using the haversine formula (proper distance on a sphere, not a flat map), inflates it by 20% to approximate actual road distance, and converts that into shipping cost and delivery time using a carrier-style zone chart. The output is a table of 150 "lanes," each tagged with whether it can deliver in two days.

### Part 3 — The optimization model (`optimizer.py`)
The heart of the project: a **mixed-integer program**. It decides how many units to ship on each lane, whether to even open each warehouse for the day (a yes/no decision, which is what makes it "mixed-integer"), and how to handle any demand it cannot meet. It minimizes total cost subject to inventory, capacity, and the two-day service promise. Solved with the free CBC solver in under a second per day.

### Part 4 — Inventory placement and the experiment (`inventory.py`, `run_simulation.py`)
Routing can only ship what a warehouse already holds, so *where you put stock* matters as much as *how you route it*. This tests three ways of placing inventory, then runs all four strategies across the sampled days and collects the results.

### Part 5 — Analysis and charts (`analyze.py`)
Turns the raw results into the comparison table, the peak-day stress analysis, and the finding that the service constraint never actually binds. Produces the figures above.

### Part 6 — Product matching (`catalog.py`, `match.py`, `sourcing_tool.py`)
The bridge to the AI half. A contractor types "half inch copper elbow," not a product code. This layer scores that vague text against a catalog of real home-improvement products and resolves it to a specific item — or declines if nothing fits well enough, because guessing wrong on a business order is worse than asking. The sourcing tool wraps the matcher and the optimizer into one function an AI can call.

### Part 7 — The agent and web service (`agent.py`, `api.py`)
The AI agent: it uses the Anthropic API to parse a plain-English request, calls the sourcing tool, keeps track of the conversation across turns, and records a reasoning trace of what it did. The FastAPI service exposes all of this over HTTP with proper endpoints. It also runs in an offline mode with no API key so tests work anywhere.

### Part 8 — Evaluating the matcher (`eval_dataset.py`, `eval_matcher.py`)
Measures how good the matching layer actually is, using a hand-labeled test set of hard queries — typos, abbreviations, and tricky "wrong variant" cases (asking for a 3/4 inch part when only 1/2 inch is stocked).

**Results on 40 held-out queries:**

| Metric | Score | Meaning |
|---|---|---|
| Top-1 accuracy | **96%** | Correct product is the #1 pick |
| Top-3 recall | **100%** | Correct product is always in the top 3 |
| Match precision | **80%** | Of what it auto-matched, how much was right |
| Correct declines | **57%** | How often it refused a wrong-variant or nonsense query |

The evaluation did its job: the first version was accepting wrong-variant queries most of the time, so I added attribute-conflict detection (noticing that "3/4" does not equal "1/2"), which raised correct declines from **36% to 57%** while keeping 96% accuracy. The remaining gap is the honest ceiling of this simpler matching approach — closing it further would need a semantic model, and that limitation is documented rather than hidden.

---

## Repository layout

```
src/
  generate_demand.py   Part 1: synthetic order data
  network.py           Part 2: distances, shipping zones, lane costs
  optimizer.py         Part 3: the mixed-integer optimization model
  inventory.py         Part 4: inventory placement strategies
  run_simulation.py    Part 4: runs all four scenarios
  analyze.py           Part 5: results and charts
  catalog.py           Part 6: home-improvement product catalog
  match.py             Part 6: text-to-product matching
  sourcing_tool.py     Part 6: the agent-callable engine wrapper
  agent.py             Part 7: the AI agent (Anthropic API + offline mode)
  api.py               Part 7: the FastAPI web service
  eval_dataset.py      Part 8: labeled test set for the matcher
  eval_matcher.py      Part 8: evaluation harness
  config.py            all settings in one place
tests/
  test_sourcing.py     matching + sourcing checks
  test_api.py          agent + API checks (runs fully offline)
  test_eval.py         matcher evaluation checks
outputs/
  figures/             the charts in this README
  results/             metrics and evaluation output
```

---

## How to run it

```bash
pip install -r requirements.txt

# The optimization engine
python src/generate_demand.py          # build the demand data
python src/network.py                  # map the network
python src/run_simulation.py --days 24 # run the four strategies
python src/analyze.py                  # results and charts

# The AI agent
python src/agent.py                    # demo the agent (works with no API key)
python src/api.py                      # start the web service, open /docs
```

The agent works out of the box in offline mode. To use the real Anthropic API for language understanding, set your key:

```bash
export ANTHROPIC_API_KEY=sk-ant-your-key
python src/agent.py
```

Try the web service directly:

```bash
python src/api.py
# in another terminal:
curl -X POST http://127.0.0.1:8000/tool/source \
  -H "Content-Type: application/json" \
  -d '{"line_items":[{"query":"2x4 studs 8ft","quantity":50}],"dest_region":"Dallas"}'
```

Interactive API docs open automatically at **http://127.0.0.1:8000/docs**.

## Tests

```bash
python tests/test_sourcing.py
python tests/test_api.py
python tests/test_eval.py
```

Tests check real properties — a constrained solution can never beat an unconstrained one, nonsense queries get declined, unknown sessions return an error — not just fixed numbers.

---

## Honest limitations

- **The data is synthetic.** It is built to match the shape of real demand, and the logic runs unchanged on real data with the same structure, but the specific numbers are illustrative.
- **Each day is solved on its own.** Inventory does not carry from one day to the next; a production version would be multi-period.
- **The matcher is text-based.** It is transparent and fast but tops out around 57% on hard wrong-variant detection. A semantic model would push that higher.
- **The matcher's accuracy numbers come from a test set I wrote.** The method is sound; the specific numbers are an internal benchmark, not a production estimate.

These are written down on purpose. Knowing exactly where a system breaks is more valuable than pretending it does not.

---

## Tech stack

Python · PuLP with the CBC solver · pandas · NumPy · matplotlib · FastAPI · Anthropic API
