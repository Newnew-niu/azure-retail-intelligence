/*
    stg.usp_load_products : raw.products -> stg.products        (key: product_id)
    Same pattern as stg.usp_load_orders (see that file for the step-by-step description).
    Renames the source typos product_name_lenght / product_description_lenght.
    Category and measurements are optional (missing for some products in the source).
*/
CREATE OR ALTER PROCEDURE stg.usp_load_products
    @run_id   NVARCHAR(100),
    @batch_id NVARCHAR(50) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @step_id INT, @rows_read INT, @rows_rejected INT, @rows_written INT;
    EXEC ops.usp_step_start @run_id = @run_id, @step_name = N'stg.usp_load_products',
                            @target_object = N'stg.products', @step_id = @step_id OUTPUT;
    BEGIN TRY
        WITH latest AS (
            SELECT r.*,
                   ROW_NUMBER() OVER (PARTITION BY r.product_id ORDER BY r.loaded_at_utc DESC, r.batch_id DESC) AS version_rank
              FROM raw.products AS r
             WHERE @batch_id IS NULL OR r.batch_id = @batch_id
        )
        SELECT l.product_id AS record_key,
               l.batch_id,
               t.*,
               CASE
                   WHEN stg.fn_is_hex32(l.product_id) = 0 THEN N'product_id is not a 32-character hex id'
                   -- An optional value that is present but not an integer is unstorable.
                   WHEN l.product_name_lenght        IS NOT NULL AND t.name_length        IS NULL THEN N'product_name_lenght is not an integer'
                   WHEN l.product_description_lenght IS NOT NULL AND t.description_length IS NULL THEN N'product_description_lenght is not an integer'
                   WHEN l.product_photos_qty         IS NOT NULL AND t.photos_qty         IS NULL THEN N'product_photos_qty is not an integer'
                   WHEN l.product_weight_g           IS NOT NULL AND t.weight_g           IS NULL THEN N'product_weight_g is not an integer'
                   WHEN l.product_length_cm          IS NOT NULL AND t.length_cm          IS NULL THEN N'product_length_cm is not an integer'
                   WHEN l.product_height_cm          IS NOT NULL AND t.height_cm          IS NULL THEN N'product_height_cm is not an integer'
                   WHEN l.product_width_cm           IS NOT NULL AND t.width_cm           IS NULL THEN N'product_width_cm is not an integer'
               END AS reject_reason
          INTO #src
          FROM latest AS l
         CROSS APPLY (SELECT
                CONVERT(CHAR(32), l.product_id)                  AS product_id,
                NULLIF(TRIM(l.product_category_name), N'')       AS category_name_pt,
                TRY_CONVERT(INT, l.product_name_lenght)          AS name_length,
                TRY_CONVERT(INT, l.product_description_lenght)   AS description_length,
                TRY_CONVERT(INT, l.product_photos_qty)           AS photos_qty,
                TRY_CONVERT(INT, l.product_weight_g)             AS weight_g,
                TRY_CONVERT(INT, l.product_length_cm)            AS length_cm,
                TRY_CONVERT(INT, l.product_height_cm)            AS height_cm,
                TRY_CONVERT(INT, l.product_width_cm)             AS width_cm
         ) AS t
         WHERE l.version_rank = 1
            OR l.product_id IS NULL;

        SELECT @rows_read = COUNT(*), @rows_rejected = COUNT(reject_reason) FROM #src;

        BEGIN TRANSACTION;

        INSERT ops.rejected_row (run_id, step_id, source_table, batch_id, record_key, reason)
        SELECT @run_id, @step_id, N'raw.products', batch_id, LEFT(record_key, 400), reject_reason
          FROM #src
         WHERE reject_reason IS NOT NULL;

        MERGE stg.products WITH (HOLDLOCK) AS tgt
        USING (SELECT * FROM #src WHERE reject_reason IS NULL) AS src
           ON tgt.product_id = src.product_id
         WHEN MATCHED AND EXISTS (
                  SELECT src.category_name_pt, src.name_length, src.description_length, src.photos_qty,
                         src.weight_g, src.length_cm, src.height_cm, src.width_cm
                  EXCEPT
                  SELECT tgt.category_name_pt, tgt.name_length, tgt.description_length, tgt.photos_qty,
                         tgt.weight_g, tgt.length_cm, tgt.height_cm, tgt.width_cm)
              THEN UPDATE SET
                   category_name_pt = src.category_name_pt, name_length = src.name_length,
                   description_length = src.description_length, photos_qty = src.photos_qty,
                   weight_g = src.weight_g, length_cm = src.length_cm, height_cm = src.height_cm, width_cm = src.width_cm,
                   batch_id = src.batch_id, run_id = @run_id, updated_at_utc = SYSUTCDATETIME()
         WHEN NOT MATCHED BY TARGET
              THEN INSERT (product_id, category_name_pt, name_length, description_length, photos_qty,
                           weight_g, length_cm, height_cm, width_cm, batch_id, run_id)
                   VALUES (src.product_id, src.category_name_pt, src.name_length, src.description_length, src.photos_qty,
                           src.weight_g, src.length_cm, src.height_cm, src.width_cm, src.batch_id, @run_id);
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
