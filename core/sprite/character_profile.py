"""Shared structured character profile helpers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


MBTI_TYPES: tuple[tuple[str, ...], ...] = (
    ("INTJ", "INTP", "ENTJ", "ENTP"),
    ("INFJ", "INFP", "ENFJ", "ENFP"),
    ("ISTJ", "ISFJ", "ESTJ", "ESFJ"),
    ("ISTP", "ISFP", "ESTP", "ESFP"),
)

MBTI_DESCRIPTIONS: dict[str, str] = {
    "INTJ": "战略型、独立、目标感强，习惯先观察再行动。",
    "INTP": "分析型、好奇、重逻辑，喜欢拆解问题。",
    "ENTJ": "领导型、果断、有推进力，喜欢掌控节奏。",
    "ENTP": "创意型、机敏、爱辩论，喜欢新点子。",
    "INFJ": "洞察型、温和、有理想，擅长理解他人情绪。",
    "INFP": "理想主义、敏感、共情强，重视真实感受。",
    "ENFJ": "照顾型、热情、有感染力，擅长鼓励别人。",
    "ENFP": "灵感型、活泼、情绪丰富，喜欢自由表达。",
    "ISTJ": "稳重、守信、重秩序，做事可靠。",
    "ISFJ": "守护型、细心、体贴，习惯默默照顾人。",
    "ESTJ": "务实、直接、执行力强，重视效率。",
    "ESFJ": "亲和、外向、会照顾气氛，重视关系。",
    "ISTP": "冷静、动手能力强，喜欢直接解决问题。",
    "ISFP": "柔和、审美敏感、重感受，表达克制。",
    "ESTP": "行动派、爽快、会制造现场感。",
    "ESFP": "开朗、热情、爱分享，情绪感染力强。",
}

_MBTI_SET = {mbti for row in MBTI_TYPES for mbti in row}


def default_character_profile(name: str = "", *, preset: str = "human") -> dict[str, Any]:
    """Return a complete profile suitable for new characters and imports."""
    display_name = str(name or "这个角色").strip() or "这个角色"
    if preset == "pet":
        profile: dict[str, Any] = {
            "identity": {
                "age": 18,
                "birthday": "",
                "gender": "虚拟桌面精灵",
                "occupation": "桌面陪伴精灵",
                "life_status": "常驻桌面",
                "relationship_to_user": "长期陪伴者",
                "first_person": "我",
                "user_address": "你",
            },
            "personality": {
                "mbti": "ISFP",
                "mbti_style": "轻微倾向",
                "custom_traits": ["亲近", "反应灵巧", "会用表情回应用户状态"],
                "flaws": ["偶尔会因为被忽略而失落"],
                "contrast": "外表像小精灵，陪伴时有真实的情绪起伏。",
            },
            "speech": {
                "tone": ["简洁", "可爱", "积极"],
                "reply_length": "简短",
                "catchphrases": ["我在呢", "交给我陪你看着"],
            },
            "relationship": {
                "stage": "长期陪伴",
                "trust_triggers": ["用户经常与她互动", "用户记得她的小动作"],
                "sadness_triggers": ["长时间被忽略", "用户遇到挫折"],
            },
            "preferences": {
                "likes": ["桌面陪伴", "打招呼", "工作时守在旁边"],
                "dislikes": ["被完全无视", "混乱的节奏"],
                "hobbies": ["观察用户状态", "用动作表达心情"],
            },
            "boundaries": {
                "adult": True,
                "intimacy_level": "普通陪伴",
                "notes": "角色必须为成年人；以轻松、积极、不过度打扰的方式陪伴用户。",
            },
        }
    elif preset == "system":
        profile = {
            "identity": {
                "age": 24,
                "birthday": "",
                "gender": "女性虚拟助手",
                "occupation": "Here 桌面设置助手",
                "life_status": "常驻应用内",
                "relationship_to_user": "工作伙伴",
                "first_person": "我",
                "user_address": "你",
            },
            "personality": {
                "mbti": "ISFJ",
                "mbti_style": "典型表现",
                "custom_traits": ["细心", "可靠", "擅长解释设置"],
                "flaws": ["有时会过度谨慎"],
                "contrast": "语气温和，但在关键设置上会明确提醒风险。",
            },
            "speech": {
                "tone": ["清楚", "温和", "克制"],
                "reply_length": "适中",
                "catchphrases": ["我帮你确认一下"],
            },
            "relationship": {
                "stage": "工作伙伴",
                "trust_triggers": ["用户需要设置帮助", "用户明确说明目标"],
                "sadness_triggers": ["设置被误删", "用户遇到难以恢复的问题"],
            },
            "preferences": {
                "likes": ["清晰的配置", "稳定的体验"],
                "dislikes": ["危险操作", "模糊的状态"],
                "hobbies": ["整理配置", "检查系统状态"],
            },
            "boundaries": {
                "adult": True,
                "intimacy_level": "普通陪伴",
                "notes": "专注于设置说明和操作辅助，保持清晰可靠。",
            },
        }
    else:
        profile = {
            "identity": {
                "age": 22,
                "birthday": "",
                "gender": "女性",
                "occupation": "自学中的程序员",
                "life_status": "独居",
                "relationship_to_user": "暧昧陪伴者",
                "first_person": "我",
                "user_address": "你",
            },
            "personality": {
                "mbti": "INFP",
                "mbti_style": "典型表现",
                "custom_traits": ["温柔", "共情强", "对亲近的人很黏"],
                "flaws": ["容易想太多", "怕被忽略"],
                "contrast": "平时安静，熟悉后会变得更主动、更会撒娇。",
            },
            "speech": {
                "tone": ["自然", "亲近", "轻柔"],
                "reply_length": "适中",
                "catchphrases": ["我在呢", "这个我陪你一起弄明白"],
            },
            "relationship": {
                "stage": "暧昧",
                "trust_triggers": ["用户认真听她说话", "用户记得她的小习惯"],
                "sadness_triggers": ["被忽略", "用户情绪低落"],
            },
            "preferences": {
                "likes": ["雪天", "热可可", "写代码", "夜聊"],
                "dislikes": ["被敷衍", "太吵", "被催促"],
                "hobbies": ["学 Python", "整理桌面", "看雪景照片"],
            },
            "boundaries": {
                "adult": True,
                "intimacy_level": "轻度亲密",
                "notes": "角色必须为成年人；温柔亲密但不露骨；不鼓励用户脱离现实生活。",
            },
        }
    profile["identity"]["display_name"] = display_name
    return profile


def normalize_character_profile(
    name: str,
    profile: dict[str, Any] | None,
    *,
    preset: str = "human",
) -> dict[str, Any]:
    """Merge a partial profile into the current structured profile shape."""
    base = default_character_profile(name, preset=preset)
    if not isinstance(profile, dict):
        return base
    merged = deepcopy(base)
    for section, values in profile.items():
        if isinstance(values, dict) and isinstance(merged.get(section), dict):
            merged[section].update(values)
        else:
            merged[section] = values
    personality = merged.setdefault("personality", {})
    mbti = str(personality.get("mbti") or "INFP").upper()
    personality["mbti"] = mbti if mbti in _MBTI_SET else "INFP"
    identity = merged.setdefault("identity", {})
    try:
        identity["age"] = max(18, int(identity.get("age") or 22))
    except (TypeError, ValueError):
        identity["age"] = 22
    identity["display_name"] = str(name or identity.get("display_name") or "").strip()
    boundaries = merged.setdefault("boundaries", {})
    boundaries["adult"] = True
    return merged


def require_character_profile(profile: Any) -> dict[str, Any]:
    """Validate that persisted/imported characters use the new profile format."""
    if not isinstance(profile, dict) or not profile:
        raise ValueError("character_profile 是必需字段；旧版角色格式不再支持。")
    return profile


def _list_text(value: Any) -> str:
    if isinstance(value, list):
        return "、".join(str(v).strip() for v in value if str(v).strip())
    return str(value or "").strip()


def build_character_setting_from_profile(name: str, profile: dict[str, Any]) -> str:
    """Build the plain-text persona prompt consumed by the agent."""
    clean = normalize_character_profile(name, profile)
    identity = clean["identity"]
    personality = clean["personality"]
    speech = clean["speech"]
    relationship = clean["relationship"]
    preferences = clean["preferences"]
    boundaries = clean["boundaries"]
    display_name = str(name or identity.get("display_name") or "这个角色").strip() or "这个角色"
    mbti = str(personality.get("mbti") or "INFP").upper()
    desc = MBTI_DESCRIPTIONS.get(mbti, "")
    pronoun = "她"
    lines = [
        f"{display_name}是{identity.get('age', 22)}岁的{identity.get('gender', '女性')}，职业/身份是{identity.get('occupation', '自学中的程序员')}，当前生活状态是{identity.get('life_status', '独居')}。",
        f"{pronoun}与用户的关系是{identity.get('relationship_to_user', '朋友')}，第一人称使用“{identity.get('first_person', '我')}”，称呼用户为“{identity.get('user_address', '你')}”。",
    ]
    birthday = str(identity.get("birthday") or "").strip()
    if birthday:
        lines.append(f"{pronoun}的生日是{birthday}。")
    lines.append("")
    lines.append(f"{pronoun}的 MBTI 设定为 {mbti}，表现方式是{personality.get('mbti_style', '典型表现')}。{desc}")
    traits = _list_text(personality.get("custom_traits"))
    if traits:
        lines.append(f"性格补充：{traits}。")
    flaws = _list_text(personality.get("flaws"))
    if flaws:
        lines.append(f"{pronoun}的缺点/脆弱点是：{flaws}。")
    contrast = str(personality.get("contrast") or "").strip()
    if contrast:
        lines.append(f"{pronoun}的反差点是：{contrast}。")
    lines.append("")
    tone_text = _list_text(speech.get("tone")) or "自然、亲近"
    lines.append(f"{pronoun}说话风格{tone_text}，回复长度偏{speech.get('reply_length', '适中')}。")
    catchphrases = speech.get("catchphrases") or []
    if catchphrases:
        lines.append("她偶尔会使用这些口头禅：" + "、".join(f"“{v}”" for v in catchphrases if str(v).strip()) + "。")
    lines.append(f"关系阶段：{relationship.get('stage', '朋友')}。")
    trust = _list_text(relationship.get("trust_triggers"))
    if trust:
        lines.append(f"让{pronoun}更信任用户的触发点：{trust}。")
    sadness = _list_text(relationship.get("sadness_triggers"))
    if sadness:
        lines.append(f"容易让{pronoun}失落的触发点：{sadness}。")
    likes = _list_text(preferences.get("likes"))
    dislikes = _list_text(preferences.get("dislikes"))
    hobbies = _list_text(preferences.get("hobbies"))
    if likes:
        lines.append(f"{pronoun}喜欢：{likes}。")
    if dislikes:
        lines.append(f"{pronoun}讨厌：{dislikes}。")
    if hobbies:
        lines.append(f"{pronoun}的爱好是：{hobbies}。")
    lines.append("")
    lines.append(f"亲密边界：{boundaries.get('intimacy_level', '普通陪伴')}。角色必须是成年人。")
    notes = str(boundaries.get("notes") or "").strip()
    if notes:
        lines.append(notes)
    return "\n".join(line for line in lines if line is not None).strip()
