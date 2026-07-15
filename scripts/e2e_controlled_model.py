from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def main() -> None:
    prompt_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    prompt = prompt_path.read_text(encoding="utf-8")
    chapter_id = _chapter_id(prompt)
    chapter_number = int(chapter_id)

    if "# Book Direction Generator" in prompt:
        result = {
            "recommendedOptionId": "direction-2",
            "options": [
                {
                    "id": f"direction-{index}",
                    "title": f"方向 {index}",
                    "genrePositioning": f"都市悬疑分支 {index}",
                    "protagonistDesire": f"查清第 {index} 条异声线索",
                    "centralConflict": f"线索与代价冲突 {index}",
                    "serialHook": f"每章推进不同谜面 {index}",
                    "targetReaderExperience": f"紧张和发现感 {index}",
                    "risks": [f"节奏风险 {index}"],
                    "recommendation": f"推荐依据 {index}",
                }
                for index in range(1, 4)
            ],
        }
    elif "# Book Architecture Builder" in prompt:
        result = {
            "directionTitle": "方向 2",
            "genrePositioning": "都市悬疑长篇连载",
            "coreSellingPoints": ["声音谜案", "选择代价"],
            "protagonistGoal": "查清异声来源",
            "centralConflict": "公开真相与保护城市持续冲突",
            "storyEngine": "每次追查都改变人物关系并打开下一层谜面",
            "escalationPath": "个人异声、旧案关联、城市真相逐层升级",
            "longTermHooks": ["异声来源", "主角过去"],
            "targetReaderExperience": "紧张和持续发现",
            "risks": ["避免重复调查结构"],
            "recommendation": "具备稳定升级空间",
        }
    elif "# Long Form Planner" in prompt or "# Long Form Replanner" in prompt:
        result = {
            "bookPlan": {
                "mainline": "主角沿声音谜案追查城市真相",
                "endingDirection": "居民共同决定城市规则",
                "longTermOpposition": "真相公开与城市稳定持续冲突",
                "corePromises": ["声音来源", "城市选择"],
            },
            "volumes": [
                {
                    "volumeId": f"volume-{volume_index:03d}",
                    "title": f"第 {volume_index} 卷",
                    "chapterRange": "001-010" if volume_index == 1 else "011-020",
                    "goal": f"完成第 {volume_index} 卷目标",
                    "mainConflict": f"第 {volume_index} 卷核心冲突",
                    "payoffs": [f"兑现承诺 {volume_index}"],
                    "endingChange": f"第 {volume_index} 卷末局势改变",
                    "failureCondition": f"第 {volume_index} 卷失败代价",
                    "beatSegments": [
                        {
                            "segmentId": f"volume-{volume_index:03d}-segment-{segment_index:02d}",
                            "title": f"节奏段 {segment_index}",
                            "chapterRange": (
                                f"{1 + (volume_index - 1) * 10:03d}-"
                                f"{5 + (volume_index - 1) * 10:03d}"
                                if segment_index == 1
                                else f"{6 + (volume_index - 1) * 10:03d}-"
                                f"{10 + (volume_index - 1) * 10:03d}"
                            ),
                            "purpose": f"推进卷目标 {segment_index}",
                            "pressure": f"升级压力 {segment_index}",
                            "payoff": f"阶段兑现 {segment_index}",
                            "density": "升级" if segment_index == 1 else "兑现",
                        }
                        for segment_index in range(1, 3)
                    ],
                }
                for volume_index in range(1, 3)
            ],
        }
        if "# Long Form Replanner" in prompt:
            result["chapterAdjustments"] = [
                {
                    "chapterId": f"{index:03d}",
                    "segmentId": "volume-001-segment-01" if index <= 5 else "volume-001-segment-02",
                    "goal": f"重规划目标 {index}",
                    "hook": f"重规划钩子 {index}",
                    "promiseProgression": f"重规划承诺推进 {index}",
                    "logicDependencies": [] if index == 1 else [f"承接第 {index - 1} 章"],
                }
                for index in range(1, 11)
            ]
    elif "# Chapter Blueprint" in prompt:
        result = {
            "chapters": [
                {
                    "title": f"第 {index} 章线索 {index}",
                    "goal": f"确认第 {index} 条独立线索",
                    "conflict": f"阻力 {index} 改变调查方向",
                    "turn": f"证据 {index} 指向意外对象",
                    "outcome": f"获得阶段结果 {index}",
                    "hook": f"新危险 {index} 在结尾出现",
                    "characterChange": f"主角完成变化 {index}",
                    "promiseProgression": f"长线承诺推进 {index}",
                    "logicDependencies": [] if index == 1 else [f"承接第 {index - 1} 章结果"],
                }
                for index in range(1, 11)
            ]
        }
    elif "# Generation Scene Contract Builder" in prompt:
        result = {
            "chapterId": chapter_id,
            "title": f"第 {chapter_number} 章线索 {chapter_number}",
            "pov": "林澈",
            "time": "雨夜",
            "location": "旧线站台",
            "focus": "追查异常声纹",
            "goal": "确认录音中警告的来源",
            "conflict": "站台断电且同行人拒绝继续",
            "turn": "警告声来自主角尚未发生的选择",
            "outcome": "主角取得完整录音并暴露行踪",
            "hook": "录音指出下一处废弃机房",
            "openingHook": "广告灯第三次闪烁时出现声纹",
            "emotionalBeat": "怀疑转为主动承担",
            "relationshipBeat": "同行人给予有限信任",
            "internalNeed": "证明自己的判断可靠",
            "woundOrFear": "害怕再次被否定",
            "stakes": "失败会永久失去录音证据",
            "cost": "主角暴露行踪",
            "subtext": "冷静外表掩盖恐惧",
            "aftertaste": "获得答案同时看见更大危险",
            "logicDependencies": ["作品架构已确认"],
            "mustInclude": ["异常声纹", "录音证据"],
            "mustAvoid": ["提前揭示最终真相"],
            "readerPromises": ["声音来源", "城市选择"],
        }
    elif "# Chapter Writer" in prompt:
        chapter_paragraphs = {
            1: (
                "雨水敲在旧线站台的铁棚上，林澈按住耳机，异常声纹再次越过噪声。"
                "他没有销毁原始录音，而是顶着断电和同行人的阻拦继续追查。"
                "每一次回放都让警告更接近他尚未做出的选择，也让暴露行踪的代价变得具体。"
            ),
            2: (
                "废弃机房的门禁灯忽明忽暗，林澈沿电缆编号核对异常声纹留下的时间差。"
                "原始录音证据藏着一段反向指令，他避开巡检人员，把损坏的控制板接回备用电源。"
                "屏幕恢复时，旧案名单与今晚的停电顺序重合，调查第一次指向城市供能中心。"
            ),
            3: (
                "天台发射器在晨雾里持续震动，林澈用频谱仪拆分异常声纹与风噪的边界。"
                "原始录音证据证明有人借公共广播覆盖求救信号，他必须在保全证据和救人之间选择。"
                "塔台重新通电后，隐藏频道播出一串居民地址，追查从个人警告升级为全城危机。"
            ),
        }
        paragraph = chapter_paragraphs.get(
            chapter_number,
            f"第 {chapter_number} 章围绕新的异常声纹推进独立调查，并保留原始录音证据。",
        )
        result = (
            f"# 第 {chapter_number} 章线索 {chapter_number}\n\n"
            + paragraph * 80
            + f"\n\n第 {chapter_number} 条线索在结尾改变了下一章方向。\n"
        )
    else:
        result = {"error": "unsupported controlled E2E prompt"}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        result if isinstance(result, str) else json.dumps(result, ensure_ascii=False),
        encoding="utf-8",
    )


def _chapter_id(prompt: str) -> str:
    match = re.search(r"(?:chapterId|chapter_id|Chapter ID)[^0-9]{0,20}(\d{1,4})", prompt)
    return (match.group(1) if match else "001").zfill(3)


if __name__ == "__main__":
    main()
