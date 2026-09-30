import unittest
from jev_search_mcp import shape_output

ROWS = [{"file": "/x/a.txt", "line": 1, "original": "Hello"}]


class ShapeOutput(unittest.TestCase):
    def test_dry_run_drops_request_and_reports_openrouter(self):
        data = {"mode": "dry-run", "requests": 1, "payload_bytes": 10, "rows": ROWS,
                "request": {"model": "typesafe/jev-1.13", "provider": {"only": ["typesafe"]}},
                "unjudged": {"reason": "dry-run", "candidates": ["l0"]}}
        out = shape_output(data)
        self.assertNotIn("request", out)
        self.assertEqual(out["rows"], ROWS)
        self.assertEqual(out["model"], "typesafe/jev-1.13")
        self.assertEqual(out["provider"], "openrouter")
        self.assertEqual(out["unjudged"], data["unjudged"])

    def test_dry_run_without_provider_block_is_typesafe(self):
        out = shape_output({"mode": "dry-run", "rows": ROWS, "request": {"model": "jev-1.13.0"}})
        self.assertEqual(out["provider"], "typesafe")

    def test_sent_moves_raw_response_into_meta(self):
        results = [dict(ROWS[0], probability=0.9, match=True)]
        data = {"mode": "sent", "latency_seconds": 0.5, "results": results,
                "ranked_results": results,
                "raw_response": {"id": "gen-1", "model": "typesafe/jev-1.13-20260917",
                                 "answers": {"l0": {}},
                                 "usage": {"cost": 1.9e-05, "input_tokens": 10, "output_tokens": 2}}}
        out = shape_output(data)
        self.assertNotIn("raw_response", out)
        self.assertEqual(out["results"], results)
        self.assertEqual(out["ranked_results"], results)
        self.assertEqual(out["meta"], {"model": "typesafe/jev-1.13-20260917", "generation_id": "gen-1",
                                       "cost": 1.9e-05, "input_tokens": 10, "output_tokens": 2})

    def test_missing_cost_is_null_not_zero(self):
        out = shape_output({"mode": "sent", "results": [], "raw_response": {"model": "jev-1.13.0", "answers": {}}})
        self.assertIsNone(out["meta"]["cost"])
        self.assertIsNone(out["meta"]["generation_id"])


if __name__ == "__main__":
    unittest.main()
