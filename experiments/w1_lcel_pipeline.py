"""
W1 实验作业 3/3 · w1_lcel_pipeline.py  ⭐ 核心作业
日期: 2026-07-04
对应视频: 阶段10/day02 第 06-12 集
对应课程代码: chapter_02/ 01_什么是Runnable和LCEL.ipynb + 02_Runnable相关类的介绍.ipynb

=== 任务清单 ===

0. 顶部加 os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
1. 初始化 ChatOpenAI（同前两个文件）
2. 基础链:
   - PromptTemplate.from_template("{topic}") | llm | StrOutputParser
   - invoke 跑通，打印结果
3. RunnableParallel:
   - 同一个 prompt 分发给两个模型实例（或同模型不同 temperature）
     例: temperature=0 vs temperature=1
   - RunnableParallel({"output_a": llm_cold, "output_b": llm_hot})
   - invoke 后拿到 {"output_a": ..., "output_b": ...}
4. RunnableLambda:
   - 自定义一个函数（比如提取关键词、统计字数、加前缀）
   - 用 RunnableLambda(func) 包成 Runnable
   - 接在 llm 后面: prompt | llm | StrOutputParser | RunnableLambda(你的函数)
5. RunnablePassthrough:
   - 用 RunnablePassthrough.assign() 给输出加一个额外字段
     例: 原样透传 + 加一个 word_count 字段
6. 完整流水线（周末作业）:
   - 搭一条: prompt | llm | JsonOutputParser | RunnableLambda(后处理)
   - 输入中文 → 输出 JSON {翻译, 摘要}
   - 用 with_fallbacks 加一条备份链（主链报错时走 fallback）
   - 跑 5 个 input 测试

=== 环境提示 ===
- venv: /Users/minjie/shangguigu/.venv/bin/python
- .env 在项目根目录
- 跑法: cd /Users/minjie/shangguigu/ai_collector_project && .venv/bin/python experiments/w1_lcel_pipeline.py

=== 验收标准 ===
- | 管道能跑通
- RunnableParallel 并行返回两个 key
- RunnableLambda 后处理有实际输出
- with_fallbacks 的 fallback 链被触发一次（可以故意让主链抛异常来验证）
- 5 个 input 都有输出

=== 学习重点 ===
LCEL 的 | 管道符不是 Python 位或运算，是 Runnable 类重载了 __or__ 方法。
这个知识点是 v3.0 项目（ai_collector）里 LangGraph 编排的隐藏底层，必须吃透。

=== 从这里开始写代码 ===
"""

'''
不太懂的点：
1、ChatPromptTemplate和和PromptTemplate的区别，什么情况下该用哪个？
2、RunnableLambda不太明白
3、 TODO5和6不太明白，用了vibe coding，请重新给我讲一遍吧
'''

import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"  # 防 macOS OpenMP abort

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import StrOutputParser, JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableParallel, RunnableLambda
from langchain_core.runnables import RunnableLambda, RunnablePassthrough

# TODO: 1. 导入依赖 + 加载 .env + 初始化模型
load_dotenv()
llm = ChatOpenAI(
    api_key=os.getenv("LLM_API_KEY_STUDY"),
    base_url=os.getenv("LLM_API_BASE_STUDY"),
    model=os.getenv("LLM_NAME_STUDY", "glm-5.2"),
)
# TODO: 2. 基础链: prompt | llm | StrOutputParser
def demo_chain():
   print("=" * 60)
   print("【2. 基础链: prompt | llm | StrOutputParser】")
   print("=" * 60)
   messages = [
      {"role": "system", "content": "你是中国近代史历史学家"},
      {"role": "user", "content": "请讲一下{topic}的历史背景和影响。"},
   ]
   prompt = ChatPromptTemplate.from_messages(messages)
   parser = StrOutputParser()
   chain = prompt | llm | parser
   resp = chain.invoke({"topic": "七七事变"})
   print(f"基础链结果: {resp}")

# TODO: 3. RunnableParallel: 同prompt分发两个模型(不同temperature)
def demo_parallel():
   print("=" * 60)
   print("【3. RunnableParallel: 同prompt分发两个模型(不同temperature)】")
   print("=" * 60)
   llm1 = ChatOpenAI(
         api_key=os.getenv("LLM_API_KEY_STUDY"),
         base_url=os.getenv("LLM_API_BASE_STUDY"),
         model=os.getenv("LLM_NAME_STUDY", "glm-5.2"),
         temperature=0.7,
   )
   llm2 = ChatOpenAI(
         api_key=os.getenv("LLM_API_KEY_STUDY"),
         base_url=os.getenv("LLM_API_BASE_STUDY"),
         model=os.getenv("LLM_NAME_STUDY", "kimi-2.6"),
         temperature=1.0,
   )

   spring_prompt = ChatPromptTemplate.from_messages([
      {"role": "system", "content": "你是现代诗人"},
      {"role": "user", "content": "请写一首{topic}的诗歌。"},
   ])
   summer_prompt = ChatPromptTemplate.from_messages([
      {"role": "system", "content": "你是现代诗人"},
      {"role": "user", "content": "请写一首{topic}的诗歌。"},
   ])

   spring_poem = spring_prompt | llm1 | StrOutputParser()
   summer_poem = summer_prompt | llm2 | StrOutputParser()
   parallel_chain = RunnableParallel({"spring": spring_poem, "summer": summer_poem})

   # RunnableParallel 会把同一个输入传给所有子链
   # 之前的 bug: {"topic": "春天", "topic": "夏天"} → Python 字典去重，只保留"夏天"
   # 正确做法: 传一个 topic，两个模型各自生成（体现"同输入不同模型对比"）
   resp = parallel_chain.invoke({"topic": "夏天"})
   print(f"RunnableParallel结果:\n【llm1 temperature=0.7】\n{resp['spring']}\n\n【llm2 temperature=1.0】\n{resp['summer']}")

# TODO: 4. RunnableLambda: 自定义函数包成Runnable，接在llm后面
def demo_lambda():
   print("=" * 60)
   print("【4. RunnableLambda: 自定义函数包成Runnable，接在llm后面】")
   print("=" * 60)
   def count_words(text):
      return len(text.split())
   word_count_runnable = RunnableLambda(count_words)
   messages = [
         {"role": "system", "content": "你是一个英语老师"},
         {"role": "user", "content": "请写一段关于{topic}的英文短文。"},
      ]
   chain = ChatPromptTemplate.from_messages(messages) | llm | StrOutputParser() | word_count_runnable
   resp = chain.invoke({"topic": "Artificial Intelligence"})
   print(f"RunnableLambda结果: {resp} 个单词")
   @RunnableLambda
   def total_len(x):
      return len(x["text1"]) + len(x["text2"])

   chain = {
      "text1": lambda x: x + " world",
      "text2": lambda x: x + ", how are you",
   } | total_len

   result = chain.invoke("hello")
   print(result)

# TODO: 5. RunnablePassthrough: assign() 给输出加额外字段
def demo_passthrough():
   print("=" * 60)
   print("【5. RunnablePassthrough: assign() 给输出加额外字段】")
   print("=" * 60)

   # --- 示例1：字典 → assign 加字段（理解 assign 基本机制）---
   chain1 = {
      "text1": lambda x: x + " world",
      "text2": lambda x: x + ", how are you",
   } | RunnablePassthrough.assign(word_count=lambda x: len(x["text1"] + x["text2"]))

   result1 = chain1.invoke("hello")
   print(f"[示例1] 字典+assign: {result1}")

   # --- 示例2：接 LLM，体现 RAG 里的真实用途 ---
   # RunnablePassthrough 在 RAG 中的核心用法：
   # 保留原始 question，同时 assign 一个检索到的 context
   messages = [
      {"role": "system", "content": "你是一个英语老师，请根据用户提供的主题写一段英文短文。"},
      {"role": "user", "content": "{topic}"},
   ]
   prompt = ChatPromptTemplate.from_messages(messages)
   base_chain = prompt | llm | StrOutputParser()  # 输出: 纯字符串(英文短文)

   # assign 在字符串后面追加 word_count 字段
   # 注意：StrOutputParser 输出的是 str，assign 会把原值放在 'output' key 下
   full_chain = base_chain | RunnablePassthrough.assign(
       word_count=lambda x: len(x.split())
   )
   # full_chain 输出: {"output": "英文短文...", "word_count": N}
   # 但 LangChain 不同版本对 str 的 assign 行为不一致，
   # 更安全的写法是先用 RunnableLambda 包成 dict：

   from langchain_core.runnables import RunnablePassthrough as RP
   full_chain_safe = (
       base_chain
       | RunnableLambda(lambda text: {"essay": text})
       | RP.assign(word_count=lambda x: len(x["essay"].split()))
   )
   result2 = full_chain_safe.invoke({"topic": "Machine Learning"})
   print(f"[示例2] LLM+assign: {result2}")

# TODO: 6. 完整流水线: prompt | llm | JsonOutputParser | RunnableLambda(后处理)
#         + with_fallbacks 备份链
#         + 跑 5 个 input 测试
def demo_full_pipeline():
   print("=" * 60)
   print("【6. 完整流水线: prompt | llm | JsonOutputParser | RunnableLambda(后处理)】")
   print("=" * 60)

   json_parser = JsonOutputParser()

   prompt = ChatPromptTemplate.from_messages([
      {"role": "system", "content": "你是中英翻译与摘要助手。对用户输入的中文，返回 JSON，"
                                    "包含字段 translation(英文翻译) 与 summary(一句话中文摘要)。"
                                    "只输出 JSON，不要任何解释。"},
      {"role": "user", "content": "{text}"},
   ])

   def post_process(data):
      # 后处理：补全字段 + 统计翻译词数
      translation = data.get("translation", "")
      summary = data.get("summary", "")
      return {
         "translation": translation,
         "summary": summary,
         "word_count": len(translation.split()),
      }

   # 主链：prompt | llm(glm-5.2) | JsonOutputParser | RunnableLambda(后处理)
   main_chain = prompt | llm | json_parser | RunnableLambda(post_process)

   # 备份链：换一条路——改用 StrOutputParser + 手动 JSON 提取
   # （而不是原路换个 prompt 措辞重试，那样 fallback 意义不大）
   import re as _re
   import json as _json

   def extract_json_from_text(text: str) -> dict:
      """从 LLM 纯文本回复中尽力提取 JSON"""
      # 尝试直接解析
      try:
         return _json.loads(text)
      except Exception:
         pass
      # 尝试提取 ```json ... ``` 代码块
      m = _re.search(r"```json\s*(.*?)\s*```", text, _re.DOTALL)
      if m:
         try:
            return _json.loads(m.group(1))
         except Exception:
            pass
      # 尝试找第一个 { ... }
      m = _re.search(r"\{.*\}", text, _re.DOTALL)
      if m:
         try:
            return _json.loads(m.group(0))
         except Exception:
            pass
      raise ValueError(f"无法从回复中提取 JSON: {text[:100]}")

   fallback_chain = (
       prompt | llm | StrOutputParser()
       | RunnableLambda(extract_json_from_text)
       | RunnableLambda(post_process)
   )

   # 兜底链：LLM 也失败时直接给默认结果，保证每个 input 都有输出
   default_chain = RunnableLambda(lambda payload: {
      "translation": "",
      "summary": "（输入无效，已走兜底链）",
      "word_count": 0,
   })

   # 输入校验：空文本让主链抛异常，从而触发 with_fallbacks 的备份链
   def validate_input(payload):
      if not payload.get("text", "").strip():
         raise ValueError("输入为空，主链拒绝处理")
      return payload

   robust_chain = (RunnableLambda(validate_input) | main_chain).with_fallbacks(
      [fallback_chain, default_chain]
   )

   inputs = [
      {"text": "今天天气真好，我们一起去公园散步吧。"},
      {"text": "人工智能正在改变我们的生活方式。"},
      {"text": ""},  # 故意空输入 → 主链抛异常 → 触发 fallback
      {"text": "请帮我预订明天下午两点的高铁票。"},
      {"text": "学而时习之，不亦说乎？"},
   ]

   for idx, item in enumerate(inputs, 1):
      text = item["text"]
      try:
         result = robust_chain.invoke(item)
         print(f"[{idx}] 输入: {text!r}")
         print(f"    结果: {result}")
      except Exception as exc:
         print(f"[{idx}] 输入: {text!r} 失败: {exc}")



if __name__ == "__main__":
      demo_chain()
      # 依次调用其他 TODO 函数
      demo_parallel()
      demo_lambda()
      demo_passthrough()
      demo_full_pipeline()
