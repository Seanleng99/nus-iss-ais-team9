import re

EDUCATION_TOPIC_PHRASES: tuple[tuple[str, str], ...] = (
    ("market risk", "market risk"),
    ("市场风险", "market risk"),
    ("credit risk", "credit risk"),
    ("信用风险", "credit risk"),
    ("liquidity risk", "liquidity risk"),
    ("流动性风险", "liquidity risk"),
    ("currency risk", "currency risk"),
    ("汇率风险", "currency risk"),
    ("货币风险", "currency risk"),
    ("counterparty risk", "counterparty risk"),
    ("交易对手风险", "counterparty risk"),
    ("tracking error", "tracking error"),
    ("跟踪误差", "tracking error"),
    ("追踪误差", "tracking error"),
    ("diversification", "diversification"),
    ("分散投资", "diversification"),
    ("多元化", "diversification"),
    ("risk tolerance", "risk tolerance"),
    ("风险承受能力", "risk tolerance"),
    ("investment risk", "investment risk"),
    ("投资风险", "investment risk"),
    ("time horizon", "investment time horizon"),
    ("investment horizon", "investment time horizon"),
    ("投资期限", "investment time horizon"),
    ("investment readiness", "investment readiness"),
    ("投资准备", "investment readiness"),
    ("risk and return", "risk and return"),
    ("risk-return", "risk and return"),
    ("risk return", "risk and return"),
    ("风险与回报", "risk and return"),
    ("investment limits", "investment limits"),
    ("投资限制", "investment limits"),
    ("investment fees", "investment fees"),
    ("investment charges", "investment fees"),
    ("fees", "investment fees"),
    ("charges", "investment fees"),
    ("费用", "investment fees"),
    ("shares", "shares"),
    ("share", "shares"),
    ("stocks", "shares"),
    ("stock", "shares"),
    ("股票", "shares"),
    ("bonds", "bonds"),
    ("bond", "bonds"),
    ("债券", "bonds"),
    ("zero-coupon bonds", "zero-coupon bonds"),
    ("zero-coupon bond", "zero-coupon bonds"),
    ("zero coupon bond", "zero-coupon bonds"),
    ("零息债券", "zero-coupon bonds"),
    ("bond duration", "bond duration"),
    ("债券久期", "bond duration"),
    ("treasury bills", "treasury bills"),
    ("treasury bill", "treasury bills"),
    ("t-bills", "treasury bills"),
    ("t-bill", "treasury bills"),
    ("国库券", "treasury bills"),
    ("singapore savings bonds", "Singapore Savings Bonds"),
    ("ssbs", "Singapore Savings Bonds"),
    ("ssb", "Singapore Savings Bonds"),
    ("新加坡储蓄债券", "Singapore Savings Bonds"),
    ("dollar-cost averaging", "dollar-cost averaging"),
    ("dollar cost averaging", "dollar-cost averaging"),
    ("dca", "dollar-cost averaging"),
    ("定期定额", "dollar-cost averaging"),
    ("定投", "dollar-cost averaging"),
    ("unit trusts", "funds"),
    ("unit trust", "funds"),
    ("mutual funds", "funds"),
    ("mutual fund", "funds"),
    ("investment funds", "funds"),
    ("investment fund", "funds"),
    ("managed funds", "funds"),
    ("managed fund", "funds"),
    ("共同基金", "funds"),
    ("单位信托", "funds"),
    ("reits", "real estate investment trusts"),
    ("reit", "real estate investment trusts"),
    ("real estate investment trusts", "real estate investment trusts"),
    ("房地产投资信托", "real estate investment trusts"),
    ("exchange-traded funds", "exchange-traded funds"),
    ("exchange traded funds", "exchange-traded funds"),
    ("交易所交易基金", "exchange-traded funds"),
    ("交易所买卖基金", "exchange-traded funds"),
    ("etf", "exchange-traded funds"),
    ("etfs", "exchange-traded funds"),
    ("cpf investment", "CPF Investment Scheme"),
    ("cpfis", "CPF Investment Scheme"),
    ("公积金投资计划", "CPF Investment Scheme"),
)

# Canonical concepts preserve educational detail without embedding the user's
# amounts, identifiers, or unrestricted text in retrieval queries.
EDUCATION_DETAIL_PHRASES = (
    ("investment pooling", ("pool", "pooled", "汇集")),
    ("passive index tracking", ("passive", "index-tracking", "outperform", "被动", "跑赢指数", "指数追踪")),
    ("investment principal loss", ("lose all", "principal-guaranteed", "invested capital", "损失全部", "本金保证", "最坏")),
    ("capital gain or loss", ("capital gain", "capital gains", "capital loss", "资本收益", "资本损失")),
    ("dividends", ("dividend", "dividends", "股息")),
    ("brokerage commissions", ("brokerage", "commissions", "commission", "经纪佣金")),
    ("net asset value", ("net asset value", "nav", "净值")),
    ("tracking error", ("execution costs", "执行成本", "交易时点")),
    ("currency risk", ("foreign exchange", "base currency", "基础货币")),
    ("market makers liquidity", ("market maker", "market makers", "做市商")),
    ("traded price demand supply", ("trading price", "traded price", "交易价格")),
    ("securities lending", ("securities lending", "证券借贷")),
    ("cash-based physical ETFs", ("physical", "cash-based", "实物ETF", "现金型ETF")),
    ("synthetic ETFs derivatives swaps", ("synthetic etf", "synthetic etfs", "swap", "swaps", "合成ETF", "掉期")),
    ("correlation", ("correlation", "correlated", "相关性")),
    ("risk tolerance", ("risk appetite", "affordable losses", "想赚多少")),
    ("investment readiness emergency cash", ("emergency cash", "应急现金")),
    ("liquidity", ("liquidity", "流动性")),
    ("net returns fees", ("net returns", "net investment returns", "净回报")),
    ("investment income", ("investment income", "投资收入")),
    ("primary market", ("primary market", "一级市场")),
    ("secondary market", ("secondary market", "二级市场")),
    ("over-the-counter OTC", ("over-the-counter", "otc", "场外交易")),
    ("CPFIS-OA CPFIS-SA components", ("account components", "账户组成")),
    ("CPFIS-OA account", ("cpfis-oa",)),
    ("CPFIS-SA account", ("cpfis-sa",)),
    ("CPFIS eligibility Self-Awareness Questionnaire", ("eligibility", "self-awareness", "saq", "资格条件", "自我认知问卷")),
    ("CPF Investment Account", ("investment account", "投资账户")),
    ("CPFIS Ordinary Account reserve", ("oa reserve", "保留多少")),
    ("CPFIS stocks gold investment limits", ("stock and gold", "股票和黄金", "投资比例限制")),
    ("total expense ratio", ("total expense ratio", "总费用率")),
    ("Singapore Savings Bonds redemption", ("redemption", "redeem", "赎回")),
    ("Singapore Government Securities SGS coupons", ("sgs", "government securities", "新加坡政府证券")),
)

GENERIC_EDUCATION_TOPIC_PHRASES = (
    "investing",
    "investment",
    "invest",
    "投资",
)

GENERIC_EDUCATION_QUESTION = re.compile(
    r"(?:\b(?:please|explain|teach|tell|me|i|want|would|like|to|learn|understand|"
    r"what|is|are|how|can|should|do|you|start|with|the|a|an|of|in|for|about|"
    r"basic|basics|beginner|beginners|general|simple|terms|introduction|education|"
    r"financial|investment|investments|investing|invest)\b|"
    r"请问|请|用|简单|中文|英文|解释|介绍|一下|什么|是|如何|开始|了解|学习|"
    r"投资|入门|基础|知识|我|想|要|[\s,.?!，。？！、])+"
)

UNSUPPORTED_EDUCATION_TOPIC_PHRASES = (
    ("tax", "tax treatment"), ("taxes", "tax treatment"),
    ("taxation", "tax treatment"), ("税", "tax treatment"),
    ("tokenized", "tokenized assets"), ("tokenised", "tokenized assets"),
    ("代币化", "tokenized assets"), ("crypto", "crypto assets"),
    ("cryptocurrency", "crypto assets"), ("加密货币", "crypto assets"),
    ("options trading", "options trading"), ("call options", "options trading"),
    ("put options", "options trading"), ("期权", "options trading"),
)

DETAILED_EDUCATION_TOPICS = {
    "bond duration", "zero-coupon bonds", "treasury bills",
    "Singapore Savings Bonds", "dollar-cost averaging",
}


def unsupported_education_topics(message: str) -> list[str]:
    return list(dict.fromkeys(
        topic for phrase, topic in UNSUPPORTED_EDUCATION_TOPIC_PHRASES
        if _contains_phrase(message.casefold(), phrase)
    ))


def education_question_intent(message: str) -> str:
    for phrases, intent in (
        (("compare", "difference", "比较", "区别"), "comparison"),
        (("why", "为什么"), "reason"),
        (("how", "如何", "怎样"), "mechanism"),
    ):
        if any(_contains_phrase(message.casefold(), phrase) for phrase in phrases):
            return intent
    return "explanation"


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= character <= "\u9fff" for character in text)


def _contains_phrase(normalized: str, phrase: str) -> bool:
    phrase = phrase.casefold()
    if _contains_cjk(phrase):
        return phrase in normalized
    return bool(
        re.search(rf"(?<![A-Za-z0-9_]){re.escape(phrase)}(?![A-Za-z0-9_])", normalized)
    )


def education_topics(message: str) -> list[str]:
    normalized = message.casefold()
    normalized = re.sub(r"\bcapital gains? tax(?:ation)?\b|资本(?:利得|收益)税", "", normalized)
    broad_text = normalized
    for phrase, topic in EDUCATION_TOPIC_PHRASES:
        if topic in {"bond duration", "zero-coupon bonds", "Singapore Savings Bonds"}:
            broad_text = broad_text.replace(phrase, " ")
    topics: list[str] = []
    for phrase, topic in EDUCATION_TOPIC_PHRASES:
        text = broad_text if topic == "bonds" else normalized
        if _contains_phrase(text, phrase) and topic not in topics:
            topics.append(topic)
    for topic, phrases in EDUCATION_DETAIL_PHRASES:
        if any(_contains_phrase(normalized, phrase) for phrase in phrases) and topic not in topics:
            if topic == "investment readiness emergency cash" and not any(
                _contains_phrase(normalized, phrase) for phrase in GENERIC_EDUCATION_TOPIC_PHRASES
            ):
                continue
            # Avoid adding a broader liquidity topic when liquidity risk was explicit.
            if topic == "liquidity" and "liquidity risk" in topics:
                continue
            topics.append(topic)
    if not topics and any(
        _contains_phrase(normalized, phrase)
        for phrase in GENERIC_EDUCATION_TOPIC_PHRASES
    ) and GENERIC_EDUCATION_QUESTION.fullmatch(normalized) and not unsupported_education_topics(message):
        topics.append("investment basics")
    return topics


def missing_education_topics(topics: list[str], contexts: list[dict]) -> list[str]:
    # Fine-grained concepts must appear in accepted evidence, not just a broad bond primer.
    evidenced = {topic for context in contexts for topic in education_topics(context["text"])}
    return [topic for topic in topics if topic in DETAILED_EDUCATION_TOPICS - evidenced]


def apply_education_scope(grounding: dict, message: str, topics: list[str]) -> None:
    missing_topics = missing_education_topics(topics, grounding["contexts"])
    grounding["query_topics"] = list(topics)
    grounding["unanswered_topics"] = list(dict.fromkeys(
        unsupported_education_topics(message) + missing_topics
    ))
    grounding["question_intent"] = education_question_intent(message)
    grounding["response_language"] = education_response_language(message)
    if missing_topics and set(topics).issubset(missing_topics):
        grounding["contexts"] = []
        grounding["sources"] = []
        grounding["evidence_status"] = "insufficient"
    elif grounding["contexts"] and grounding["unanswered_topics"]:
        grounding["evidence_status"] = "partial"


def education_gap_message(grounding: dict) -> str:
    topics = grounding.get("unanswered_topics", [])
    if grounding.get("response_language") == "Chinese":
        message = "经批准的知识库没有足够资料回答这个问题。"
        return message + ("未覆盖的主题：" + "、".join(topics) + "。" if topics else "")
    message = "The approved knowledge base does not contain enough information to answer this question."
    return message + (" Uncovered topics: " + ", ".join(topics) + "." if topics else "")


def education_response_language(message: str) -> str:
    return "Chinese" if _contains_cjk(message) else "English"


def should_request_education_context(message: str) -> bool:
    return bool(education_topics(message))


def build_minimal_education_query(message: str) -> tuple[str, list[str]]:
    topics = education_topics(message)
    if not topics:
        raise ValueError("No allowlisted education topic was identified.")
    return f"General investment education about {', '.join(topics)}", topics
