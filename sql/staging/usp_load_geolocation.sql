/*
    stg.usp_load_geolocation : raw.geolocation -> stg.geolocation     (key: zip_code_prefix)

    Different from the other staging procedures on purpose:
      * The source is reference data with no natural key (~53 rows per zip prefix, 261,831
        exact duplicates), so it is SUMMARISED to one row per prefix instead of merged.
      * It is rebuilt from ALL raw batches every time (@batch_id is accepted for a uniform
        interface but ignored): a new batch can change the average of an existing prefix.
      * Points outside Brazil's bounding box are excluded from the averages and counted.
      * State = most frequent state for the prefix (8 prefixes appear under 2 states).
      * City names are not taken from this table: they are spelled inconsistently
        ('sao paulo', 'são paulo', 'saopaulo'); customer and seller tables carry city instead.
*/
CREATE OR ALTER PROCEDURE stg.usp_load_geolocation
    @run_id   NVARCHAR(100),
    @batch_id NVARCHAR(50) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @step_id INT, @rows_read INT, @rows_rejected INT, @rows_written INT;
    EXEC ops.usp_step_start @run_id = @run_id, @step_name = N'stg.usp_load_geolocation',
                            @target_object = N'stg.geolocation', @step_id = @step_id OUTPUT;
    BEGIN TRY
        SELECT r.batch_id,
               r.geolocation_zip_code_prefix AS record_key,
               CONVERT(CHAR(5), r.geolocation_zip_code_prefix) AS zip_code_prefix,
               UPPER(TRIM(r.geolocation_state))                 AS state,
               t.latitude,
               t.longitude,
               CASE WHEN t.latitude BETWEEN -34.0 AND 5.5 AND t.longitude BETWEEN -74.0 AND -34.0
                    THEN 1 ELSE 0 END AS inside_brazil,
               CASE
                   WHEN stg.fn_is_zip5(r.geolocation_zip_code_prefix) = 0 THEN N'geolocation_zip_code_prefix is not 5 digits'
                   WHEN LEN(TRIM(r.geolocation_state)) <> 2 OR r.geolocation_state IS NULL
                                                                         THEN N'geolocation_state is not a 2-letter code'
                   WHEN t.latitude IS NULL OR t.longitude IS NULL        THEN N'latitude/longitude is not a number'
               END AS reject_reason
          INTO #src
          FROM raw.geolocation AS r
         CROSS APPLY (SELECT TRY_CONVERT(FLOAT, r.geolocation_lat) AS latitude,
                             TRY_CONVERT(FLOAT, r.geolocation_lng) AS longitude) AS t;

        SELECT @rows_read = COUNT(*), @rows_rejected = COUNT(reject_reason) FROM #src;

        BEGIN TRANSACTION;

        INSERT ops.rejected_row (run_id, step_id, source_table, batch_id, record_key, reason)
        SELECT @run_id, @step_id, N'raw.geolocation', batch_id, LEFT(record_key, 400), reject_reason
          FROM #src
         WHERE reject_reason IS NOT NULL;

        DELETE FROM stg.geolocation;

        WITH valid AS (
            SELECT * FROM #src WHERE reject_reason IS NULL
        ),
        state_rank AS (
            SELECT zip_code_prefix, state,
                   ROW_NUMBER() OVER (PARTITION BY zip_code_prefix ORDER BY COUNT(*) DESC, state) AS rn
              FROM valid
             GROUP BY zip_code_prefix, state
        )
        INSERT stg.geolocation (zip_code_prefix, latitude, longitude, state, source_rows, excluded_points, run_id)
        SELECT v.zip_code_prefix,
               CONVERT(DECIMAL(9,6), AVG(CASE WHEN v.inside_brazil = 1 THEN v.latitude END)),
               CONVERT(DECIMAL(9,6), AVG(CASE WHEN v.inside_brazil = 1 THEN v.longitude END)),
               s.state,
               COUNT(*),
               SUM(1 - v.inside_brazil),
               @run_id
          FROM valid AS v
          JOIN state_rank AS s ON s.zip_code_prefix = v.zip_code_prefix AND s.rn = 1
         GROUP BY v.zip_code_prefix, s.state;
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
