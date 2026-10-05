from collector.keyword_filter import score_text


def test_title_weighted_and_capped(cfg) -> None:
    r = score_text("ローカル5G・Wi-Fi EXPO", "", cfg.keywords)
    assert r.score == 100
    assert {"ローカル5G", "5G", "Wi-Fi"} <= set(r.keywords)


def test_body_only_scores_lower(cfg) -> None:
    title_hit = score_text("IoT展", "", cfg.keywords).score
    body_hit = score_text("展示会", "IoT", cfg.keywords).score
    assert title_hit > body_hit > 0


def test_short_ascii_word_boundary(cfg) -> None:
    assert score_text("MAIL ORDER展", "", cfg.keywords).score == 0  # "AI" を部分一致させない


def test_unrelated_event_below_threshold(cfg) -> None:
    assert score_text("フラワーフェスタ 2026", "季節の花と園芸用品の展示即売会", cfg.keywords).score < 40


def test_negative_and_no_event_term(cfg) -> None:
    assert score_text("AIアニメ同人即売会", "", cfg.keywords).score == 0
    halved = score_text("AI", "", cfg.keywords).score  # 展示会を示す語が無い
    assert halved == 20


def test_major_event_names(cfg) -> None:
    assert score_text("CEATEC 2026", "", cfg.keywords).score >= 40
