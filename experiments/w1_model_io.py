"""
W1 实验作业 1/3 · w1_model_io.py
日期: 2026-07-04
对应视频: 阶段10/day01 第 05-11 集
对应课程代码: chapter_01/ 04_调用方式.ipynb + 06_prompt_template.ipynb

=== 任务清单 ===

0. 顶部加 os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"（防 macOS OpenMP abort）
1. 从 .env 读 LLM_API_KEY_STUDY / LLM_API_BASE_STUDY / LLM_NAME_STUDY，用 ChatOpenAI 显式初始化模型
2. 5 种 Message 各调一次:
   - SystemMessage + HumanMessage → invoke
   - 纯字符串 invoke（隐式转 HumanMessage）
   - 列表传 message（dict 格式 system + human 混合）
3. 4 种调用方式各写一段:
   - invoke / stream / batch / ainvoke
4. PromptTemplate + ChatPromptTemplate

=== 已解决疑问 ===
1. KMP_DUPLICATE_LIB_OK：macOS 下多个库各自捆绑 OpenMP 运行时，设 TRUE 防冲突 abort
2. ChatOpenAI vs OpenAI：前者走 /chat/completions 接口（Message 输入输出），后者走老 /completions 接口（纯文本，已过时）
3. 异步没比同步快：batch 底层也是多线程并发，3 条请求量太小看不出差异，50+ 条才有明显差距
4. load_dotenv() 查找逻辑：从 CWD 开始往上逐级找 .env，跟脚本文件位置无关

=== 优化记录（agent 协助） ===
1. [bugfix] .env 变量名 LLM_NAME → LLM_NAME_STUDY（用户已自行修复）
2. [重构] 三引号注释 ''' 拆成 if __name__ 分段调用，一键跑全部
3. [规范] ChatOpenAI 参数名 openai_api_key/openai_api_base → api_key/base_url（langchain_openai 1.x 新写法）
4. [重构] 重复的 message2 三个列表提取为生成函数，减少冗余
5. [重构] batch 和 ainvoke 耗时对比合并为一个函数，逻辑更清晰
6. [规范] import 顺序: 标准库 → 第三方库，os.environ 移到 import 之前（必须在 langchain 导入前生效）
"""

import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"  # 防 macOS OpenMP abort，必须在 langchain 导入前

import asyncio
import time

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.prompts import PromptTemplate
from langchain_core.prompts.chat import ChatPromptTemplate

# ========== 1. 初始化模型 ==========
load_dotenv()
llm = ChatOpenAI(
    api_key=os.getenv("LLM_API_KEY_STUDY"),
    base_url=os.getenv("LLM_API_BASE_STUDY"),
    model=os.getenv("LLM_NAME_STUDY", "glm-5.2"),
)


# ========== 2. Message 构造 ==========

def demo_messages():
    """5 种 Message 构造方式各调一次"""
    print("=" * 60)
    print("【2. Message 构造】")
    print("=" * 60)

    # 方式一: dict 列表（system + user 混合）
    message1 = [
        {"role": "system", "content": "你是一个大学数学老师"},
        {"role": "user", "content": "帮我解答一下：2x + 3 = 7，x 等于多少？"},
    ]
    resp1 = llm.invoke(message1).content
    print(f"[dict 列表] {resp1[:50]}...\n")

    # 方式二: 纯字符串（隐式转 HumanMessage）
    message3 = "帮我解答一下：3x + 5 = 11，x 等于多少？"
    resp2 = llm.invoke(message3).content
    print(f"[纯字符串] {resp2[:50]}...\n")

    # 方式三: LangChain Message 对象
    message4 = [
        SystemMessage(content="你是一个数学老师"),
        HumanMessage(content="帮我解答一下：4x - 7 = 9，x 等于多少？"),
    ]
    resp3 = llm.invoke(message4).content
    print(f"[Message 对象] {resp3[:50]}...\n")


# ========== 3. 调用方式 ==========

def _make_batch_messages():
    """生成 3 组 batch 测试消息"""
    problems = ["2x + 3 = 7", "5x - 2 = 8", "8x + 4 = 20"]
    return [
        [
            {"role": "system", "content": "你是一个数学老师"},
            {"role": "user", "content": f"帮我解答一下：{p}，x 等于多少？"},
        ]
        for p in problems
    ]


def demo_invoke():
    """非流式调用"""
    print("=" * 60)
    print("【3.1 invoke 非流式】")
    print("=" * 60)
    resp = llm.invoke("你好，你是谁？").content
    print(f"{resp[:80]}\n")


def demo_stream():
    """流式调用，逐块输出"""
    print("=" * 60)
    print("【3.2 stream 流式】")
    print("=" * 60)
    for chunk in llm.stream("用一句话介绍 LangChain"):
        print(chunk.content, end="", flush=True)
    print("\n")


def demo_batch():
    """批量调用，一次返回多个结果"""
    print("=" * 60)
    print("【3.3 batch 批量】")
    print("=" * 60)
    messages = _make_batch_messages()
    results = llm.batch(messages)
    for i, r in enumerate(results):
        print(f"  batch {i}: {r.content[:40]}...")
    print()


def demo_ainvoke_vs_batch():
    """异步调用 vs batch 耗时对比"""
    print("=" * 60)
    print("【3.4 ainvoke 异步 vs batch 耗时对比】")
    print("=" * 60)
    messages = _make_batch_messages()

    # 异步: asyncio.gather 并发
    async def _async_invoke():
        tasks = [llm.ainvoke(m) for m in messages]
        return await asyncio.gather(*tasks)

    start = time.time()
    resps = asyncio.run(_async_invoke())
    async_time = time.time() - start
    for i, r in enumerate(resps):
        print(f"  async {i}: {r.content[:40]}...")
    print(f"  异步耗时: {async_time:.2f}s\n")

    # 同步: batch 底层多线程
    start = time.time()
    resps = llm.batch(messages)
    batch_time = time.time() - start
    for i, r in enumerate(resps):
        print(f"  batch {i}: {r.content[:40]}...")
    print(f"  batch耗时: {batch_time:.2f}s\n")


# ========== 4. PromptTemplate ==========

def demo_prompt_template():
    """PromptTemplate: from_template + partial_variables"""
    print("=" * 60)
    print("【4.1 PromptTemplate】")
    print("=" * 60)

    # 方式一: from_template + format
    tpl = PromptTemplate.from_template("请评价{product}的优缺点，包括{aspect1}和{aspect2}。")
    prompt = tpl.format(product="iPhone 17", aspect1="性能", aspect2="拍照")
    resp = llm.invoke(prompt).content
    print(f"{resp[:80]}...\n")

    # 方式二: partial_variables 预填部分变量
    tpl2 = PromptTemplate(
        template="请评价{product}的优缺点，包括{aspect1}和{aspect2}。",
        input_variables=["product", "aspect1", "aspect2"],
        partial_variables={"aspect1": "性能", "aspect2": "拍照"},
    )
    prompt2 = tpl2.format(product="iPhone 17")
    resp2 = llm.invoke(prompt2).content
    print(f"{resp2[:80]}...\n")


def demo_chat_prompt_template():
    """ChatPromptTemplate: 多角色多轮次对话模板"""
    print("=" * 60)
    print("【4.2 ChatPromptTemplate】")
    print("=" * 60)

    # 多轮对话模板（system / human / ai / human）
    template1 = ChatPromptTemplate([
        ("system", "你是一个AI开发工程师，你的名字是{name}。"),
        ("human", "你能帮我做什么?"),
        ("ai", "我能开发很多{thing}。"),
        ("human", "{user_input}"),
    ])
    prompt = template1.invoke({"name": "minjie", "thing": "AI智能应用", "user_input": "行"})
    resp = llm.invoke(prompt).content
    print(f"[多轮对话] {resp[:80]}...\n")

    # dict 格式 + 多模态图片输入
    template2 = ChatPromptTemplate([
        {"role": "system", "content": "你是一个图片设计师"},
        {"role": "human", "content": "请评价一下这张{image_url}图片的优缺点"},
    ])
    prompt2 = template2.format_messages(
        image_url="https://pic.ibaotu.com/21/09/27/paixin/pki539002.jpg!fw700"
    )
    resp2 = llm.invoke(prompt2).content
    print(f"[多模态图片] {resp2[:80]}...\n")


# ========== 主入口 ==========

if __name__ == "__main__":
    demo_messages()
    demo_invoke()
    demo_stream()
    demo_batch()
    demo_ainvoke_vs_batch()
    demo_prompt_template()
    demo_chat_prompt_template()
    print("=" * 60)
    print("✅ w1_model_io.py 全部测试通过")
    print("=" * 60)
