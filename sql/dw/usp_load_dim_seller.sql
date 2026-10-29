/*
    dw.usp_load_dim_seller : stg.sellers (+ stg.geolocation) -> dw.dim_seller   (SCD type 1)
    Same change-only MERGE pattern as dw.usp_load_dim_customer.
*/
CREATE OR ALTER PROCEDURE dw.usp_load_dim_seller
    @run_id   NVARCHAR(100),
    @batch_id NVARCHAR(50) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @step_id INT, @rows_read INT, @rows_written INT;
    EXEC ops.usp_step_start @run_id = @run_id, @step_name = N'dw.usp_load_dim_seller',
                            @target_object = N'dw.dim_seller', @step_id = @step_id OUTPUT;
    BEGIN TRY
        SELECT s.seller_id, s.zip_code_prefix, s.city, s.state, g.latitude, g.longitude
          INTO #src
          FROM stg.sellers AS s
          LEFT JOIN stg.geolocation AS g ON g.zip_code_prefix = s.zip_code_prefix;
        SET @rows_read = @@ROWCOUNT;

        MERGE dw.dim_seller WITH (HOLDLOCK) AS tgt
        USING #src AS src
           ON tgt.seller_id = src.seller_id
         WHEN MATCHED AND EXISTS (
                  SELECT src.zip_code_prefix, src.city, src.state, src.latitude, src.longitude
                  EXCEPT
                  SELECT tgt.zip_code_prefix, tgt.city, tgt.state, tgt.latitude, tgt.longitude)
              THEN UPDATE SET zip_code_prefix = src.zip_code_prefix, city = src.city, state = src.state,
                              latitude = src.latitude, longitude = src.longitude,
                              run_id = @run_id, updated_at_utc = SYSUTCDATETIME()
         WHEN NOT MATCHED BY TARGET
              THEN INSERT (seller_id, zip_code_prefix, city, state, latitude, longitude, run_id)
                   VALUES (src.seller_id, src.zip_code_prefix, src.city, src.state, src.latitude, src.longitude, @run_id);
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
