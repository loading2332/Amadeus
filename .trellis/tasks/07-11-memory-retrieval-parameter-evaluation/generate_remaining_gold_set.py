from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import yaml
from amadeus.evaluation.memory_retrieval_benchmark import (
    MemoryRetrievalBenchmark,
    load_memory_retrieval_benchmark,
)

ROOT = Path(__file__).resolve().parents[3]
CASE_DIR = ROOT / "tests" / "evaluation" / "cases"
REVIEW_DIR = Path(__file__).resolve().parent / "review"
FIXTURE_CORRECTION_PATH = (
    CASE_DIR / "memory_retrieval_benchmark_v1_fixture_correction_1.yaml"
)
POOL_QREL_OVERLAYS = (
    (
        CASE_DIR / "memory_retrieval_benchmark_v1_development_pool_qrels.yaml",
        "memory-retrieval-v1-development-pool-qrels",
        280,
        "development",
    ),
    (
        CASE_DIR
        / "memory_retrieval_benchmark_v1_development_pool_qrels_supplemental_1.yaml",
        "memory-retrieval-v1-development-pool-qrels-supplemental-1",
        4,
        "development",
    ),
    (
        CASE_DIR
        / "memory_retrieval_benchmark_v1_development_pool_qrels_supplemental_2.yaml",
        "memory-retrieval-v1-development-pool-qrels-supplemental-2",
        2,
        "development",
    ),
)
POST_FIXTURE_QREL_OVERLAYS = (
    (
        CASE_DIR
        / "memory_retrieval_benchmark_v1_development_pool_qrels_supplemental_3.yaml",
        "memory-retrieval-v1-development-pool-qrels-supplemental-3",
        4,
        "development",
    ),
    (
        CASE_DIR
        / "memory_retrieval_benchmark_v1_development_pool_qrels_supplemental_4.yaml",
        "memory-retrieval-v1-development-pool-qrels-supplemental-4",
        5,
        "development",
    ),
    (
        CASE_DIR
        / "memory_retrieval_benchmark_v1_development_pool_qrels_supplemental_5.yaml",
        "memory-retrieval-v1-development-pool-qrels-supplemental-5",
        21,
        "development",
    ),
)
HOLDOUT_QREL_OVERLAYS = (
    (
        CASE_DIR
        / "memory_retrieval_benchmark_v1_holdout_pool_qrels_supplemental_1.yaml",
        "memory-retrieval-v1-holdout-pool-qrels-supplemental-1",
        103,
        "holdout",
    ),
)


@dataclass(frozen=True)
class Spec:
    family: str
    batch: int
    split: str
    scenario: str
    capability: str
    language: str
    query: str
    answer: str
    related: str
    unrelated: str
    strata: tuple[str, ...]
    dangerous_related: bool = False
    abstention: bool = False
    multi_answer: str | None = None


SPECS = (
    Spec("personal_coffee_update", 3, "development", "personal_assistant", "knowledge_update", "zh", "我现在喝咖啡要选哪种？", "用户目前只喝低因咖啡。", "用户以前每天喝双份浓缩咖啡。", "用户喜欢茉莉花茶。", ("zh", "vector", "preference", "knowledge-update"), True),
    Spec("personal_train_seat", 3, "development", "personal_assistant", "information_extraction", "mixed", "G128 booking 的座位在哪？", "G128 订单的座位是 06 车 12A。", "G182 订单的座位是 08 车 12A。", "用户高铁出行偏好靠窗。", ("mixed", "both-lanes", "event", "rare-identifier")),
    Spec("personal_weekly_class", 3, "development", "personal_assistant", "temporal_reasoning", "zh", "这周六的游泳课几点？", "2026 年 7 月 18 日周六游泳课是上午九点。", "上周六游泳课是上午十点。", "周六下午有钢琴课。", ("zh", "vector", "event", "temporal-reasoning")),
    Spec("personal_allergy_restaurant", 3, "development", "personal_assistant", "cross_session", "en", "What allergy should I mention at the restaurant?", "The user has a severe peanut allergy.", "The user dislikes very spicy food.", "The user prefers window seats.", ("en", "vector", "fact", "safety")),
    Spec("personal_unknown_parking", 3, "development", "personal_assistant", "abstention", "zh", "我把车停在地下几层了？", "用户常去的商场有地下停车场。", "用户的汽车是白色。", "用户今天下午去过商场。", ("zh", "abstention", "event"), False, True),
    Spec("personal_shared_shopping", 3, "development", "personal_assistant", "information_extraction", "zh", "周末采购还缺哪两样？", "周末采购还缺燕麦奶。", "采购清单中的鸡蛋已经买到。", "下周需要购买打印纸。", ("zh", "vector", "procedure", "multi-evidence"), False, False, "周末采购还缺洗衣液。"),
    Spec("project_migration_decision", 3, "development", "project_assistant", "knowledge_update", "mixed", "memory schema migration 最后选 online 还是 downtime？", "最终决定使用 online migration。", "早期方案要求两小时 downtime。", "前端迁移使用 codemod。", ("mixed", "vector", "fact", "dangerous-obsolete"), True),
    Spec("project_test_command", 3, "development", "project_assistant", "information_extraction", "en", "What command runs the memory acceptance suite?", "Run uv run pytest tests/memory/test_memory_retrieval_acceptance.py.", "Run uv run pytest tests/runtime for runtime tests.", "Run uv run ruff check for lint.", ("en", "both-lanes", "procedure", "exact-command")),
    Spec("project_feature_owner", 3, "development", "project_assistant", "cross_session", "zh", "Telegram outbound 这块现在谁负责？", "Telegram outbound 当前由 Nora 负责。", "Memory evaluation 当前由 Lin 负责。", "Kai 曾临时代管 Telegram outbound。", ("mixed", "vector", "fact", "ownership")),
    Spec("stress_scope_channel", 3, "development", "stress", "information_extraction", "zh", "这个群的发布口令是什么？", "当前项目群的发布口令是 ORBIT-27。", "另一个私有群的发布口令是 ORBIT-72。", "当前群的值班人是 Nora。", ("zh", "both-lanes", "fact", "scope-filter")),

    Spec("personal_home_temperature", 4, "development", "personal_assistant", "cross_session", "zh", "睡觉时卧室空调设多少度？", "用户睡觉时偏好卧室空调设为 25 度。", "用户工作时书房空调设为 23 度。", "用户喜欢温水。", ("zh", "vector", "preference")),
    Spec("personal_passport_expiry", 4, "development", "personal_assistant", "temporal_reasoning", "mixed", "我的 passport 什么时候过期？", "用户护照于 2031 年 4 月 10 日过期。", "用户旧护照于 2026 年 4 月过期。", "用户签证于 2027 年 8 月过期。", ("mixed", "both-lanes", "fact", "date-disambiguation"), True),
    Spec("personal_bookmark_article", 4, "development", "personal_assistant", "information_extraction", "en", "Which article did I save about PostgreSQL indexing?", "The saved article is 'GIN and GiST Index Types'.", "The user saved an article about SQLite WAL.", "The user bookmarked a Python typing guide.", ("en", "vector", "fact")),
    Spec("personal_family_birthday", 4, "development", "personal_assistant", "temporal_reasoning", "zh", "姐姐生日是几月几号？", "用户姐姐的生日是 9 月 16 日。", "用户妹妹的生日是 6 月 19 日。", "用户姐姐喜欢蓝色。", ("zh", "vector", "fact", "entity-disambiguation")),
    Spec("personal_delivery_address_update", 4, "development", "personal_assistant", "knowledge_update", "zh", "现在默认收货地址是哪？", "默认收货地址已改为梧桐路 28 号 3 栋 502。", "旧默认地址是银杏路 18 号。", "公司地址是科技路 66 号。", ("zh", "vector", "fact", "dangerous-obsolete"), True),
    Spec("personal_unknown_wifi", 4, "development", "personal_assistant", "abstention", "mixed", "新公寓 Wi-Fi password 是什么？", "用户的新公寓已经开通宽带。", "旧公寓 Wi-Fi 名为 Home-5G。", "用户路由器品牌是 ASUS。", ("mixed", "abstention", "fact"), False, True),
    Spec("project_env_variable", 4, "development", "project_assistant", "information_extraction", "mixed", "DashScope embedding 的 env var 叫什么？", "DashScope embedding 使用 DASHSCOPE_API_KEY。", "OpenAI chat 使用 OPENAI_API_KEY。", "数据库使用 AMADEUS_DATABASE_URL。", ("mixed", "both-lanes", "fact", "exact-identifier")),
    Spec("project_release_date", 4, "development", "project_assistant", "temporal_reasoning", "zh", "0.4.0-beta.3 计划哪天发？", "0.4.0-beta.3 计划在 2026 年 7 月 24 日发布。", "0.3.2 曾计划在 2026 年 6 月发布。", "pgvector 0.8.4 在 2026 年 7 月升级。", ("zh", "both-lanes", "event", "temporal-reasoning")),
    Spec("project_error_policy", 4, "development", "project_assistant", "cross_session", "en", "How should lexical lane failure degrade?", "A lexical lane failure keeps vector results and records degraded status.", "A vector lane failure keeps lexical results and records degraded status.", "Embedding cache miss aborts a formal experiment.", ("en", "vector", "procedure")),
    Spec("project_unknown_pr", 4, "development", "project_assistant", "abstention", "zh", "PR #842 最后是谁 approve 的？", "PR #824 由 Lin approve。", "Issue #842 由 Nora 关闭。", "代码审核要求至少一人批准。", ("zh", "abstention", "fact", "identifier-hard-negative"), False, True),

    Spec("stress_forgotten_secret", 5, "development", "stress", "knowledge_update", "zh", "之前保存的门禁临时密码是什么？", "门禁临时密码已按用户要求遗忘。", "旧记录曾包含门禁临时密码 7391。", "物业电话是 021-5550-9876。", ("zh", "abstention", "forgotten", "dangerous-obsolete"), True, True),
    Spec("stress_time_boundary", 5, "development", "stress", "temporal_reasoning", "zh", "昨天深夜提交的是哪个 build？", "2026 年 7 月 11 日 23:58 提交的是 build-a91c。", "2026 年 7 月 12 日 00:03 提交的是 build-a92d。", "2026 年 7 月 11 日上午提交了文档。", ("zh", "both-lanes", "event", "time-boundary")),
    Spec("holdout_personal_pet_food", 5, "holdout", "personal_assistant", "knowledge_update", "zh", "现在给猫买哪款粮？", "猫目前改吃低敏配方粮。", "猫以前吃鸡肉配方粮。", "用户喜欢鸡肉沙拉。", ("zh", "vector", "preference", "knowledge-update"), True),
    Spec("holdout_personal_tax_document", 5, "holdout", "personal_assistant", "information_extraction", "mixed", "报税用的 document ID 是什么？", "报税文件编号是 TAX-CN-8842。", "保险文件编号是 TAX-CN-8482。", "报税截止日期是五月底。", ("mixed", "both-lanes", "fact", "rare-identifier")),
    Spec("holdout_personal_call_time", 5, "holdout", "personal_assistant", "temporal_reasoning", "en", "When is my call with Maya tomorrow?", "The call with Maya is at 10:30 on July 13, 2026.", "The call with Mina is at 10:30 on July 14, 2026.", "Maya sent an email yesterday.", ("en", "vector", "event", "temporal-reasoning")),
    Spec("holdout_personal_unknown_insurance", 5, "holdout", "personal_assistant", "abstention", "zh", "我的旅行保险保单号是多少？", "用户购买过旅行保险。", "用户汽车保险号是 AUTO-771。", "用户下月计划旅行。", ("zh", "abstention", "fact"), False, True),
    Spec("holdout_project_queue_choice", 5, "holdout", "project_assistant", "cross_session", "en", "Which queue backend did the worker design choose?", "The worker design chose PostgreSQL SKIP LOCKED.", "An early draft proposed Redis Streams.", "The scheduler uses APScheduler.", ("en", "vector", "fact", "dangerous-obsolete"), True),
    Spec("holdout_project_config_key", 5, "holdout", "project_assistant", "information_extraction", "mixed", "memory lexical kill switch 的 config key？", "The lexical kill switch is memory.lexical_enabled.", "The vector switch is memory.vector_enabled.", "The retry key is runtime.max_retries.", ("mixed", "both-lanes", "fact", "exact-identifier")),
    Spec("holdout_project_schema_update", 5, "holdout", "project_assistant", "knowledge_update", "zh", "trace 里的候选并集字段现在叫什么？", "当前候选并集字段是 candidate_count。", "旧草案字段是 union_size。", "lane 数量字段是 lane_counts。", ("zh", "vector", "fact", "knowledge-update"), True),
    Spec("holdout_stress_cross_user", 5, "holdout", "stress", "abstention", "zh", "我的生产数据库密码是什么？", "另一个用户的数据库密码记录存在但不可访问。", "当前用户使用 PostgreSQL。", "数据库运行在 WSL Docker。", ("zh", "abstention", "cross-user", "dangerous"), True, True),

    Spec("holdout_personal_language_exception", 6, "holdout", "personal_assistant", "cross_session", "mixed", "给客户的 incident report 用什么语言？", "给海外客户的 incident report 使用英文。", "日常解释默认使用中文。", "代码标识符保持英文。", ("mixed", "vector", "preference")),
    Spec("holdout_personal_recipe_steps", 6, "holdout", "personal_assistant", "information_extraction", "zh", "家庭版汤底要加哪两种香料？", "家庭版汤底需要加八角。", "餐厅版汤底需要加花椒。", "用户不喜欢太辣。", ("zh", "vector", "procedure", "multi-evidence"), False, False, "家庭版汤底还需要加香叶。"),
    Spec("holdout_personal_morning_alarm", 6, "holdout", "personal_assistant", "temporal_reasoning", "zh", "明天早班要几点起床？", "2026 年 7 月 13 日早班需要 05:50 起床。", "平时工作日起床时间是 07:20。", "明天下午三点有会议。", ("zh", "vector", "event", "temporal-reasoning")),
    Spec("holdout_personal_diet_update", 6, "holdout", "personal_assistant", "knowledge_update", "en", "What is my current dairy restriction?", "The user currently avoids all dairy products.", "The user previously allowed small amounts of cheese.", "The user avoids peanuts.", ("en", "vector", "preference", "knowledge-update"), True),
    Spec("holdout_personal_unknown_locker", 6, "holdout", "personal_assistant", "abstention", "zh", "健身房储物柜密码是多少？", "用户常去星河健身房。", "用户家门密码已更新。", "健身房会员号是 GYM-2291。", ("zh", "abstention", "fact"), False, True),
    Spec("holdout_project_incident_time", 6, "holdout", "project_assistant", "temporal_reasoning", "en", "When did INC-319 recover?", "INC-319 recovered at 02:14 UTC on July 5, 2026.", "INC-319 started at 01:42 UTC.", "INC-391 recovered at 02:14 UTC.", ("en", "both-lanes", "event", "identifier-disambiguation")),
    Spec("holdout_project_review_rule", 6, "holdout", "project_assistant", "cross_session", "zh", "改 memory ranking 至少要谁 review？", "修改 memory ranking 至少需要 memory owner 和一名 runtime reviewer。", "修改前端样式只需 frontend owner。", "旧规则只要求任意一名 reviewer。", ("zh", "vector", "procedure", "dangerous-obsolete"), True),
    Spec("holdout_project_unknown_flag", 6, "holdout", "project_assistant", "abstention", "mixed", "feature flag MEM-992 默认值是什么？", "feature flag MEM-929 默认关闭。", "MEM-992 是尚未记录的实验编号。", "所有生产 flag 需要审批。", ("mixed", "abstention", "fact", "identifier-hard-negative"), False, True),
    Spec("holdout_stress_homonym", 6, "holdout", "stress", "information_extraction", "zh", "苹果账号绑定的是哪个邮箱？", "用户的 Apple 账号绑定邮箱是 user@example.test。", "用户喜欢吃青苹果。", "公司邮箱使用 Outlook。", ("zh", "vector", "fact", "same-term-different-meaning")),
    Spec("holdout_stress_conflict", 6, "holdout", "stress", "knowledge_update", "mixed", "production region 现在到底是哪？", "Production 当前迁移到 ap-southeast-1。", "Production 过去位于 us-west-2。", "Backup region 是 ap-northeast-1。", ("mixed", "both-lanes", "fact", "dangerous-obsolete"), True),
)


def _memory(key: str, summary: str, *, status: str = "active") -> dict[str, object]:
    item: dict[str, object] = {
        "key": key,
        "summary": summary,
        "memory_type": "fact",
        "happened_at": "2026-07-01T09:00:00+08:00",
        "updated_at": "2026-07-01T09:00:00+08:00",
        "reinforcement": 2,
        "emotional_weight": 1,
    }
    if status != "active":
        item["status"] = status
    return item


def _payload(specs: tuple[Spec, ...], batch: int) -> dict[str, object]:
    corpora = []
    queries = []
    for spec in specs:
        relevant_keys = [] if spec.abstention else [f"{spec.family}_answer"]
        memories = [_memory(f"{spec.family}_answer", spec.answer)]
        if spec.multi_answer is not None:
            second_key = f"{spec.family}_answer_2"
            memories.append(_memory(second_key, spec.multi_answer))
            relevant_keys.append(second_key)
        memories.extend(
            [
                _memory(
                    f"{spec.family}_related",
                    spec.related,
                    status="superseded" if spec.dangerous_related else "active",
                ),
                _memory(f"{spec.family}_irrelevant", spec.unrelated),
            ]
        )
        corpora.append({"id": spec.family, "memories": memories})
        judgments = []
        for key in relevant_keys:
            judgments.append(
                {
                    "memory_key": key,
                    "relevance": 3,
                    "dangerous": False,
                    "expected_lanes": ["vector", "lexical"]
                    if "both-lanes" in spec.strata
                    else ["vector"],
                    "rationale": "当前有效，直接回答问题。",
                }
            )
        if spec.abstention:
            judgments.append(
                {
                    "memory_key": f"{spec.family}_answer",
                    "relevance": 0,
                    "dangerous": False,
                    "rationale": "主题接近，但没有问题所需的具体答案。",
                }
            )
        related_judgment: dict[str, object] = {
            "memory_key": f"{spec.family}_related",
            "relevance": 0 if spec.abstention else 1,
            "dangerous": spec.dangerous_related,
            "rationale": "容易混淆，但不是当前问题的有效答案。",
        }
        if spec.dangerous_related:
            related_judgment["danger_reasons"] = ["superseded"]
        judgments.extend(
            [
                related_judgment,
                {
                    "memory_key": f"{spec.family}_irrelevant",
                    "relevance": 0,
                    "dangerous": False,
                    "rationale": "同域或词面相近，但实体、时间或问题属性不匹配。",
                },
            ]
        )
        queries.append(
            {
                "id": f"{spec.family}_{spec.language}",
                "family_id": spec.family,
                "corpus_id": spec.family,
                "split": spec.split,
                "review_status": "approved",
                "review_batch": batch,
                "product_scenario": spec.scenario,
                "memory_capability": spec.capability,
                "language": spec.language,
                "raw_query": spec.query,
                "fixed_hypotheses": {
                    "event": spec.answer,
                    "general": f"与问题“{spec.query}”对应的长期记忆。",
                },
                "strata": list(spec.strata),
                "expected_abstention": spec.abstention,
                "required_memory_keys": relevant_keys,
                "judgments": judgments,
                "rationale": "用于检验相关答案、近邻干扰项和无关项之间的排序边界。",
            }
        )
    return {
        "version": f"memory-retrieval-v1-batch-{batch}-draft",
        "review_status": "draft",
        "corpora": corpora,
        "queries": queries,
    }


def _review(specs: tuple[Spec, ...], batch: int) -> str:
    lines = [
        f"# Gold Set 第 {batch} 批审核表",
        "",
        "本批已于 2026-07-12 由用户整体审核通过，所有 family 均为 `approved`。",
        "",
    ]
    for index, spec in enumerate(specs, 1):
        lines.extend(
            [
                f"## {index}. {spec.family}",
                "",
                f"- Split：`{spec.split}`；场景：`{spec.scenario}`；能力：`{spec.capability}`",
                f"- Query：`{spec.query}`",
                f"- 直接答案候选：{spec.answer}",
                f"- 近邻干扰项：{spec.related}",
                f"- 无关项：{spec.unrelated}",
                f"- Expected abstention：{'是' if spec.abstention else '否'}；Dangerous related：{'是' if spec.dangerous_related else '否'}",
                "- [x] Query/场景通过",
                "- [x] qrels 与 required 通过",
                "- [x] Dangerous/abstention 通过",
                "",
            ]
        )
    lines.extend(
        [
            "## 批次结论",
            "",
            "- [x] 本批全部通过。",
            "- [ ] 需要修改部分 family。",
            "- [ ] rubric 需要调整。",
            "",
        ]
    )
    return "\n".join(lines)


def _review_existing_batch(payload: dict[str, object], batch: int) -> str:
    queries = payload["queries"]
    assert isinstance(queries, list)
    lines = [
        f"# Gold Set 第 {batch} 批审核表",
        "",
        "本批已于 2026-07-12 由用户整体审核通过，所有 family 均为 `approved`。",
        "",
    ]
    for index, raw_query in enumerate(queries, 1):
        assert isinstance(raw_query, dict)
        judgments = raw_query["judgments"]
        assert isinstance(judgments, list)
        lines.extend(
            [
                f"## {index}. {raw_query['family_id']}",
                "",
                f"- Query：`{raw_query['raw_query']}`",
                f"- 场景：`{raw_query['product_scenario']}`；能力：`{raw_query['memory_capability']}`",
                f"- Required：`{raw_query['required_memory_keys']}`；Expected abstention：`{raw_query['expected_abstention']}`",
                "- Judgments："
                + "；".join(
                    f"`{item['memory_key']}`={item['relevance']}"
                    + ("/dangerous" if item["dangerous"] else "")
                    for item in judgments
                    if isinstance(item, dict)
                ),
                "- [x] Query/场景通过",
                "- [x] qrels 与 required 通过",
                "- [x] Dangerous/abstention 通过",
                "",
            ]
        )
    lines.extend(
        [
            "## 批次结论",
            "",
            "- [x] 本批全部通过。",
            "- [ ] 需要修改部分 family。",
            "- [ ] rubric 需要调整。",
            "",
        ]
    )
    return "\n".join(lines)


def _apply_approved_pool_qrels(
    queries: list[object],
    *,
    overlay_path: Path,
    expected_version: str,
    expected_count: int,
    expected_split: str,
    source_dataset_hash: str,
) -> int:
    payload = yaml.safe_load(overlay_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{overlay_path.name}: qrels overlay must be an object")
    if payload.get("version") != expected_version:
        raise ValueError(f"{overlay_path.name}: unexpected qrels overlay version")
    if payload.get("review_status") != "approved":
        raise ValueError(f"{overlay_path.name}: qrels overlay must be approved")
    if payload.get("split", "development") != expected_split:
        raise ValueError(f"{overlay_path.name}: qrels overlay split mismatch")
    if payload.get("source_dataset_hash") != source_dataset_hash:
        raise ValueError(f"{overlay_path.name}: source dataset hash mismatch")
    raw_judgments = payload.get("judgments")
    if not isinstance(raw_judgments, list) or len(raw_judgments) != expected_count:
        raise ValueError(
            f"{overlay_path.name}: qrels overlay must contain {expected_count} judgments"
        )
    query_by_id = {
        query["id"]: query for query in queries if isinstance(query, dict)
    }
    seen: set[tuple[str, str]] = set()
    for judgment in raw_judgments:
        if not isinstance(judgment, dict):
            raise ValueError(f"{expected_split} pool judgments must be objects")
        query_id = judgment.get("query_id")
        memory_key = judgment.get("memory_key")
        if not isinstance(query_id, str) or not isinstance(memory_key, str):
            raise ValueError(
                f"{expected_split} pool judgments require query_id/memory_key"
            )
        marker = (query_id, memory_key)
        if marker in seen:
            raise ValueError(f"{overlay_path.name}: duplicate judgment: {marker}")
        seen.add(marker)
        query = query_by_id.get(query_id)
        if query is None or query.get("split") != expected_split:
            raise ValueError(
                f"{overlay_path.name}: unknown {expected_split} query {query_id}"
            )
        existing = query.get("judgments")
        if not isinstance(existing, list):
            raise ValueError(f"{query_id}: judgments must be a list")
        if any(item.get("memory_key") == memory_key for item in existing):
            raise ValueError(
                f"{overlay_path.name}: {query_id} already judges {memory_key}"
            )
        existing.append(
            {
                "memory_key": memory_key,
                "relevance": judgment.get("relevance"),
                "dangerous": judgment.get("dangerous"),
                "danger_reasons": judgment.get("danger_reasons", []),
                "rationale": judgment.get("rationale"),
            }
        )
    return len(raw_judgments)


def _load_generated_benchmark(
    payload: dict[str, object],
    *,
    temp_path: Path,
) -> MemoryRetrievalBenchmark:
    try:
        temp_path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        benchmark = load_memory_retrieval_benchmark(temp_path)
        benchmark.require_approved()
        return benchmark
    finally:
        temp_path.unlink(missing_ok=True)


def _apply_qrel_overlay_sequence(
    queries: list[object],
    approved: dict[str, object],
    *,
    overlays: tuple[tuple[Path, str, int, str], ...],
    current_benchmark: MemoryRetrievalBenchmark,
    temp_label: str,
) -> tuple[MemoryRetrievalBenchmark, list[tuple[Path, int]]]:
    applied_counts: list[tuple[Path, int]] = []
    for index, (
        overlay_path,
        expected_version,
        expected_count,
        expected_split,
    ) in enumerate(
        overlays,
        start=1,
    ):
        applied_count = _apply_approved_pool_qrels(
            queries,
            overlay_path=overlay_path,
            expected_version=expected_version,
            expected_count=expected_count,
            expected_split=expected_split,
            source_dataset_hash=current_benchmark.content_hash,
        )
        applied_counts.append((overlay_path, applied_count))
        current_benchmark = _load_generated_benchmark(
            approved,
            temp_path=CASE_DIR
            / f".memory_retrieval_benchmark_v1_{temp_label}_{index}.tmp.yaml",
        )
    return current_benchmark, applied_counts


def _apply_approved_fixture_correction(
    queries: list[object],
    corpora: list[object],
    *,
    source_dataset_hash: str,
) -> tuple[int, int, int]:
    payload = yaml.safe_load(FIXTURE_CORRECTION_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("fixture correction must be an object")
    if payload.get("version") != "memory-retrieval-v1-fixture-correction-1":
        raise ValueError("unexpected fixture correction version")
    if payload.get("review_status") != "approved":
        raise ValueError("fixture correction must be approved")
    if payload.get("source_dataset_hash") != source_dataset_hash:
        raise ValueError("fixture correction source dataset hash mismatch")

    memory_updates = payload.get("memory_updates")
    query_updates = payload.get("query_updates")
    judgment_updates = payload.get("judgment_updates")
    if not isinstance(memory_updates, list) or len(memory_updates) != 19:
        raise ValueError("fixture correction must contain 19 memory updates")
    if not isinstance(query_updates, list) or len(query_updates) != 6:
        raise ValueError("fixture correction must contain 6 query updates")
    if not isinstance(judgment_updates, list) or len(judgment_updates) != 2:
        raise ValueError("fixture correction must contain 2 judgment updates")

    memory_by_key = {
        memory["key"]: memory
        for corpus in corpora
        if isinstance(corpus, dict)
        for memory in corpus.get("memories", [])
        if isinstance(memory, dict) and isinstance(memory.get("key"), str)
    }
    seen_memories: set[str] = set()
    for raw_update in memory_updates:
        if not isinstance(raw_update, dict):
            raise ValueError("fixture memory updates must be objects")
        memory_key = raw_update.get("memory_key")
        if not isinstance(memory_key, str) or not memory_key:
            raise ValueError("fixture memory update requires memory_key")
        if memory_key in seen_memories:
            raise ValueError(f"duplicate fixture memory update: {memory_key}")
        seen_memories.add(memory_key)
        memory = memory_by_key.get(memory_key)
        if memory is None:
            raise ValueError(f"unknown fixture memory update: {memory_key}")
        fields = set(raw_update) - {"memory_key"}
        if not fields or not fields <= {"scope_channel", "scope_chat_id", "status"}:
            raise ValueError(f"{memory_key}: unsupported fixture memory fields")
        scope_fields = {"scope_channel", "scope_chat_id"} & fields
        if scope_fields and scope_fields != {"scope_channel", "scope_chat_id"}:
            raise ValueError(f"{memory_key}: scope updates require channel and chat")
        for field in scope_fields:
            value = raw_update.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{memory_key}: {field} must be a string")
            memory[field] = value.strip()
        if "status" in fields:
            status = raw_update.get("status")
            if status not in {"active", "superseded"}:
                raise ValueError(f"{memory_key}: invalid status")
            memory["status"] = status

    query_by_id = {
        query["id"]: query for query in queries if isinstance(query, dict)
    }
    seen_queries: set[str] = set()
    for raw_update in query_updates:
        if not isinstance(raw_update, dict):
            raise ValueError("fixture query updates must be objects")
        query_id = raw_update.get("query_id")
        if not isinstance(query_id, str) or not query_id:
            raise ValueError("fixture query update requires query_id")
        if query_id in seen_queries:
            raise ValueError(f"duplicate fixture query update: {query_id}")
        seen_queries.add(query_id)
        query = query_by_id.get(query_id)
        if query is None:
            raise ValueError(f"unknown fixture query update: {query_id}")
        if set(raw_update) != {"query_id", "scope_channel", "scope_chat_id"}:
            raise ValueError(f"{query_id}: unsupported fixture query fields")
        for field in ("scope_channel", "scope_chat_id"):
            value = raw_update.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{query_id}: {field} must be a string")
            query[field] = value.strip()

    seen_judgments: set[tuple[str, str]] = set()
    for raw_update in judgment_updates:
        if not isinstance(raw_update, dict):
            raise ValueError("fixture judgment updates must be objects")
        query_id = raw_update.get("query_id")
        memory_key = raw_update.get("memory_key")
        if not isinstance(query_id, str) or not isinstance(memory_key, str):
            raise ValueError("fixture judgment update requires query_id/memory_key")
        marker = (query_id, memory_key)
        if marker in seen_judgments:
            raise ValueError(f"duplicate fixture judgment update: {marker}")
        seen_judgments.add(marker)
        query = query_by_id.get(query_id)
        if query is None:
            raise ValueError(f"unknown fixture judgment query: {query_id}")
        judgments = query.get("judgments")
        if not isinstance(judgments, list):
            raise ValueError(f"{query_id}: judgments must be a list")
        judgment = next(
            (
                item
                for item in judgments
                if isinstance(item, dict) and item.get("memory_key") == memory_key
            ),
            None,
        )
        if judgment is None:
            raise ValueError(f"{query_id}: unknown judgment {memory_key}")
        expected_fields = {
            "query_id",
            "memory_key",
            "relevance",
            "dangerous",
            "danger_reasons",
            "rationale",
        }
        if set(raw_update) != expected_fields:
            raise ValueError(f"{query_id}/{memory_key}: unsupported judgment fields")
        judgment.update(
            {
                "relevance": raw_update.get("relevance"),
                "dangerous": raw_update.get("dangerous"),
                "danger_reasons": raw_update.get("danger_reasons"),
                "rationale": raw_update.get("rationale"),
            }
        )
    return len(memory_updates), len(query_updates), len(judgment_updates)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--selection-snapshot",
        help="在应用 holdout qrels 前输出 development 选择时的数据集快照",
    )
    args = parser.parse_args()

    for batch in range(3, 7):
        specs = tuple(spec for spec in SPECS if spec.batch == batch)
        if len(specs) != 10:
            raise ValueError(f"batch {batch} must contain 10 specs")
        case_path = CASE_DIR / f"memory_retrieval_benchmark_v1_batch_{batch}_draft.yaml"
        case_path.write_text(
            yaml.safe_dump(_payload(specs, batch), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        (REVIEW_DIR / f"batch-{batch}.md").write_text(
            _review(specs, batch), encoding="utf-8"
        )
    batch_two_path = CASE_DIR / "memory_retrieval_benchmark_v1_batch_2_draft.yaml"
    batch_two = yaml.safe_load(batch_two_path.read_text(encoding="utf-8"))
    for query in batch_two["queries"]:
        query["review_status"] = "approved"
    batch_two_path.write_text(
        yaml.safe_dump(batch_two, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (REVIEW_DIR / "batch-2.md").write_text(
        _review_existing_batch(batch_two, 2), encoding="utf-8"
    )
    batch_one_review = REVIEW_DIR / "batch-1.md"
    batch_one_text = batch_one_review.read_text(encoding="utf-8")
    alternatives = (
        "- [ ] 需要修改部分案例；请按 family 编号写出修改意见。",
        "- [ ] rubric 本身需要调整；请指出 `3/2/1/0` 或 dangerous/required/abstention 的定义问题。",
    )
    placeholders = ("__BATCH_ONE_MODIFICATION__", "__BATCH_ONE_RUBRIC__")
    for alternative, placeholder in zip(alternatives, placeholders, strict=True):
        batch_one_text = batch_one_text.replace(alternative, placeholder)
    batch_one_text = batch_one_text.replace("- [ ]", "- [x]")
    for alternative, placeholder in zip(alternatives, placeholders, strict=True):
        batch_one_text = batch_one_text.replace(placeholder, alternative)
    batch_one_review.write_text(batch_one_text, encoding="utf-8")

    combined_corpora: list[object] = []
    combined_queries: list[object] = []
    combined: dict[str, object] = {
        "version": "memory-retrieval-v1-draft",
        "review_status": "draft",
        "corpora": combined_corpora,
        "queries": combined_queries,
    }
    for batch in range(1, 7):
        path = CASE_DIR / f"memory_retrieval_benchmark_v1_batch_{batch}_draft.yaml"
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        combined_corpora.extend(payload["corpora"])
        combined_queries.extend(payload["queries"])
    approved = {**combined, "version": "memory-retrieval-v1", "review_status": "approved"}
    approved_path = CASE_DIR / "memory_retrieval_benchmark_v1.yaml"
    current_benchmark = _load_generated_benchmark(
        approved,
        temp_path=CASE_DIR / ".memory_retrieval_benchmark_v1_base.tmp.yaml",
    )
    current_benchmark, applied_overlay_counts = _apply_qrel_overlay_sequence(
        combined_queries,
        approved,
        overlays=POOL_QREL_OVERLAYS,
        current_benchmark=current_benchmark,
        temp_label="pre_fixture_overlay",
    )
    fixture_correction_counts = _apply_approved_fixture_correction(
        combined_queries,
        combined_corpora,
        source_dataset_hash=current_benchmark.content_hash,
    )
    current_benchmark = _load_generated_benchmark(
        approved,
        temp_path=CASE_DIR
        / ".memory_retrieval_benchmark_v1_fixture_correction.tmp.yaml",
    )
    current_benchmark, post_fixture_overlay_counts = _apply_qrel_overlay_sequence(
        combined_queries,
        approved,
        overlays=POST_FIXTURE_QREL_OVERLAYS,
        current_benchmark=current_benchmark,
        temp_label="post_fixture_overlay",
    )
    if args.selection_snapshot:
        selection_snapshot = Path(args.selection_snapshot)
        selection_snapshot.parent.mkdir(parents=True, exist_ok=True)
        selection_snapshot.write_text(
            yaml.safe_dump(approved, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        selection_benchmark = load_memory_retrieval_benchmark(selection_snapshot)
        selection_benchmark.require_approved()
        if selection_benchmark.content_hash != current_benchmark.content_hash:
            raise ValueError("selection snapshot hash changed during serialization")
    current_benchmark, holdout_overlay_counts = _apply_qrel_overlay_sequence(
        combined_queries,
        approved,
        overlays=HOLDOUT_QREL_OVERLAYS,
        current_benchmark=current_benchmark,
        temp_label="holdout_overlay",
    )
    approved_output = yaml.safe_dump(approved, allow_unicode=True, sort_keys=False)
    approved_temp_path = approved_path.with_suffix(".yaml.tmp")
    try:
        approved_temp_path.write_text(approved_output, encoding="utf-8")
        benchmark = load_memory_retrieval_benchmark(approved_temp_path)
        benchmark.require_approved()
        if benchmark.content_hash != current_benchmark.content_hash:
            raise ValueError("final benchmark hash changed after overlay validation")
        approved_temp_path.replace(approved_path)
    finally:
        approved_temp_path.unlink(missing_ok=True)
    (CASE_DIR / "memory_retrieval_benchmark_v1_draft.yaml").write_text(
        yaml.safe_dump(combined, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    primary_count = applied_overlay_counts[0][1]
    supplemental_one_count = applied_overlay_counts[1][1]
    supplemental_two_count = applied_overlay_counts[2][1]
    supplemental_three_count = post_fixture_overlay_counts[0][1]
    supplemental_four_count = post_fixture_overlay_counts[1][1]
    supplemental_five_count = post_fixture_overlay_counts[2][1]
    development_pooled_total = sum(
        count
        for _path, count in (*applied_overlay_counts, *post_fixture_overlay_counts)
    )
    holdout_supplemental_one_count = holdout_overlay_counts[0][1]
    formal_judgment_count = sum(len(query.judgments) for query in benchmark.queries)
    memory_correction_count, query_correction_count, judgment_correction_count = (
        fixture_correction_counts
    )
    freeze_path = REVIEW_DIR / "dataset-freeze.md"
    freeze_temp_path = freeze_path.with_suffix(".md.tmp")
    freeze_output = (
        "# Gold Set v1 冻结记录\n\n"
        "- 审核状态：`approved`\n"
        "- 审核完成时间：`2026-07-12`\n"
        "- Families：`60`（development `42` / locked holdout `18`）\n"
        f"- 首轮 development pooled qrels：`{primary_count}`\n"
        f"- Supplemental-1 pooled qrels：`{supplemental_one_count}`\n"
        f"- Supplemental-2 pooled qrels：`{supplemental_two_count}`\n"
        f"- Supplemental-3 pooled qrels：`{supplemental_three_count}`\n"
        f"- Supplemental-4 pooled qrels：`{supplemental_four_count}`\n"
        f"- Supplemental-5 pooled qrels：`{supplemental_five_count}`\n"
        f"- Development pooled qrels 合计：`{development_pooled_total}`\n"
        "- Holdout Supplemental-1 pooled qrels："
        f"`{holdout_supplemental_one_count}`\n"
        f"- 正式 judgments 合计：`{formal_judgment_count}`\n"
        "- Fixture correction："
        f"memory `{memory_correction_count}` / query `{query_correction_count}` / "
        f"judgment `{judgment_correction_count}`\n"
        f"- Dataset SHA-256：`{benchmark.content_hash}`\n"
        "- 正式文件：`tests/evaluation/cases/memory_retrieval_benchmark_v1.yaml`\n\n"
        "第一批已在全部 rubric 稳定后完成最终回看；六批、首轮 pooled qrels、"
        "supplemental-1 四条、supplemental-2 两条、fixture-correction-1 与 "
        "supplemental-3 四条、supplemental-4 五条、supplemental-5 二十一条 "
        "development qrels，以及 holdout supplemental-1 qrels 均由用户批准。"
        "此 hash 冻结语料、query、qrels、dangerous、required、split 与 strata。\n"
    )
    try:
        freeze_temp_path.write_text(freeze_output, encoding="utf-8")
        freeze_temp_path.replace(freeze_path)
    finally:
        freeze_temp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
