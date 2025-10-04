import time
import logging
import csv
import os
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
import re
import pandas as pd

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException, NoSuchElementException, TimeoutException, ElementClickInterceptedException, StaleElementReferenceException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler('scraper_review.log', maxBytes=5*1024*1024, backupCount=2, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Định nghĩa các cột trong file CSV
REVIEW_FIELDNAMES = [
    "Review_id", "Restaurant_id", "Reviewer_name", "Reviewer_info", "Rating", "Review_time",
    "Review_text", "Service_rating", "Food_rating", "Atmosphere_rating",
    "Service_type", "Meal_type", "Language", "Created_at", "Crawl_date"
]

def setup_driver(headless=False):
    """Thiết lập và cấu hình trình duyệt Chrome.

    Args:
        headless (bool): Chạy trình duyệt ở chế độ không giao diện nếu True.

    Returns:
        WebDriver: Trình duyệt Chrome đã được cấu hình.

    Raises:
        Exception: Nếu thiết lập trình duyệt thất bại.
    """
    chrome_options = Options()
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    if headless:
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")

    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.execute_cdp_cmd("Emulation.setGeolocationOverride", {
            "latitude": 16.0544,
            "longitude": 108.2022,
            "accuracy": 100
        })
        logger.info("Thiết lập trình duyệt thành công.")
        return driver
    except Exception as e:
        logger.error(f"Lỗi khi thiết lập trình duyệt: {e}")
        raise

def click(driver, element, wait_time=2, retries=3):
    """Click phần tử bằng JavaScript với cơ chế thử lại. (dùng JS để tránh lỗi nếu elem bị che khuất)

    Args:
        driver: WebDriver instance.
        element: WebElement để click.
        wait_time: Thời gian chờ sau khi click (2 giây).
        retries: Số lần thử lại nếu click thất bại (3 lần).

    Returns:
        bool: True nếu click thành công, False nếu thất bại.
    """
    for attempt in range(retries):
        try:
            WebDriverWait(driver, 5).until(EC.element_to_be_clickable(element))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            driver.execute_script("arguments[0].click();", element)
            WebDriverWait(driver, wait_time).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            logger.info("Click thành công.")
            return True
        except (ElementClickInterceptedException, TimeoutException, StaleElementReferenceException) as e:
            logger.warning(f"Click thất bại (lần {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                WebDriverWait(driver, 1).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    logger.error(f"Click thất bại sau {retries} lần thử.")
    return False

def scroll_and_click_more(driver, scrollable_div, max_scrolls=20):
    """Cuộn và mở rộng nút 'Xem thêm' trong đánh giá.

    Args:
        driver: WebDriver instance.
        scrollable_div: Phần tử WebElement chứa danh sách đánh giá.
        max_scrolls: Số lần cuộn tối đa.
    """
    last_height = driver.execute_script("return arguments[0].scrollHeight;", scrollable_div)
    scroll_count = 0
    reviews_loaded = 0
    
    while scroll_count < max_scrolls:
        current_reviews = len(driver.find_elements(By.CSS_SELECTOR, "div.jftiEf.fontBodyMedium"))
        logger.info(f"Đã tải {current_reviews} đánh giá.")

        more_buttons = driver.find_elements(By.CSS_SELECTOR, "button.w8nwRe.kyuRq")
        for btn in more_buttons:
            if click(driver, btn, wait_time=0.5):
                time.sleep(0.5)
        
        driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", scrollable_div)
        time.sleep(1.5)
        
        new_height = driver.execute_script("return arguments[0].scrollHeight;", scrollable_div)
        new_reviews = len(driver.find_elements(By.CSS_SELECTOR, "div.jftiEf.fontBodyMedium"))
        
        if new_height == last_height and new_reviews == reviews_loaded:
            scroll_count += 1
            if scroll_count >= 3:
                logger.info("Không còn đánh giá mới, dừng cuộn.")
                break
        else:
            scroll_count = 0
            logger.info(f"Tải thêm dữ liệu mới. Đánh giá mới: {new_reviews}")
        
        last_height = new_height
        reviews_loaded = new_reviews

def click_sort_newest(driver, wait):
    """Click vào nút Sort và chọn tùy chọn 'Newest' để sắp xếp đánh giá theo mới nhất.

    Args:
        driver: WebDriver instance.
        wait: WebDriverWait instance.

    Returns:
        bool: True nếu click và chọn 'Newest' thành công, False nếu thất bại.
    """
    try:
        sort_span = wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//span[contains(@class, 'GMtm7c') and contains(@class, 'fontTitleSmall') and text()='Sort']")
            ),
            message="Không tìm thấy span chứa text 'Sort' sau 15 giây."
        )
        sort_button = sort_span.find_element(By.XPATH, "./ancestor::button | ./ancestor::div[@role='button']")
        if not click(driver, sort_button):
            logger.warning("Không thể click vào nút Sort.")
            return False
        dropdown = wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//div[@id='action-menu' and @role='menu']")
            ),
            message="Dropdown menu không xuất hiện sau 15 giây."
        )
        newest_option = wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//div[@id='action-menu' and @role='menu']//div[@role='menuitemradio' and .//div[text()='Newest']]")
            ),
            message="Không tìm thấy tùy chọn 'Newest' sau 10 giây."
        )
        if not click(driver, newest_option):
            logger.warning("Không thể click vào tùy chọn 'Newest'.")
            return False
        wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "div.jftiEf.fontBodyMedium")
            ),
            message="Danh sách đánh giá không cập nhật sau 10 giây."
        )
        logger.info("Đã chọn 'Newest' trong Sort thành công.")
        return True
    except (TimeoutException, NoSuchElementException) as e:
        logger.error(f"Lỗi khi click Sort hoặc chọn 'Newest': {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Lỗi không xác định khi xử lý Sort: {str(e)}")
        return False

def convert_review_time(created_time, review_time):
    """Chuyển đổi Review_time thành ngày thực tế của đánh giá.

    Args:
        created_time: Thời gian crawl (datetime).
        review_time: Chuỗi thời gian tương đối (e.g., '2 days ago').

    Returns:
        date: Ngày thực tế của đánh giá hoặc None nếu không xử lý được.
    """
    if pd.isnull(review_time):
        return None
    if "hour" in review_time or "minute" in review_time:
        return created_time.date()
    review_time = review_time.replace("a ", "1 ")
    match = re.match(r"(\d+) (day|week|month|year)s? ago", review_time)
    if not match:
        return None
    amount, unit = int(match.group(1)), match.group(2)
    if unit == "day":
        delta = timedelta(days=amount)
    elif unit == "week":
        delta = timedelta(weeks=amount)
    elif unit == "month":
        delta = timedelta(days=amount * 30)
    elif unit == "year":
        delta = timedelta(days=amount * 365)
    return (created_time - delta).date()

def init_csv(output_file="reviews.csv"):
    """Tạo file CSV nếu chưa tồn tại, với các cột đã được định nghĩa.

    Args:
        output_file: Đường dẫn file CSV.
    """
    if not os.path.isfile(output_file):
        try:
            with open(output_file, mode="w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=REVIEW_FIELDNAMES)
                writer.writeheader()
            logger.info(f"Tạo file CSV mới: {output_file}")
        except Exception as e:
            logger.error(f"Lỗi khi tạo file CSV {output_file}: {e}")
            raise
    else:
        logger.info(f"File CSV {output_file} đã tồn tại.")

def scrape_reviews(driver, wait, Restaurant_id):
    """Thu thập đánh giá từ một nhà hàng.

    Args:
        driver: WebDriver instance.
        wait: WebDriverWait instance.
        Restaurant_id: ID của nhà hàng.

    Returns:
        list: Danh sách các đánh giá (dict).
    """
    reviews_list = []
    try:
        reviews_tabs = wait.until(
            EC.presence_of_all_elements_located((By.XPATH, "//div[text()='Reviews']"))
        )
        if reviews_tabs and click(driver, reviews_tabs[0]):
            if not click_sort_newest(driver, wait):
                logger.warning("Không thể sắp xếp theo 'Newest', tiếp tục với mặc định.")
            
            scrollable_divs = wait.until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.m6QErb.DxyBCb.kA9KIf.dS8AEf"))
            )
            if scrollable_divs:
                scroll_and_click_more(driver, scrollable_divs[0])
            
            review_containers = driver.find_elements(By.CSS_SELECTOR, "div.jftiEf.fontBodyMedium")
            logger.info(f"Tìm thấy {len(review_containers)} đánh giá.")
            
            for container in review_containers:
                review_data = {
                    "Review_id": "",
                    "Restaurant_id": Restaurant_id,
                    "Reviewer_name": "",
                    "Reviewer_info": "",
                    "Rating": "",
                    "Review_time": "",
                    "Review_text": "",
                    "Service_rating": "",
                    "Food_rating": "",
                    "Atmosphere_rating": "",
                    "Service_type": "",
                    "Meal_type": "",
                    "Language": "",
                    "Created_at": "",
                    "Crawl_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                
                try:
                    review_data["Reviewer_name"] = container.find_element(By.CSS_SELECTOR, "div.d4r55").text or ""
                except NoSuchElementException:
                    logger.warning("Không tìm thấy Reviewer_name")
                
                try:
                    review_data["Reviewer_info"] = container.find_element(By.CSS_SELECTOR, "div.RfnDt").text or ""
                except NoSuchElementException:
                    logger.warning("Không tìm thấy Reviewer_info")
                
                try:
                    rating_elem = container.find_element(By.CSS_SELECTOR, "span[aria-label]")
                    rating_text = rating_elem.get_attribute('aria-label').split()[0]
                    review_data["Rating"] = float(rating_text.replace(',', '.'))
                except (NoSuchElementException, ValueError):
                    logger.warning("Không tìm thấy hoặc lỗi khi lấy Rating")
                
                try:
                    review_data["Review_time"] = container.find_element(By.CSS_SELECTOR, "span.rsqaWe").text or ""
                except NoSuchElementException:
                    logger.warning("Không tìm thấy Review_time")
                
                try:
                    review_data["Review_text"] = container.find_element(By.CSS_SELECTOR, "span.wiI7pd").text or ""
                except NoSuchElementException:
                    logger.warning("Không tìm thấy Review_text")
                
                try:
                    language_elem = container.find_element(By.CSS_SELECTOR, "div.oqftme")
                    text = language_elem.text
                    if "(" in text and ")" in text:
                        review_data["Language"] = text.split("(")[-1].replace(")", "").strip()
                except NoSuchElementException:
                    logger.warning("Không tìm thấy Language")
                
                rating_elements = container.find_elements(By.CSS_SELECTOR, "span.RfDO5c")
                for elem in rating_elements:
                    text = elem.text.strip()
                    if "Service:" in text:
                        review_data["Service_rating"] = text.split(":")[-1].strip()
                    elif "Food:" in text:
                        review_data["Food_rating"] = text.split(":")[-1].strip()
                    elif "Atmosphere:" in text:
                        review_data["Atmosphere_rating"] = text.split(":")[-1].strip()
                    elif text in ["Dine in", "Takeout"]:
                        review_data["Service_type"] = text
                    elif text in ["Breakfast", "Lunch", "Dessert", "Brunch", "Dinner", "Seating"]:
                        review_data["Meal_type"] = text
                
                # Xử lý review_text rỗng
                if not review_data["Review_text"] or review_data["Review_text"].strip() == "":
                    if review_data["Rating"]:
                        review_data["Review_text"] = f"Rated {review_data['Rating']}"
                        logger.info(f"Đã gán Review_text thành 'Rated {review_data['Rating']}' vì không có nội dung đánh giá.")
                
                # Tính Created_at từ Review_time
                crawl_time = datetime.now()
                created_date = convert_review_time(crawl_time, review_data["Review_time"])
                review_data["Created_at"] = created_date.strftime("%Y-%m-%d") if created_date else ""
                
                # Chuẩn hóa độ dài
                review_data["Reviewer_name"] = review_data["Reviewer_name"][:500] if review_data["Reviewer_name"] else ""
                review_data["Reviewer_info"] = review_data["Reviewer_info"][:500] if review_data["Reviewer_info"] else ""
                review_data["Review_time"] = review_data["Review_time"][:100] if review_data["Review_time"] else ""
                review_data["Language"] = review_data["Language"][:100] if review_data["Language"] else ""
                
                reviews_list.append(review_data)
        else:
            logger.warning("Không tìm thấy hoặc không click được tab 'Reviews'")
    except (TimeoutException, NoSuchElementException) as e:
        logger.warning(f"Lỗi khi truy cập tab 'Reviews': {e}")
    
    return reviews_list

def update_reviews_and_save(driver, restaurants_file="restaurants.csv", output_file="reviews.csv", batch_size=10):
    """Cập nhật đánh giá cho từng nhà hàng từ restaurants.csv.
    Chỉ thêm đánh giá mới dựa trên Reviewer_name và Restaurants_id.

    Args:
        driver: WebDriver instance.
        restaurants_file: Đường dẫn file restaurants.csv.
        output_file: Đường dẫn file reviews.csv.
        batch_size: Số lượng mỗi batch log tiến độ.

    Returns:
        int: Số lượng đánh giá được thêm mới.
    """
    wait = WebDriverWait(driver, 10)
    
    try:
        restaurants_df = pd.read_csv(restaurants_file)
        if 'Restaurant_id' not in restaurants_df.columns or 'Url' not in restaurants_df.columns or 'Restaurant_name' not in restaurants_df.columns:
            raise ValueError("File restaurants.csv phải chứa các cột 'Restaurant_id', 'Url', và 'Restaurant_name'")
    except Exception as e:
        logger.error(f"Lỗi khi đọc file {restaurants_file}: {e}")
        return 0

    existing_reviews = set()
    next_id = 1
    if os.path.isfile(output_file):
        try:
            with open(output_file, mode="r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    reviewer_name = row.get("Reviewer_name", "").strip().lower()
                    restaurants_id = row.get("Restaurant_id", "")
                    if reviewer_name and restaurants_id:
                        existing_reviews.add((restaurants_id, reviewer_name))
                    if row.get("Review_id"):
                        try:
                            current_id = int(row["Review_id"])
                            next_id = max(next_id, current_id + 1)
                        except ValueError:
                            logger.warning(f"Review_id không hợp lệ: {row['Review_id']}")
        except Exception as e:
            logger.error(f"Lỗi khi đọc file CSV {output_file}: {e}")
            return 0

    added = 0
    total_restaurants = len(restaurants_df)

    for i, row in restaurants_df.iterrows():
        restaurants_id = str(row['Restaurant_id'])
        url = row['Url']
        restaurant_name = str(row['Restaurant_name'])
        logger.info(f"Scraping đánh giá cho nhà hàng {i+1}/{total_restaurants}: {restaurant_name}")
        try:
            driver.get(url)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "h1.DUwDvf")))
            
            reviews = scrape_reviews(driver, wait, restaurants_id)
            if reviews:
                new_reviews = []
                for review in reviews:
                    reviewer_name = review["Reviewer_name"].strip().lower()
                    if reviewer_name and (restaurants_id, reviewer_name) not in existing_reviews:
                        review["Review_id"] = str(next_id)
                        new_reviews.append(review)
                        existing_reviews.add((restaurants_id, reviewer_name))
                        next_id += 1
                        added += 1
                
                if new_reviews:
                    try:
                        with open(output_file, mode="a", newline="", encoding="utf-8-sig") as f:
                            writer = csv.DictWriter(f, fieldnames=REVIEW_FIELDNAMES)
                            writer.writerows(new_reviews)
                        logger.info(f"Đã thêm {len(new_reviews)} đánh giá mới cho nhà hàng {restaurants_id}")
                    except Exception as e:
                        logger.error(f"Lỗi khi ghi file CSV {output_file}: {e}")
        except (TimeoutException, NoSuchElementException) as e:
            logger.error(f"Lỗi scrape {url}: {e}")
            continue

        if (i + 1) % batch_size == 0:
            logger.info(f"Đã xử lý {i+1}/{total_restaurants} nhà hàng...")

    logger.info(f"Hoàn thành! Đã thêm {added} đánh giá mới và lưu vào {output_file}.")
    return added

def main(restaurants_file="restaurants.csv", output_file="reviews.csv", batch_size=10, headless=False):
    """Hàm chính để chạy chương trình crawl đánh giá.

    Args:
        restaurants_file: Đường dẫn file restaurants.csv.
        output_file: Đường dẫn file reviews.csv.
        batch_size: Số lượng mỗi batch log tiến độ.
        headless: Chạy headless nếu True.
    """
    start_time = datetime.now()
    logger.info(f"Bắt đầu crawl đánh giá: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    driver = None
    try:
        driver = setup_driver(headless=headless)
        init_csv(output_file)
        logger.info("Bắt đầu cập nhật đánh giá...")
        added = update_reviews_and_save(driver, restaurants_file, output_file, batch_size)
        logger.info(f"Hoàn thành cập nhật đánh giá! Đã thêm {added} đánh giá mới.")
    except (TimeoutException, WebDriverException) as e:
        logger.error(f"Lỗi trong quá trình thực thi: {e}")
        raise
    finally:
        if driver:
            driver.quit()
            logger.info("Đã đóng trình duyệt.")
        end_time = datetime.now()
        logger.info(f"Kết thúc crawl: {end_time.strftime('%Y-%m-%d %H:%M:%S')}, thời gian chạy: {end_time - start_time}")

if __name__ == "__main__":
    main()
