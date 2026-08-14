"""
协程入门 demo —— 同步 vs 协程 抓 5 个岗位页面的耗时对比
场景：模拟采集 Boss 直聘，每个页面"等服务器响应"2 秒（IO 等待）
"""
import asyncio  # 导入 asyncio：Python 标准库，提供事件循环、协程调度、并发原语
import time  # 导入 time：用来 time.sleep() 阻塞等待，以及 time.time() 计时


# ---------- 第一版：同步（傻等） ----------
def fetch_job_sync(job_id):  # 定义普通同步函数，模拟抓取单个岗位；job_id 是岗位编号
    print(f"  开始抓岗位 {job_id} ...")  # 打印开始日志，f-string 把 job_id 嵌入字符串
    time.sleep(2)              # 模拟"等服务器响应 2 秒"——程序在这里傻站着（阻塞整个线程，什么都干不了）
    print(f"  岗位 {job_id} 抓完")  # 等待结束后打印完成日志
    return f"岗位{job_id}的数据"  # 返回这个岗位的"数据"（这里用字符串模拟真实返回内容）


def run_sync():  # 定义同步版的总调度函数，串行抓取 5 个岗位
    print("【同步版】一个接一个抓：")  # 打印小标题，提示进入同步模式
    start = time.time()  # 记录开始时间戳（秒），用于最后计算总耗时
    results = []  # 初始化空列表，用来收集每个岗位返回的数据
    for jid in range(1, 6):    # 抓 5 个（range(1, 6) 生成 1,2,3,4,5，不含 6）
        results.append(fetch_job_sync(jid))  # 逐个调用同步抓取，必须等上一个抓完才抓下一个
    print(f"  同步总耗时：{time.time() - start:.1f} 秒\n")  # 当前时间减开始时间=总耗时，:.1f 保留 1 位小数，\n 末尾换行
    return results  # 返回收集到的 5 条岗位数据列表


# ---------- 第二版：协程（等的时候去干别的） ----------
async def fetch_job_async(job_id):  # async def 定义协程函数；调用它返回协程对象，不会立即执行
    print(f"  开始抓岗位 {job_id} ...")  # 打印开始日志（与同步版一致）
    await asyncio.sleep(2)     # 关键：await——"我要等了，把控制权交出去，让别的岗位也开抓"（非阻塞等待）
    print(f"  岗位 {job_id} 抓完")  # 等待结束、事件循环把控制权交还后，打印完成日志
    return f"岗位{job_id}的数据"  # 返回这个岗位的"数据"（协程的返回值由 await/gather 取回）


async def run_async():  # 定义协程版的总调度函数，并发抓取 5 个岗位
    print("【协程版】5 个一起抓，一起等：")  # 打印小标题，提示进入协程模式
    start = time.time()  # 记录开始时间戳，用于最后计算总耗时
    # asyncio.gather = "把这 5 个任务一起扔出去，并发跑"
    tasks = [fetch_job_async(jid) for jid in range(1, 6)]  # 列表推导式创建 5 个协程对象（此时还未真正运行）
    results = await asyncio.gather(*tasks)  # gather 并发调度所有协程；* 解包列表为多个参数；await 等全部完成并按顺序收集结果
    print(f"  协程总耗时：{time.time() - start:.1f} 秒\n")  # 计算并打印总耗时（预期约 2 秒，因为 5 个等待重叠）
    return results  # 返回 5 条岗位数据列表（顺序与传入的协程顺序一致）


if __name__ == "__main__":  # 只有直接运行本文件时才执行下面代码；被 import 时不会触发
    run_sync()                 # 同步：预计约 10 秒（5 × 2）——串行累加，无法重叠等待
    asyncio.run(run_async())   # 协程：预计约 2 秒（5 个一起等）——asyncio.run 启动事件循环并跑完 run_async
