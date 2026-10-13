from __future__ import annotations
import unittest
import app

MATE_PGN = '[Event "Mate test"]\n[Result "1-0"]\n\n1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0'
NON_MATE_PGN = '[Event "Non-mate"]\n[Result "*"]\n\n1. e4 e5 2. Nf3 Nc6 *'

class WorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.load_pieces()

    def test_all_twelve_neo_sprites_load(self):
        self.assertEqual(set(app.PIECES), {c + p for c in "wb" for p in "KQRBNP"})

    def test_legal_mate_line_is_confirmed(self):
        states, moves, sans, mate = app.parse_pgn(MATE_PGN, True)
        self.assertTrue(mate)
        self.assertEqual(sans[-1], "Qxf7#")
        self.assertEqual(len(states), len(moves) + 1)

    def test_non_mate_line_is_rejected_for_puzzles(self):
        with self.assertRaises(RuntimeError):
            app.parse_pgn(NON_MATE_PGN, True)

if __name__ == "__main__":
    unittest.main(verbosity=2)
