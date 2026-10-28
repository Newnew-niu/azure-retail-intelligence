/*
    Logging procedures. Called by the local runner and by ADF Stored Procedure activities,
    so both execution paths produce the same operational metadata.
*/

CREATE OR ALTER PROCEDURE ops.usp_run_start
    @run_id         NVARCHAR(100),
    @pipeline_name  NVARCHAR(100),
    @batch_id       NVARCHAR(50) = NULL,
    @trigger_source NVARCHAR(20)
AS
BEGIN
    SET NOCOUNT ON;
    -- A rerun with the same run_id (e.g. ADF activity retry) resets the run instead of failing on the key.
    UPDATE ops.pipeline_run
       SET status = N'RUNNING', started_at_utc = SYSUTCDATETIME(), ended_at_utc = NULL, error_message = NULL
     WHERE run_id = @run_id;

    IF @@ROWCOUNT = 0
        INSERT ops.pipeline_run (run_id, pipeline_name, batch_id, trigger_source, status)
        VALUES (@run_id, @pipeline_name, @batch_id, @trigger_source, N'RUNNING');
END;
GO

CREATE OR ALTER PROCEDURE ops.usp_run_end
    @run_id        NVARCHAR(100),
    @status        NVARCHAR(20),
    @error_message NVARCHAR(4000) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE ops.pipeline_run
       SET status = @status, ended_at_utc = SYSUTCDATETIME(), error_message = @error_message
     WHERE run_id = @run_id;

    IF @@ROWCOUNT = 0
        THROW 50001, N'ops.usp_run_end: unknown run_id', 1;
END;
GO

CREATE OR ALTER PROCEDURE ops.usp_step_start
    @run_id        NVARCHAR(100),
    @step_name     NVARCHAR(200),
    @target_object NVARCHAR(200) = NULL,
    @step_id       INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    INSERT ops.step_log (run_id, step_name, target_object, status)
    VALUES (@run_id, @step_name, @target_object, N'RUNNING');
    SET @step_id = SCOPE_IDENTITY();
END;
GO

CREATE OR ALTER PROCEDURE ops.usp_step_end
    @step_id       INT,
    @status        NVARCHAR(20),
    @rows_read     INT = NULL,
    @rows_written  INT = NULL,
    @rows_rejected INT = NULL,
    @error_message NVARCHAR(4000) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE ops.step_log
       SET status = @status, rows_read = @rows_read, rows_written = @rows_written,
           rows_rejected = @rows_rejected, error_message = @error_message, ended_at_utc = SYSUTCDATETIME()
     WHERE step_id = @step_id;
END;
GO

/*
    One-call step log for ADF Copy activities. A Stored Procedure activity cannot read an
    OUTPUT parameter, so ADF cannot use usp_step_start/usp_step_end around a Copy; instead it
    logs the finished copy once, with the counts and duration from the Copy activity output.
*/
CREATE OR ALTER PROCEDURE ops.usp_log_copy
    @run_id           NVARCHAR(100),
    @step_name        NVARCHAR(200),
    @target_object    NVARCHAR(200),
    @status           NVARCHAR(20),
    @rows_read        INT = NULL,
    @rows_written     INT = NULL,
    @duration_seconds INT = NULL,
    @error_message    NVARCHAR(4000) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @ended DATETIME2(3) = SYSUTCDATETIME();
    INSERT ops.step_log (run_id, step_name, target_object, status, rows_read, rows_written, rows_rejected,
                         started_at_utc, ended_at_utc, error_message)
    VALUES (@run_id, @step_name, @target_object, @status, @rows_read, @rows_written,
            @rows_read - @rows_written,  -- rows the copy skipped (0 unless fault tolerance is enabled)
            DATEADD(SECOND, -ISNULL(@duration_seconds, 0), @ended), @ended, @error_message);
END;
GO
