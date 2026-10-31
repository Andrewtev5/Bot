"""Measures ranking quality on labelled queries and how much it depends on the exact weights.

Run from the Bot directory: python -m app.search.evaluate
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, fields, replace
from pathlib import Path

from app.domain.models import Product
from app.search.ranking import DEFAULT_WEIGHTS, RankingWeights, comparable_text, product_text, rank_products
from app.services.polish_language import enrich_with_polish_lemmas

GOLDEN_PATH = Path(__file__).resolve().parents[2] / "tests" / "data" / "ranking_golden.json"
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


def evaluate(golden_set: list[dict[str, str]], products: list[Product], rank) -> Metrics:
    """rank(query) returns the products in the order the search would show them."""
    precision = mrr = ndcg = hits = 0.0

    for entry in golden_set:
        relevant = relevant_ids(products, entry["relevant"])
        ranked = [product.id for product in rank(entry["query"])[:TOP_K]]
        flags = [product_id in relevant for product_id in ranked]

        precision += sum(flags) / TOP_K
        hits += any(flags)
        mrr += next((1 / (index + 1) for index, flag in enumerate(flags) if flag), 0.0)
        dcg = sum(1 / math.log2(index + 2) for index, flag in enumerate(flags) if flag)
        ideal = sum(1 / math.log2(index + 2) for index in range(min(TOP_K, len(relevant))))
        ndcg += dcg / ideal if ideal else 0.0

    total = len(golden_set)
    return Metrics(precision / total, mrr / total, ndcg / total, hits / total)


def weighted_ranker(products: list[Product], weights: RankingWeights = DEFAULT_WEIGHTS):
    return lambda query: rank_products(products, enrich_with_polish_lemmas(query), TOP_K, weights)


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


def bm25_ranker(products: list[Product], k1: float = 1.2, b: float = 0.75):
    """Textbook BM25 over the same product text and lemmas, with no synonyms and no rules."""
    documents = {product.id: comparable_text(product_text(product)).split() for product in products}
    average_length = sum(len(words) for words in documents.values()) / len(documents)
    document_frequency: Counter[str] = Counter()
    for words in documents.values():
        document_frequency.update(set(words))
    by_id = {product.id: product for product in products}

    def rank(query: str) -> list[Product]:
        terms = set(comparable_text(enrich_with_polish_lemmas(query)).split())
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


def main() -> None:
    from app.api.dependencies import get_product_repository

    products = get_product_repository().list_products()
    golden_set = load_golden_set()
    print(f"Queries: {len(golden_set)}, products: {len(products)}\n")

    print(f"{'Catalog order':<22}{evaluate(golden_set, products, catalog_order_ranker(products))}")
    print(f"{'BM25':<22}{evaluate(golden_set, products, bm25_ranker(products))}")
    print(f"{'Rules, equal weights':<22}{evaluate(golden_set, products, weighted_ranker(products, uniform_weights()))}")
    baseline = evaluate(golden_set, products, weighted_ranker(products))
    print(f"{'Rules, scale weights':<22}{baseline}\n")

    print(f"Sensitivity of MRR (baseline {baseline.mrr:.3f}), each weight x{SENSITIVITY_FACTORS}:")
    for name, worst, best in sensitivity(golden_set, products):
        print(f"  {name:<28}{worst:.3f} .. {best:.3f}")

    print("\nQueries with no relevant product in the top results:")
    rank = weighted_ranker(products)
    for entry in golden_set:
        relevant = relevant_ids(products, entry["relevant"])
        ranked = [product.id for product in rank(entry["query"])[:TOP_K]]
        if not set(ranked) & relevant:
            print(f"  {entry['query']}: {ranked[:3]}")


if __name__ == "__main__":
    main()
