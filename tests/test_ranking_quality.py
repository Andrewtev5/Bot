import pytest

from app.repositories.product_repository import SqlServerProductRepository
from app.search.evaluate import (
    bm25_ranker,
    catalog_order_ranker,
    evaluate,
    load_golden_set,
    relevant_ids,
    weighted_ranker,
)
from app.search.ranking import DEFAULT_WEIGHTS, RankingWeights


@pytest.fixture(scope="module")
def catalog(sql_pool):
    return SqlServerProductRepository(sql_pool).list_products()


@pytest.fixture(scope="module")
def golden_set():
    return load_golden_set()


def test_every_golden_query_has_relevant_products(catalog, golden_set):
    assert len(catalog) == 170
    for entry in golden_set:
        assert relevant_ids(catalog, entry["relevant"]), entry["query"]


def test_ranking_keeps_the_measured_quality(catalog, golden_set):
    metrics = evaluate(golden_set, catalog, weighted_ranker(catalog))

    assert metrics.mrr >= 0.93
    assert metrics.precision >= 0.70
    assert metrics.hit_rate >= 0.95


def test_ranking_is_better_than_the_baselines(catalog, golden_set):
    ranking = evaluate(golden_set, catalog, weighted_ranker(catalog))
    bm25 = evaluate(golden_set, catalog, bm25_ranker(catalog))
    catalog_order = evaluate(golden_set, catalog, catalog_order_ranker(catalog))

    assert ranking.mrr > bm25.mrr > catalog_order.mrr
    assert ranking.precision > bm25.precision > catalog_order.precision


def test_every_weight_is_a_level_of_the_scale():
    allowed = {10, 20, 40, 80, 160, 320}

    for name in RankingWeights.__slots__:
        if name != "profile_max_markers":
            assert abs(getattr(DEFAULT_WEIGHTS, name)) in allowed, name
