"""
L3 长期记忆 —— 用户画像自动沉淀（独立 md 文件，不修改 my_profile.yaml）。

设计：
- 与 my_profile.yaml 分工：yaml 是用户手写的权威核心画像；本文件是聊天过程中
  由 LLM 自动提炼、增量沉淀的用户画像（技能 / 学习状态 / 偏好禁忌）。
- 两者在对话时合并注入 system prompt，互不污染。
- 写入策略：仅追加去重，绝不删除已有项；md 格式天然可读、可 Git 跟踪。
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

LONGTERM_PATH = Path(__file__).parent / "long_term_memory.md"

_SECTION_KEYS = {
    "have": "已掌握技能 (have)",
    "learning": "学习中 (learning)",
    "avoid": "偏好 / 禁忌 (avoid)",
}


def load_longterm_md() -> str:
    """读取长期记忆 md 全文；不存在返回空串。"""
    if not LONGTERM_PATH.exists():
        return ""
    try:
        return LONGTERM_PATH.read_text(encoding="utf-8").strip()
    except Exception as e:
        logger.warning(f"[LongTermMemory] 读取失败: {e}")
        return ""


def _parse_sections(md: str) -> dict[str, list[str]]:
    """解析 md 为 {have:[], learning:[], avoid:[]}。"""
    result: dict[str, list[str]] = {k: [] for k in _SECTION_KEYS}
    current = None
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("## "):
            title = s[3:].strip()
            low = title.lower()
            if "have" in low or "已掌握" in title:
                current = "have"
            elif "learning" in low or "学习中" in title:
                current = "learning"
            elif "avoid" in low or "偏好" in title or "禁忌" in title:
                current = "avoid"
            else:
                current = None
            continue
        if current and s.startswith("- "):
            item = s[2:].strip()
            if item and item not in result[current]:
                result[current].append(item)
    return result


def _render_md(sections: dict[str, list[str]]) -> str:
    lines = ["# 用户长期记忆（自动沉淀，由对话学习，请勿手改）", ""]
    for key, title in _SECTION_KEYS.items():
        lines.append(f"## {title}")
        for item in sections[key]:
            lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def extract_profile_delta(user_msg: str, assistant_reply: str) -> dict | None:
    """用 LLM 从一轮对话中提炼用户画像增量。失败返回 None。"""
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from src.agent.nodes import _extract_json, _llm

        prompt = (
            "你是用户画像提取器。下面是求职助手与用户的一段对话。"
            "请从中提取用户明确透露的、可沉淀为长期记忆的信息，只输出 JSON：\n"
            "{\n"
            '  "add_to_have": [用户已掌握或熟练的技能/领域],\n'
            '  "add_to_learning": [用户正在学习或想学的技能/领域],\n'
            '  "add_to_avoid": [用户明确表达不想要的工作类型/方向/禁忌]\n'
            "}\n"
            "规则：只提取用户明确说出的信号，不要猜测、不要编造；"
            "若没有新信息，三项均返回空数组。"
        )
        user_block = f"【用户发言】\n{user_msg}\n\n【助手回复】\n{assistant_reply[:1500]}"
        resp = _llm().invoke([
            SystemMessage(content=prompt),
            HumanMessage(content=user_block),
        ])
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        data = _extract_json(text)
        return {
            "have": [str(x).strip() for x in (data.get("add_to_have") or []) if str(x).strip()],
            "learning": [str(x).strip() for x in (data.get("add_to_learning") or []) if str(x).strip()],
            "avoid": [str(x).strip() for x in (data.get("add_to_avoid") or []) if str(x).strip()],
        }
    except Exception as e:
        logger.warning(f"[LongTermMemory] 提炼画像失败: {e}")
        return None


def update_longterm_md(delta: dict) -> bool:
    """合并 delta 到 md（追加去重）。返回是否发生变化。"""
    if not delta:
        return False
    existing = _parse_sections(load_longterm_md())
    changed = False
    for key in ("have", "learning", "avoid"):
        items = delta.get(key) or []
        # 大小写不敏感去重，但保留首次写入时的原写法
        lower_existing = {x.lower() for x in existing[key]}
        for it in items:
            if it.lower() not in lower_existing:
                existing[key].append(it)
                lower_existing.add(it.lower())
                changed = True
    if changed:
        try:
            LONGTERM_PATH.write_text(_render_md(existing), encoding="utf-8")
            logger.info("[LongTermMemory] 已更新长期记忆 md")
        except Exception as e:
            logger.warning(f"[LongTermMemory] 写入 md 失败: {e}")
            return False
    return changed


def upsert_longterm_async(user_msg: str, assistant_reply: str) -> None:
    """异步提炼并写回（供对话后调用，不阻塞回复）。"""
    try:
        delta = extract_profile_delta(user_msg, assistant_reply)
        if delta:
            update_longterm_md(delta)
    except Exception as e:
        logger.warning(f"[LongTermMemory] 异步沉淀失败: {e}")
