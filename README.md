# Fulfillment Network Optimization and AI Sourcing Agent

**In a nutshell:** this project works out the cheapest and fastest way to ship online orders from warehouses to customers, and also puts an AI assistant on top of that engine so a contractor can describe a project in plain English and get an instant sourcing plan back.

There are two halves, and the second builds on the first:

1. **The optimization engine** decides which warehouse should ship which product to which city. It cut shipping distance by **8.4%** while still getting **95%** of orders delivered within two days.
2. **The AI agent** lets a professional customer describe a project in their own words, like "I need 120 studs and 6 rolls of wire in Atlanta." It reads the request, calls the engine, and hands back a sourcing and fulfillment plan with an estimated cost.

---

## More context:

**What is sourcing and fulfillment?**
When you order something online, a company has to answer two questions behind the scenes. Sourcing is deciding which of its products match what you asked for. Fulfillment is deciding which warehouse ships them to you, and how, so they arrive on time and cost as little as possible. Big retailers run whole teams and a lot of software to make these decisions millions of times a day.

**Why add an AI assistant?**
Regular shoppers click on exact products, so sourcing is easy for them. Professional customers do not shop that way. A contractor shows up with a messy list: "I need a couple hundred studs, some half inch copper elbows, a few rolls of romex, and paint, delivered to my job site by Thursday." Turning that rough list into exact products, checking what is in stock, and building a delivery plan normally takes a sales rep a lot of back and forth. The assistant does it in seconds. The contractor talks the way they normally would, and the assistant handles the rest.

**What does the assistant actually do?**
- Reads a plain-English request and works out each product the person means.
- Handles trade shorthand, abbreviations, and typos ("1/2 cu ell" means a half inch copper elbow).
- Checks inventory across all the warehouses.
- Runs the optimization engine to find the cheapest plan that still hits the two-day delivery promise.
- Writes back a clear plan: which products, from which warehouses, at what cost, by when.
- Asks a clarifying question instead of guessing when a request is unclear, because a wrong order on a job site is expensive.

**Who would use this, and where?**
Any business that sells to professional or bulk buyers rather than one-item-at-a-time shoppers. Home-improvement and building-supply retailers (the example used here), industrial and electrical distributors, plumbing and HVAC suppliers, auto-parts wholesalers, restaurant and food-service suppliers, and medical or lab supply companies. Anywhere a customer arrives with a long, messy list of items and a deadline, this pattern fits.

**What jobs does it make easier?**
- Sales reps stop spending hours turning a customer's rough list into a formal quote.
- Supply chain and operations teams get routing that is optimized instead of guessed.
- The customer gets an instant, accurate answer instead of waiting a day for a callback.

In short: the optimization engine is the kind of tool a supply chain team uses to run a delivery network efficiently, and the assistant is the kind of tool that turns a slow, manual quoting process into an instant self-serve one.

---

## The whole project at a glance

![Project overview](outputs/figures/project_flowchart.png)

**How to read this diagram, top to bottom:**

The blue and peach boxes at the top are the optimization engine (Parts 1 to 5). It builds a realistic year of order data, maps out the cost and delivery time between warehouses and cities, then uses a mathematical model to decide the best way to route every order. The yellow box shows its result: 8.4% fewer shipping miles while still hitting 95% two-day delivery.

The purple boxes in the middle are the AI assistant (Parts 6 and 7). A contractor speaks in plain English, the system matches their words to real products, and an AI agent calls the engine as a tool to build a plan. The pink box on the right, "What it looks like in use," is a real example. A contractor asks for 40 half inch copper elbows to Atlanta, and the assistant returns the plan: sourced from the Atlanta and Joliet warehouses, $1,204, 100% two-day delivery. That one exchange is the whole point of the project. A rough spoken request goes in, a costed and optimized plan comes out, in seconds instead of hours.

The green box at the bottom is the evaluation (Part 8), where the matching layer was tested on hard examples and improved based on what the test exposed.

One rule runs through the whole design: the AI handles the language, the solver handles the math. Language models are not reliable at arithmetic or hard constraints, so the AI only reads the request and decides when to call the engine. The actual optimization is done by a proper solver. That is how you get an assistant whose numbers people can trust.

---

## Why this problem is harder than it looks

A two-day delivery promise seems simple from the customer's side. Behind the scenes, several decisions have to line up at once:

- The closest warehouse is the fastest, but it might be out of stock or already at capacity.
- The cheapest warehouse might be far away, which breaks the two-day promise.
- Every warehouse holds limited inventory and can only pack so many orders per day.

These goals pull against each other. That is why optimization is needed. You cannot get all three for free, so the job is to find the best balance, and that is what this project measures.

---

## The results

Four strategies were tested against a full year of simulated demand, sampled across 24 days including the busiest days of the year like Black Friday and Cyber Monday.

![Results comparison](outputs/figures/results_comparison.png)

| Strategy | Miles per unit | vs Baseline | 2-Day Service | Cost per unit |
|---|---|---|---|---|
| Nearest FC (baseline) | 221.7 | n/a | 93.6% | $11.84 |
| Cost-Minimizing model | 204.9 | down 7.6% | 94.4% | $10.71 |
| Service-Constrained model | 204.9 | down 7.6% | 94.4% | $10.71 |
| **Forward Positioning (best)** | **203.1** | **down 8.4%** | **95.1%** | **$10.63** |

The best strategy improved all three numbers at once: fewer miles, better service, lower cost. That was possible because the "just use the nearest warehouse" baseline was genuinely wasteful, so there was a lot of room to do better.

### The finding I did not expect

I assumed faster delivery would cost more. It barely did.

![Lane cost insight](outputs/figures/lane_cost_insight.png)

Short shipping routes turned out to be both faster and cheaper, because both speed and cost come down to distance. So minimizing cost automatically produced good delivery speed. When I tested delivery targets from 90% all the way to 95%, the answer barely moved. In plain terms, the company does not really face a cost versus speed tradeoff in its normal operating range. That is worth knowing before spending money to defend a delivery target it already hits for free.

### The real bottleneck

The network has no warehouse in the Pacific Northwest, so Seattle and Portland sit more than 1,000 miles from every warehouse and can never reach two-day delivery. That caps the best possible service level at about 95%, no matter how good the routing is.

![FC coverage](outputs/figures/fc_coverage.png)

The lesson is that the real constraint was where the warehouses are, not how orders get routed. That is the kind of finding that changes a business decision, like whether to build a new warehouse, rather than just tuning software.

---

## The project, part by part

The project was built in eight stages. Each stage is a file or two in the `src/` folder.

### Part 1: Generate the demand data (`generate_demand.py`)
Real order data is private, so this builds a realistic year of fake orders: 3.6 million units across 25 cities and 12 products. It bakes in the patterns real demand has, like busier Mondays, big spikes on Black Friday and Cyber Monday, and larger cities ordering more. Demand is made lumpy the way real orders are, not artificially smooth.

### Part 2: Map the network (`network.py`)
Calculates the distance between every warehouse and every city, accounting for the curve of the earth, then adds about 20% because roads are longer than a straight line. It turns those distances into shipping cost and delivery time using a carrier-style zone chart. The output is a table of 150 shipping routes, each tagged with whether it can deliver in two days.

### Part 3: The optimization model (`optimizer.py`)
The heart of the project. It is a mixed-integer program, which means it mixes normal number decisions (how many units to ship on each route) with yes/no decisions (whether to open a warehouse for the day at all). It picks the combination that costs the least while respecting inventory limits, warehouse capacity, and the two-day promise. It solves in under a second per day with a free solver.

### Part 4: Inventory placement and the experiment (`inventory.py`, `run_simulation.py`)
Routing can only ship what a warehouse already holds, so where you put stock matters as much as how you route orders. This tests three ways of placing inventory, then runs all four strategies across the sampled days and collects the results.

### Part 5: Analysis and charts (`analyze.py`)
Turns the raw results into the comparison table, the busy-day stress test, and the finding that the service constraint never actually kicks in. It also produces the charts above.

### Part 6: Product matching (`catalog.py`, `match.py`, `sourcing_tool.py`)
The bridge to the AI half. A contractor types "half inch copper elbow," not a product code. This layer scores that vague text against a catalog of real home-improvement products and picks the right one, or declines if nothing fits well enough, because guessing wrong on a business order is worse than asking. The sourcing tool bundles the matcher and the optimizer into a single function an AI can call.

### Part 7: The agent and web service (`agent.py`, `api.py`)
The AI agent uses the Anthropic API to read a plain-English request, call the sourcing tool, keep track of the conversation across turns, and record a trace of what it did. FastAPI exposes all of it over the web with proper endpoints. It also has an offline mode that needs no API key, so the tests run anywhere.

### Part 8: Evaluating the matcher (`eval_dataset.py`, `eval_matcher.py`)
Covered in full detail in the next section.

---

## How the matcher was evaluated, and what the numbers mean

The matching layer is the part most likely to fail quietly, so it got a proper evaluation instead of a "looks fine to me."

**How the test set was built.**
I hand-wrote 40 test queries, each labeled with the product it should map to and whether the matcher should confidently match it, ask a clarifying question, or refuse it. The queries were written to be hard on purpose. There is no point testing a matcher on the exact product names it already knows, because that only proves it can copy its own catalog. So the set is full of the messy things a real contractor types:

- **Abbreviations and shorthand:** "1/2 cu ell", "20a sp brkr", "wht int paint 5g"
- **Reordered words and typos:** "elbow 1/2 coper", "insluation r13 fiberglas"
- **Brand names not in the catalog:** "quikrete", "sheetrock"
- **Wrong-variant traps:** asking for a "3/4 copper elbow" when only the 1/2 inch is stocked, or "14-2 romex" when the catalog has 12-2. These share almost every word with a real product but are the wrong item.
- **Pure nonsense:** "purple widget frobnicator", "unicorn horn polish"

**What the results mean.**

| Metric | Score | What it means in plain terms |
|---|---|---|
| Top-1 accuracy | 96% | When the right product exists, it was the number one pick 96% of the time |
| Top-3 recall | 100% | The right product was always somewhere in the top three guesses |
| Match precision | 80% | Of everything it confidently auto-matched, 80% was the correct product |
| Correct declines | 57% | Of the wrong-variant and nonsense queries, it correctly refused 57% |

Top-1 and top-3 measure whether it finds the right answer. Precision and correct-declines measure whether it knows when to say no. For a business tool, knowing when to say no is the important half, because shipping the wrong part to a job site is far more costly than asking one extra question.

**The failure the evaluation caught, and how it was fixed.**
The first version of the matcher scored badly on the wrong-variant traps. It was only correctly refusing about **36%** of them. When someone asked for a "3/4 copper elbow" and only the 1/2 inch existed, the matcher confidently matched it to the 1/2 inch, because the two share every word except the size. In a real business this is a serious failure. It would quietly ship the wrong part.

The reason was that the matcher rewarded matching words but never noticed a conflicting number. "3/4" and "1/2" are both just tokens to a word-matching system. So I added a check that reads the sizes and gauges out of the query and compares them to the product's actual specs. If the query clearly names a size, gauge, or other spec that does not match the product, the match gets heavily penalized. After that change, correct declines rose from **36% to 57%**, while top-1 accuracy stayed at 96%.

**The honest ceiling.**
Fifty-seven percent is not perfect, and I stopped there on purpose. The queries it still gets wrong are ones like "exterior door" matching an interior door, where the difference is a word, not a number, so a size-checking rule cannot catch it. Pushing past this point would need a semantic model (something that understands that interior and exterior are opposites), not more hand-written rules. Adding more special cases just to score higher on my own test set would be gaming the number rather than genuinely improving the matcher, so the limitation is documented instead of hidden.

---

## Some problems I hit along the way

Nothing about this worked on the first try. A few of the more useful bugs and how they got fixed:

**The optimizer quoted a total failure on small orders.**
When I first ran a single contractor's order through the engine, it said it could not fill anything. It turned out the engine was correct but was answering the wrong question. It included each warehouse's full daily running cost, so for one small order it decided the cheapest option was to ship nothing and eat the penalty, rather than "pay a whole day of warehouse rent" for a handful of items. That is the right answer when you are deciding whether to run a warehouse for a full day, but wrong for a single live order where the warehouse is already open. The fix was a switch that turns off the daily fixed cost for single-order quotes, so they are priced only on the actual cost of shipping. Same engine, but now it answers the right question depending on the situation.

**The simulation silently returned nothing.**
Every scenario run came back empty at one point, with no error. After digging in, the "did this succeed" flag was buried one level deeper in the results than the code checking it expected, so the check always failed and threw the results away. A one-line fix, but a good reminder that "no error" does not mean "working."

**The matcher refused valid products it should have accepted.**
A query like "r13 batts" (a real insulation product) was scoring just below the accept threshold and getting declined. The matcher was pulling out "r13" but never also comparing it against the plain "13" stored in the product's specs, so a genuine match looked weaker than it was. Fixing how it reads sizes and values out of a query brought these back in.

**"1/2" would not match "0.5".**
Contractors write sizes as fractions ("1/2"), but the catalog stores them as decimals ("0.5"), so a correct query kept failing to line up with the right product. Adding a small fraction-to-decimal conversion fixed it.

**The plain-English parser dropped the first item.**
The offline version of the agent (the one that runs without an API key) kept losing the first product in a list, because a request like "I need about 120 studs" has words before the quantity that confused it. Teaching it to skip the lead-in text before the first number fixed it.

**My first evaluation was too easy, so I threw it out.**
The very first version of the matcher evaluation came back at 100% on everything. That is a warning sign, not a victory. It meant the test was too soft. I rebuilt the test set with the wrong-variant traps described above, and the honest score dropped to where it actually belonged. A test that a system cannot fail is not measuring anything.

**The fix for one bug caused another.**
When I added the size-conflict check to the matcher, it overcorrected and started penalizing correct matches too, because it was comparing every stray number in a query, including things like lengths, against every product spec. I narrowed it to only compare like with like (a size against a size, a gauge against a gauge, never a length against a size), which kept the wrong-variant rejections while letting the correct matches back through.

---

## Repository layout

```
src/
  generate_demand.py   Part 1: synthetic order data
  network.py           Part 2: distances, shipping zones, route costs
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
  test_sourcing.py     matching and sourcing checks
  test_api.py          agent and API checks (runs fully offline)
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

The agent works out of the box in offline mode. To use the real Anthropic API for language understanding, set your key first:

```bash
export ANTHROPIC_API_KEY=sk-ant-your-key
python src/agent.py
```

Try the web service directly:

```bash
python src/api.py
# then, in another terminal:
curl -X POST http://127.0.0.1:8000/tool/source \
  -H "Content-Type: application/json" \
  -d '{"line_items":[{"query":"2x4 studs 8ft","quantity":50}],"dest_region":"Dallas"}'
```

Interactive API docs open at **http://127.0.0.1:8000/docs**.

## Tests

```bash
python tests/test_sourcing.py
python tests/test_api.py
python tests/test_eval.py
```

The tests check real properties, like the fact that adding a constraint can never make a solution cheaper, that nonsense queries get declined, and that unknown sessions return an error. They do not just check fixed numbers.

---

## Honest limitations

- **The data is synthetic.** It is built to match the shape of real demand, and the logic runs unchanged on real data with the same structure, but the specific numbers are illustrative.
- **Each day is solved on its own.** Inventory does not carry from one day to the next. A production version would connect the days together.
- **The matcher is text-based.** It is fast and easy to explain, but it tops out around 57% on the hard wrong-variant cases. A model that understands meaning, not just words, would push that higher.
- **The matcher's accuracy numbers come from a test set I wrote myself.** The method is sound, but the specific numbers are an internal benchmark, not a production estimate.

These are written down on purpose. Knowing exactly where a system breaks is more useful than pretending it does not.

---

## Tech stack

Python, PuLP with the CBC solver, pandas, NumPy, matplotlib, FastAPI, Anthropic API.
