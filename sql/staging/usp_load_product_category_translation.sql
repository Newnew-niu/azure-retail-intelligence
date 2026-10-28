/*
    stg.usp_load_product_category_translation
        : raw.product_category_translation -> stg.product_category_translation   (key: category_name_pt)
    Same pattern as stg.usp_load_orders (see that file for the step-by-step description).
    Two categories used by products have no translation in the source; the English
    fallback is applied in the product dimension, not here.
*/
CREATE OR ALTER PROCEDURE stg.usp_load_product_category_translation
    @run_id   NVARCHAR(100),
    @batch_id NVARCHAR(50) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @step_id INT, @rows_read INT, @rows_rejected INT, @rows_written INT;
    EXEC ops.usp_step_start @run_id = @run_id, @step_name = N'stg.usp_load_product_category_translation',
                            @target_object = N'stg.product_category_translation', @step_id = @step_id OUTPUT;
    BEGIN TRY
        WITH latest AS (
            SELECT r.*,
                   ROW_NUMBER() OVER (PARTITION BY r.product_category_name ORDER BY r.loaded_at_utc DESC, r.batch_id DESC) AS version_rank
              FROM raw.product_category_translation AS r
             WHERE @batch_id IS NULL OR r.batch_id = @batch_id
        )
        SELECT l.product_category_name AS record_key,
               l.batch_id,
               t.*,
               CASE
                   WHEN t.category_name_pt IS NULL THEN N'product_category_name is empty'
                   WHEN t.category_name_en IS NULL THEN N'product_category_name_english is empty'
               END AS reject_reason
          INTO #src
          FROM latest AS l
         CROSS APPLY (SELECT
                NULLIF(TRIM(l.product_category_name), N'')         AS category_name_pt,
                NULLIF(TRIM(l.product_category_name_english), N'') AS category_name_en
         ) AS t
         WHERE l.version_rank = 1
            OR l.product_category_name IS NULL;

        SELECT @rows_read = COUNT(*), @rows_rejected = COUNT(reject_reason) FROM #src;

        BEGIN TRANSACTION;

        INSERT ops.rejected_row (run_id, step_id, source_table, batch_id, record_key, reason)
        SELECT @run_id, @step_id, N'raw.product_category_translation', batch_id, LEFT(record_key, 400), reject_reason
          FROM #src
         WHERE reject_reason IS NOT NULL;

        MERGE stg.product_category_translation WITH (HOLDLOCK) AS tgt
        USING (SELECT * FROM #src WHERE reject_reason IS NULL) AS src
           ON tgt.category_name_pt = src.category_name_pt
         WHEN MATCHED AND EXISTS (SELECT src.category_name_en EXCEPT SELECT tgt.category_name_en)
              THEN UPDATE SET
                   category_name_en = src.category_name_en,
                   batch_id = src.batch_id, run_id = @run_id, updated_at_utc = SYSUTCDATETIME()
         WHEN NOT MATCHED BY TARGET
              THEN INSERT (category_name_pt, category_name_en, batch_id, run_id)
                   VALUES (src.category_name_pt, src.category_name_en, src.batch_id, @run_id);
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
