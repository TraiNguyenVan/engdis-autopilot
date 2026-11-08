import unittest
from unittest.mock import Mock, patch

import solver


class ErrorFixSolverTests(unittest.TestCase):
    def test_do_task_classifies_errorfix_widget(self):
        tab = Mock()
        tab.js.side_effect = [
            1,            # ready check
            "errorfix",   # kind
        ]
        with patch.object(solver, "solve_errorfix", return_value="errorfix: ok") as mock_fix:
            result = solver.do_task(tab, "context")
        self.assertEqual(result, "errorfix: ok")
        mock_fix.assert_called_once_with(tab, "context")

    def test_solve_errorfix_uses_embedded_answers_without_llm(self):
        tab = Mock()
        extract = {
            "ctx": "There seem to be a lot of [[1]] ... courses are [[2]].",
            "errs": ["benefit", "more cheap"],
            "inst": "Correct the errors in this e-mail.",
            "vals": ["benefit", "more cheap"],
            "answers": ["benefits", "cheaper"],
            "hasItem": True,
            "count": 2,
        }
        tab.js.side_effect = [
            extract,                       # extract
            1, 1,                          # setter + jQuery change, input 1 and 2
            1,                             # checkAnswer
            {"prog": 1, "done": None},     # verify
        ]
        with patch.object(solver, "ask_json") as mock_llm, \
             patch.object(solver, "time"):
            result = solver.solve_errorfix(tab, "src")

        self.assertEqual(result, "errorfix: 2/2 prog=1 done=None")
        mock_llm.assert_not_called()
        tab.send.assert_not_called()

    def test_solve_errorfix_falls_back_to_llm_when_answers_missing(self):
        tab = Mock()
        extract = {
            "ctx": "", "errs": [], "inst": "", "vals": ["benefit"],
            "answers": None, "hasItem": True, "count": 1,
        }
        tab.js.side_effect = [
            extract,                       # extract
            1,                             # setter + change
            1,                             # checkAnswer
            {"prog": 1, "done": None},     # verify
        ]
        with patch.object(solver, "ask_json", return_value={"1": "benefits"}) as mock_llm, \
             patch.object(solver, "time"):
            result = solver.solve_errorfix(tab, "")
        self.assertEqual(result, "errorfix: 1/1 prog=1 done=None")
        mock_llm.assert_called_once()

    def test_solve_errorfix_returns_nodata_without_fields(self):
        tab = Mock()
        tab.js.return_value = None
        self.assertEqual(solver.solve_errorfix(tab, ""), "errorfix: nodata")

    def test_solve_errorfix_unloads_when_progress_stays_zero(self):
        tab = Mock()
        extract = {
            "ctx": "", "errs": [], "inst": "", "vals": ["a"],
            "answers": ["b"], "hasItem": True, "count": 1,
        }
        tab.js.side_effect = [
            extract,                       # extract
            1,                             # setter + change
            1,                             # checkAnswer
        ] + [{"prog": 0, "done": None}] * 12 + [
            1,                             # onItemUnloaded
            {"prog": 1, "done": None},     # verify after unload
        ]
        with patch.object(solver, "time"):
            result = solver.solve_errorfix(tab, "")
        self.assertEqual(result, "errorfix: 1/1 prog=1 done=None")


if __name__ == "__main__":
    unittest.main()
