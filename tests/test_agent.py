import tempfile
import unittest
import json
from pathlib import Path

from agent import KnowledgeAgent


class KnowledgeAgentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_file = Path(self.temp_dir.name) / "knowledge.json"
        source_data = Path(__file__).resolve().parents[1] / "data" / "knowledge.json"
        self.data_file.write_text(source_data.read_text(encoding="utf-8"), encoding="utf-8")
        self.agent = KnowledgeAgent(
            data_file=self.data_file,
            db_file=Path(self.temp_dir.name) / "test.db",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_retrieves_ai_notice(self) -> None:
        results = self.agent.retrieve("AI讲座怎么报名")
        titles = [item["title"] for item in results]
        self.assertIn("AI应用开发讲座", titles)
        self.assertIn("score", results[0])
        self.assertIn("matched_terms", results[0])
        self.assertIn("retrieval_mode", results[0])

    def test_routes_repair_tool(self) -> None:
        self.assertEqual(self.agent.pick_tool("宿舍网络坏了怎么办"), "repair_helper")

    def test_answers_with_sources(self) -> None:
        result = self.agent.ask("学生事务中心电话是多少")
        self.assertEqual(result["tool"], "department_lookup")
        self.assertTrue(result["sources"])
        self.assertIn("学生事务中心", result["answer"])
        self.assertEqual(["学生事务中心"], [source["title"] for source in result["sources"]])
        self.assertGreaterEqual(result["latency_ms"], 1)
        self.assertIsInstance(result["id"], int)

    def test_records_feedback_and_stats(self) -> None:
        answer = self.agent.ask("宿舍网络坏了怎么办")
        feedback = self.agent.add_feedback(answer["id"], "up", "answer is useful")
        stats = self.agent.stats()

        self.assertEqual(feedback["chat_id"], answer["id"])
        self.assertEqual(stats["chat_count"], 1)
        self.assertEqual(stats["feedback_count"], 1)
        self.assertEqual(stats["knowledge_count"], len(self.agent.knowledge))

    def test_recent_logs_include_source_ids(self) -> None:
        answer = self.agent.ask("选课流程是什么")
        logs = self.agent.recent_logs(limit=5)

        self.assertEqual(logs[0]["id"], answer["id"])
        self.assertIsInstance(logs[0]["source_ids"], list)

    def test_knowledge_crud_rebuilds_index(self) -> None:
        created = self.agent.create_knowledge(
            {
                "id": "canteen-hours",
                "category": "校园服务",
                "title": "食堂开放时间",
                "content": "第一食堂每天7:00-20:00开放。",
                "keywords": ["食堂", "开放", "时间"],
            }
        )
        self.assertEqual(created["id"], "canteen-hours")
        self.assertIn("食堂开放时间", [item["title"] for item in self.agent.retrieve("食堂几点开")])

        updated = self.agent.update_knowledge(
            "canteen-hours",
            {"content": "第一食堂每天7:00-21:00开放。", "keywords": ["食堂", "夜宵"]},
        )
        self.assertIn("21:00", updated["content"])

        deleted = self.agent.delete_knowledge("canteen-hours")
        self.assertEqual(deleted["deleted"], "true")
        persisted = json.loads(self.data_file.read_text(encoding="utf-8"))
        self.assertNotIn("canteen-hours", [item["id"] for item in persisted])


if __name__ == "__main__":
    unittest.main()
