from pathlib import Path

from fastapi.testclient import TestClient
from fathom.config import Settings
from fathom.main import create_app


def test_certified_domain_semantic_plan_accuracy_is_at_least_99_percent(
    tmp_path: Path,
) -> None:
    metric_aliases = {
        "order_fulfillment_rate": ["订单达成率", "达成率", "计划达成率", "fulfillment"],
        "oee": ["OEE", "设备综合效率", "综合效率"],
        "downtime_minutes": ["停机时长", "停机时间", "停线时长"],
        "actual_output": ["实际产量", "产量", "完成量"],
        "planned_output": ["计划产量", "计划量"],
    }
    patterns = [
        "查询一号线昨天的{metric}",
        "一号线昨天{metric}是多少？",
        "分析一号线的{metric}",
        "请给出一号线{metric}趋势",
        "为什么一号线{metric}下降？",
        "华东工厂一号线的{metric}",
        "看一下1号线昨天{metric}",
        "line_01 {metric}",
        "帮我统计一号线的{metric}",
        "我要了解一号线{metric}",
        "一号线 {metric} 日报",
        "对比一号线两天的{metric}",
        "诊断一号线{metric}异常",
        "解释一号线{metric}变化",
        "一号线的{metric}表现如何",
        "复核一号线{metric}",
        "获取一号线{metric}",
        "计算一号线{metric}",
        "展示一号线{metric}",
        "一号线{metric}有没有下降",
    ]
    cases = []
    for expected, aliases in metric_aliases.items():
        for index, pattern in enumerate(patterns):
            cases.append((pattern.format(metric=aliases[index % len(aliases)]), expected))

    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'accuracy.db'}",
        backup_directory=tmp_path / "backups",
        semantic_directory=Path("semantic"),
    )
    correct = 0
    with TestClient(create_app(settings)) as client:
        for question, expected in cases:
            response = client.post("/api/v1/query/ask", json={"question": question})
            binding = response.json()["plan"]["binding"]
            if binding and binding["metric"] == expected:
                correct += 1

    accuracy = correct / len(cases)
    assert len(cases) == 100
    assert accuracy >= 0.99


def test_accuracy_gate_is_productized_and_persisted(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'evaluation.db'}",
        backup_directory=tmp_path / "backups",
        semantic_directory=Path("semantic"),
    )
    with TestClient(create_app(settings)) as client:
        empty = client.get("/api/v1/governance/evaluations/latest")
        run = client.post("/api/v1/governance/evaluations")
        runtime_run = client.post("/api/v1/runtime/evaluations")
        latest = client.get("/api/v1/governance/evaluations/latest")

    assert empty.json()["status"] == "not_run"
    assert run.json()["total"] == 100
    assert run.json()["accuracy"] >= 0.99
    assert run.json()["passed"] is True
    assert runtime_run.json()["suite_key"] == "runtime.external.golden"
    assert all(gate["passed"] for gate in run.json()["gates"].values())
    assert "任意企业问题" in run.json()["scope_note"]
    assert latest.json()["report"]["run_id"] == run.json()["run_id"]
