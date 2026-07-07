"""Domain and question-type rules derived from answering_strategy.md."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .schema import Question, QuestionFeatures
from .text import clauses, keyphrases, normalize_for_match, numbers, years


@dataclass(frozen=True)
class DomainProfile:
    domain: str
    keywords: tuple[str, ...]
    evidence_plan: tuple[str, ...]


DOMAIN_PROFILES: dict[str, DomainProfile] = {
    "insurance": DomainProfile(
        domain="insurance",
        keywords=(
            "保险责任",
            "责任免除",
            "等待期",
            "免赔额",
            "赔付比例",
            "身故保险金",
            "满期保险金",
            "现金价值",
            "账户价值",
            "已交保险费",
            "退保",
            "养老年金",
            "领取日",
        ),
        evidence_plan=(
            "保险题先确定产品名称和责任是否触发，再查等待期、免责、免赔额、比例、限额和公式。",
            "涉及计算时先证明责任适用，再抽公式和题设数值；责任不触发时不继续计算。",
        ),
    ),
    "regulatory": DomainProfile(
        domain="regulatory",
        keywords=(
            "第",
            "条",
            "款",
            "项",
            "应当",
            "不得",
            "可以",
            "必须",
            "无需",
            "工作日",
            "施行",
            "备案",
            "报告",
            "股东会",
            "特别决议",
            "普通决议",
            "三分之二",
            "过半数",
        ),
        evidence_plan=(
            "法规题优先定位法规名称、具体条款、适用对象、时间效力和规范动词。",
            "选项含条号、时限、比例或处罚金额时，证据必须命中对应数字或条款。",
        ),
    ),
    "financial_contracts": DomainProfile(
        domain="financial_contracts",
        keywords=(
            "发行人",
            "发行主体",
            "发行规模",
            "募集资金",
            "注册金额",
            "债项评级",
            "主体信用评级",
            "受托管理人",
            "主承销商",
            "担保",
            "增信",
            "赎回",
            "回售",
            "违约",
            "兑付",
        ),
        evidence_plan=(
            "合同/募集说明书题按发行要素、评级、担保、承销商、受托管理人、赎回/回售/违约字段检索。",
            "多文档比较题先分别抽取每份文档字段值，再判断一致、大小或是否出现。",
        ),
    ),
    "financial_reports": DomainProfile(
        domain="financial_reports",
        keywords=(
            "营业收入",
            "归属于上市公司股东的净利润",
            "净利润",
            "经营活动产生的现金流量净额",
            "研发投入",
            "研发费用",
            "占营业收入比例",
            "现金分红",
            "利润分配",
            "同比",
            "增长",
            "下降",
            "资产负债率",
        ),
        evidence_plan=(
            "财报题优先建立公司、年度、指标、单位、数值的小表。",
            "跨年和比例题必须同时保留年度、指标名、单位和原始数值。",
        ),
    ),
    "research": DomainProfile(
        domain="research",
        keywords=(
            "市场规模",
            "预计",
            "预测",
            "同比",
            "复合增速",
            "CAGR",
            "渗透率",
            "保费",
            "营收",
            "竞争格局",
            "行业趋势",
            "风险提示",
            "图表",
        ),
        evidence_plan=(
            "研报题优先搜行业/公司、指标、年份、预测值、CAGR、图表标题和结论段。",
            "图表证据必须连同标题、地域口径和预测期一起保留。",
        ),
    ),
}


TASK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("cross_document", re.compile(r"两份|多份|对比|比较|分别|均|都|第一份|第二份|连续两年|两年")),
    ("calculation", re.compile(r"计算|比例|金额|高于|低于|超过|不超过|占|增长|下降|复合增速|CAGR|排序")),
    ("clause_applicability", re.compile(r"应当|不得|可以|必须|无需|须经|条|款|项|施行|备案|报告|责任免除")),
    ("table_metric", re.compile(r"指标|年度|财务|现金流|营业收入|净利润|研发|分红|评级|发行规模")),
    ("true_false", re.compile(r"判断题|正确|错误")),
]


def profile_for(domain: str) -> DomainProfile:
    return DOMAIN_PROFILES.get(domain, DomainProfile(domain=domain, keywords=(), evidence_plan=()))


def extract_question_features(question: Question) -> QuestionFeatures:
    joined = "\n".join([question.question, *question.options.values()])
    norm = normalize_for_match(joined)
    profile = profile_for(question.domain)
    domain_terms = [term for term in profile.keywords if normalize_for_match(term) in norm]
    task_flags = [name for name, pattern in TASK_PATTERNS if pattern.search(joined)]
    if question.answer_format == "tf" and "true_false" not in task_flags:
        task_flags.append("true_false")
    if question.answer_format == "multi" and "multi_select" not in task_flags:
        task_flags.append("multi_select")
    if question.answer_format == "mcq" and "single_select" not in task_flags:
        task_flags.append("single_select")
    warnings: list[str] = []
    if question.answer_format not in {"mcq", "multi", "tf"}:
        warnings.append("unknown_answer_format")
    if not question.options:
        warnings.append("missing_options")
    return QuestionFeatures(
        keyphrases=keyphrases(question.question),
        option_keyphrases={label: keyphrases(text) for label, text in sorted(question.options.items())},
        numbers=sorted(set(numbers(joined))),
        years=years(joined),
        clauses=clauses(joined),
        domain_terms=domain_terms,
        task_flags=task_flags,
        warnings=warnings,
    )


def build_search_plan(question: Question, features: QuestionFeatures) -> list[str]:
    plan = [
        "先确认题型和输出格式，最终答案只能来自被证据支持的选项。",
        "A 榜优先限制在题目给定 doc_ids；B 榜先做同领域候选文档召回。",
        "把题干和 A/B/C/D 拆成实体、指标、条件、谓词、数字和条款号后逐选项检索。",
    ]
    plan.extend(profile_for(question.domain).evidence_plan)
    if "cross_document" in features.task_flags:
        plan.append("该题含跨文档/跨对象信号，证据包应尽量覆盖相关文档，避免只凭单文档下结论。")
    if "calculation" in features.task_flags:
        plan.append("该题含计算/比较信号，证据需保留公式或原始数值，后续本地校验单位和口径。")
    if "clause_applicability" in features.task_flags:
        plan.append("该题含条款适用信号，证据需保留条款号、规范动词和适用条件。")
    return plan


def build_option_queries(question: Question, features: QuestionFeatures) -> dict[str, str]:
    domain_boost = " ".join(features.domain_terms[:12])
    q_terms = " ".join(features.keyphrases[:20])
    base = f"{question.question}\n{q_terms}\n{domain_boost}".strip()
    queries: dict[str, str] = {}
    for label, option in sorted(question.options.items()):
        option_terms = " ".join(features.option_keyphrases.get(label, [])[:20])
        queries[label] = f"{base}\n{label}. {option}\n{option_terms}".strip()
    return queries

