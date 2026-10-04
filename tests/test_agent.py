import tempfile
import unittest
from pathlib import Path

from app import KnowledgeAgent


class KnowledgeAgentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.agent = KnowledgeAgent(
            data_file=Path(__file__).resolve().parents[1] / "data" / "knowledge.json",
            db_file=Path(self.temp_dir.name) / "test.db",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_retrieves_ai_notice(self) -> None:
        results = self.agent.retrieve("AI讲座怎么报名")
        titles = [item["title"] for item in results]
        self.assertIn("AI应用开发讲座", titles)

    def test_routes_repair_tool(self) -> None:
        self.assertEqual(self.agent.pick_tool("宿舍网络坏了怎么办"), "repair_helper")

    def test_answers_with_sources(self) -> None:
        result = self.agent.ask("学生事务中心电话是多少")
        self.assertEqual(result["tool"], "department_lookup")
        self.assertTrue(result["sources"])
        self.assertIn("学生事务中心", result["answer"])


if __name__ == "__main__":
    unittest.main()
