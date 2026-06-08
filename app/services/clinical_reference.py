from __future__ import annotations

from copy import deepcopy
from typing import Any


MEDICATION_RULES: list[dict[str, Any]] = [
    {
        "drug_name": "阿莫西林",
        "aliases": ["阿莫西林", "amoxicillin"],
        "category": "β-内酰胺类抗菌药",
        "contraindications": ["青霉素或β-内酰胺类过敏史禁用", "传染性单核细胞增多症患者慎用"],
        "interactions": ["与别嘌醇合用可能增加皮疹风险", "与华法林等抗凝药合用需关注凝血指标"],
        "special_populations": {
            "children": "儿童需由医生按体重和感染情况确定剂量。",
            "pregnancy": "妊娠或哺乳期需由医生评估获益与风险。",
            "renal": "肾功能异常可能需要调整给药方案。",
        },
        "dose_note": "平台不提供具体剂量；抗菌药需凭医生诊断和处方使用。",
        "alcohol_warning": "用药期间不建议饮酒，以免影响恢复或增加不良反应。",
    },
    {
        "drug_name": "甲硝唑",
        "aliases": ["甲硝唑", "metronidazole"],
        "category": "硝基咪唑类抗菌药",
        "contraindications": ["硝基咪唑类药物过敏禁用", "活动性中枢神经系统疾病患者慎用"],
        "interactions": ["与酒精同用可出现双硫仑样反应", "与华法林等抗凝药合用可能增强抗凝作用"],
        "special_populations": {
            "children": "儿童使用需医生明确适应证和剂量。",
            "pregnancy": "妊娠期尤其早期需医生评估后使用。",
            "hepatic": "肝功能异常者需医生评估。",
        },
        "dose_note": "不得自行延长疗程或叠加其他抗菌药；剂量由医生决定。",
        "alcohol_warning": "用药期间及停药后短期内避免饮酒。",
    },
    {
        "drug_name": "布洛芬",
        "aliases": ["布洛芬", "ibuprofen"],
        "category": "非甾体抗炎镇痛药",
        "contraindications": ["NSAIDs或阿司匹林过敏/诱发哮喘史禁用", "活动性消化性溃疡、严重心肾疾病或妊娠晚期应避免使用"],
        "interactions": ["与抗凝药、抗血小板药或糖皮质激素合用可增加出血和胃肠道风险"],
        "special_populations": {
            "children": "儿童需按年龄和体重由医生或药师确认。",
            "pregnancy": "妊娠晚期通常应避免，其他阶段需医生评估。",
            "renal": "肾功能异常、心衰或高血压患者需谨慎。",
        },
        "dose_note": "仅作短期镇痛辅助；持续牙痛需处理病因。",
        "alcohol_warning": "饮酒会增加胃肠道出血和肝肾负担风险。",
    },
    {
        "drug_name": "对乙酰氨基酚",
        "aliases": ["对乙酰氨基酚", "扑热息痛", "acetaminophen", "paracetamol"],
        "category": "解热镇痛药",
        "contraindications": ["严重肝功能不全禁用或慎用", "对本品过敏禁用"],
        "interactions": ["与酒精或其他含同成分感冒药叠加会增加肝损伤风险"],
        "special_populations": {
            "children": "儿童需按体重确认剂量，避免重复用药。",
            "pregnancy": "妊娠期用药需医生评估并遵循最小有效原则。",
            "hepatic": "肝病或长期饮酒者需医生复核。",
        },
        "dose_note": "注意避免与复方感冒药重复摄入同成分。",
        "alcohol_warning": "服药期间避免饮酒。",
    },
    {
        "drug_name": "氯己定含漱液",
        "aliases": ["氯己定", "洗必泰", "chlorhexidine"],
        "category": "口腔局部抗菌含漱剂",
        "contraindications": ["对氯己定过敏禁用"],
        "interactions": ["与牙膏中的阴离子表面活性剂同时使用可能降低效果，建议间隔使用"],
        "special_populations": {
            "children": "儿童需确认能安全含漱并避免吞咽。",
            "pregnancy": "妊娠期如需长期使用应咨询医生。",
        },
        "dose_note": "含漱剂不能替代洁治、根管或牙周治疗。",
        "alcohol_warning": "部分制剂可能含酒精，口腔黏膜敏感者需查看说明书。",
    },
    {
        "drug_name": "利多卡因",
        "aliases": ["利多卡因", "lidocaine", "局麻药"],
        "category": "口腔局部麻醉药",
        "contraindications": ["对酰胺类局麻药过敏禁用", "严重传导阻滞或严重心功能异常患者需专科评估"],
        "interactions": ["与抗心律失常药、β受体阻滞剂等合用需关注心血管不良反应"],
        "special_populations": {
            "children": "儿童局麻剂量必须按体重和最大安全剂量由医生控制。",
            "pregnancy": "妊娠期局麻需医生评估并选择合适制剂。",
            "cardiac": "心血管疾病患者需评估是否含肾上腺素及总剂量。",
        },
        "dose_note": "局麻药不得由患者自行使用；剂量、浓度和是否含肾上腺素由医生决定。",
        "alcohol_warning": "治疗前后饮酒可能增加不适和出血风险，建议避免。",
    },
    {
        "drug_name": "阿替卡因",
        "aliases": ["阿替卡因", "articaine", "碧兰麻"],
        "category": "口腔局部麻醉药",
        "contraindications": ["对酰胺类局麻药过敏禁用", "严重心血管疾病或甲状腺功能亢进患者使用含肾上腺素制剂需谨慎"],
        "interactions": ["与非选择性β受体阻滞剂、三环类抗抑郁药等同用需医生评估"],
        "special_populations": {
            "children": "儿童需按体重核定最大剂量。",
            "pregnancy": "妊娠或哺乳期需医生评估。",
            "cardiac": "心血管疾病患者需控制含肾上腺素局麻药总量。",
        },
        "dose_note": "局麻药仅限医疗操作场景，由医生根据体重、病史和操作范围控制剂量。",
        "alcohol_warning": "治疗当天避免饮酒。",
    },
    {
        "drug_name": "头孢克洛",
        "aliases": ["头孢克洛", "头孢", "cefaclor"],
        "category": "头孢菌素类抗菌药",
        "contraindications": ["头孢菌素过敏禁用", "严重青霉素过敏史需医生评估交叉过敏风险"],
        "interactions": ["与抗凝药合用需关注出血风险", "与酒精同用不建议"],
        "special_populations": {
            "children": "儿童需按体重和感染情况由医生确定剂量。",
            "pregnancy": "妊娠期需医生评估。",
            "renal": "肾功能异常可能需要调整方案。",
        },
        "dose_note": "抗菌药需明确感染适应证，不用于单纯止痛。",
        "alcohol_warning": "用药期间避免饮酒。",
    },
    {
        "drug_name": "米诺环素凝胶",
        "aliases": ["米诺环素", "米诺环素凝胶", "牙周辅助药物", "minocycline"],
        "category": "牙周局部辅助抗菌药",
        "contraindications": ["四环素类过敏禁用", "儿童、妊娠期和哺乳期需避免或严格医生评估"],
        "interactions": ["与全身四环素类药物叠加需医生评估"],
        "special_populations": {
            "children": "儿童不宜自行使用。",
            "pregnancy": "妊娠和哺乳期需避免或医生严格评估。",
            "periodontal": "只能作为牙周基础治疗后的局部辅助，不能替代洁治和刮治。",
        },
        "dose_note": "局部牙周药物需由医生置入或指导使用。",
        "alcohol_warning": "治疗期间建议避免饮酒并维护口腔清洁。",
    },
]


TREATMENT_OPTIONS: list[dict[str, Any]] = [
    {
        "option_name": "根管治疗",
        "category": "牙体牙髓治疗",
        "keywords": ["根管", "牙髓炎", "根尖周炎", "杀神经"],
        "steps": ["术前检查与影像评估", "开髓、根管预备和消毒", "根管充填", "牙体修复或冠修复评估"],
        "duration_note": "通常需要1至3次复诊，复杂根管或急性炎症可能增加次数。",
        "cost_factors": ["牙位和根管数", "显微根管或再治疗难度", "是否需要桩核、嵌体或牙冠修复"],
        "advantages": ["保留天然牙", "针对牙髓/根尖感染病因处理", "后续可结合修复恢复咀嚼功能"],
        "disadvantages": ["需复诊", "治疗后牙体脆弱时可能需要冠修复", "复杂病例存在遗漏根管或再感染风险"],
        "alternatives": ["拔除后修复", "急性期先行开髓引流或止痛处理"],
    },
    {
        "option_name": "种植修复",
        "category": "种植与修复",
        "keywords": ["种植", "种植牙", "缺牙", "植体"],
        "steps": ["缺牙区检查和CBCT评估", "种植体植入", "愈合期观察", "上部修复和维护"],
        "duration_note": "常需数月完成；骨量不足、植骨或上颌窦提升会延长周期。",
        "cost_factors": ["植体系统", "骨量和植骨需求", "修复材料", "维护和复诊要求"],
        "advantages": ["不依赖邻牙磨除", "稳定性和咀嚼效率较好", "适合多数单颗或多颗缺牙修复场景"],
        "disadvantages": ["费用较高", "需要手术和长期维护", "牙周控制差或全身疾病控制不佳时风险上升"],
        "alternatives": ["固定桥", "活动义齿", "保留残根后的覆盖义齿需医生评估"],
    },
    {
        "option_name": "正畸治疗",
        "category": "正畸",
        "keywords": ["正畸", "矫正", "牙齿不齐", "隐形牙套", "托槽"],
        "steps": ["口扫/模型、影像和面型评估", "制定矫治方案", "佩戴矫治器并定期复诊", "保持器维护"],
        "duration_note": "常见疗程约1至3年，取决于错颌类型、年龄和配合度。",
        "cost_factors": ["矫治器类型", "复杂程度", "是否需拔牙、支抗钉或联合治疗"],
        "advantages": ["改善牙列排列和清洁条件", "可改善咬合功能和美观", "有利于部分修复/种植前空间管理"],
        "disadvantages": ["周期长", "需高度配合口腔卫生", "可能出现牙龈炎、脱矿或复发风险"],
        "alternatives": ["局部修复改善", "正颌联合治疗", "暂不治疗并定期观察"],
    },
    {
        "option_name": "牙周洁治与基础治疗",
        "category": "牙周治疗",
        "keywords": ["洁治", "洗牙", "牙周", "牙龈出血", "龈下刮治"],
        "steps": ["牙周检查和风险评估", "龈上洁治", "必要时龈下刮治/根面平整", "维护期复查"],
        "duration_note": "基础洁治可一次完成；牙周炎通常需要分区治疗和3至6个月维护。",
        "cost_factors": ["牙石和炎症程度", "是否需龈下治疗", "复查维护频率"],
        "advantages": ["控制牙龈炎症和出血", "降低牙周进展风险", "为修复、正畸或种植创造基础条件"],
        "disadvantages": ["不能恢复已明显丧失的牙槽骨", "治疗后短期敏感可能出现", "需要长期维护"],
        "alternatives": ["强化家庭清洁并观察", "牙周手术治疗需专科评估"],
    },
    {
        "option_name": "全冠/烤瓷冠修复",
        "category": "修复治疗",
        "keywords": ["烤瓷冠", "全冠", "牙冠", "冠修复", "嵌体"],
        "steps": ["牙体和咬合评估", "牙体预备或嵌体设计", "取模/口扫和临时修复", "试戴、粘接和复查"],
        "duration_note": "通常需要2至3次就诊；根管后修复需确认根尖和牙体条件。",
        "cost_factors": ["材料类型", "牙体缺损范围", "是否需要桩核或牙周处理"],
        "advantages": ["保护大面积缺损牙体", "改善形态和咀嚼功能", "适合部分根管治疗后的牙体保护"],
        "disadvantages": ["可能需要磨除牙体组织", "边缘密合和牙龈维护要求高", "长期仍需复查"],
        "alternatives": ["嵌体/高嵌体", "直接树脂修复", "拔除后修复"],
    },
]


def medication_rules_for_text(text: str) -> list[dict[str, Any]]:
    lowered = text.lower()
    matched = []
    for rule in MEDICATION_RULES:
        aliases = [str(item).lower() for item in rule.get("aliases", [])]
        if any(alias and alias in lowered for alias in aliases):
            matched.append(deepcopy(rule))
    return matched


def treatment_options_for_text(text: str) -> list[dict[str, Any]]:
    lowered = text.lower()
    matched = []
    for option in TREATMENT_OPTIONS:
        keywords = [str(item).lower() for item in option.get("keywords", [])]
        if any(keyword and keyword in lowered for keyword in keywords):
            matched.append(deepcopy(option))
    return matched
