from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="fathom", description="渊渟 FATHOM runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve", help="启动 FATHOM Web 服务")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8000, type=int)
    subparsers.add_parser("init", help="创建本地数据目录")

    demo = subparsers.add_parser(
        "demo-init", help="载入 seed/ 下的示例数据，便于立即体验与评测"
    )
    demo.add_argument(
        "--status",
        action="store_true",
        help="只显示当前示例数据状态，不做写入",
    )
    demo.add_argument(
        "--reset",
        action="store_true",
        help="先清除已载入的示例数据再重新写入",
    )

    subparsers.add_parser("eval", help="运行黄金问题集认证评测并输出报告")

    token = subparsers.add_parser("token-hash", help="为配置生成 API 令牌摘要")
    token.add_argument("token")
    args = parser.parse_args()

    if args.command == "init":
        Path("data").mkdir(exist_ok=True)
        print("FATHOM Lite initialized: data/")
        return

    if args.command == "token-hash":
        from fathom.application.security import token_hash

        print(token_hash(args.token))
        return

    if args.command == "demo-init":
        _demo_init(status=args.status, reset=args.reset)
        return

    if args.command == "eval":
        _run_eval()
        return

    import uvicorn

    uvicorn.run("fathom.main:app", host=args.host, port=args.port, reload=False)


def _demo_init(*, status: bool, reset: bool) -> None:
    from fathom.adapters.storage.database import create_session_factory
    from fathom.application.demo_data import (
        DEMO_DATASET_FILENAME,
        clear_demo_dataset,
        dataset_summary,
        load_demo_dataset,
        seed_demo_dataset,
    )
    from fathom.config import load_settings

    settings = load_settings()
    dataset = load_demo_dataset(settings.seed_directory / DEMO_DATASET_FILENAME)
    session_factory = create_session_factory(settings)

    if status:
        summary = dataset_summary(session_factory, dataset.source_key)
        if summary["objects"] == 0:
            print("示例数据尚未载入。运行 `fathom demo-init` 即可写入。")
            return
        print(
            f"示例数据已载入：对象 {summary['objects']}，指标观测 {summary['observations']}，"
            f"事件 {summary['events']}（数据集 {dataset.name}）。"
        )
        return

    if reset:
        removed = clear_demo_dataset(session_factory, dataset.source_key)
        if removed:
            print(f"已清除 {removed} 个示例对象及其事实。")

    result = seed_demo_dataset(session_factory, dataset)
    if result["skipped"]:
        print("示例数据已存在，未做改动。需要重建请加 --reset。")
        return
    print(
        f"已载入示例数据集 {dataset.name}：对象 {result['objects']}，关系 {result['relations']}，"
        f"指标观测 {result['observations']}，事件 {result['events']}。"
    )
    print("下一步可运行 `fathom eval` 验证黄金问题集，或 `fathom serve` 启动服务。")


def _run_eval() -> None:
    from fathom.adapters.storage.database import create_session_factory
    from fathom.adapters.storage.semantic_repository import SqlSemanticRepository
    from fathom.application.contract_loader import load_contracts
    from fathom.application.demo_data import GOLDEN_QUESTIONS_FILENAME, load_golden_question_set
    from fathom.application.evaluation import EvaluationService
    from fathom.config import load_settings

    settings = load_settings()
    session_factory = create_session_factory(settings)
    repository = SqlSemanticRepository(session_factory)
    for contract in load_contracts(settings.semantic_directory):
        repository.replace_contract(contract)
    golden_set = load_golden_question_set(
        settings.seed_directory / GOLDEN_QUESTIONS_FILENAME
    )
    # 认证评测只依赖语义绑定与确定性口径；知识库、模型与运行时均为可选依赖，
    # 不传即走纯确定性路径，无需在 CLI 中重复装配一遍应用服务。
    from fathom.application.query_service import QueryService

    service = EvaluationService(
        session_factory,
        QueryService(session_factory, repository),
        golden_set,
    )
    report = service.run_certified_suite()
    print(
        f"评测 {report['suite_key']}：{report['correct']}/{report['total']} "
        f"（{report['accuracy_percent']}%），门槛 {report['threshold']:.0%}"
    )
    for gate, result in report["gates"].items():
        print(f"  {'通过' if result['passed'] else '未通过'} · {gate}")
    if report["passed"]:
        print("认证评测通过。")
    else:
        for failure in report["failures"][:5]:
            print(
                f"  失败：{failure['question']} "
                f"期望 {failure['expected']} 实际 {failure['actual']}"
            )
        raise SystemExit(1)


if __name__ == "__main__":
    main()