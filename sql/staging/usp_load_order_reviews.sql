/*
    stg.usp_load_order_reviews : raw.order_reviews -> stg.order_reviews   (key: review_id, order_id)
    Same pattern as stg.usp_load_orders (see that file for the step-by-step description).
    review_id alone is NOT unique in the source (the same review can be linked to several
    orders), and an order can have several reviews - consumers must aggregate per order.
*/
CREATE OR ALTER PROCEDURE stg.usp_load_order_reviews
    @run_id   NVARCHAR(100),
    @batch_id NVARCHAR(50) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @step_id INT, @rows_read INT, @rows_rejected INT, @rows_written INT;
    EXEC ops.usp_step_start @run_id = @run_id, @step_name = N'stg.usp_load_order_reviews',
                            @target_object = N'stg.order_reviews', @step_id = @step_id OUTPUT;
    BEGIN TRY
        WITH latest AS (
            SELECT r.*,
                   ROW_NUMBER() OVER (PARTITION BY r.review_id, r.order_id
                                      ORDER BY r.loaded_at_utc DESC, r.batch_id DESC) AS version_rank
              FROM raw.order_reviews AS r
             WHERE @batch_id IS NULL OR r.batch_id = @batch_id
        )
        SELECT CONCAT(l.review_id, N'|', l.order_id) AS record_key,
               l.batch_id,
               t.*,
               CASE
                   WHEN stg.fn_is_hex32(l.review_id) = 0 THEN N'review_id is not a 32-character hex id'
                   WHEN stg.fn_is_hex32(l.order_id) = 0  THEN N'order_id is not a 32-character hex id'
                   WHEN t.review_score IS NULL           THEN N'review_score is empty or not an integer'
                   WHEN t.created_at IS NULL             THEN N'review_creation_date is empty or not a timestamp'
                   WHEN t.answered_at IS NULL            THEN N'review_answer_timestamp is empty or not a timestamp'
               END AS reject_reason
          INTO #src
          FROM latest AS l
         CROSS APPLY (SELECT
                CONVERT(CHAR(32), l.review_id)                            AS review_id,
                CONVERT(CHAR(32), l.order_id)                             AS order_id,
                TRY_CONVERT(INT, l.review_score)                          AS review_score,
                NULLIF(TRIM(l.review_comment_title), N'')                 AS comment_title,
                NULLIF(TRIM(l.review_comment_message), N'')               AS comment_message,
                TRY_CONVERT(DATETIME2(0), l.review_creation_date, 120)    AS created_at,
                TRY_CONVERT(DATETIME2(0), l.review_answer_timestamp, 120) AS answered_at
         ) AS t
         WHERE l.version_rank = 1
            OR l.review_id IS NULL OR l.order_id IS NULL;

        SELECT @rows_read = COUNT(*), @rows_rejected = COUNT(reject_reason) FROM #src;

        BEGIN TRANSACTION;

        INSERT ops.rejected_row (run_id, step_id, source_table, batch_id, record_key, reason)
        SELECT @run_id, @step_id, N'raw.order_reviews', batch_id, LEFT(record_key, 400), reject_reason
          FROM #src
         WHERE reject_reason IS NOT NULL;

        MERGE stg.order_reviews WITH (HOLDLOCK) AS tgt
        USING (SELECT * FROM #src WHERE reject_reason IS NULL) AS src
           ON tgt.review_id = src.review_id AND tgt.order_id = src.order_id
         WHEN MATCHED AND EXISTS (
                  SELECT src.review_score, src.comment_title, src.comment_message, src.created_at, src.answered_at
                  EXCEPT
                  SELECT tgt.review_score, tgt.comment_title, tgt.comment_message, tgt.created_at, tgt.answered_at)
              THEN UPDATE SET
                   review_score = src.review_score, comment_title = src.comment_title,
                   comment_message = src.comment_message, created_at = src.created_at, answered_at = src.answered_at,
                   batch_id = src.batch_id, run_id = @run_id, updated_at_utc = SYSUTCDATETIME()
         WHEN NOT MATCHED BY TARGET
              THEN INSERT (review_id, order_id, review_score, comment_title, comment_message, created_at, answered_at,
                           batch_id, run_id)
                   VALUES (src.review_id, src.order_id, src.review_score, src.comment_title, src.comment_message,
                           src.created_at, src.answered_at, src.batch_id, @run_id);
        SET @rows_written = @@ROWCOUNT;

        COMMIT TRANSACTION;

        EXEC ops.usp_step_end @step_id = @step_id, @status = N'SUCCEEDED', @rows_read = @rows_read,
                              @rows_written = @rows_written, @rows_rejected = @rows_rejected;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
        DECLARE @error NVARCHAR(4000) = ERROR_MESSAGE();
        EXEC ops.usp_step_end @step_id = @step_id, @status = N'FAILED', @error_message = @error;
        THROW;
    END CATCH;
END;
GO
