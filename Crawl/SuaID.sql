-- ===============================================
-- 🟢 Chuẩn hóa kiểu dữ liệu cột id (NVARCHAR -> INT)
-- Tạo bảng mới + Sao chép dữ liệu + Thiết lập lại khóa chính & khóa ngoại
-- ===============================================

-- Bước 1: Tạo bảng mới cho new_restaurants
CREATE TABLE [restaurants].[dbo].[new_restaurants_temp] (
    id INT PRIMARY KEY,
    restaurants_name NVARCHAR(MAX),
    url NVARCHAR(MAX),
    restaurant_type NVARCHAR(255),
    rating FLOAT,
    price_level NVARCHAR(50),
    address NVARCHAR(MAX),
    phone NVARCHAR(50),
    Monday NVARCHAR(255),
    Tuesday NVARCHAR(255),
    Wednesday NVARCHAR(255),
    Thursday NVARCHAR(255),
    Friday NVARCHAR(255),
    Saturday NVARCHAR(255),
    Sunday NVARCHAR(255),
    accessibility_info NVARCHAR(MAX),
    created_at DATETIME
);

-- Bước 2: Copy dữ liệu và convert id
INSERT INTO [restaurants].[dbo].[new_restaurants_temp]
SELECT 
    CAST(id AS INT),
    title AS restaurants_name,
    url, restaurant_type, rating, price_level, address, phone,
    Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday,
    accessibility_info, created_at
FROM [restaurants].[dbo].[new_restaurants];

-- Bước 3: Tạo bảng mới cho new_reviews
CREATE TABLE [restaurants].[dbo].[new_reviews_temp] (
    review_id NVARCHAR(10) PRIMARY KEY,
    reviewer_name NVARCHAR(500),
    reviewer_info NVARCHAR(500),
    rating FLOAT,
    review_time NVARCHAR(100),
    review_text NVARCHAR(MAX),
    service_rating NVARCHAR(50),
    food_rating NVARCHAR(50),
    atmosphere_rating NVARCHAR(50),
    service_type NVARCHAR(100),
    meal_type NVARCHAR(100),
    nation NVARCHAR(100),
    created_at DATETIME,
    restaurant_id INT
);

-- Bước 4: Copy dữ liệu và convert restaurant_id
INSERT INTO [restaurants].[dbo].[new_reviews_temp]
SELECT 
    review_id,
    reviewer_name,
    reviewer_info,
    rating,
    review_time,
    review_text,
    service_rating,
    food_rating,
    atmosphere_rating,
    service_type,
    meal_type,
    nation,
    created_at,
    CAST(restaurant_id AS INT)
FROM [restaurants].[dbo].[new_reviews];

-- Bước 5: Xóa khóa ngoại + bảng cũ
ALTER TABLE [restaurants].[dbo].[new_reviews] DROP CONSTRAINT FK_new_reviews_restaurants;
DROP TABLE [restaurants].[dbo].[new_reviews];
DROP TABLE [restaurants].[dbo].[new_restaurants];

-- Bước 6: Đổi tên bảng mới
EXEC sp_rename 'restaurants.dbo.new_restaurants_temp', 'new_restaurants';
EXEC sp_rename 'restaurants.dbo.new_reviews_temp', 'new_reviews';

-- Bước 7: Tạo lại khóa ngoại
ALTER TABLE [restaurants].[dbo].[new_reviews]
ADD CONSTRAINT FK_new_reviews_restaurants
FOREIGN KEY (restaurant_id) 
REFERENCES [restaurants].[dbo].[new_restaurants](id);

-- ===============================================
-- ✅ Done - Kiểu dữ liệu id đã là INT và liên kết đúng, review_id giữ nguyên NVARCHAR(10)
-- ===============================================