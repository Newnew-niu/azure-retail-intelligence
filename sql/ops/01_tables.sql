/*
    Operational metadata: what ran, when, on which batch, with how many rows, and why it failed.
    Written by both the local runner (trigger_source = 'local') and Azure Data Factory ('adf').
*/

-- One row per pipeline execution.
IF OBJECT_ID(N'ops.pipeline_run') IS NULL
CREATE TABLE ops.pipeline_run (
    run_id          NVARCHAR(100)  NOT NULL CONSTRAINT pk_pipeline_run PRIMARY KEY,  -- ADF: pipeline().RunId
    pipeline_name   NVARCHAR(100)  NOT NULL,
    batch_id        NVARCHAR(50)   NULL,
    trigger_source  NVARCHAR(20)   NOT NULL CONSTRAINT ck_pipeline_run_trigger CHECK (trigger_source IN (N'local', N'adf')),
    status          NVARCHAR(20)   NOT NULL CONSTRAINT ck_pipeline_run_status  CHECK (status IN (N'RUNNING', N'SUCCEEDED', N'FAILED')),
    started_at_utc  DATETIME2(3)   NOT NULL CONSTRAINT df_pipeline_run_started DEFAULT SYSUTCDATETIME(),
    ended_at_utc    DATETIME2(3)   NULL,
    error_message   NVARCHAR(4000) NULL
);
GO

-- One row per step (load of one table, one stored procedure) within a run.
IF OBJECT_ID(N'ops.step_log') IS NULL
CREATE TABLE ops.step_log (
    step_id         INT IDENTITY(1, 1) NOT NULL CONSTRAINT pk_step_log PRIMARY KEY,
    run_id          NVARCHAR(100)  NOT NULL CONSTRAINT fk_step_log_run REFERENCES ops.pipeline_run (run_id),
    step_name       NVARCHAR(200)  NOT NULL,
    target_object   NVARCHAR(200)  NULL,
    status          NVARCHAR(20)   NOT NULL CONSTRAINT ck_step_log_status CHECK (status IN (N'RUNNING', N'SUCCEEDED', N'FAILED')),
    rows_read       INT            NULL,
    rows_written    INT            NULL,
    rows_rejected   INT            NULL,
    started_at_utc  DATETIME2(3)   NOT NULL CONSTRAINT df_step_log_started DEFAULT SYSUTCDATETIME(),
    ended_at_utc    DATETIME2(3)   NULL,
    error_message   NVARCHAR(4000) NULL
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_step_log_run' AND object_id = OBJECT_ID(N'ops.step_log'))
    CREATE INDEX ix_step_log_run ON ops.step_log (run_id);
GO

-- Records that could not be converted into staging. They are kept for inspection
-- instead of being silently dropped; staging receives only the valid records.
IF OBJECT_ID(N'ops.rejected_row') IS NULL
CREATE TABLE ops.rejected_row (
    rejected_row_id BIGINT IDENTITY(1, 1) NOT NULL CONSTRAINT pk_rejected_row PRIMARY KEY,
    run_id          NVARCHAR(100)  NOT NULL,
    step_id         INT            NULL,
    source_table    NVARCHAR(200)  NOT NULL,
    batch_id        NVARCHAR(50)   NULL,
    record_key      NVARCHAR(400)  NULL,
    reason          NVARCHAR(400)  NOT NULL,
    logged_at_utc   DATETIME2(3)   NOT NULL CONSTRAINT df_rejected_row_logged DEFAULT SYSUTCDATETIME()
);
GO
