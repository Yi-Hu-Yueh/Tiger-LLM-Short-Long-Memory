"""Frozen synthetic V2-1A development and holdout oracles.

These domains are evaluation data only and never become production rules.
"""

from __future__ import annotations

from dataclasses import dataclass

from memory_v2_semantic.semantic_models import Intent, ReasonCode, ScalarCandidate, TemporalRelation


@dataclass(frozen=True)
class Case:
    case_id: str
    category: str
    message: str
    candidates: tuple[ScalarCandidate, ...]
    intent: Intent
    target_id: str | None = None
    literal: str | None = None
    temporal: TemporalRelation = TemporalRelation.NONE
    reason: ReasonCode = ReasonCode.NONE
    critical: bool = False


DEVELOPMENT_DOMAINS = (
    ("望遠鏡", "鏡片鍍膜", "透明", "防眩光"),
    ("溫室", "濕度模式", "手動", "自動"),
    ("無人機", "韌體通道", "穩定版", "測試版"),
    ("倉庫貨架", "標籤", "A17", "B20"),
    ("相機", "鏡頭接環", "E接環", "L接環"),
    ("路由器", "協定模式", "IPv4", "IPv6"),
    ("水族箱", "溫度設定", "冷水", "溫水"),
    ("發電機", "燃料模式", "柴油", "天然氣"),
    ("鍵盤", "佈局", "QWERTY", "Dvorak"),
    ("船舶", "航行模式", "手動", "自動"),
    ("風扇", "速度檔位", "低速", "高速"),
    ("感測器", "取樣頻率", "十赫茲", "二十赫茲"),
    ("伺服器", "備援模式", "主動", "被動"),
    ("投影機", "解析度", "高清", "超高清"),
    ("太陽能板", "傾角", "十五度", "三十度"),
    ("電梯", "運行模式", "普通", "節能"),
    ("農場", "灌溉模式", "滴灌", "噴灌"),
    ("橋梁", "監測頻率", "每天", "每小時"),
    ("地圖", "圖層樣式", "地形", "衛星"),
    ("火車月台", "代碼", "C2", "D4"),
    ("收音機", "頻道", "FM88", "FM92"),
    ("氣象站", "風速單位", "節", "公尺每秒"),
    ("機器臂", "夾具模式", "柔性", "剛性"),
    ("烘箱", "溫度檔", "低溫", "高溫"),
    ("導航儀", "座標格式", "十進位", "度分秒"),
    ("警報器", "音量", "安靜", "響亮"),
    ("窗簾", "開合模式", "半開", "全開"),
    ("儲水槽", "水位警戒", "中等", "偏高"),
    ("天線", "極化方向", "水平", "垂直"),
    ("照明設備", "亮度", "柔和", "明亮"),
)


HOLDOUT_DOMAINS = (
    ("潮汐儀", "顯示單位", "英尺", "公尺"),
    ("冷凍櫃", "除霜模式", "手動", "自動"),
    ("軌道探測器", "訊號頻帶", "窄頻", "寬頻"),
    ("纜車", "運轉速度", "慢速", "快速"),
    ("地震儀", "校準狀態", "待校準", "已校準"),
    ("養蜂箱", "通風模式", "關閉", "開啟"),
    ("光譜儀", "掃描模式", "連續", "分段"),
    ("浮標", "電池模式", "省電", "標準"),
    ("隧道感測站", "回報週期", "每小時", "每分鐘"),
    ("考古標本盒", "封存狀態", "開放", "密封"),
)


def _candidate(index: int, entity: str, property_name: str, current: str,
               *, holdout: bool = False, suffix: str = "a") -> ScalarCandidate:
    tag = "h" if holdout else "d"
    return ScalarCandidate(
        memory_id=f"mem-{tag}-{index:02d}-{suffix}",
        entity_id=f"entity-{tag}-{index:02d}-{suffix}",
        entity_name=entity,
        semantic_key=f"synthetic.scalar.{tag}.{index:02d}",
        display_label=property_name,
        current_value=current,
    )


def development_cases() -> tuple[Case, ...]:
    cases: list[Case] = []
    for i, (entity, prop, old, new) in enumerate(DEVELOPMENT_DOMAINS):
        named = f"東區{entity}"
        other = f"西區{entity}"
        candidate = _candidate(i, named, prop, old)
        catalog = (candidate,)
        assertion = (
            f"{named}的{prop}是{new}。",
            f"記錄一下，{named}的{prop}現在為{new}。",
            f"目前{named}採用的{prop}：{new}。",
        )[i % 3]
        current = (
            f"{named}目前的{prop}是什麼？",
            f"請問{named}現行{prop}為何？",
            f"現在{named}用哪個{prop}？",
        )[i % 3]
        correction = (
            f"{named}的{prop}改成{new}了。",
            f"修正一下，{named}的{prop}應為{new}。",
            f"{named}現在改用{new}作為{prop}。",
        )[i % 3]
        reassert = (
            f"{named}的{prop}仍然是{old}。",
            f"確認一下，{named}的{prop}沒有變，還是{old}。",
            f"{named}繼續使用{old}這個{prop}。",
        )[i % 3]
        previous = (
            f"{named}的{prop}先前是什麼？",
            f"請查{named}的{prop}上一個值。",
            f"在目前設定之前，{named}的{prop}為何？",
        )[i % 3]
        unknown = f"{other}的{prop}現在是什麼？"
        prefix = f"D{i:02d}"
        cases.extend((
            Case(prefix + "-NEW", "new_assertion", assertion, (), Intent.UNSUPPORTED,
                 literal=new, reason=ReasonCode.GOVERNANCE_REQUIRED),
            Case(prefix + "-CUR", "current_read", current, catalog, Intent.READ_CURRENT,
                 target_id=candidate.memory_id, temporal=TemporalRelation.CURRENT,
                 critical=True),
            Case(prefix + "-UPD", "correction", correction, catalog, Intent.UPDATE_SCALAR,
                 target_id=candidate.memory_id, literal=new, critical=True),
            Case(prefix + "-REA", "reassertion", reassert, catalog, Intent.REASSERT_SCALAR,
                 target_id=candidate.memory_id, literal=old),
            Case(prefix + "-PRE", "previous_read", previous, catalog, Intent.READ_PREVIOUS,
                 target_id=candidate.memory_id, temporal=TemporalRelation.PREVIOUS,
                 critical=True),
            Case(prefix + "-UNK", "unknown_target", unknown, catalog, Intent.UNKNOWN_TARGET,
                 reason=ReasonCode.TARGET_NOT_FOUND, critical=True),
        ))
    first = _candidate(80, "北側潮汐鐘", "刻度顏色", "銀色")
    second = _candidate(80, "南側潮汐鐘", "刻度顏色", "金色", suffix="b")
    pair = (first, second)
    cases.extend((
        Case("A-ENTITY-A", "same_key_entity", "北側潮汐鐘的刻度顏色現在是什麼？", pair,
             Intent.READ_CURRENT, first.memory_id, temporal=TemporalRelation.CURRENT,
             critical=True),
        Case("A-ENTITY-B", "same_key_entity", "南側潮汐鐘的刻度顏色現在是什麼？", pair,
             Intent.READ_CURRENT, second.memory_id, temporal=TemporalRelation.CURRENT,
             critical=True),
        Case("A-ENTITY-AMB", "ambiguous_target", "潮汐鐘的刻度顏色現在是什麼？", pair,
             Intent.AMBIGUOUS_TARGET, reason=ReasonCode.MULTIPLE_TARGETS, critical=True),
        Case("A-ADJACENT", "value_boundary", "北側潮汐鐘刻度顏色：紫色。", pair,
             Intent.UPDATE_SCALAR, first.memory_id, literal="紫色", critical=True),
        Case("A-PUNCT", "value_boundary", "南側潮汐鐘的刻度顏色改為「橘色」。", pair,
             Intent.UPDATE_SCALAR, second.memory_id, literal="橘色", critical=True),
        Case("A-MIXED", "mixed_read", "北側潮汐鐘現在與先前的刻度顏色各是什麼？", pair,
             Intent.UNSUPPORTED, reason=ReasonCode.MIXED_READ, critical=True),
        Case("A-PRONOUN", "ambiguous_target", "它的刻度顏色是什麼？", pair,
             Intent.AMBIGUOUS_TARGET, reason=ReasonCode.MULTIPLE_TARGETS, critical=True),
        Case("A-TWO-FACTS", "multi_fact", "北側潮汐鐘變成藍色，南側潮汐鐘變成紅色。", pair,
             Intent.UNSUPPORTED, reason=ReasonCode.OUT_OF_SCOPE),
        Case("A-GENERAL", "unrelated", "解釋潮汐如何形成。", pair,
             Intent.UNSUPPORTED, reason=ReasonCode.OUT_OF_SCOPE),
        Case("A-COLLECTION", "collection", "把紫色和藍色都加入刻度顏色清單。", pair,
             Intent.UNSUPPORTED, reason=ReasonCode.OUT_OF_SCOPE, critical=True),
        Case("A-DELETE", "destructive", "忘記北側潮汐鐘的刻度顏色。", pair,
             Intent.UNSUPPORTED, reason=ReasonCode.OUT_OF_SCOPE),
        Case("A-TIMELINE", "timeline", "列出北側潮汐鐘刻度顏色的完整變更歷程。", pair,
             Intent.READ_TIMELINE, first.memory_id, temporal=TemporalRelation.TIMELINE),
    ))
    return tuple(cases)


def holdout_cases() -> tuple[Case, ...]:
    cases: list[Case] = []
    for i, (entity, prop, old, new) in enumerate(HOLDOUT_DOMAINS):
        named = f"海港{entity}"
        c = _candidate(i, named, prop, old, holdout=True)
        if i % 2 == 0:
            cases.append(Case(f"H{i:02d}-PRE", "previous_read",
                              f"海港{entity}的{prop}在最近一次更動前是什麼？", (c,),
                              Intent.READ_PREVIOUS, c.memory_id,
                              temporal=TemporalRelation.PREVIOUS, critical=True))
            cases.append(Case(f"H{i:02d}-UPD", "correction",
                              f"把海港{entity}的{prop}調整為{new}。", (c,),
                              Intent.UPDATE_SCALAR, c.memory_id, literal=new,
                              critical=True))
        else:
            cases.append(Case(f"H{i:02d}-UNK", "unknown_target",
                              f"山區{entity}目前的{prop}資料呢？", (c,),
                              Intent.UNKNOWN_TARGET, reason=ReasonCode.TARGET_NOT_FOUND,
                              critical=True))
            cases.append(Case(f"H{i:02d}-REA", "reassertion",
                              f"海港{entity}的{prop}維持{old}不變。", (c,),
                              Intent.REASSERT_SCALAR, c.memory_id, literal=old))
    return tuple(cases)
