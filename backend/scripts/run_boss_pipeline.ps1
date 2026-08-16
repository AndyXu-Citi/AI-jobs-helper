# Boss 直聘一键采集流水线（PowerShell 快捷入口）
#
# 用法：
#   .\run_boss_pipeline.ps1
#   .\run_boss_pipeline.ps1 -Cities "杭州,苏州" -Keywords "AI应用开发,Agent" -Pages 2
#   .\run_boss_pipeline.ps1 -SmokeTest "杭州 AI 应用开发"
#   .\run_boss_pipeline.ps1 -SkipEnrich -NoRebuild
#   .\run_boss_pipeline.ps1 -SkipExtractSkills        # 跳过 LLM 技能提取（不调 LLM）
#   .\run_boss_pipeline.ps1 -ForceExtract              # 强制重提全部 JD 技能
#
# 任意参数都会原样透传给 run_boss_pipeline.py，所以也可以用 --cities 等长参数。

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PipelineArgs
)

$ErrorActionPreference = "Stop"

$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

& $python "run_boss_crawler_pipeline.py" @PipelineArgs
