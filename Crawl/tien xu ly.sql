UPDATE new_restaurants
SET opening_hours = REPLACE(
                        REPLACE(
                            opening_hours, 
                            N'\u2013', -- Thay thế dấu gạch ngang dài Unicode
                            N'-'
                        ),
                        N'\u202f', -- Thay thế khoảng trắng hẹp không ngắt
                        N' '
                    );
-- IV. Tạo thủ tục để điền giá trị null bằng giá trị mà người lập trình truyền vào
GO
CREATE PROCEDURE Hand_Null_Value (
   @table_name NVARCHAR(50),
   @column_name NVARCHAR(50),         
   @replace_value NVARCHAR(MAX),
   @data_type NVARCHAR(50)
)
AS
BEGIN
   DECLARE @sql NVARCHAR(MAX);
   
   SET @sql = 'UPDATE ' + QUOTENAME(@table_name) + 
              ' SET ' + QUOTENAME(@column_name) + ' = ' + 
              'CASE WHEN ' + QUOTENAME(@column_name) + ' IS NULL ' + 
              'THEN CAST(@replace_value AS ' + @data_type + ') ' +
              'ELSE ' + QUOTENAME(@column_name) + ' END;';
   
   EXEC sp_executesql @sql, N'@replace_value NVARCHAR(MAX)', @replace_value;
END;
GO

-- Gọi thủ tục để điền giá trị null trong cột quantity_sold bằng '0'
EXEC Hand_Null_Value 
    @table_name = 'new_restaurants',
    @column_name = 'opening_hours',
    @replace_value = 'Unknown',
	@data_type = 'nvarchar(max)';


-- IV. Tạo thủ tục để điền giá trị null hoặc khoảng trắng bằng giá trị mà người lập trình truyền vào
GO
CREATE PROCEDURE Hand_Null_Or_Empty_Value (
   @table_name NVARCHAR(50),
   @column_name NVARCHAR(50),         
   @replace_value NVARCHAR(MAX),
   @data_type NVARCHAR(50)
)
AS
BEGIN
   DECLARE @sql NVARCHAR(MAX);
   
   SET @sql = 'UPDATE ' + QUOTENAME(@table_name) + 
              ' SET ' + QUOTENAME(@column_name) + ' = ' + 
              'CASE WHEN ' + QUOTENAME(@column_name) + ' IS NULL OR LTRIM(RTRIM(' + QUOTENAME(@column_name) + ')) = '''' ' + 
              'THEN CAST(@replace_value AS ' + @data_type + ') ' +
              'ELSE ' + QUOTENAME(@column_name) + ' END;';
   
   EXEC sp_executesql @sql, N'@replace_value NVARCHAR(MAX)', @replace_value;
END;
GO

-- Gọi thủ tục để điền giá trị null trong cột quantity_sold bằng '0'
EXEC Hand_Null_Or_Empty_Value 
    @table_name = 'new_reviews',
    @column_name = 'meal_type',
    @replace_value = 'Unknown',
	@data_type = 'nvarchar(100)';

EXEC Hand_Null_Or_Empty_Value 
    @table_name = 'new_reviews',
    @column_name = 'review_time',
    @replace_value = 'Unknown',
	@data_type = 'nvarchar(100)';

-- I. Thủ tục đếm số giá trị null của từng cột trong bảng
GO
CREATE PROCEDURE CountNullsInColumn
    @table_name NVARCHAR(128)  -- Tên bảng
AS
BEGIN
    DECLARE @sql NVARCHAR(MAX) = '';
    
    -- Tạo câu truy vấn động để đếm NULL cho mỗi cột
    SELECT @sql = @sql +
        CASE 
            WHEN @sql = '' THEN ''
            ELSE ' UNION ALL '
        END +
        'SELECT ''' + COLUMN_NAME + ''' AS ColumnName, ' +
        'COUNT(*) AS NullCount ' +
        'FROM ' + QUOTENAME(@table_name) + ' ' +
        'WHERE ' + QUOTENAME(COLUMN_NAME) + ' IS NULL'
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_NAME = @table_name;

    -- Thực thi câu truy vấn động
    EXEC sp_executesql @sql;
END;
GO

EXEC CountNullsInColumn 'new_reviews'
EXEC CountNullsInColumn 'new_restaurants'

-- III. Thủ tục xóa hàng có giá trị xác định trong cột
GO
CREATE OR ALTER PROCEDURE DeleteRowByColumnValue
   @TableName NVARCHAR(50),  
   @ColumnName NVARCHAR(50), 
   @ColumnValue NVARCHAR(MAX)  
AS
BEGIN
   DECLARE @SQL NVARCHAR(MAX);

   -- Xử lý riêng trường hợp NULL
   IF @ColumnValue IS NULL
   BEGIN
       SET @SQL = N'DELETE FROM ' + QUOTENAME(@TableName) + 
                  N' WHERE ' + QUOTENAME(@ColumnName) + N' IS NULL';
       EXEC sp_executesql @SQL;
   END
   ELSE
   BEGIN
       SET @SQL = N'DELETE FROM ' + QUOTENAME(@TableName) + 
                  N' WHERE ' + QUOTENAME(@ColumnName) + N' = @Value';
       EXEC sp_executesql @SQL, 
                         N'@Value NVARCHAR(MAX)', 
                         @Value = @ColumnValue;
   END
END;
GO


EXEC DeleteRowByColumnValue 
    @TableName = 'new_reviews',
    @ColumnName = 'rating',
    @ColumnValue = NULL;

-- review_text
UPDATE reviews
SET review_text = 'Rated ' + CAST(rating AS NVARCHAR(10))
WHERE (review_text IS NULL OR review_text = '') AND rating IS NOT NULL;

-- Gọi thủ tục để điền giá trị null trong cột quantity_sold bằng '0'
EXEC Hand_Null_Or_Empty_Value 
    @table_name = 'reviews',
    @column_name = 'nation',
    @replace_value = 'N/A',
	@data_type = 'nvarchar(100)';

-- Gọi thủ tục để điền giá trị null trong cột quantity_sold bằng '0'
EXEC Hand_Null_Or_Empty_Value 
    @table_name = 'new_reviews',
    @column_name = 'atmosphere_rating',
    @replace_value = 'N/A',
	@data_type = 'nvarchar(100)';

UPDATE [restaurant].[dbo].[reviews]
SET 
    [service_type] = CASE WHEN [service_type] = 'N/A' THEN 'Unknown' ELSE [service_type] END,
    [meal_type] = CASE WHEN [meal_type] = 'N/A' THEN 'Unknown' ELSE [meal_type] END,
    [nation] = CASE WHEN [nation] = 'N/A' THEN 'Unknown' ELSE [nation] END;


UPDATE [restaurant].[dbo].[reviews]
SET [restaurant_id] = 27
WHERE [restaurant_id] = 1;


DELETE FROM [restaurants].[dbo].[new_reviews]
WHERE review_id = 'RV07545';

WITH NumberedReviews AS (
    SELECT 
        review_id,
        ROW_NUMBER() OVER (ORDER BY restaurant_id) AS row_num
    FROM [restaurants].[dbo].[new_reviews]
)
UPDATE [restaurants].[dbo].[new_reviews]
SET review_id = 'RV' + RIGHT('00000' + CAST(n.row_num AS NVARCHAR(5)), 5)
FROM [restaurants].[dbo].[new_reviews] r
INNER JOIN NumberedReviews n ON r.review_id = n.review_id;