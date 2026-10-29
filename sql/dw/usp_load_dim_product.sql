/*
    dw.usp_load_dim_product : stg.products (+ category translation) -> dw.dim_product   (SCD type 1)

    Category rules (documented so report totals by category can be explained):
      * 610 products have no category in the source       -> 'sem_categoria' / 'uncategorised'
      * 13 products are in 2 categories with no English name in the translation file
        ('pc_gamer', 'portateis_cozinha_e_preparadores_de_alimentos')
                                                           -> English name = Portuguese name,
                                                              is_category_translated = 0
    Same change-only MERGE pattern as dw.usp_load_dim_customer.
*/
CREATE OR ALTER PROCEDURE dw.usp_load_dim_product
    @run_id   NVARCHAR(100),
    @batch_id NVARCHAR(50) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @step_id INT, @rows_read INT, @rows_written INT;
    EXEC ops.usp_step_start @run_id = @run_id, @step_name = N'dw.usp_load_dim_product',
                            @target_object = N'dw.dim_product', @step_id = @step_id OUTPUT;
    BEGIN TRY
        SELECT p.product_id,
               COALESCE(p.category_name_pt, N'sem_categoria')                       AS category_name_pt,
               CASE WHEN p.category_name_pt IS NULL THEN N'uncategorised'
                    ELSE COALESCE(t.category_name_en, p.category_name_pt) END        AS category_name_en,
               CASE WHEN p.category_name_pt IS NULL OR t.category_name_en IS NOT NULL THEN 1 ELSE 0 END
                                                                                    AS is_category_translated,
               p.name_length, p.description_length, p.photos_qty, p.weight_g, p.length_cm, p.height_cm, p.width_cm
          INTO #src
          FROM stg.products AS p
          LEFT JOIN stg.product_category_translation AS t ON t.category_name_pt = p.category_name_pt;
        SET @rows_read = @@ROWCOUNT;

        MERGE dw.dim_product WITH (HOLDLOCK) AS tgt
        USING #src AS src
           ON tgt.product_id = src.product_id
         WHEN MATCHED AND EXISTS (
                  SELECT src.category_name_pt, src.category_name_en, src.is_category_translated, src.name_length,
                         src.description_length, src.photos_qty, src.weight_g, src.length_cm, src.height_cm, src.width_cm
                  EXCEPT
                  SELECT tgt.category_name_pt, tgt.category_name_en, tgt.is_category_translated, tgt.name_length,
                         tgt.description_length, tgt.photos_qty, tgt.weight_g, tgt.length_cm, tgt.height_cm, tgt.width_cm)
              THEN UPDATE SET category_name_pt = src.category_name_pt, category_name_en = src.category_name_en,
                              is_category_translated = src.is_category_translated, name_length = src.name_length,
                              description_length = src.description_length, photos_qty = src.photos_qty,
                              weight_g = src.weight_g, length_cm = src.length_cm, height_cm = src.height_cm,
                              width_cm = src.width_cm, run_id = @run_id, updated_at_utc = SYSUTCDATETIME()
         WHEN NOT MATCHED BY TARGET
              THEN INSERT (product_id, category_name_pt, category_name_en, is_category_translated, name_length,
                           description_length, photos_qty, weight_g, length_cm, height_cm, width_cm, run_id)
                   VALUES (src.product_id, src.category_name_pt, src.category_name_en, src.is_category_translated,
                           src.name_length, src.description_length, src.photos_qty, src.weight_g, src.length_cm,
                           src.height_cm, src.width_cm, @run_id);
        SET @rows_written = @@ROWCOUNT;

        EXEC ops.usp_step_end @step_id = @step_id, @status = N'SUCCEEDED', @rows_read = @rows_read,
                              @rows_written = @rows_written, @rows_rejected = 0;
    END TRY
    BEGIN CATCH
        DECLARE @error NVARCHAR(4000) = ERROR_MESSAGE();
        EXEC ops.usp_step_end @step_id = @step_id, @status = N'FAILED', @error_message = @error;
        THROW;
    END CATCH;
END;
GO
