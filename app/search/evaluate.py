"""Measures ranking quality on labelled queries and how much it depends on the exact weights.

Run from the Bot directory: python -m app.search.evaluate
Options: --seed PATH reads the catalog from the SQL seed script instead of the database,
--json PATH also saves every number (and the top 5 of every query) for the thesis.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from types import SimpleNamespace

from app.domain.models import Product
from app.search.ranking import DEFAULT_WEIGHTS, RankingWeights, comparable_text, product_text, rank_products
from app.services.polish_language import enrich_with_polish_lemmas, is_morfeusz_available

DATA_DIR = Path(__file__).resolve().parents[2] / "tests" / "data"
GOLDEN_PATH = DATA_DIR / "ranking_golden.json"
# Extra query sets used only for measurement. The main set above is the one the tests guard.
QUERY_SETS = {
    "podstawowy": GOLDEN_PATH,
    "fleksyjny": DATA_DIR / "ranking_inflection.json",
    "nieprecyzyjny": DATA_DIR / "ranking_vague.json",
}
TOP_K = 5
SENSITIVITY_FACTORS = (0.5, 0.75, 1.25, 1.5)
# Not a score: changing the cap by a fraction would only round back to the same count.
NON_SCORE_FIELDS = {"profile_max_markers"}


@dataclass(frozen=True, slots=True)
class Metrics:
    precision: float
    mrr: float
    ndcg: float
    hit_rate: float

    def __str__(self) -> str:
        return f"P@{TOP_K}={self.precision:.3f}  MRR={self.mrr:.3f}  nDCG@{TOP_K}={self.ndcg:.3f}  Hit@{TOP_K}={self.hit_rate:.3f}"


def load_golden_set(path: Path = GOLDEN_PATH) -> list[dict[str, str]]:
    return json.loads(path.read_text(encoding="utf-8"))


def relevant_ids(products: list[Product], pattern: str) -> set[str]:
    return {product.id for product in products if re.search(pattern, product.id)}


def query_scores(entry: dict[str, str], products: list[Product], rank) -> dict:
    """Metrics of one query, so results can be compared query by query."""
    relevant = relevant_ids(products, entry["relevant"])
    ranked = [product.id for product in rank(entry["query"])[:TOP_K]]
    flags = [product_id in relevant for product_id in ranked]
    dcg = sum(1 / math.log2(index + 2) for index, flag in enumerate(flags) if flag)
    ideal = sum(1 / math.log2(index + 2) for index in range(min(TOP_K, len(relevant))))
    return {
        "query": entry["query"],
        "top": ranked,
        "precision": sum(flags) / TOP_K,
        "rr": next((1 / (index + 1) for index, flag in enumerate(flags) if flag), 0.0),
        "ndcg": dcg / ideal if ideal else 0.0,
        "hit": any(flags),
    }


def evaluate(golden_set: list[dict[str, str]], products: list[Product], rank) -> Metrics:
    """rank(query) returns the products in the order the search would show them."""
    rows = [query_scores(entry, products, rank) for entry in golden_set]
    total = len(rows)
    return Metrics(
        sum(row["precision"] for row in rows) / total,
        sum(row["rr"] for row in rows) / total,
        sum(row["ndcg"] for row in rows) / total,
        sum(row["hit"] for row in rows) / total,
    )


def weighted_ranker(products: list[Product], weights: RankingWeights = DEFAULT_WEIGHTS):
    return lambda query: rank_products(products, enrich_with_polish_lemmas(query), TOP_K, weights)


def lemma_free_ranker(products: list[Product], weights: RankingWeights = DEFAULT_WEIGHTS):
    """The same rules and weights, but the query is not lemmatized: shows what Morfeusz 2 contributes."""
    return lambda query: rank_products(products, query, TOP_K, weights)


def uniform_weights() -> RankingWeights:
    """Every signal counts the same: shows what the differences between weights contribute."""
    values = {
        field.name: 1 if getattr(DEFAULT_WEIGHTS, field.name) > 0 else -1
        for field in fields(RankingWeights)
        if field.name not in NON_SCORE_FIELDS
    }
    return RankingWeights(**values)


def catalog_order_ranker(products: list[Product]):
    return lambda query: products[:TOP_K]


def bm25_ranker(products: list[Product], k1: float = 1.2, b: float = 0.75, use_lemmas: bool = True):
    """Textbook BM25 over the same product text and lemmas, with no synonyms and no rules."""
    documents = {product.id: comparable_text(product_text(product)).split() for product in products}
    average_length = sum(len(words) for words in documents.values()) / len(documents)
    document_frequency: Counter[str] = Counter()
    for words in documents.values():
        document_frequency.update(set(words))
    by_id = {product.id: product for product in products}

    def rank(query: str) -> list[Product]:
        text = enrich_with_polish_lemmas(query) if use_lemmas else query
        terms = set(comparable_text(text).split())
        scores: dict[str, float] = {}
        for product_id, words in documents.items():
            counts = Counter(words)
            score = 0.0
            for term in terms:
                frequency = counts[term]
                if not frequency:
                    continue
                idf = math.log(1 + (len(documents) - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
                score += idf * frequency * (k1 + 1) / (frequency + k1 * (1 - b + b * len(words) / average_length))
            if score:
                scores[product_id] = score
        return [by_id[product_id] for product_id in sorted(scores, key=scores.get, reverse=True)]

    return rank


def sensitivity(golden_set: list[dict[str, str]], products: list[Product]) -> list[tuple[str, float, float]]:
    """For each weight: the worst and best MRR when only that weight is scaled."""
    results = []
    for field in fields(RankingWeights):
        if field.name in NON_SCORE_FIELDS:
            continue

        values = []
        for factor in SENSITIVITY_FACTORS:
            changed = replace(DEFAULT_WEIGHTS, **{field.name: round(getattr(DEFAULT_WEIGHTS, field.name) * factor)})
            values.append(evaluate(golden_set, products, weighted_ranker(products, changed)).mrr)
        results.append((field.name, min(values), max(values)))
    return results


def load_seed_catalog(path: Path) -> list[Product]:
    """Reads the products from the seed script, mapped exactly like rows read from SQL Server."""
    from app.repositories.product_repository import map_sql_server_product

    text = path.read_text(encoding="utf-8-sig")
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("(N'"):
            continue
        line = re.sub(r"CAST\(([\d.]+) AS DECIMAL\(\d+, \d+\)\)", r"N'\1'", line)
        values = [value.replace("''", "'") for value in re.findall(r"N'((?:[^']|'')*)'", line)]
        if len(values) != 15:
            raise ValueError(f"Unexpected seed row: {line[:80]}")
        (product_id, image, price, currency, name_en, _tag_en, description_en, meta_en, _alt_en,
         name_pl, tag_pl, description_pl, meta_pl, _alt_pl, stock_status) = values
        rows.append(SimpleNamespace(
            id=product_id, name=name_pl, price=float(price), currency=currency, category=tag_pl,
            description=description_pl, name_en=name_en, description_en=description_en,
            meta_pl=meta_pl, meta_en=meta_en, stock_status=stock_status, image_url=image,
        ))
    # The repository orders the catalog by the Polish name.
    rows.sort(key=lambda row: row.name)
    return [map_sql_server_product(row) for row in rows]


def rankers(products: list[Product]) -> dict:
    return {
        "Kolejność z katalogu": catalog_order_ranker(products),
        "BM25 bez lematyzacji": bm25_ranker(products, use_lemmas=False),
        "BM25 z lematyzacją": bm25_ranker(products),
        "Reguły bez lematyzacji": lemma_free_ranker(products),
        "Reguły, wagi równe": weighted_ranker(products, uniform_weights()),
        "Reguły, skala wag (pełny)": weighted_ranker(products),
    }


def average_time_ms(products: list[Product], queries: list[str], repeats: int = 5) -> float:
    rank = weighted_ranker(products)
    for query in queries:  # warm the caches, as in a running bot
        rank(query)
    start = time.perf_counter()
    for _ in range(repeats):
        for query in queries:
            rank(query)
    return (time.perf_counter() - start) * 1000 / (repeats * len(queries))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=Path, help="read the catalog from this SQL seed script")
    parser.add_argument("--json", type=Path, help="save all results to this JSON file")
    args = parser.parse_args()

    if args.seed:
        products = load_seed_catalog(args.seed)
    else:
        from app.api.dependencies import get_product_repository

        products = get_product_repository().list_products()

    query_sets = {name: load_golden_set(path) for name, path in QUERY_SETS.items() if path.exists()}
    golden_set = query_sets["podstawowy"]
    report: dict = {
        "products": len(products),
        "morfeusz": is_morfeusz_available(),
        "sets": {name: len(entries) for name, entries in query_sets.items()},
        "metrics": {},
        "queries": {},
    }
    print(f"Products: {len(products)}, Morfeusz 2: {'yes' if report['morfeusz'] else 'NO'}")

    methods = rankers(products)
    for set_name, entries in query_sets.items():
        print(f"\n== Query set: {set_name} ({len(entries)} queries)")
        report["metrics"][set_name] = {}
        report["queries"][set_name] = {}
        for method, rank in methods.items():
            rows = [query_scores(entry, products, rank) for entry in entries]
            metrics = evaluate(entries, products, rank)
            report["metrics"][set_name][method] = asdict(metrics)
            report["queries"][set_name][method] = rows
            print(f"{method:<28}{metrics}")

    baseline = evaluate(golden_set, products, weighted_ranker(products))
    print(f"\nSensitivity of MRR (baseline {baseline.mrr:.3f}), each weight x{SENSITIVITY_FACTORS}:")
    report["sensitivity"] = []
    for name, worst, best in sensitivity(golden_set, products):
        report["sensitivity"].append({"weight": name, "min": worst, "max": best})
        print(f"  {name:<28}{worst:.3f} .. {best:.3f}")

    all_queries = [entry["query"] for entries in query_sets.values() for entry in entries]
    report["avg_ms_per_query"] = average_time_ms(products, all_queries)
    print(f"\nAverage ranking time: {report['avg_ms_per_query']:.2f} ms per query")

    print("\nQueries with no relevant product in the top results (full ranking):")
    rank = weighted_ranker(products)
    for set_name, entries in query_sets.items():
        for entry in entries:
            row = query_scores(entry, products, rank)
            if not row["hit"]:
                print(f"  [{set_name}] {entry['query']}: {row['top'][:3]}")

    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nSaved: {args.json}")


if __name__ == "__main__":
    main()
