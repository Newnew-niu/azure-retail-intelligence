/*
    dw.usp_load_dim_date : calendar from 1 January of the earliest year to 31 December of the
    latest year found in any staging date column. Only missing dates are inserted, so the
    calendar grows when a new batch brings a later date and a rerun writes 0 rows.
    Names are built with CHOOSE, not DATENAME, so they do not depend on the session language.
*/
CREATE OR ALTER PROCEDURE dw.usp_load_dim_date
    @run_id   NVARCHAR(100),
    @batch_id NVARCHAR(50) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @step_id INT, @rows_written INT, @first DATE, @last DATE;
    EXEC ops.usp_step_start @run_id = @run_id, @step_name = N'dw.usp_load_dim_date',
                            @target_object = N'dw.dim_date', @step_id = @step_id OUTPUT;
    BEGIN TRY
        SELECT @first = MIN(d), @last = MAX(d)
          FROM (SELECT MIN(CAST(purchased_at AS DATE)) AS lo, MAX(CAST(COALESCE(delivered_customer_at, purchased_at) AS DATE)) AS hi FROM stg.orders
                UNION ALL SELECT MIN(estimated_delivery_date), MAX(estimated_delivery_date) FROM stg.orders
                UNION ALL SELECT MIN(CAST(delivered_carrier_at AS DATE)), MAX(CAST(delivered_carrier_at AS DATE)) FROM stg.orders
                UNION ALL SELECT MIN(CAST(shipping_limit_at AS DATE)), MAX(CAST(shipping_limit_at AS DATE)) FROM stg.order_items
               ) AS r
         CROSS APPLY (VALUES (r.lo), (r.hi)) AS v(d);

        IF @first IS NOT NULL
        BEGIN
            SET @first = DATEFROMPARTS(YEAR(@first), 1, 1);
            SET @last  = DATEFROMPARTS(YEAR(@last), 12, 31);

            -- 0 .. 9999 (27 years) from constants: no numbers table, and no catalog view whose
            -- visible rows depend on the caller's permissions
            WITH ten AS (SELECT v FROM (VALUES (0),(1),(2),(3),(4),(5),(6),(7),(8),(9)) AS t(v)),
            n AS (
                SELECT TOP (DATEDIFF(DAY, @first, @last) + 1)
                       a.v * 1000 + b.v * 100 + c.v * 10 + d.v AS i
                  FROM ten AS a CROSS JOIN ten AS b CROSS JOIN ten AS c CROSS JOIN ten AS d
                 ORDER BY i
            ),
            d AS (
                SELECT DATEADD(DAY, i, @first) AS [date] FROM n
            ),
            c AS (
                SELECT [date],
                       DATEDIFF(DAY, '19000101', [date]) % 7 + 1 AS dow  -- 1900-01-01 was a Monday
                  FROM d
            )
            INSERT dw.dim_date (date_key, [date], [year], quarter, month, month_name, year_month, month_start,
                                day_of_month, day_of_week, day_name, is_weekend)
            SELECT YEAR([date]) * 10000 + MONTH([date]) * 100 + DAY([date]),
                   [date], YEAR([date]), DATEPART(QUARTER, [date]), MONTH([date]),
                   CHOOSE(MONTH([date]), N'January', N'February', N'March', N'April', N'May', N'June', N'July',
                          N'August', N'September', N'October', N'November', N'December'),
                   CONVERT(CHAR(7), [date], 126),
                   DATEFROMPARTS(YEAR([date]), MONTH([date]), 1),
                   DAY([date]), dow,
                   CHOOSE(dow, N'Monday', N'Tuesday', N'Wednesday', N'Thursday', N'Friday', N'Saturday', N'Sunday'),
                   CASE WHEN dow >= 6 THEN 1 ELSE 0 END
              FROM c
             WHERE NOT EXISTS (SELECT 1 FROM dw.dim_date AS x WHERE x.[date] = c.[date]);
            SET @rows_written = @@ROWCOUNT;
        END;

        EXEC ops.usp_step_end @step_id = @step_id, @status = N'SUCCEEDED',
                              @rows_written = @rows_written, @rows_rejected = 0;
    END TRY
    BEGIN CATCH
        DECLARE @error NVARCHAR(4000) = ERROR_MESSAGE();
        EXEC ops.usp_step_end @step_id = @step_id, @status = N'FAILED', @error_message = @error;
        THROW;
    END CATCH;
END;
GO
