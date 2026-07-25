"""
match.py
Resolves a vague Pro-speak query into a ranked list of candidate SKUs.

This is the "similarity scoring and attribute-matching to resolve vague
technical queries" layer named in the job description. It runs before the
optimizer: the agent extracts a raw line item like "half inch copper elbow x
40", this module maps it to SKU_001 with a confidence score, and only then does
the sourcing tool check inventory and route it.

APPROACH
--------
Deliberately dependency-light. No embedding model, no vector database, because
for a 12-family catalog a transparent lexical scorer is both sufficient and far
easier to explain and debug than a black-box similarity model. The scoring
blends three signals:

  1. Token overlap (Jaccard) between the query and each alias/name.
  2. A fuzzy character-level ratio, to survive typos and word-order changes.
  3. An attribute bonus, when the query contains a facet value (a size like
     "1/2", a gauge like "12-2") that matches the product's attributes.

The design intentionally mirrors how a production system layers a cheap lexical
prefilter before an expensive semantic reranker. Here only the prefilter is
built; the seam for a reranker is called out in the notes.
"""

import re
from difflib import SequenceMatcher

from catalog import CATALOG, CATEGORY_SYNONYMS, build_alias_index


_ALIAS_INDEX = build_alias_index()

# Tokens that carry no discriminating signal and only add noise to overlap.
_STOPWORDS = {"in", "inch", "inches", "ft", "foot", "feet", "of", "the",
              "a", "for", "with", "and", "x"}


def _tokens(text):
    """Lowercase, split on non-alphanumeric, drop stopwords and empties."""
    raw = re.split(r"[^a-z0-9/.-]+", text.lower())
    return [t for t in raw if t and t not in _STOPWORDS]


def _jaccard(a_tokens, b_tokens):
    """Token-set overlap. Robust to word order, ignores repetition."""
    a, b = set(a_tokens), set(b_tokens)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _fuzzy_ratio(a, b):
    """Character-level similarity, catches typos and minor variants."""
    return SequenceMatcher(None, a, b).ratio()


def _extract_facets(query):
    """
    Pull structured facet values out of free text so they can be matched
    against catalog attributes. Handles the fraction and dimension formats
    Pros actually use: 1/2, 3/4, 5/4, 12-2, 2x4, R-13, numeric sizes.
    """
    facets = set()
    q = query.lower()

    # Fractions and dimensions like 1/2, 3/4, 5/4
    for frac in re.findall(r"\d+/\d+", q):
        facets.add(frac)
    # Wire specs like 12-2, 12/2
    for wire in re.findall(r"\d+[-/]\d+", q):
        facets.add(wire.replace("/", "-"))
    # Nominal lumber like 2x4, 5/4x6
    for dim in re.findall(r"\d+x\d+", q):
        facets.add(dim)
    # R-values like r13, r-13. Keep both the r-prefixed token and the bare
    # number, since the catalog may store the r_value attribute as just 13.
    for r in re.findall(r"r-?(\d+)", q):
        facets.add("r" + r)
        facets.add(r)
    # Bare integers (amp, gauge, length) as weak signals
    for n in re.findall(r"\b\d+\b", q):
        facets.add(n)
    return facets


def _fraction_to_decimal(token):
    """
    Convert a fraction token like '1/2' to its decimal string '0.5'.
    Pros write sizes as fractions but the catalog stores them as decimals,
    so the two must be reconciled for size facets to match.
    """
    m = re.fullmatch(r"(\d+)/(\d+)", token)
    if not m:
        return None
    num, den = int(m.group(1)), int(m.group(2))
    if den == 0:
        return None
    val = num / den
    return ("%g" % val)   # 0.5 not 0.50, 1.25 not 1.2500


def _attribute_bonus(query_facets, product):
    """
    Reward a candidate when a query facet appears in its attributes.
    A size or gauge match is a strong disambiguator: "1/2 copper" versus
    "3/4 copper" is entirely an attribute distinction, not a word one.
    """
    attr_str = " ".join(str(v).lower() for v in product["attributes"].values())
    attr_facets = _extract_facets(attr_str) | set(attr_str.split())

    # Expand query facets with decimal equivalents of any fractions, so a
    # Pro's "1/2" can match a stored size of 0.5.
    expanded = set(query_facets)
    for f in query_facets:
        dec = _fraction_to_decimal(f)
        if dec is not None:
            expanded.add(dec)

    hits = 0
    for f in expanded:
        if f in attr_facets or f.replace("-", "") in attr_facets:
            hits += 1
    # Cap the bonus so attribute agreement supports but does not dominate.
    return min(hits * 0.15, 0.45)


def _category_prior(query_tokens, product):
    """Small nudge when the query names the product's category loosely."""
    syns = CATEGORY_SYNONYMS.get(product["category"], [])
    if any(t in syns for t in query_tokens):
        return 0.08
    return 0.0


def score_query(query, top_k=3):
    """
    Score a single line-item query against the whole catalog.

    Returns a list of dicts sorted by confidence, each with sku_id, name,
    score, and the component signals for transparency. Component visibility
    matters: an agent should be able to log why it chose a SKU, which is the
    "reasoning traces" expectation in the JD.
    """
    q_tokens = _tokens(query)
    q_facets = _extract_facets(query)

    # Score every alias/name surface form, keep the best per SKU.
    best = {}
    for surface, sku_id, source in _ALIAS_INDEX:
        s_tokens = _tokens(surface)
        jac = _jaccard(q_tokens, s_tokens)
        fuz = _fuzzy_ratio(query.lower(), surface)
        lexical = 0.6 * jac + 0.4 * fuz
        if sku_id not in best or lexical > best[sku_id]["_lex"]:
            best[sku_id] = {"_lex": lexical, "_surface": surface,
                            "_source": source}

    results = []
    for sku_id, comp in best.items():
        product = CATALOG[sku_id]
        attr = _attribute_bonus(q_facets, product)
        cat = _category_prior(q_tokens, product)
        score = min(comp["_lex"] + attr + cat, 1.0)
        results.append({
            "sku_id": sku_id,
            "name": product["name"],
            "score": round(score, 3),
            "lexical": round(comp["_lex"], 3),
            "attribute_bonus": round(attr, 3),
            "category_prior": round(cat, 3),
            "matched_on": comp["_surface"],
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_k]


def resolve_line_item(query, accept_threshold=0.45, ambiguous_gap=0.12):
    """
    Turn a raw query into a resolution decision.

    Returns a dict with:
      status : "matched" | "ambiguous" | "no_match"
      sku_id : the chosen SKU when matched
      candidates : the ranked list, always included for auditing

    The two thresholds encode a real product decision. accept_threshold is how
    confident the top candidate must be to auto-accept. ambiguous_gap is how far
    ahead of the runner-up it must be; a narrow gap means two products fit almost
    equally and the agent should ask the Pro to clarify rather than guess.
    Guessing wrong on a B2B sourcing quote is worse than asking.
    """
    cands = score_query(query, top_k=3)
    if not cands or cands[0]["score"] < accept_threshold:
        return {"status": "no_match", "sku_id": None, "candidates": cands}

    if len(cands) > 1 and (cands[0]["score"] - cands[1]["score"]) < ambiguous_gap:
        return {"status": "ambiguous", "sku_id": None, "candidates": cands}

    return {"status": "matched", "sku_id": cands[0]["sku_id"],
            "candidates": cands}


if __name__ == "__main__":
    tests = [
        "half inch copper elbow",
        "1/2 cu 90 elbow",
        "12-2 romex 250ft",
        "romex wire",
        "2x4 studs 8ft",
        "5 gal white interior paint",
        "quikrete fast set",
        "r13 batts",
        "deck screws 3 inch",
        "purple widget frobnicator",
    ]
    for t in tests:
        r = resolve_line_item(t)
        top = r["candidates"][0] if r["candidates"] else None
        line = f"[{r['status']:>9}] {t!r:<32}"
        if top:
            line += f" -> {top['sku_id']} ({top['name'][:32]}) score={top['score']}"
        print(line)