import re

from .retrieval import retrieve
from .ollama_client import generate
from .config import load_config

SYSTEM_RULES = """You are a careful research assistant specialized in EURUSD,
foreign exchange markets, macroeconomics and monetary policy.

Answer in the user's language.

Use only the supplied source excerpts for factual claims about retrieved documents.
Cite factual claims with [S1], [S2], etc.
Every factual sentence must have at least one citation.

Distinguish clearly between:
1. Facts explicitly supported by the sources.
2. Economic interpretation or hypotheses.
3. Information that the available sources do not establish.

Never invent current prices, news, economic calendar events, interest rates,
source contents, publication dates or causal relationships.

Do not assume that correlation proves causation.

Distinguish policy rates, money market rates, government bond yields,
inflation and market expectations.

If the evidence is incomplete or contradictory, explain the limitation.

Never issue live trading orders or claim certainty.
"""

def contains_any(text, terms):
    for term in terms:
        if term.isascii() and term.isalpha() and len(term) <= 4:
            if re.search(
                rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])",
                text
            ):
                return True
        elif term in text:
            return True

    return False


QUESTION_TOPIC_TERMS = {
    "fed_policy": (
        "federal reserve", "federal funds rate", "fomc", "fed rate",
        "فدرال رزرو", "نرخ بهره آمریکا", "نرخ وجوه فدرال"
    ),
    "ecb_policy": (
        "ecb", "european central bank", "deposit facility rate",
        "main refinancing rate", "بانک مرکزی اروپا", "نرخ سپرده‌گذاری"
    ),
    "policy_rate": (
        "policy rate", "policy rates", "interest rate", "interest rates",
        "monetary policy", "نرخ بهره", "سیاست پولی"
    ),
    "rate_differential": (
        "rate differential", "interest rate differential",
        "policy divergence", "monetary policy divergence",
        "interest rate spread", "policy rate gap",
        "اختلاف نرخ بهره", "واگرایی سیاست پولی"
    ),
    "money_market_rates": (
        "€str", "estr", "euribor", "sofr", "money market rate",
        "money market rates", "نرخ بازار پول"
    ),
    "usd_money_market_rates": (
        "sofr", "usd overnight rate", "us dollar overnight funding",
        "dollar overnight funding"
    ),
    "euro_money_market_rates": (
        "€str", "estr", "euribor", "euro short-term rate",
        "euro short term rate"
    ),
    "inflation": (
        "inflation", "cpi", "pce", "hicp", "تورم"
    ),
    "bond_market": (
        "government bond yield", "government bond yields",
        "sovereign spread", "sovereign spreads", "treasury yield",
        "bond yield", "bond yields", "yield curve",
        "government bond market", "government bond markets",
        "short-term government bonds", "treasury bills",
        "بازده اوراق", "اسپرد اوراق", "اوراق دولتی"
    ),
    "bond_yield_spread": (
        "yield spread", "yield spreads", "bond yield spread",
        "bond yield spreads", "yield differential", "yield differentials",
        "us-german yield spread", "treasury-bund spread",
        "bund-treasury spread", "treasury bund spread"
    ),
    "sovereign_spread": (
        "sovereign spread", "sovereign spreads",
        "sovereign bond spread", "sovereign bond spreads",
        "euro area sovereign spreads", "euro area sovereign bond spreads"
    ),
    "yield_curve": (
        "yield curve", "yield curves", "curve inversion",
        "curve steepening", "curve flattening"
    ),
    "central_bank_balance_sheet": (
        "balance sheet", "reserve balances", "bank reserves",
        "central bank assets", "central bank liabilities",
        "ترازنامه", "ذخایر بانکی"
    ),
    "euro_effective_rate": (
        "effective exchange rate", "nominal effective exchange rate",
        "euro effective rate", "شاخص ارز مؤثر یورو",
        "نرخ مؤثر یورو"
    ),
    "fx_market": (
        "eurusd", "eur/usd", "exchange rate", "foreign exchange",
        "forex", "currency pair", "currency market", "currency markets",
        "euro depreciated",
        "euro depreciation", "euro appreciated", "against the us dollar",
        "نرخ برابری", "نرخ ارز", "فارکس", "یورودلار"
    ),
    "stablecoins": (
        "stablecoin", "stablecoins", "استیبل‌کوین", "استیبل کوین"
    ),
    "stablecoin_reserves": (
        "stablecoin reserve", "stablecoin reserves",
        "stablecoin reserve assets", "stablecoin reserve asset"
    ),
}

QUESTION_TOPIC_PATTERNS = {
    "bond_yield_spread": (
        r"\b(?:us|u\.s\.|united states|treasury)\s*[-–—/]\s*"
        r"(?:german|germany|bund)\b.{0,40}\b(?:bond\s+)?"
        r"yield\s+spread[s]?\b",
        r"\b(?:us|u\.s\.|united states)\s+and\s+"
        r"(?:german|germany)\b.{0,40}\byield\s+spread[s]?\b",
    ),
    "sovereign_spread": (
        r"\bsovereign(?:\s+bond)?\s+spreads?\b",
        r"\beuro\s+area\s+sovereign(?:\s+bond)?\s+spreads?\b",
    ),
    "stablecoin_reserves": (
        r"\bstablecoins?\b.{0,80}\breserve(?:s| assets?)?\b",
        r"\breserve(?:s| assets?)?\b.{0,80}\bstablecoins?\b",
    ),
    "rate_differential": (
        r"\bdifference in (?:interest|policy) rates? between\b",
        r"\b(?:interest|policy) rate (?:differential|spread|gap)s?\b",
        r"\brate differences? between\b",
    ),
}

QUESTION_QUERY_TEMPLATES = {
    "fed_policy": (
        "Federal Reserve federal funds rate FOMC monetary policy",
    ),
    "ecb_policy": (
        "ECB deposit facility rate Governing Council monetary policy",
    ),
    "rate_differential": (
        "United States euro area interest rate differential policy rates",
    ),
    "policy_rate": (
        "central bank policy rates monetary policy decisions",
    ),
    "inflation": (
        "United States euro area inflation CPI PCE HICP central bank decisions",
    ),
    "bond_market": (
        "government bond yields sovereign spreads Treasury Bund EURUSD",
    ),
    "bond_yield_spread": (
        "US German Treasury Bund government bond yield spreads",
    ),
    "sovereign_spread": (
        "euro area sovereign bond spreads government bond yields",
    ),
    "yield_curve": (
        "government bond yield curve slope steepening flattening",
    ),
    "usd_money_market_rates": (
        "SOFR US dollar overnight funding money market rates",
    ),
    "euro_money_market_rates": (
        "€STR EURIBOR euro area money market overnight rates",
    ),
    "central_bank_balance_sheet": (
        "central bank balance sheet bank reserves reserve balances liquidity",
    ),
    "euro_effective_rate": (
        "euro nominal effective exchange rate EURUSD",
    ),
    "fx_market": (
        "EUR USD exchange rate euro dollar foreign exchange",
    ),
    "stablecoins": (
        "stablecoin euro dollar reserves monetary policy",
    ),
    "stablecoin_reserves": (
        "stablecoin reserve assets short-term government bonds Treasury bills",
    ),
}


def classify_regions(text):
    """Identify explicit US, euro-area and German-market references."""
    t = text.lower()
    regions = set()

    us_patterns = (
        r"\bunited states\b",
        r"\bu\.s\.\s+(?:dollar|treasury|yield|yields|bond|bonds|"
        r"interest|policy|inflation|cpi)\b",
        r"\bus\s+(?:dollar|treasury|yield|yields|bond|bonds|"
        r"interest|policy|inflation|cpi)\b",
        r"\bus\s+(?:and|[-–—/])\s+(?:german|germany|euro|european)\b",
        r"\b(?:usd|sofr|eurusd)\b",
        r"\bdollars?\b",
    )
    if any(re.search(pattern, t) for pattern in us_patterns):
        regions.add("united_states")

    if contains_any(t, (
        "euro area", "eurozone", "euro", "€str", "estr", "euribor",
        "european central bank"
    )) or re.search(r"\beurusd\b|\beur\s*/\s*usd\b", t):
        regions.add("euro_area")

    if contains_any(t, ("germany", "german", "bund")):
        regions.update(("germany", "euro_area"))

    return regions


def classify_question(question):
    """Identify requested subjects and institutions from the question text."""

    q = question.lower()
    topics = {
        topic for topic, terms in QUESTION_TOPIC_TERMS.items()
        if contains_any(q, terms)
    }
    for topic, patterns in QUESTION_TOPIC_PATTERNS.items():
        if any(re.search(pattern, q) for pattern in patterns):
            topics.add(topic)

    institutions = set()
    if contains_any(q, (
        "federal reserve", "federal funds", "fomc", "fed",
        "آمریکا", "فدرال رزرو", "us policy", "us monetary",
        "us interest rate", "united states policy",
        "united states interest rate"
    )):
        institutions.add("federal_reserve")
    if contains_any(q, (
        "ecb", "european central bank", "euro area",
        "eurozone", "بانک مرکزی اروپا", "منطقه یورو"
    )):
        institutions.add("ecb")
    if (
        contains_any(q, ("us and euro area", "united states and euro area"))
        and contains_any(q, ("inflation", "policy", "central bank"))
    ):
        institutions.update(("federal_reserve", "ecb"))
    if "rate_differential" in topics:
        institutions.update(("federal_reserve", "ecb"))

    regions = classify_regions(q)
    if "federal_reserve" in institutions:
        regions.add("united_states")
    if "ecb" in institutions:
        regions.add("euro_area")

    return {
        "topics": sorted(topics),
        "institutions": institutions,
        "regions": regions
    }


def build_queries(question):
    q = question.lower()
    queries = [question]
    question_topics = classify_question(question)["topics"]
    has_sofr = "sofr" in q
    has_euro_market_instrument = any(
        instrument in q for instrument in ("€str", "euribor")
    )

    for topic in question_topics:
        if topic == "money_market_rates":
            instruments = [
                instrument for instrument in ("€STR", "EURIBOR", "SOFR")
                if instrument.lower() in q
            ]
            if instruments:
                for instrument in instruments:
                    if instrument == "SOFR":
                        queries.append(
                            "SOFR US dollar overnight funding money market rates"
                        )
                    elif instrument == "EURIBOR":
                        queries.append(
                            "EURIBOR euro area term money market rates"
                        )
                    else:
                        queries.append(
                            "€STR euro area overnight money market rate"
                        )
            else:
                queries.append(
                    "€STR EURIBOR SOFR euro dollar money market rates"
                )
        elif topic == "usd_money_market_rates" and has_sofr:
            continue
        elif topic == "euro_money_market_rates" and has_euro_market_instrument:
            continue
        else:
            queries.extend(QUESTION_QUERY_TEMPLATES.get(topic, ()))

    unique = []
    seen = set()

    for query in queries:
        key = query.strip().lower()

        if key and key not in seen:
            seen.add(key)
            unique.append(query.strip())

    return unique


def classify_evidence(text):
    """Classify document topics from its text, not its file or title."""
    t = text.lower()
    tags = []

    has_fed_rate = contains_any(t, (
        "federal funds rate", "federal funds target range",
        "fed funds rate", "fomc target range"
    ))
    has_ecb_rate = contains_any(t, (
        "deposit facility rate", "main refinancing rate",
        "key ecb interest rates", "ecb interest rates"
    ))
    has_general_policy_rate = (
        contains_any(t, ("policy rate", "policy rates"))
        and contains_any(t, (
            "monetary policy", "central bank", "federal reserve",
            "european central bank", "ecb", "fomc"
        ))
    )

    if has_fed_rate or (
        has_general_policy_rate and contains_any(
            t, ("federal reserve", "federal funds", "fomc")
        )
    ):
        tags.append("fed_policy")
    if has_ecb_rate or (
        has_general_policy_rate and contains_any(
            t, ("ecb", "european central bank", "governing council")
        )
    ):
        tags.append("ecb_policy")
    if has_fed_rate or has_ecb_rate or has_general_policy_rate:
        tags.append("policy_rate")

    has_sofr = contains_any(t, ("sofr",))
    has_euro_market_rate = contains_any(t, (
        "€str", "estr", "euribor", "euro short-term rate",
        "euro short term rate"
    ))
    if (
        has_sofr
        or has_euro_market_rate
        or contains_any(t, (
            "money market interest rates", "money market rates"
        ))
    ):
        tags.append("money_market_rates")
    if has_sofr:
        tags.append("usd_money_market_rates")
    if has_euro_market_rate:
        tags.append("euro_money_market_rates")

    if contains_any(t, (
        "rate differential", "rate differentials",
        "interest rate differential", "interest rate differentials",
        "policy rate differential", "policy rate differentials",
        "interest rate spread", "policy rate gap",
        "policy divergence", "rate differences between"
    )) or re.search(
        r"\b(?:difference|differential|spread|gap)s?\s+in\s+"
        r"(?:interest|policy) rates?\b",
        t
    ):
        tags.append("rate_differential")

    if contains_any(t, (
        "yield spread", "yield spreads", "yield differential",
        "yield differentials", "bond yield spread",
        "bond yield spreads", "treasury-bund spread",
        "bund-treasury spread", "treasury bund spread",
        "us-german yield spread", "u.s.-german yield spread"
    )) or re.search(
        r"\b(?:spread|differential)s?\b.{0,45}\b"
        r"(?:treasury|bund|german|united states|u\.s\.)\b",
        t
    ):
        tags.append("bond_yield_spread")

    if contains_any(t, (
        "sovereign spread", "sovereign spreads",
        "sovereign bond spread", "sovereign bond spreads"
    )) or re.search(
        r"\bsovereign\b.{0,45}\bspreads?\b|\bspreads?\b.{0,45}"
        r"\bsovereign\b",
        t
    ):
        tags.append("sovereign_spread")

    if contains_any(t, (
        "yield curve", "yield curves", "curve inversion",
        "curve steepening", "curve flattening"
    )):
        tags.append("yield_curve")

    if contains_any(t, (
        "foreign exchange markets", "exchange rate", "euro depreciated",
        "euro appreciated", "against the us dollar", "eur/usd", "eurusd"
    )):
        tags.append("fx_market")

    if contains_any(t, (
        "inflation", "consumer prices", "price stability",
        "hicp", "cpi", "pce"
    )):
        tags.append("inflation")

    if contains_any(t, (
        "government bond yield", "government bond yields",
        "government bond market", "government bond markets",
        "short-term government bond", "short-term government bonds",
        "treasury rate", "treasury yield", "treasury bills",
        "t-bills", "bund yield", "bond spread", "bond spreads",
        "sovereign spread", "sovereign spreads"
    )):
        tags.append("bond_market")

    if contains_any(t, (
        "balance sheet", "reserve balances", "bank reserves",
        "federal reserve assets", "federal reserve liabilities"
    )):
        tags.append("central_bank_balance_sheet")

    if contains_any(t, (
        "nominal effective exchange rate", "euro effective exchange rate"
    )):
        tags.append("euro_effective_rate")

    if contains_any(t, ("stablecoin", "stablecoins")):
        tags.append("stablecoins")

    if re.search(
        r"\bstablecoins?\b.{0,100}\breserve(?:s| assets?)?\b|"
        r"\breserve(?:s| assets?)?\b.{0,100}\bstablecoins?\b",
        t
    ):
        tags.append("stablecoin_reserves")

    return tags


def classify_institution(text):
    """Identify institutions explicitly discussed in the document text."""
    t = text.lower()
    has_fed = contains_any(t, (
        "federal reserve", "federal funds", "fomc",
        "federal open market committee"
    ))
    has_ecb = contains_any(t, (
        "european central bank", "ecb", "governing council"
    ))

    if has_fed and has_ecb:
        return "both"
    if has_fed:
        return "federal_reserve"
    if has_ecb:
        return "ecb"
    return "general"


def relevance_adjustment(question, text, tags, institution=None):
    """Return a bounded subject-ranking adjustment, never a confidence score."""
    profile = classify_question(question)
    question_topics = set(profile["topics"])
    question_regions = profile["regions"]
    document_topics = set(tags)
    institution = institution or classify_institution(text)
    document_regions = classify_regions(text)

    policy_topics = {"fed_policy", "ecb_policy"}
    requested_policy_topics = question_topics & policy_topics
    requested_money_topics = question_topics & {
        "usd_money_market_rates", "euro_money_market_rates"
    }
    comparison_topics = {
        "rate_differential", "bond_yield_spread", "sovereign_spread"
    }
    document_is_comparative = bool(
        document_topics & comparison_topics
    ) or (
        {"united_states", "euro_area"} <= document_regions
    )

    if len(requested_policy_topics) == 1 and not document_is_comparative:
        requested_policy = next(iter(requested_policy_topics))
        opposite_policy = (
            "ecb_policy" if requested_policy == "fed_policy"
            else "fed_policy"
        )
        if (
            opposite_policy in document_topics
            and requested_policy not in document_topics
        ):
            return -0.18

        requested_institution = (
            "federal_reserve" if requested_policy == "fed_policy" else "ecb"
        )
        if (
            institution in ("federal_reserve", "ecb")
            and institution != requested_institution
        ):
            return -0.14

    if requested_money_topics:
        has_requested_market = bool(
            requested_money_topics & document_topics
        )
        has_other_market = bool(
            (
                {"usd_money_market_rates", "euro_money_market_rates"}
                - requested_money_topics
            ) & document_topics
        )
        if has_other_market and not has_requested_market:
            return -0.14
        if (
            not has_requested_market
            and not has_other_market
            and "money_market_rates" not in document_topics
            and not (
                (question_topics - requested_money_topics
                 - {"money_market_rates"}) & document_topics
            )
        ):
            return -0.12

    requested_macro_regions = question_regions & {
        "united_states", "euro_area"
    }
    document_macro_regions = document_regions & {
        "united_states", "euro_area"
    }
    if (
        len(requested_macro_regions) == 1
        and document_macro_regions
        and not requested_macro_regions & document_macro_regions
        and not document_is_comparative
    ):
        return -0.10

    specific_weights = {
        "rate_differential": 0.18,
        "bond_yield_spread": 0.18,
        "sovereign_spread": 0.18,
        "yield_curve": 0.16,
        "stablecoin_reserves": 0.18,
        "usd_money_market_rates": 0.16,
        "euro_money_market_rates": 0.16,
        "fed_policy": 0.16,
        "ecb_policy": 0.16,
    }
    general_weights = {
        "policy_rate": 0.07,
        "inflation": 0.08,
        "bond_market": 0.09,
        "money_market_rates": 0.09,
        "fx_market": 0.07,
        "euro_effective_rate": 0.11,
        "central_bank_balance_sheet": 0.09,
        "stablecoins": 0.07,
    }
    direct_scores = [
        weight for topic, weight in specific_weights.items()
        if topic in question_topics and topic in document_topics
    ]
    direct_scores.extend(
        weight for topic, weight in general_weights.items()
        if topic in question_topics and topic in document_topics
    )
    if direct_scores:
        return max(direct_scores)

    related_scores = []
    related_topics = {
        "rate_differential": (
            {"fed_policy", "ecb_policy", "policy_rate",
             "money_market_rates", "bond_yield_spread", "sovereign_spread"},
            0.06
        ),
        "bond_yield_spread": ({"bond_market", "sovereign_spread"}, 0.06),
        "sovereign_spread": ({"bond_market", "bond_yield_spread"}, 0.06),
        "yield_curve": ({"bond_market"}, 0.05),
        "stablecoin_reserves": ({"stablecoins", "bond_market"}, 0.05),
        "usd_money_market_rates": ({"money_market_rates"}, 0.05),
        "euro_money_market_rates": ({"money_market_rates"}, 0.05),
        "inflation": ({"policy_rate"}, 0.05),
        "euro_effective_rate": ({"fx_market"}, 0.05),
        "fx_market": (
            {"bond_market", "policy_rate", "money_market_rates"}, 0.04
        ),
        "central_bank_balance_sheet": ({"fx_market"}, 0.04),
        "stablecoins": ({"stablecoin_reserves"}, 0.08),
    }
    for topic, (related_documents, weight) in related_topics.items():
        if topic in question_topics and related_documents & document_topics:
            related_scores.append(weight)
    if related_scores:
        return max(related_scores)

    if "stablecoins" in document_topics and "stablecoins" not in question_topics:
        return -0.12
    if (
        "central_bank_balance_sheet" in document_topics
        and "central_bank_balance_sheet" not in question_topics
    ):
        return -0.08

    return 0.0

def collect_evidence(question):
    cfg = load_config()
    top_k = max(6, int(cfg.get("top_k", 6)))
    queries = build_queries(question)
    collected = {}

    for query_index, query in enumerate(queries):
        try:
            hits = retrieve(query, top_k=top_k)

        except Exception as exc:
            raise RuntimeError(
                f"Evidence retrieval failed for query "
                f"{query_index + 1}: {query}"
            ) from exc

        for hit in hits:
            chunk_id = hit.get("chunk_id", hit.get("id"))

            if chunk_id is None:
                continue

            if chunk_id not in collected:
                collected[chunk_id] = {
                    "hit": hit,
                    "best_score": float(hit.get("score", 0.0)),
                    "query_matches": set()
                }

            item = collected[chunk_id]
            score = float(hit.get("score", 0.0))
            item["best_score"] = max(
                item["best_score"],
                score
            )
            item["query_matches"].add(query_index)

    results = []

    for chunk_id, item in collected.items():
        hit = item["hit"]
        text = hit.get("text") or ""
        tags = classify_evidence(text)
        institution = classify_institution(text)
        base_score = item["best_score"]
        adjustment = relevance_adjustment(
            question,
            text,
            tags,
            institution
        )
        final_score = base_score + adjustment

        results.append({
            **hit,
            "chunk_id": chunk_id,
            "base_score": round(base_score, 4),
            "relevance_adjustment": round(adjustment, 4),
            "score": round(final_score, 4),
            "query_match_count": len(item["query_matches"]),
            "topic_tags": tags,
            "institution": institution
        })

    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    max_evidence = min(10, max(6, top_k + 2))
    return results[:max_evidence], queries

def ask(question):
    hits, queries = collect_evidence(question)

    if not hits:
        return {
            "answer": (
                "در پایگاه دانش هنوز شواهد مرتبطی پیدا نشد. "
                "ابتدا اسناد مرتبط را وارد کن یا سؤال را دقیق‌تر بنویس."
            ),
            "sources": []
        }

    excerpts = []
    sources = []

    for i, hit in enumerate(hits, 1):
        sid = f"S{i}"
        title = hit.get("title") or "Unknown title"
        path = hit.get("source_path") or "Unknown path"
        url = hit.get("source_url") or "not provided"
        content = hit.get("text") or ""

        excerpts.append(
            f"[{sid}]\n"
            f"Title: {title}\n"
            f"Path: {path}\n"
            f"URL: {url}\n"
            f"Topic labels: {', '.join(hit['topic_tags']) or 'unclassified'}\n"
            f"Institution: {hit['institution']}\n"
            f"Excerpt:\n{content}"
        )

        sources.append({
            "id": sid,
            "title": title,
            "path": path,
            "url": hit.get("source_url"),
            "score": hit["score"],
            "base_score": hit["base_score"],
            "relevance_adjustment": hit["relevance_adjustment"],
            "topic_tags": hit["topic_tags"],
            "institution": hit["institution"],
            "query_match_count": hit["query_match_count"]
        })

    prompt = (
        SYSTEM_RULES
        + "\n\nRETRIEVED SOURCE EXCERPTS:\n"
        + "\n\n".join(excerpts)
        + "\n\nIMPORTANT INSTRUCTIONS:\n"
        + "Use all relevant evidence, including evidence from different documents.\n"
        + "Do not force a comparison if the sources do not support one.\n"
        + "Do not treat retrieval scores as probabilities.\n"
        + "Do not confuse policy rates with market rates or bond yields.\n"
        + "Do not infer causation unless the excerpts explicitly support it.\n"
        + "Cite factual statements using only the supplied source IDs.\n"
        + "If the evidence is insufficient, state what is missing.\n"
        + "\nUSER QUESTION:\n"
        + question
    )

    answer = generate(prompt)

    valid_ids = {
        source["id"] for source in sources
    }

    cited_ids = set(
        re.findall(r"\[(S\d+)\]", answer)
    )

    if not cited_ids or not cited_ids.issubset(valid_ids):
        answer = (
            "پاسخ مدل به دلیل نداشتن ارجاع معتبر به منابع پذیرفته نشد. "
            "منابع بازیابی‌شده در پایین نمایش داده شده‌اند."
        )

    return {
        "answer": answer,
        "sources": sources
    }
