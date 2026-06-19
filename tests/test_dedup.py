from app.pipeline.dedup import hamming, near_duplicate_groups, simhash


def test_hamming_counts_differing_bits() -> None:
    assert hamming(0b1011, 0b1001) == 1
    assert hamming(0, (1 << 64) - 1) == 64
    assert hamming(5, 5) == 0


def test_simhash_normalizes_case_and_punctuation() -> None:
    # 대소문자·문장부호만 다르면 동일 토큰 → 동일 지문 (근접중복의 명백한 사례).
    assert simhash("Bitcoin tops $100K") == simhash("BITCOIN TOPS $100K!!!")


def test_simhash_empty_is_zero() -> None:
    assert simhash("") == 0
    assert simhash("   ") == 0


def test_groups_near_duplicates() -> None:
    items = [
        (1, "Bitcoin tops $100K"),
        (2, "BITCOIN TOPS $100K!!!"),
        (3, "Ethereum upgrade goes live on mainnet"),
    ]
    assert near_duplicate_groups(items) == [[1, 2]]


def test_unrelated_titles_not_grouped() -> None:
    items = [
        (1, "Bitcoin tops $100K"),
        (2, "Ethereum upgrade goes live on mainnet"),
        (3, "Solana network outage under investigation"),
    ]
    assert near_duplicate_groups(items) == []


def test_empty_titles_excluded() -> None:
    # 토큰 없는 제목끼리 거짓 군집으로 묶이지 않아야 한다.
    items = [(1, ""), (2, "   "), (3, "Bitcoin tops $100K")]
    assert near_duplicate_groups(items) == []
