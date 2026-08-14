"""
W1 实验作业 2/3 · w1_output_parser.py
日期: 2026-07-04
对应视频: 阶段10/day02 第 01-05 集
对应课程代码: chapter_01/ 7_输出解析器.ipynb

=== 任务清单 ===

0. 顶部加 os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
1. 初始化 ChatOpenAI（同 w1_model_io.py，从 .env 读配置）
2. StrOutputParser: AIMessage → str
3. JsonOutputParser: str → dict（pydantic BaseModel + get_format_instructions）
4. with_structured_output: 直接返回 pydantic 对象
5. LCEL 管道: prompt | llm | json_parser → 一步出 dict

=== 验收标准 ===
三种 parser 的输出类型在 print(type(...)) 时能看到区别:
  - StrOutputParser         → str
  - JsonOutputParser        → dict
  - with_structured_output  → pydantic 对象

=== 踩坑记录 ===
GLM-5.2 不支持 json_schema（with_structured_output 默认 method），报 400 错误。
解决: 加 method='function_calling'，走 function calling 路线。

=== 优化记录（agent 协助） ===
1. [规范] import 顺序: os.environ 移到最前 + 标准库→第三方库分组
2. [规范] 清理 TODO 注释，加分段标题
3. [规范] 补 print 内容预览，方便调试确认
4. [bugfix] 修复 patch 导致的缩进错误
"""

import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"  # 防 macOS OpenMP abort，必须在 langchain 导入前

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import StrOutputParser, JsonOutputParser
from langchain_core.prompts.chat import ChatPromptTemplate
from pydantic import BaseModel, Field

# ========== 1. 初始化模型 ==========
load_dotenv()
llm = ChatOpenAI(
    api_key=os.getenv("LLM_API_KEY_STUDY"),
    base_url=os.getenv("LLM_API_BASE_STUDY"),
    model=os.getenv("LLM_NAME_STUDY", "glm-5.2"),
)


# ========== 2. StrOutputParser ==========
# AIMessage → str，提取 .content 的纯文本
def demo_str_output_parser():
    print("=" * 60)
    print("【2. StrOutputParser】")
    print("=" * 60)
    messages = [
        {"role": "system", "content": "你是历史学家"},
        {"role": "user", "content": "你好"},
    ]
    resp = llm.invoke(messages)
    str_resp = StrOutputParser().invoke(resp)
    print("AIMessage 类型:", type(resp))
    print("StrOutputParser 类型:", type(str_resp))
    print("内容预览:", str(str_resp)[:50], "...\n")


# ========== 3. JsonOutputParser ==========
# pydantic BaseModel 定义 schema → get_format_instructions 生成格式提示 → 解析成 dict
class MovieSuggestion(BaseModel):
    film_name: str = Field(description="电影名称")
    year: int = Field(description="电影上映年份")
    description: str = Field(description="电影简介")


json_parser = JsonOutputParser(pydantic_object=MovieSuggestion)

prompt = ChatPromptTemplate.from_messages([
    ("system", "你是电影推荐专家。请按格式要求返回结果。\n{format_instructions}"),
    ("user", "{question}"),
]).partial(format_instructions=json_parser.get_format_instructions())


def demo_json_output_parser():
    print("=" * 60)
    print("【3. JsonOutputParser】")
    print("=" * 60)
    json_raw = llm.invoke(prompt.format(question="推荐一部科幻电影"))
    json_resp = json_parser.invoke(json_raw)
    print("LLM 原始输出类型:", type(json_raw.content))
    print("JsonOutputParser 类型:", type(json_resp))
    print("解析结果:", json_resp, "\n")


# ========== 4. with_structured_output ==========
# 直接返回 pydantic 对象（不是 dict）
# 注意: GLM-5.2 不支持 json_schema，必须用 method='function_calling'
def demo_structured_output():
    print("=" * 60)
    print("【4. with_structured_output】")
    print("=" * 60)
    structured_llm = llm.with_structured_output(
        schema=MovieSuggestion, method="function_calling"
    )
    movie = structured_llm.invoke(prompt.format(question="推荐一部科幻电影"))
    print("with_structured_output 类型:", type(movie))
    print("解析结果:", movie, "\n")


# ========== 5. LCEL 管道 ==========
# prompt | llm | json_parser → 一步出 dict
def demo_lcel_chain():
    print("=" * 60)
    print("【5. LCEL 管道: prompt | llm | json_parser】")
    print("=" * 60)
    chain = prompt | llm | json_parser
    chain_resp = chain.invoke({"question": "推荐一部科幻电影"})
    print("管道类型:", type(chain))
    print("输出类型:", type(chain_resp))
    print("解析结果:", chain_resp, "\n")


# ========== 主入口 ==========
if __name__ == "__main__":
    demo_str_output_parser()
    demo_json_output_parser()
    demo_structured_output()
    demo_lcel_chain()
    print("=" * 60)
    print("✅ w1_output_parser.py 全部测试通过")
    print("=" * 60)
