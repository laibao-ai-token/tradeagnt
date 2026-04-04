import unittest


class TestFundSymbols(unittest.TestCase):
    def test_normalize_cn_fund_symbol_exchange_codes(self) -> None:
        from src.fund_symbols import normalize_cn_fund_symbol

        self.assertEqual(normalize_cn_fund_symbol("SH510300"), "SH510300")
        self.assertEqual(normalize_cn_fund_symbol("SZ159915"), "SZ159915")
        self.assertEqual(normalize_cn_fund_symbol("510300.SH"), "SH510300")
        self.assertEqual(normalize_cn_fund_symbol("159915.SZ"), "SZ159915")
        self.assertEqual(normalize_cn_fund_symbol("159915"), "159915")

    def test_normalize_cn_fund_symbol_offmarket_code(self) -> None:
        from src.fund_symbols import normalize_cn_fund_symbol

        self.assertEqual(normalize_cn_fund_symbol("024389"), "024389")
        self.assertEqual(normalize_cn_fund_symbol(" 024389 "), "024389")
        self.assertEqual(normalize_cn_fund_symbol("abc"), "")

    def test_normalize_cn_fund_symbols_csv_mixed(self) -> None:
        from src.fund_symbols import normalize_cn_fund_symbols_csv

        self.assertEqual(
            normalize_cn_fund_symbols_csv("510300,159915,SH512100,024389,021490.SZ"),
            ["510300", "159915", "SH512100", "024389", "SZ021490"],
        )

    def test_cn_fund_exchange_candidates_inference(self) -> None:
        from src.fund_symbols import cn_fund_exchange_candidates

        self.assertEqual(cn_fund_exchange_candidates("SH510300"), ["SH510300"])
        self.assertEqual(cn_fund_exchange_candidates("510300"), ["SH510300"])
        self.assertEqual(cn_fund_exchange_candidates("159915"), ["SZ159915"])
        self.assertEqual(cn_fund_exchange_candidates("024389"), [])

    def test_match_cn_fund_signal_examples(self) -> None:
        from src.fund_symbols import match_cn_fund_signal

        self.assertTrue(match_cn_fund_signal("510300", "SH510300"))
        self.assertTrue(match_cn_fund_signal("159915", "SZ159915"))
        self.assertTrue(match_cn_fund_signal("021490", "SZ021490"))
        self.assertTrue(match_cn_fund_signal("SZ159915", "159915"))
        self.assertTrue(match_cn_fund_signal("SZ021490", "021490"))
        self.assertTrue(match_cn_fund_signal("024389", "024389"))
        self.assertFalse(match_cn_fund_signal("024389", "SH510300"))
