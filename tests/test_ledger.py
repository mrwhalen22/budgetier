import unittest

from budgetier.ledger import Ledger
from tests.support import Tmp, raw


class Merge(Tmp):
    def test_overlap_adds_only_new_rows(self):
        led = Ledger(self.dir)
        first = [raw(1, "A", -100), raw(2, "B", -200)]
        second = [raw(2, "B", -200), raw(3, "C", -300)]
        led.merge("x", first, "1.csv")
        result = led.merge("x", second, "2.csv")
        self.assertEqual((result["added"], result["duplicates"]), (1, 1))
        self.assertEqual(len(led.rows), 3)

    def test_identical_rows_in_one_file_are_kept(self):
        led = Ledger(self.dir)
        coffee = [raw(1, "COFFEE", -500), raw(1, "COFFEE", -500)]
        led.merge("x", coffee, "1.csv")
        self.assertEqual(len(led.rows), 2)

    def test_reimport_is_a_no_op(self):
        led = Ledger(self.dir)
        rows = [raw(1, "COFFEE", -500), raw(1, "COFFEE", -500), raw(2, "B", -1)]
        led.merge("x", rows, "1.csv")
        self.assertEqual(led.merge("x", rows, "copy.csv")["added"], 0)

    def test_second_export_reveals_one_more_repeat(self):
        led = Ledger(self.dir)
        led.merge("x", [raw(1, "COFFEE", -500)], "1.csv")
        led.merge("x", [raw(1, "COFFEE", -500), raw(1, "COFFEE", -500)], "2.csv")
        self.assertEqual(len(led.rows), 2)

    def test_description_spacing_and_case_ignored(self):
        led = Ledger(self.dir)
        led.merge("x", [raw(1, "Coffee  Shop", -500)], "1.csv")
        self.assertEqual(led.merge("x", [raw(1, "COFFEE SHOP", -500)], "2.csv")["added"], 0)

    def test_same_row_on_another_account_is_separate(self):
        led = Ledger(self.dir)
        led.merge("x", [raw(1, "A", -100)], "1.csv")
        led.merge("y", [raw(1, "A", -100)], "2.csv")
        self.assertEqual(len(led.rows), 2)

    def test_round_trip_through_disk(self):
        led = Ledger(self.dir)
        led.accounts["x"] = {"name": "X", "bank": "B", "number": "1", "type": "checking"}
        led.merge("x", [raw(1, "A", -5), raw(2, "B", 123456, balance=-99)], "1.csv")
        led.save()
        again = Ledger(self.dir)
        self.assertEqual([r["cents"] for r in again.rows], [-5, 123456])
        self.assertEqual(again.rows[1]["balance"], -99)
        self.assertEqual(again.merge("x", [raw(1, "A", -5)], "2.csv")["added"], 0)


if __name__ == "__main__":
    unittest.main()
