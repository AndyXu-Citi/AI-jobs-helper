-- ============================================================
-- AI Collector Project — MySQL 建表脚本
-- ============================================================
-- 用法：
--   1. 确保 MySQL 服务已运行
--   2. mysql -u root -p < scripts/init_db.sql
--   3. 在 .env 中配置 DB_HOST/DB_USER/DB_PASSWORD/DB_NAME
--
-- 或者不手动执行也行：首次启动时 DBManager 会自动执行建表。
-- ============================================================

CREATE DATABASE IF NOT EXISTS ai_collector
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;

USE ai_collector;

-- ============================================================
-- 1. URL 历史表
--    记录所有见过并处理过的 URL
-- ============================================================
CREATE TABLE IF NOT EXISTS urls_history (
    url             VARCHAR(255) PRIMARY KEY,
    first_seen_at   DATETIME,
    last_seen_at    DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================================
-- 2. 任务队列表
--    驱动采集和处理的流程
-- ============================================================
CREATE TABLE IF NOT EXISTS task_queue (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    url             VARCHAR(255) UNIQUE,
    status          VARCHAR(20) DEFAULT 'PENDING',
    source_type     VARCHAR(50) DEFAULT 'bilibili',
    retry_count     INT DEFAULT 0,
    error_message   TEXT,
    last_attempt_at DATETIME,
    created_at      DATETIME,
    INDEX idx_tq_status (status),
    INDEX idx_tq_source (source_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================================
-- 3. 原始内容表
--    存储 Playwright/API 采集的原始文本（Markdown / JSON）
-- ============================================================
CREATE TABLE IF NOT EXISTS raw_contents (
    url             VARCHAR(255) PRIMARY KEY,
    markdown_text   LONGTEXT,
    collected_at    DATETIME,
    FOREIGN KEY (url) REFERENCES task_queue(url)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================================
-- 4. 最终结果表
--    存储 LLM 清洗后的结构化数据 / Boss API 直接入库的结构化数据
-- ============================================================
CREATE TABLE IF NOT EXISTS final_results (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    url             VARCHAR(255),
    source_type     VARCHAR(50) DEFAULT 'bilibili',
    structured_json LONGTEXT,
    processed_at    DATETIME,
    INDEX idx_fr_source (source_type),
    INDEX idx_fr_url (url),
    FOREIGN KEY (url) REFERENCES task_queue(url)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================================
-- 5. Agent 运行记录表（原 agent_runs.db）
--    每次跑 Agent 自动落一条，用于 Bad Case 闭环
-- ============================================================
CREATE TABLE IF NOT EXISTS agent_runs (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    run_at          DATETIME NOT NULL,
    query           TEXT NOT NULL,
    result_count    INT NOT NULL,
    elapsed_seconds FLOAT DEFAULT 0,
    reflect_rounds  INT DEFAULT 0,
    status          VARCHAR(20) NOT NULL DEFAULT 'unreviewed',
    root_cause      TEXT,
    fix_commit      VARCHAR(40) DEFAULT '',
    fix_notes       TEXT,
    trace_json      LONGTEXT,
    final_report    LONGTEXT,
    INDEX idx_ar_status (status),
    INDEX idx_ar_run_at (run_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
