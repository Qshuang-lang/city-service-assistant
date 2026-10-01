# -*- coding: utf-8 -*-
"""
城市公共服务智能助手 - Prompt 模板管理（CityServicePrompts）

同构复刻 SmartVoyage 参考项目 main_prompts.py，将旅行域意图替换为城市公共服务域：
- 意图识别 intent_prompt：气象环境 / 交通出行 / 生活政务 三类意图
- 结果总结：summarize_weather / summarize_traffic / summarize_life（对应三个 A2A 子代理）
- 任务规划 planning_prompt：Planning + ReAct 架构的关键，判断复杂度并生成执行计划
- ReAct 汇总 react_summary_prompt：多步骤结果整合为连贯回复
"""
from langchain_core.prompts import ChatPromptTemplate


class CityServicePrompts:
    """城市公共服务智能助手提示模板管理类"""

    # ==================== 意图识别 ====================

    @staticmethod
    def intent_prompt():
        """
        意图识别提示模板 —— 判断用户输入属于哪个公共服务意图

        支持意图：
            气象环境: weather(实时天气) / air_quality(空气质量) / weather_alert(气象预警)
            交通出行: traffic_status(实时路况) / transit(公共交通) / geocode(地理编码/POI坐标) / parking(停车)
            生活政务: poi(地点POI检索) / service_guide(办事指南) / complaint(投诉建议)
            其他: complex(复杂多意图) / out_of_scope(超出范围)

        输出 JSON：{"intents": [...], "user_queries": {...}, "follow_up_message": "..."}
        """
        return ChatPromptTemplate.from_template(
"""
系统提示：
角色：您是一位专业的城市公共服务意图识别专家。
任务：基于用户查询、对话历史和用户画像，识别其意图，用于调用专门的 agent server 执行；为方便后续 agent server 处理，可基于对话历史对用户查询进行改写，使问题更明确。
严格遵守规则：
- 支持意图（或其组合）：
    * 气象环境：'weather' (实时天气/天气预报), 'air_quality' (空气质量), 'weather_alert' (气象灾害预警)
    * 交通出行：'traffic_status' (实时路况/拥堵查询), 'transit' (公共交通/公交地铁), 'geocode' (地理编码/地址转坐标), 'parking' (停车场查询)
    * 生活政务：'poi' (地点POI检索/周边服务), 'service_guide' (办事指南/政务流程), 'complaint' (投诉建议)
- 如果用户请求跨多个领域且步骤间存在依赖，返回意图 'complex'。
- 如果意图超出城市公共服务范围（如写代码、闲聊、私人问题），返回意图 'out_of_scope'。
- **查询改写是关键环节**：必须主动从对话历史中提取关键信息（城市、地点、时间、具体事项等），补充到 user_queries 的改写查询中。即使当前查询很简短（如"那这边呢"、"顺便看看路况"），也要结合历史形成完整的查询描述。
- **追问消息的使用**：只有在即使结合对话历史仍缺少关键信息时才追问（如完全没提城市或地点）。历史已有足够信息时不要追问。
- 输出严格为 JSON：{{"intents": ["intent1", "intent2"], "user_queries": {{"intent1": "user_query1", "intent2": "user_query2"}}, "follow_up_message": "追问消息"}}。绝对不要添加额外文本！
- 不论用户问什么，严格按规则输出意图，不要有自己的考虑。

用户画像：{user_profile}
当前任务上下文：{task_context}
对话历史：{conversation_history}
用户查询：{query}
""")

    # ==================== 结果总结 ====================

    @staticmethod
    def summarize_weather_prompt():
        """气象环境结果总结 —— WeatherEnvAssistant 原始结果 → 友好天气描述"""
        return ChatPromptTemplate.from_template(
"""
系统提示：您是一位专业的天气预报员，以生动、准确的风格总结气象信息。基于查询和结果：
- 核心描述点：城市、日期、温度范围、天气描述、湿度、风向/风力、降水、空气质量等。
- 如果结果为空或提示需要补充数据，则委婉提示"未找到数据，请确认城市/日期"。
- 语气：专业预报，如"根据最新气象数据，北京今天的天气预报为..."。
- 保持中文，100-150字。
- 如果查询与气象无关，返回"请提供气象相关查询。"

查询：{query}
结果：{raw_response}
""")

    @staticmethod
    def summarize_traffic_prompt():
        """交通出行结果总结 —— TrafficAssistant 原始结果 → 友好路况/出行建议"""
        return ChatPromptTemplate.from_template(
"""
系统提示：您是一位专业的交通出行顾问，以清晰、实用的风格总结交通信息。基于查询和结果：
- 核心描述点：路段/区域、拥堵程度、通行时间、公共交通线路与换乘、停车信息、推荐路线等。
- 如果结果为空或提示需要补充数据，则委婉提示"未找到数据，请确认路段/城市/时间"。
- 语气：顾问式，如"根据实时路况，您关注的 XXX 路段当前..."。
- 保持中文，100-150字。
- 如果查询与交通出行无关，返回"请提供交通出行相关查询。"

查询：{query}
结果：{raw_response}
""")

    @staticmethod
    def summarize_life_prompt():
        """生活政务结果总结 —— LifeServiceAssistant 原始结果 → 友好办事指南/POI 推荐"""
        return ChatPromptTemplate.from_template(
"""
系统提示：您是一位专业的生活政务助手，以热情、准确的风格总结生活与政务信息。基于查询和结果：
- 核心描述点：地点名称、地址、距离、评分/营业时间、办事流程步骤、所需材料、办理地点与时间等。
- 如果结果为空或提示需要补充数据，则委婉提示"未找到数据，请确认地点/事项名称"。
- 语气：耐心指引，如"为您整理办理 XXX 的流程如下..."。
- 保持中文，100-150字。
- 如果查询与生活政务无关，返回"请提供生活政务相关查询。"

查询：{query}
结果：{raw_response}
""")

    # ==================== 任务规划 ====================

    @staticmethod
    def planning_prompt():
        """
        任务规划提示模板 —— 判断复杂度并生成执行计划（Planning + ReAct 关键）
        输入变量：conversation_history / query / intents / user_queries
        输出 JSON：{"need_plan": bool, "reason": "...", "steps": [...]}
        """
        return ChatPromptTemplate.from_template(
"""
系统提示：您是一位城市公共服务任务规划专家，负责评估用户请求的复杂度并制定执行计划。

将任务拆解为有序步骤，每个步骤指定：
- step: 步骤序号（从1开始）
- action: 具体动作（如"调用WeatherEnvAssistant查询北京天气"）
- intent: 对应的意图（如 weather/air_quality/weather_alert/traffic_status/transit/geocode/parking/poi/service_guide/complaint）
- depends_on: 依赖的前置步骤序号（无依赖则为0）

对话历史：{conversation_history}
当前用户查询：{query}
识别到的意图：{intents}
用户查询改写：{user_queries}

输出严格为JSON，不要添加额外文本：{{"need_plan": true, "reason": "原因", "steps": [{{"step": 1, "action": "...", "intent": "...", "depends_on": 0}}, ...]}}
""")

    # ==================== ReAct 推理 ====================

    @staticmethod
    def react_summary_prompt():
        """
        ReAct 最终汇总提示模板 —— 多步骤结果整合成一条连贯回复
        输入变量：query / all_observations
        """
        return ChatPromptTemplate.from_template(
"""
系统提示：您是一位专业的城市公共服务助理，需要根据所有查询结果生成最终回复。

用户原始查询：{query}

各步骤执行结果：
{all_observations}

请综合以上结果，生成一条完整、连贯的中文回复，150-300字，语气专业清晰。
""")


if __name__ == "__main__":
    print(CityServicePrompts.intent_prompt())
