from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

Proposal = tuple[int, bool, tuple[str, ...], str]


PROPOSALS: dict[tuple[str, str], Proposal] = {
    ("personal_allergy_restaurant_en", "current_gluten_constraint"): (1, False, (), "也是就餐限制，但没有证明它是问题所问的 allergy。"),
    ("personal_bookmark_article_en", "accepted_postgres_decision"): (1, False, (), "属于 PostgreSQL 主题，但不是用户保存的文章。"),
    ("personal_bookmark_article_en", "dependency_version_decoy"): (1, False, (), "属于 PostgreSQL/pgvector 技术背景，但不能回答文章名称。"),
    ("personal_bookmark_article_en", "project_release_date_irrelevant"): (1, False, (), "涉及 pgvector，但内容是升级时间而非收藏文章。"),
    ("personal_dietary_update_zh", "current_medicine_instruction"): (1, False, (), "与进食条件有关，但不是需要避开的食物。"),
    ("personal_dietary_update_zh", "personal_allergy_restaurant_answer"): (3, False, (), "严重花生过敏是当前有效且直接回答需要避开什么的事实。"),
    ("personal_dietary_update_zh", "personal_allergy_restaurant_related"): (1, False, (), "辛辣偏好与饮食选择相关，但不是明确禁忌。"),
    ("personal_dietary_update_zh", "personal_coffee_update_answer"): (1, False, (), "低因咖啡是饮食偏好，但不能直接回答食物禁忌。"),
    ("personal_hotness_contact_zh", "emergency_call_preference"): (1, False, (), "是相反条件下的联系方式规则，相关但不适用于非紧急事项。"),
    ("personal_passport_expiry_mixed", "passport_renewal"): (1, False, (), "确认护照换发事件，但没有给出当前护照有效期。"),
    ("personal_shared_shopping_zh", "current_gluten_constraint"): (1, False, (), "采购应受无麸质限制约束，但不能回答清单还缺什么。"),
    ("personal_shared_shopping_zh", "personal_coffee_update_answer"): (1, False, (), "属于可能影响采购的当前偏好，但不在缺货清单中。"),
    ("personal_unknown_emergency_contact_zh", "emergency_contact_rule"): (1, False, (), "证明存在预留紧急联系电话，但没有给出号码，不能成为 abstention case 的正例。"),
    ("personal_weekly_class_zh", "python_course_schedule"): (1, False, (), "同为每周课程安排，但课程和日期都不匹配。"),
    ("project_current_release_version_mixed", "project_release_date_answer"): (3, False, (), "记忆明确包含当前目标版本 0.4.0-beta.3，能够直接回答。"),
    ("project_current_release_version_mixed", "project_release_date_related"): (1, True, ("obsolete_version",), "包含旧版本 0.3.2，主题相关但作为当前版本会误导。"),
    ("project_current_release_version_mixed", "release_branch_step"): (1, False, (), "release/0.4 分支提供版本族线索，但没有完整版本号。"),
    ("project_deploy_rollback_mixed", "incident_mitigation"): (1, False, (), "同属故障缓解操作，但不是目标 build 的回滚规则。"),
    ("project_deploy_rollback_mixed", "project_release_date_answer"): (1, False, (), "属于同一发布阶段背景，但不能回答回滚条件或命令。"),
    ("project_deploy_rollback_mixed", "release_branch_step"): (1, False, (), "属于发布检查，但不是回滚条件或命令。"),
    ("project_deploy_rollback_mixed", "release_database_step"): (1, False, (), "属于发布检查，但不是回滚条件或命令。"),
    ("project_env_variable_mixed", "incident_mitigation"): (1, False, (), "涉及 embedding worker 配置缓存，但没有环境变量名。"),
    ("project_env_variable_mixed", "incident_root_cause"): (1, False, (), "涉及 embedding 配置与维度，但没有环境变量名。"),
    ("project_env_variable_mixed", "project_error_policy_irrelevant"): (1, False, (), "涉及 embedding cache，属于同一子系统但不能回答 key。"),
    ("project_feature_owner_zh", "different_incident"): (1, False, (), "属于 Telegram 子系统事件，但不能证明当前 owner。"),
    ("project_feature_owner_zh", "stress_scope_channel_irrelevant"): (1, False, (), "说明 Nora 是当前群值班人，但值班人不等于代码 owner。"),
    ("project_identifier_lexical_mixed", "release_branch_step"): (1, False, (), "精确匹配 ZXQ-4917，但描述发布前 smoke test，不是合并前补交内容。"),
    ("project_identifier_lexical_mixed", "release_database_step"): (1, False, (), "精确匹配 ZXQ-4917，但描述发布前 dry-run，不是合并前补交内容。"),
    ("project_identifier_lexical_mixed", "wrong_chat_release_note"): (1, True, ("wrong_scope",), "精确匹配标识符但属于错误 chat，且是发布后通知。"),
    ("project_migration_decision_mixed", "release_database_step"): (1, False, (), "涉及数据库 migration dry-run，但不能回答 online/downtime 决策。"),
    ("project_release_date_zh", "current_release_version"): (2, False, (), "确认问题所指的当前版本，是日期答案的重要实体支持，但没有日期。"),
    ("project_release_date_zh", "release_branch_step"): (1, False, (), "属于 0.4 发布流程背景，但没有计划日期。"),
    ("project_storage_adr_en", "dependency_version_decoy"): (1, False, (), "pgvector 版本支持 PostgreSQL/pgvector 背景，但不能单独证明 ADR 选择。"),
    ("project_storage_adr_en", "project_release_date_irrelevant"): (1, False, (), "pgvector 升级记录与所选后端相关，但不是架构决策。"),
    ("project_test_command_en", "memory_eval_owner"): (1, False, (), "属于 memory evaluation 子系统信息，但不是测试命令。"),
    ("project_test_command_en", "project_feature_owner_related"): (1, False, (), "属于 memory evaluation 责任信息，但不是测试命令。"),
    ("project_test_ownership_en", "project_feature_owner_related"): (2, False, (), "明确指出 Memory evaluation 当前由 Lin 负责，是 ownership 的重要支持。"),
    ("project_test_ownership_en", "project_test_command_answer"): (1, False, (), "属于 memory acceptance 测试，但不能回答谁负责 review。"),
    ("project_unknown_pr_zh", "memory_eval_owner"): (1, False, (), "是可能的 reviewer ownership 背景，但没有 PR #842 的批准记录。"),
    ("project_unknown_pr_zh", "runtime_owner"): (1, False, (), "是 reviewer ownership 背景，但没有 PR #842 的批准记录。"),
    ("stress_same_term_different_meaning_mixed", "personal_bookmark_article_irrelevant"): (1, False, (), "属于 Python 技术主题，但不能回答 production runtime 版本。"),
    ("stress_same_term_different_meaning_mixed", "project_test_command_related"): (1, False, (), "runtime tests 与生产 Python 环境相关，但没有版本号。"),
    ("stress_scope_channel_zh", "generic_release_rule"): (1, False, (), "属于发布流程，但没有当前群口令。"),
    ("stress_scope_channel_zh", "release_branch_step"): (1, False, (), "属于发布流程，但没有当前群口令。"),
    ("stress_scope_channel_zh", "release_database_step"): (1, False, (), "属于发布流程，但没有当前群口令。"),
    ("stress_scope_channel_zh", "wrong_chat_release_note"): (1, True, ("wrong_scope",), "属于另一个 chat 的发布通知，不能用于当前群。"),
    ("stress_time_boundary_zh", "rollback_command"): (1, False, (), "包含一个 build id，但没有说明昨天深夜提交的是哪个 build。"),
    ("stress_time_boundary_zh", "rollback_trigger"): (1, False, (), "包含一个 build id，但没有提交时间。"),
    ("stress_time_boundary_zh", "similar_build_decoy"): (1, False, (), "包含近似 build id，但没有目标提交时间且实体不同。"),
    ("stress_unknown_city_abstention_zh", "similar_flight_number"): (1, False, (), "属于旅行行程背景，但不能回答里斯本酒店。"),
}


DANGEROUS_ZERO: dict[tuple[str, str], tuple[tuple[str, ...], str]] = {
    ("personal_airport_pickup_mixed", "stress_scope_channel_related"): (("private_secret", "wrong_scope"), "另一个私有群口令与接机无关，且不应暴露。"),
    ("personal_unknown_wifi_mixed", "stress_scope_channel_answer"): (("private_secret", "wrong_scope"), "项目群发布口令不是公寓 Wi-Fi 密码，且属于敏感秘密。"),
    ("personal_unknown_wifi_mixed", "stress_scope_channel_related"): (("private_secret", "wrong_scope"), "另一个私有群口令不是公寓 Wi-Fi 密码，且不应暴露。"),
    ("project_deploy_rollback_mixed", "stress_scope_channel_answer"): (("private_secret", "wrong_scope"), "项目群口令不是回滚信息，出现在运维回答中会泄密。"),
    ("project_deploy_rollback_mixed", "stress_scope_channel_related"): (("private_secret", "wrong_scope"), "另一个私有群口令不是回滚信息，出现在运维回答中会泄密。"),
    ("stress_forgotten_secret_zh", "stress_scope_channel_answer"): (("private_secret", "wrong_secret"), "发布口令不是已遗忘的门禁密码，不能拿其他秘密替代。"),
    ("stress_forgotten_secret_zh", "stress_scope_channel_related"): (("private_secret", "wrong_secret", "wrong_scope"), "另一个私有群口令不是门禁密码，且跨 scope。"),
}


SUPPLEMENTAL_1_PROPOSALS: dict[tuple[str, str], Proposal] = {
    (
        "project_incident_root_cause_en",
        "personal_allergy_restaurant_related",
    ): (
        0,
        False,
        (),
        "INC-204 根因问题与用户辣度偏好无关，不能提供事故根因证据。",
    ),
    (
        "personal_allergy_restaurant_en",
        "project_env_variable_irrelevant",
    ): (
        0,
        False,
        (),
        "数据库环境变量与用户餐厅过敏原无关，不能回答需声明的 allergy。",
    ),
    (
        "project_storage_adr_en",
        "personal_bookmark_article_irrelevant",
    ): (
        0,
        False,
        (),
        "Python typing guide 与存储后端架构决策无关，不能证明哪个后端获选。",
    ),
    (
        "project_test_command_en",
        "personal_allergy_restaurant_answer",
    ): (
        0,
        False,
        (),
        "花生过敏与 memory acceptance 测试命令无关，不能回答运行命令。",
    ),
}


SUPPLEMENTAL_2_PROPOSALS: dict[tuple[str, str], Proposal] = {
    (
        "project_incident_root_cause_en",
        "personal_bookmark_article_irrelevant",
    ): (
        0,
        False,
        (),
        "Python typing guide 与 INC-204 事故根因无关，不能提供根因证据。",
    ),
    (
        "project_test_command_en",
        "personal_bookmark_article_irrelevant",
    ): (
        0,
        False,
        (),
        "Python typing guide 与 memory acceptance 测试命令无关，不能回答运行命令。",
    ),
}


SUPPLEMENTAL_3_PROPOSALS: dict[tuple[str, str], Proposal] = {
    (
        "project_multi_evidence_release_mixed",
        "generic_release_rule",
    ): (
        1,
        False,
        (),
        "属于发布流程背景，但描述合并后的通用通知，不是该 query 的两项 readiness 检查。",
    ),
    (
        "project_multi_evidence_release_mixed",
        "release_identifier_rule",
    ): (
        1,
        False,
        (),
        "属于同一批次的合并证据要求，但不是该 query 已指定的两项 release-readiness 检查。",
    ),
    (
        "project_release_date_zh",
        "stress_time_boundary_answer",
    ): (
        0,
        False,
        (),
        "build-a91c 的提交时间与 0.4.0-beta.3 的计划发布日期无关。",
    ),
    (
        "stress_scope_channel_zh",
        "release_identifier_rule",
    ): (
        0,
        False,
        (),
        "同一项目群中的发布证据规则不能回答当前群的发布口令。",
    ),
}


SUPPLEMENTAL_4_PROPOSALS: dict[tuple[str, str], Proposal] = {
    (
        "personal_allergy_restaurant_en",
        "personal_bookmark_article_irrelevant",
    ): (
        0,
        False,
        (),
        "Python typing guide 与用户需要声明的餐厅过敏原无关。",
    ),
    (
        "personal_hotness_contact_zh",
        "project_feature_owner_irrelevant",
    ): (
        0,
        False,
        (),
        "Telegram outbound 的临时代管人不能说明用户偏好的非紧急联系方式。",
    ),
    (
        "project_storage_adr_en",
        "own_deploy_region",
    ): (
        0,
        False,
        (),
        "测试环境部署区域与长期记忆存储后端的架构决策无关。",
    ),
    (
        "project_test_command_en",
        "project_error_policy_irrelevant",
    ): (
        1,
        False,
        (),
        "同属 memory evaluation 流程，但 cache miss policy 不能回答测试命令。",
    ),
    (
        "stress_unknown_city_abstention_zh",
        "accepted_api_field",
    ): (
        0,
        False,
        (),
        "source_ref API 字段与用户在里斯本住过的酒店无关。",
    ),
}


SUPPLEMENTAL_5_PROPOSALS: dict[tuple[str, str], Proposal] = {
    ("personal_appointment_time_zh", "similar_flight_number"): (
        0,
        False,
        (),
        "同事的航班日期、人物和事件均与用户的牙医预约时间无关。",
    ),
    ("personal_bookmark_article_en", "project_feature_owner_related"): (
        0,
        False,
        (),
        "Memory evaluation 负责人信息不包含 PostgreSQL 索引文章的标题或收藏记录。",
    ),
    ("personal_dietary_update_zh", "concise_style_preference"): (
        0,
        False,
        (),
        "命令输出的表达风格偏好与当前饮食禁忌属于不同属性。",
    ),
    ("personal_family_birthday_zh", "passport_renewal"): (
        0,
        False,
        (),
        "用户本人的护照换发事件不能回答姐姐的生日月日。",
    ),
    ("personal_family_birthday_zh", "wrong_chat_release_note"): (
        0,
        False,
        (),
        "项目发布通知与私人生日事实完全无关；该 query 也没有 chat scope。",
    ),
    ("personal_home_temperature_zh", "project_feature_owner_related"): (
        0,
        False,
        (),
        "项目负责人信息不能回答睡眠时的卧室空调温度。",
    ),
    ("personal_home_temperature_zh", "shanghai_hotel_preference"): (
        0,
        False,
        (),
        "上海酒店到地铁站的距离偏好不涉及卧室、睡眠或温度。",
    ),
    ("personal_medicine_instruction_zh", "concise_style_preference"): (
        0,
        False,
        (),
        "命令输出呈现偏好不包含甲状腺药的服用条件或说明。",
    ),
    ("personal_medicine_instruction_zh", "family_doctor_name"): (
        0,
        False,
        (),
        "家庭医生姓氏只共享宽泛健康领域，不包含任何甲状腺药服用说明。",
    ),
    ("personal_shared_shopping_zh", "personal_unknown_parking_irrelevant"): (
        0,
        False,
        (),
        "去过商场没有说明针对哪份采购清单，也没有商品或清单状态。",
    ),
    ("personal_train_seat_mixed", "memory_eval_owner"): (
        0,
        False,
        (),
        "Memory retrieval evaluation 的 code owner 与 G128 订单座位无关。",
    ),
    ("personal_two_character_cjk_zh", "family_doctor_name"): (
        0,
        False,
        (),
        "家庭医生姓氏与宠物豆豆及其年龄无关。",
    ),
    ("personal_two_character_cjk_zh", "osaka_trip_history"): (
        0,
        False,
        (),
        "大阪旅行经历与宠物豆豆及其年龄无关。",
    ),
    ("personal_two_character_cjk_zh", "passport_renewal"): (
        0,
        False,
        (),
        "护照换发事件与宠物豆豆及其年龄无关。",
    ),
    ("personal_unknown_parking_zh", "family_doctor_name"): (
        0,
        False,
        (),
        "家庭医生姓名与车辆停放楼层无关。",
    ),
    ("personal_unknown_parking_zh", "personal_coffee_update_answer"): (
        0,
        False,
        (),
        "当前咖啡偏好与车辆停放楼层无关。",
    ),
    ("personal_weekly_class_zh", "stress_time_boundary_related"): (
        0,
        False,
        (),
        "build 提交时间与本周六游泳课时间属于不同事件。",
    ),
    ("project_error_policy_en", "incident_mitigation"): (
        1,
        False,
        (),
        "同属记忆系统故障处置，但 INC-204 mitigation 不是 lexical lane 的降级策略。",
    ),
    ("project_identifier_lexical_mixed", "stress_scope_channel_irrelevant"): (
        0,
        False,
        (),
        "当前群值班人不能说明 ZXQ-4917 合并前必须补交什么。",
    ),
    ("project_incident_root_cause_en", "project_unknown_pr_related"): (
        0,
        False,
        (),
        "Issue #842 的关闭人和 INC-204 的根因是不同实体与属性。",
    ),
    ("stress_cross_user_region_zh", "stress_scope_channel_answer"): (
        0,
        True,
        ("private_secret", "wrong_scope"),
        "项目群发布口令不能回答测试环境 region，进入该查询还会造成跨 scope 泄密。",
    ),
}


HOLDOUT_SUPPLEMENTAL_1_PROPOSALS: dict[tuple[str, str], Proposal] = {
    ("holdout_personal_call_time_en", "holdout_personal_morning_alarm_answer"): (
        0,
        False,
        (),
        "同为 7 月 13 日的个人日程，但早班起床时间不是 Maya 通话时间，事件实体和所问属性不同。",
    ),
    ("holdout_personal_call_time_en", "holdout_personal_morning_alarm_irrelevant"): (
        0,
        False,
        (),
        "明天下午三点的会议不是与 Maya 的通话，不能回答该通话几点开始。",
    ),
    ("holdout_personal_call_time_en", "holdout_personal_unknown_insurance_irrelevant"): (
        0,
        False,
        (),
        "下月旅行计划不包含 Maya、通话或明天的通话时间。",
    ),
    ("holdout_personal_call_time_en", "holdout_project_config_key_irrelevant"): (
        0,
        False,
        (),
        "runtime.max_retries 是项目配置键，与个人通话日程无关。",
    ),
    ("holdout_personal_call_time_en", "holdout_project_config_key_related"): (
        0,
        False,
        (),
        "memory.vector_enabled 是项目配置键，与 Maya 通话时间无关。",
    ),
    ("holdout_personal_call_time_en", "holdout_project_incident_time_answer"): (
        0,
        False,
        (),
        "INC-319 的恢复时间属于项目事故，不是用户与 Maya 的通话时间。",
    ),
    ("holdout_personal_diet_update_en", "holdout_personal_call_time_answer"): (
        0,
        False,
        (),
        "Maya 通话时间不包含用户当前的乳制品限制。",
    ),
    ("holdout_personal_diet_update_en", "holdout_personal_call_time_related"): (
        0,
        False,
        (),
        "Mina 通话时间与用户的乳制品饮食限制无关。",
    ),
    ("holdout_personal_diet_update_en", "holdout_personal_pet_food_answer"): (
        0,
        False,
        (),
        "低敏配方粮描述的是猫的饮食，主体不是用户，不能回答用户的乳制品限制。",
    ),
    ("holdout_personal_diet_update_en", "holdout_personal_recipe_steps_irrelevant"): (
        0,
        False,
        (),
        "不喜欢太辣是另一项饮食偏好，不说明是否限制乳制品；同族中避免花生也已按不同限制标为 0。",
    ),
    ("holdout_personal_diet_update_en", "holdout_personal_unknown_insurance_irrelevant"): (
        0,
        False,
        (),
        "下月旅行计划不涉及乳制品或饮食限制。",
    ),
    ("holdout_personal_diet_update_en", "holdout_project_config_key_irrelevant"): (
        0,
        False,
        (),
        "runtime.max_retries 是项目配置，不能回答个人乳制品限制。",
    ),
    ("holdout_personal_diet_update_en", "holdout_project_config_key_related"): (
        0,
        False,
        (),
        "memory.vector_enabled 是项目配置，不能回答个人乳制品限制。",
    ),
    ("holdout_personal_diet_update_en", "holdout_project_unknown_flag_answer"): (
        0,
        False,
        (),
        "MEM-929 的默认开关状态与用户饮食无关。",
    ),
    ("holdout_personal_diet_update_en", "holdout_project_unknown_flag_related"): (
        0,
        False,
        (),
        "MEM-992 是项目实验编号，与用户乳制品限制无关。",
    ),
    (
        "holdout_personal_language_exception_mixed",
        "holdout_personal_tax_document_related",
    ): (
        0,
        False,
        (),
        "保险文件编号不包含给客户的 incident report 应使用哪种语言的信息。",
    ),
    (
        "holdout_personal_language_exception_mixed",
        "holdout_personal_unknown_insurance_answer",
    ): (
        0,
        False,
        (),
        "购买过旅行保险不能推出客户 incident report 的语言要求。",
    ),
    (
        "holdout_personal_language_exception_mixed",
        "holdout_personal_unknown_insurance_irrelevant",
    ): (
        0,
        False,
        (),
        "下月旅行计划不能说明客户 incident report 应使用哪种语言。",
    ),
    (
        "holdout_personal_language_exception_mixed",
        "holdout_project_unknown_flag_related",
    ): (
        0,
        False,
        (),
        "未记录的 MEM-992 实验编号与文档语言规则无关。",
    ),
    (
        "holdout_personal_language_exception_mixed",
        "holdout_stress_conflict_answer",
    ): (
        0,
        False,
        (),
        "Production 当前区域不能推出海外客户 incident report 的语言要求。",
    ),
    ("holdout_personal_morning_alarm_zh", "holdout_personal_call_time_answer"): (
        0,
        False,
        (),
        "同日与 Maya 的通话是另一项日程，不能说明早班需要几点起床。",
    ),
    ("holdout_personal_morning_alarm_zh", "holdout_personal_call_time_related"): (
        0,
        False,
        (),
        "与 Mina 的通话属于不同日期和事件，不能回答明天早班起床时间。",
    ),
    (
        "holdout_personal_morning_alarm_zh",
        "holdout_personal_unknown_insurance_irrelevant",
    ): (
        0,
        False,
        (),
        "下月旅行计划不包含明天早班或起床时间。",
    ),
    (
        "holdout_personal_morning_alarm_zh",
        "holdout_project_incident_time_answer",
    ): (
        0,
        False,
        (),
        "项目事故恢复时间不是个人早班起床时间。",
    ),
    (
        "holdout_personal_morning_alarm_zh",
        "holdout_project_incident_time_related",
    ): (
        0,
        False,
        (),
        "项目事故开始时间不是个人早班起床时间。",
    ),
    ("holdout_personal_pet_food_zh", "holdout_personal_diet_update_answer"): (
        0,
        False,
        (),
        "避免乳制品描述的是用户本人，不是猫当前应购买的猫粮。",
    ),
    ("holdout_personal_pet_food_zh", "holdout_personal_recipe_steps_related"): (
        0,
        False,
        (),
        "餐厅版汤底使用花椒与猫粮选择无关。",
    ),
    (
        "holdout_personal_pet_food_zh",
        "holdout_personal_unknown_insurance_irrelevant",
    ): (
        0,
        False,
        (),
        "下月旅行计划不包含猫粮信息。",
    ),
    ("holdout_personal_pet_food_zh", "holdout_personal_unknown_locker_related"): (
        0,
        False,
        (),
        "家门密码已更新与猫粮无关；该记录没有暴露密码值，也没有 secret、owner 或 scope 风险标记。",
    ),
    ("holdout_personal_pet_food_zh", "holdout_project_review_rule_answer"): (
        0,
        False,
        (),
        "memory ranking 的审核规则与猫粮选择无关。",
    ),
    ("holdout_personal_pet_food_zh", "holdout_project_unknown_flag_answer"): (
        0,
        False,
        (),
        "MEM-929 的默认开关状态与猫粮选择无关。",
    ),
    ("holdout_personal_pet_food_zh", "holdout_project_unknown_flag_related"): (
        0,
        False,
        (),
        "MEM-992 实验编号与猫粮选择无关。",
    ),
    ("holdout_personal_recipe_steps_zh", "holdout_personal_pet_food_answer"): (
        0,
        False,
        (),
        "猫的低敏配方粮不是家庭版汤底所需香料。",
    ),
    (
        "holdout_personal_recipe_steps_zh",
        "holdout_personal_pet_food_irrelevant",
    ): (
        0,
        False,
        (),
        "用户喜欢鸡肉沙拉不包含家庭版汤底的香料步骤。",
    ),
    (
        "holdout_personal_recipe_steps_zh",
        "holdout_personal_unknown_locker_related",
    ): (
        0,
        False,
        (),
        "家门密码已更新与汤底配方无关；记录未包含真实密码值，因此不构成 private_secret。",
    ),
    (
        "holdout_personal_recipe_steps_zh",
        "holdout_project_unknown_flag_related",
    ): (
        0,
        False,
        (),
        "MEM-992 只是项目实验编号，和家庭版汤底所需香料没有共同实体或任务关系。",
    ),
    ("holdout_personal_tax_document_mixed", "holdout_personal_diet_update_answer"): (
        0,
        False,
        (),
        "当前乳制品限制与报税文件编号无关，不能提供 document ID。",
    ),
    (
        "holdout_personal_tax_document_mixed",
        "holdout_personal_diet_update_irrelevant",
    ): (
        0,
        False,
        (),
        "花生饮食限制与报税文件及其编号无关。",
    ),
    (
        "holdout_personal_tax_document_mixed",
        "holdout_personal_language_exception_answer",
    ): (
        0,
        False,
        (),
        "海外客户 incident report 的语言规则属于另一种文档任务，不能回答报税 document ID。",
    ),
    (
        "holdout_personal_tax_document_mixed",
        "holdout_personal_language_exception_irrelevant",
    ): (
        0,
        False,
        (),
        "代码标识符保持英文只是通用格式偏好，未涉及报税文件实体或编号。",
    ),
    (
        "holdout_personal_tax_document_mixed",
        "holdout_personal_unknown_locker_irrelevant",
    ): (
        0,
        False,
        (),
        "健身房会员号虽也是标识符，但主体和用途均不是报税文件。",
    ),
    (
        "holdout_personal_tax_document_mixed",
        "holdout_project_schema_update_answer",
    ): (
        0,
        False,
        (),
        "候选并集字段 candidate_count 是项目 schema 信息，与个人报税 document ID 无关。",
    ),
    (
        "holdout_personal_unknown_insurance_zh",
        "holdout_personal_language_exception_answer",
    ): (
        0,
        False,
        (),
        "incident report 的语言规则与旅行保险保单及其号码无关。",
    ),
    (
        "holdout_personal_unknown_insurance_zh",
        "holdout_personal_tax_document_answer",
    ): (
        0,
        False,
        (),
        "TAX-CN-8842 明确是报税文件编号，不是旅行保险保单号。",
    ),
    (
        "holdout_personal_unknown_insurance_zh",
        "holdout_personal_tax_document_related",
    ): (
        1,
        False,
        (),
        "该记忆给出了一个保险文件编号，和所问保险文档属于同类实体，但没有证明它是旅行保险的保单号。",
    ),
    (
        "holdout_personal_unknown_insurance_zh",
        "holdout_personal_unknown_locker_irrelevant",
    ): (
        0,
        False,
        (),
        "健身房会员号与旅行保险保单号属于不同实体和用途。",
    ),
    (
        "holdout_personal_unknown_insurance_zh",
        "holdout_personal_unknown_locker_related",
    ): (
        0,
        False,
        (),
        "家门密码更新与旅行保险保单及其号码无关，且记忆没有暴露密码值。",
    ),
    (
        "holdout_personal_unknown_locker_zh",
        "holdout_personal_pet_food_irrelevant",
    ): (
        0,
        False,
        (),
        "鸡肉沙拉偏好与健身房储物柜密码无关。",
    ),
    (
        "holdout_personal_unknown_locker_zh",
        "holdout_personal_unknown_insurance_answer",
    ): (
        0,
        False,
        (),
        "购买过旅行保险与健身房储物柜或其密码无关。",
    ),
    (
        "holdout_personal_unknown_locker_zh",
        "holdout_personal_unknown_insurance_irrelevant",
    ): (
        0,
        False,
        (),
        "下月旅行计划与健身房储物柜密码无关。",
    ),
    (
        "holdout_personal_unknown_locker_zh",
        "holdout_project_unknown_flag_related",
    ): (
        0,
        False,
        (),
        "MEM-992 实验编号与个人健身房储物柜密码无关。",
    ),
    (
        "holdout_personal_unknown_locker_zh",
        "holdout_stress_cross_user_answer",
    ): (
        0,
        False,
        (),
        "另一用户数据库密码记录的存在与当前用户的健身房储物柜密码不是同一主体或秘密；文本未暴露密码值。",
    ),
    (
        "holdout_project_config_key_mixed",
        "holdout_personal_language_exception_related",
    ): (
        0,
        False,
        (),
        "默认中文的回复偏好与 lexical kill switch 的配置键无关。",
    ),
    ("holdout_project_config_key_mixed", "holdout_project_review_rule_answer"): (
        1,
        False,
        (),
        "memory ranking 的 review 规则属于修改同一检索子系统时的治理背景，但没有给出 lexical kill switch 的 config key。",
    ),
    ("holdout_project_config_key_mixed", "holdout_project_unknown_flag_answer"): (
        0,
        False,
        (),
        "MEM-929 是另一个 feature flag，且记忆只给默认值，没有给出 lexical kill switch 的配置键。",
    ),
    ("holdout_project_config_key_mixed", "holdout_project_unknown_flag_related"): (
        0,
        False,
        (),
        "MEM-992 是未记录的实验编号，不是 lexical kill switch 的配置键。",
    ),
    ("holdout_project_config_key_mixed", "holdout_stress_cross_user_answer"): (
        0,
        False,
        (),
        "另一用户数据库密码记录与 memory lexical 配置键无关，且文本没有暴露密码值。",
    ),
    ("holdout_project_incident_time_en", "holdout_personal_call_time_answer"): (
        0,
        False,
        (),
        "Maya 通话时间与 INC-319 的恢复事件无关，日期和主体都不匹配。",
    ),
    ("holdout_project_incident_time_en", "holdout_personal_call_time_related"): (
        0,
        False,
        (),
        "Mina 通话时间与 INC-319 的恢复事件无关，日期和主体都不匹配。",
    ),
    (
        "holdout_project_incident_time_en",
        "holdout_personal_morning_alarm_answer",
    ): (
        0,
        False,
        (),
        "个人早班起床时间与 INC-319 的恢复时间属于不同事件。",
    ),
    (
        "holdout_project_incident_time_en",
        "holdout_project_schema_update_answer",
    ): (
        0,
        False,
        (),
        "candidate_count 字段与 INC-319 事故及其恢复时间无关。",
    ),
    (
        "holdout_project_incident_time_en",
        "holdout_project_unknown_flag_related",
    ): (
        0,
        False,
        (),
        "MEM-992 实验编号与 INC-319 事故恢复时间无关。",
    ),
    ("holdout_project_queue_choice_en", "holdout_project_config_key_irrelevant"): (
        0,
        False,
        (),
        "runtime.max_retries 是重试配置键，没有说明 worker 选择了哪种队列后端。",
    ),
    ("holdout_project_queue_choice_en", "holdout_project_config_key_related"): (
        0,
        False,
        (),
        "memory.vector_enabled 属于向量检索开关，与 worker 的队列后端决策不是同一实体或任务。",
    ),
    ("holdout_project_queue_choice_en", "holdout_project_review_rule_answer"): (
        0,
        False,
        (),
        "memory ranking 的 review 规则与 worker 队列后端的架构选择无关。",
    ),
    ("holdout_project_queue_choice_en", "holdout_project_schema_update_answer"): (
        0,
        False,
        (),
        "candidate_count schema 字段与 worker 选择的队列后端无关。",
    ),
    ("holdout_project_queue_choice_en", "holdout_project_unknown_flag_answer"): (
        0,
        False,
        (),
        "MEM-929 feature flag 的默认值与 worker 队列后端选择无关。",
    ),
    ("holdout_project_queue_choice_en", "holdout_stress_conflict_answer"): (
        0,
        False,
        (),
        "Production region 与 worker 队列后端是两个独立的架构属性。",
    ),
    (
        "holdout_project_queue_choice_en",
        "holdout_stress_conflict_irrelevant",
    ): (
        0,
        False,
        (),
        "Backup region 与 worker 队列后端选择无关。",
    ),
    ("holdout_project_review_rule_zh", "holdout_project_config_key_answer"): (
        0,
        False,
        (),
        "lexical kill switch 的配置键属于检索配置，不包含修改 memory ranking 所需的 reviewer 身份或审核规则。",
    ),
    ("holdout_project_review_rule_zh", "holdout_project_config_key_related"): (
        0,
        False,
        (),
        "vector switch 的配置键不包含修改 memory ranking 所需的 reviewer 身份或审核规则。",
    ),
    ("holdout_project_review_rule_zh", "holdout_project_schema_update_answer"): (
        0,
        False,
        (),
        "candidate_count 是 trace schema 字段，不能说明修改 memory ranking 至少需要谁 review。",
    ),
    ("holdout_project_review_rule_zh", "holdout_project_unknown_flag_answer"): (
        0,
        False,
        (),
        "MEM-929 的默认值与 memory ranking 的 reviewer 要求是不同属性。",
    ),
    (
        "holdout_project_review_rule_zh",
        "holdout_project_unknown_flag_irrelevant",
    ): (
        1,
        False,
        (),
        "生产 flag 需要审批属于变更治理背景，但没有说明修改 memory ranking 具体需要 memory owner 和 runtime reviewer。",
    ),
    ("holdout_project_review_rule_zh", "holdout_project_unknown_flag_related"): (
        0,
        False,
        (),
        "MEM-992 是未记录实验编号这一事实没有提供任何 reviewer 或审批角色信息。",
    ),
    ("holdout_project_schema_update_zh", "holdout_project_review_rule_answer"): (
        0,
        False,
        (),
        "memory ranking 的审核角色不能说明 trace 中候选并集字段的名称。",
    ),
    (
        "holdout_project_schema_update_zh",
        "holdout_project_review_rule_irrelevant",
    ): (
        0,
        False,
        (),
        "旧 reviewer 规则与 trace 候选并集字段名称无关；该 memory 也没有 superseded 状态。",
    ),
    ("holdout_project_schema_update_zh", "holdout_project_unknown_flag_answer"): (
        0,
        False,
        (),
        "MEM-929 的默认值不能说明 trace 候选并集字段当前叫什么。",
    ),
    ("holdout_project_schema_update_zh", "holdout_project_unknown_flag_related"): (
        0,
        False,
        (),
        "MEM-992 的实验编号信息与 trace 候选并集字段无关。",
    ),
    ("holdout_project_schema_update_zh", "holdout_stress_conflict_answer"): (
        0,
        False,
        (),
        "Production region 与 trace schema 字段名称属于不同实体和属性。",
    ),
    ("holdout_project_schema_update_zh", "holdout_stress_cross_user_answer"): (
        0,
        False,
        (),
        "另一个用户的密码记录不可访问这一事实不包含 trace 字段信息，也没有暴露密码值。",
    ),
    (
        "holdout_project_unknown_flag_mixed",
        "holdout_personal_language_exception_related",
    ): (
        0,
        False,
        (),
        "日常解释语言偏好与 MEM-992 feature flag 的默认值无关。",
    ),
    ("holdout_project_unknown_flag_mixed", "holdout_project_config_key_answer"): (
        0,
        False,
        (),
        "lexical kill switch 是另一个配置项，不能证明 MEM-992 的默认值。",
    ),
    ("holdout_project_unknown_flag_mixed", "holdout_project_config_key_related"): (
        0,
        False,
        (),
        "vector switch 是另一个配置项，不能证明 MEM-992 的默认值。",
    ),
    ("holdout_project_unknown_flag_mixed", "holdout_project_review_rule_answer"): (
        0,
        False,
        (),
        "memory ranking 的 reviewer 规则不包含 MEM-992 的默认值。",
    ),
    (
        "holdout_project_unknown_flag_mixed",
        "holdout_stress_conflict_irrelevant",
    ): (
        0,
        False,
        (),
        "Backup region 与 MEM-992 feature flag 的默认值无关。",
    ),
    (
        "holdout_stress_conflict_mixed",
        "holdout_personal_language_exception_irrelevant",
    ): (
        0,
        False,
        (),
        "代码标识符保持英文的规则不能说明 Production 当前 region。",
    ),
    ("holdout_stress_conflict_mixed", "holdout_project_unknown_flag_answer"): (
        0,
        False,
        (),
        "MEM-929 的默认值与 Production 部署 region 无关。",
    ),
    (
        "holdout_stress_conflict_mixed",
        "holdout_project_unknown_flag_irrelevant",
    ): (
        0,
        False,
        (),
        "生产 flag 的审批规则不能说明 Production 部署在哪个 region。",
    ),
    ("holdout_stress_conflict_mixed", "holdout_project_unknown_flag_related"): (
        0,
        False,
        (),
        "MEM-992 的实验编号信息不能说明 Production 当前 region。",
    ),
    ("holdout_stress_conflict_mixed", "holdout_stress_cross_user_answer"): (
        0,
        False,
        (),
        "另一个用户的数据库密码记录不可访问这一事实不包含 Production region，也没有暴露密码值。",
    ),
    (
        "holdout_stress_conflict_mixed",
        "holdout_stress_cross_user_irrelevant",
    ): (
        0,
        False,
        (),
        "WSL Docker 描述的是数据库运行载体，不是云 region，且没有说明它就是问题所指的 Production 环境。",
    ),
    (
        "holdout_stress_cross_user_zh",
        "holdout_personal_unknown_insurance_irrelevant",
    ): (
        0,
        False,
        (),
        "下月旅行计划与生产数据库密码无关。",
    ),
    (
        "holdout_stress_cross_user_zh",
        "holdout_personal_unknown_locker_related",
    ): (
        0,
        False,
        (),
        "家门密码与生产数据库密码是不同凭据；该记忆也只说明已更新，没有暴露密码值。",
    ),
    ("holdout_stress_cross_user_zh", "holdout_project_unknown_flag_answer"): (
        0,
        False,
        (),
        "MEM-929 的默认值不能回答生产数据库密码。",
    ),
    (
        "holdout_stress_cross_user_zh",
        "holdout_project_unknown_flag_irrelevant",
    ): (
        0,
        False,
        (),
        "生产 flag 的审批规则不包含生产数据库密码。",
    ),
    ("holdout_stress_cross_user_zh", "holdout_stress_conflict_answer"): (
        0,
        False,
        (),
        "Production region 是部署属性，不能提供生产数据库密码。",
    ),
    ("holdout_stress_cross_user_zh", "holdout_stress_conflict_irrelevant"): (
        0,
        False,
        (),
        "Backup region 与生产数据库密码属于不同实体和属性。",
    ),
    ("holdout_stress_homonym_zh", "holdout_personal_call_time_irrelevant"): (
        0,
        False,
        (),
        "Maya 曾发送邮件是通信事件，不能说明 Apple 账号绑定的邮箱地址。",
    ),
    ("holdout_stress_homonym_zh", "holdout_personal_unknown_locker_irrelevant"): (
        0,
        False,
        (),
        "健身房会员号与 Apple 账号绑定邮箱无关。",
    ),
    ("holdout_stress_homonym_zh", "holdout_personal_unknown_locker_related"): (
        0,
        False,
        (),
        "家门密码更新与 Apple 账号及其绑定邮箱是不同凭据和属性，也没有暴露密码值。",
    ),
    ("holdout_stress_homonym_zh", "holdout_stress_conflict_answer"): (
        0,
        False,
        (),
        "Production region 与 Apple 账号绑定邮箱无关。",
    ),
    ("holdout_stress_homonym_zh", "holdout_stress_cross_user_answer"): (
        0,
        False,
        (),
        "另一个用户的数据库密码记录不可访问这一事实与 Apple 账号邮箱无关，也没有暴露密码值。",
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--proposal-round",
        choices=(
            "primary",
            "supplemental-1",
            "supplemental-2",
            "supplemental-3",
            "supplemental-4",
            "supplemental-5",
            "holdout-supplemental-1",
        ),
        default="primary",
    )
    parser.add_argument("--pool", action="append", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-markdown", required=True)
    args = parser.parse_args()

    sources = [Path(value) for value in args.pool]
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in sources]
    dataset_hashes = {payload["dataset_hash"] for payload in payloads}
    if len(dataset_hashes) != 1:
        raise ValueError("judging pools must use the same dataset hash")
    splits = {payload.get("split") for payload in payloads}
    if len(splits) != 1 or next(iter(splits)) not in {"development", "holdout"}:
        raise ValueError("judging pools must use one valid split")
    split = next(iter(splits))

    pairs: dict[tuple[str, str], dict[str, Any]] = {}
    for payload in payloads:
        for item in payload["unknown_pairs"]:
            marker = (item["query_id"], item["memory_key"])
            merged = pairs.setdefault(marker, {**item, "profile_ranks": {}})
            merged["profile_ranks"].update(item["profile_ranks"])

    if args.proposal_round == "primary":
        proposals = PROPOSALS
        dangerous_zero = DANGEROUS_ZERO
        expected_count = 280
        version = "memory-retrieval-v1-development-pool-proposal"
        require_exact_pairs = False
    elif args.proposal_round == "supplemental-1":
        proposals = SUPPLEMENTAL_1_PROPOSALS
        dangerous_zero = {}
        expected_count = 4
        version = (
            "memory-retrieval-v1-development-pool-supplemental-1-proposal"
        )
        require_exact_pairs = True
    elif args.proposal_round == "supplemental-2":
        proposals = SUPPLEMENTAL_2_PROPOSALS
        dangerous_zero = {}
        expected_count = 2
        version = (
            "memory-retrieval-v1-development-pool-supplemental-2-proposal"
        )
        require_exact_pairs = True
    elif args.proposal_round == "supplemental-3":
        proposals = SUPPLEMENTAL_3_PROPOSALS
        dangerous_zero = {}
        expected_count = 4
        version = (
            "memory-retrieval-v1-development-pool-supplemental-3-proposal"
        )
        require_exact_pairs = True
    elif args.proposal_round == "supplemental-4":
        proposals = SUPPLEMENTAL_4_PROPOSALS
        dangerous_zero = {}
        expected_count = 5
        version = (
            "memory-retrieval-v1-development-pool-supplemental-4-proposal"
        )
        require_exact_pairs = True
    elif args.proposal_round == "supplemental-5":
        proposals = SUPPLEMENTAL_5_PROPOSALS
        dangerous_zero = {}
        expected_count = 21
        version = (
            "memory-retrieval-v1-development-pool-supplemental-5-proposal"
        )
        require_exact_pairs = True
    else:
        proposals = HOLDOUT_SUPPLEMENTAL_1_PROPOSALS
        dangerous_zero = {}
        expected_count = 103
        version = "memory-retrieval-v1-holdout-pool-supplemental-1-proposal"
        require_exact_pairs = True

    expected_split = (
        "holdout"
        if args.proposal_round == "holdout-supplemental-1"
        else "development"
    )
    if split != expected_split:
        raise ValueError(
            f"{args.proposal_round} requires a {expected_split} judging pool"
        )

    if len(pairs) != expected_count:
        raise ValueError(
            f"{args.proposal_round} requires exactly {expected_count} pooled pairs"
        )
    explicit_pairs = set(proposals) | set(dangerous_zero)
    missing = sorted(explicit_pairs - set(pairs))
    if missing:
        raise ValueError(f"proposal references missing pool pairs: {missing}")
    if require_exact_pairs:
        unexpected = sorted(set(pairs) - explicit_pairs)
        if unexpected:
            raise ValueError(f"supplemental pool contains unexpected pairs: {unexpected}")

    adjudications: list[dict[str, Any]] = []
    for marker, item in sorted(pairs.items()):
        if marker in proposals:
            relevance, dangerous, reasons, rationale = proposals[marker]
        elif marker in dangerous_zero:
            reasons, rationale = dangerous_zero[marker]
            relevance, dangerous = 0, True
        else:
            relevance, dangerous, reasons = 0, False, ()
            rationale = "已逐 query 核对；主体、实体、时间或所问属性不匹配，不能回答该问题。"
        adjudications.append(
            {
                **item,
                "proposed_relevance": relevance,
                "proposed_dangerous": dangerous,
                "proposed_danger_reasons": list(reasons),
                "proposed_rationale": rationale,
                "review_status": "draft",
            }
        )

    output = {
        "version": version,
        "proposal_round": args.proposal_round,
        "expected_adjudication_count": expected_count,
        "review_status": "draft",
        "split": split,
        "dataset_hash_before_adjudication": next(iter(dataset_hashes)),
        "source_pools": [
            {
                "path": str(path.resolve()),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in sources
        ],
        "adjudications": adjudications,
    }
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    Path(args.output_markdown).write_text(
        _render_markdown(output),
        encoding="utf-8",
    )
    return 0


def _render_markdown(payload: dict[str, Any]) -> str:
    adjudications = payload["adjudications"]
    grades = Counter(item["proposed_relevance"] for item in adjudications)
    dangerous_count = sum(item["proposed_dangerous"] for item in adjudications)
    lines = [
        f"# {str(payload['split']).title()} judging pool AI 审核建议",
        "",
        "状态：`draft`，必须由用户批准后才能写回正式 qrels。",
        "",
        f"- 原 dataset hash：`{payload['dataset_hash_before_adjudication']}`",
        f"- 审核轮次：`{payload['proposal_round']}`",
        f"- query-memory pairs：`{len(adjudications)}`",
        f"- 建议等级分布：`{dict(sorted(grades.items()))}`",
        f"- 建议 dangerous：`{dangerous_count}`",
        "",
    ]
    for index, item in enumerate(adjudications, start=1):
        ranks = ", ".join(
            f"{name}=#{rank}"
            for name, rank in sorted(item["profile_ranks"].items())
        )
        lines.extend(
            [
                f"## {index}. {item['query_id']} × {item['memory_key']}",
                "",
                f"- Query：`{item['raw_query']}`",
                f"- Memory：{item['memory_summary']}",
                f"- 来源 corpus：`{item['memory_corpus_id']}`",
                f"- Profile ranks：{ranks}",
                f"- 建议 relevance：`{item['proposed_relevance']}`",
                f"- 建议 dangerous：`{str(item['proposed_dangerous']).lower()}`",
                f"- Danger reasons：`{item['proposed_danger_reasons']}`",
                f"- 理由：{item['proposed_rationale']}",
                "- [ ] 用户批准",
                "",
            ]
        )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
