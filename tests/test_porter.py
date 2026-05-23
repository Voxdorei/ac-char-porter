import unittest

from ac_char_porter.porter import PorterError, remap_row, to_base36, validate_character_name
from ac_char_porter.schema import TableRule
from ac_char_porter.sql import insert_sql, quote_identifier


class SqlTests(unittest.TestCase):
    def test_quote_identifier_rejects_unsafe_names(self):
        with self.assertRaises(ValueError):
            quote_identifier("characters; DROP TABLE characters")

    def test_insert_sql_uses_columns_in_row_order(self):
        sql, params = insert_sql("characters", {"guid": 7, "name": "Astra"})
        self.assertEqual(sql, "INSERT INTO `characters` (`guid`, `name`) VALUES (%s, %s)")
        self.assertEqual(params, [7, "Astra"])


class RemapTests(unittest.TestCase):
    def test_remaps_character_and_inventory_item_guids(self):
        rule = TableRule("character_inventory", item_columns=("item", "bag"))
        row = {"guid": 10, "bag": 100, "item": 101, "slot": 4}
        remapped = remap_row(row, 10, 20, rule.character_columns, {100: 900, 101: 901}, rule.item_columns)

        self.assertEqual(remapped, {"guid": 20, "bag": 900, "item": 901, "slot": 4})
        self.assertEqual(row["guid"], 10)


class CheckoutTests(unittest.TestCase):
    def test_base36_shortens_guid_for_parked_names(self):
        self.assertEqual(to_base36(0), "0")
        self.assertEqual(to_base36(35), "z")
        self.assertEqual(to_base36(36), "10")


class CharacterNameTests(unittest.TestCase):
    def test_rejects_names_that_do_not_fit_wow_limits(self):
        with self.assertRaises(PorterError):
            validate_character_name("Exporttestcopy")
        with self.assertRaises(PorterError):
            validate_character_name("Test1")

    def test_accepts_twelve_letter_names(self):
        validate_character_name("Exportcopy")


if __name__ == "__main__":
    unittest.main()
