/*
    Format checks shared by the staging procedures.
    All Olist identifiers are 32-character hexadecimal strings (MD5-style hashes).
*/
CREATE OR ALTER FUNCTION stg.fn_is_hex32 (@value NVARCHAR(255))
RETURNS BIT
WITH SCHEMABINDING
AS
BEGIN
    RETURN CASE WHEN LEN(@value) = 32 AND @value NOT LIKE N'%[^0-9a-f]%' THEN 1 ELSE 0 END;
END;
GO

-- Brazilian CEP prefix: exactly five digits (leading zeros are significant).
CREATE OR ALTER FUNCTION stg.fn_is_zip5 (@value NVARCHAR(255))
RETURNS BIT
WITH SCHEMABINDING
AS
BEGIN
    RETURN CASE WHEN LEN(@value) = 5 AND @value NOT LIKE N'%[^0-9]%' THEN 1 ELSE 0 END;
END;
GO
