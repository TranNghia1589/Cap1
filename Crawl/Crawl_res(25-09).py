import time
import logging
import csv
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException, NoSuchElementException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from openlocationcode import openlocationcode as olc

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler('scraper.log', maxBytes=5*1024*1024, backupCount=2, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

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

def scroll_until_end(driver, scrollable_div, max_attempts=5):
    last_height = driver.execute_script("return arguments[0].scrollHeight;", scrollable_div)
    no_change_count = 0
    last_restaurant_count = 0

    while no_change_count < max_attempts:
        restaurants = driver.find_elements(By.CSS_SELECTOR, ".Nv2PK.THOPZb.CpccDe")
        total_restaurants = len(restaurants)
        new_count = total_restaurants - last_restaurant_count
        logger.info(f"Tìm thấy {total_restaurants} nhà hàng (mới: {new_count if new_count > 0 else 0})")

        driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", scrollable_div)
        time.sleep(2)

        new_height = driver.execute_script("return arguments[0].scrollHeight;", scrollable_div)
        updated_total = len(driver.find_elements(By.CSS_SELECTOR, ".Nv2PK.THOPZb.CpccDe"))

        if new_height == last_height and updated_total == total_restaurants:
            no_change_count += 1
            logger.info(f"Không tìm thấy dữ liệu mới: {no_change_count}/{max_attempts}")
        else:
            no_change_count = 0
            logger.info(f"Đã cuộn và tìm thấy thêm dữ liệu!")

        last_height = new_height
        last_restaurant_count = total_restaurants  
    
    logger.info(f"Hoàn thành cuộn! Tìm thấy tổng cộng {total_restaurants} nhà hàng.")

# Định nghĩa các cột cần có trong file csv
FIELDNAMES = [
    "Restaurant_id", "Url", "Restaurant_name", "Restaurant_type", "Rating_average",
    "Num_of_reviews", "Phone", "Price_level", "Address",
    "Latitude", "Longitude", "Crawl_date"
]

def init_csv(output_file="restaurants.csv"):
    """Tạo file CSV nếu chưa tồn tại."""
    if not os.path.isfile(output_file):
        try:
            with open(output_file, mode="w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
                writer.writeheader()
            logger.info(f"Tạo file CSV mới: {output_file}")
        except Exception as e:
            logger.error(f"Lỗi khi tạo file CSV {output_file}: {e}")
            raise
    else:
        logger.info(f"File CSV {output_file} đã tồn tại.")
        
def save_links(driver, output_file="restaurants.csv"):
    """Crawl danh sách link và tên nhà hàng, thêm các mục mới vào CSV dựa trên tên để tránh trùng lặp.

    Args:
        driver: WebDriver instance.
        output_file: Đường dẫn file CSV (mặc định: restaurants.csv).
    """
    wait = WebDriverWait(driver, 10)
    try:
        # Chờ danh sách nhà hàng xuất hiện
        element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='feed']")))
        # Lấy các thẻ <a> chứa URL và aria-label
        divs = element.find_elements(By.XPATH, "./div[position() > 2 and not(@class='TFQHme')]")
        restaurants = []
        for div in divs:
            a_tags = div.find_elements(By.CSS_SELECTOR, "a.hfpxzc")
            if a_tags:
                url = a_tags[0].get_attribute("href")
                name = a_tags[0].get_attribute("aria-label")
                if url and "google.com/maps/place" in url and name:
                    restaurants.append({"Url": url, "Restaurant_name": name})
        logger.info(f"Tìm thấy {len(restaurants)} nhà hàng.")
    except TimeoutException as e:
        logger.error(f"Không thể tìm thấy danh sách nhà hàng: {e}")
        return

    # Đọc tên nhà hàng hiện có và xác định next_id
    existing_names = set()
    next_id = 1
    try:
        with open(output_file, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["Restaurant_name"]:
                    existing_names.add(row["Restaurant_name"].strip().lower())  # Chuẩn hóa để so sánh (bỏ khoảng trắng, chữ thường)
                if row["Restaurant_id"]:
                    try:
                        current_id = int(row["Restaurant_id"])
                        next_id = max(next_id, current_id + 1)
                    except ValueError:
                        logger.warning(f"Restaurant_id không hợp lệ: {row['Restaurant_id']}")
    except Exception as e:
        logger.error(f"Lỗi khi đọc file CSV {output_file}: {e}")
        return

    # Ghi nhà hàng mới vào file CSV
    try:
        with open(output_file, mode="a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            count_new = 0
            for restaurant in restaurants:
                name = restaurant["Restaurant_name"].strip().lower()
                if name not in existing_names:
                    restaurant_id = str(next_id)
                    writer.writerow({
                        "Restaurant_id": restaurant_id,
                        "Url": restaurant["Url"],
                        "Restaurant_name": restaurant["Restaurant_name"]
                    })
                    count_new += 1
                    existing_names.add(name)
                    next_id += 1
            logger.info(f"Đã thêm {count_new} nhà hàng mới vào {output_file}")
    except Exception as e:
        logger.error(f"Lỗi khi ghi file CSV {output_file}: {e}")
        
def scrape_restaurant(driver):
    wait = WebDriverWait(driver, 10)

    data = {
        "Restaurant_type": "",
        "Rating_average": "",
        "Num_of_reviews": "",
        "Phone": "",
        "Price_level": "",
        "Address": "",
        "Latitude": "",
        "Longitude": "",
        "Crawl_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    # Mức giá
    try:
        data["Price_level"] = driver.find_element(
            By.XPATH,
            '//*[@id="QA0Szd"]/div/div/div[1]/div[2]/div/div[1]/div/div/div[2]/div/div[1]/div[2]/div/div[1]/span/span/span/span[2]/span/span'
        ).text
    except (NoSuchElementException, TimeoutException):
        logger.warning(f"Lỗi khi lấy mức giá")

    # Rating
    try:
        data["Rating_average"] = wait.until(
            EC.presence_of_element_located((By.XPATH,
                '//*[@id="QA0Szd"]/div/div/div[1]/div[2]/div/div[1]/div/div/div[2]/div/div[1]/div[2]/div/div[1]/div[2]/span[1]/span[1]'
            ))
        ).text
    except (TimeoutException, NoSuchElementException):
        logger.warning(f"Lỗi khi lấy rating")

    # Số lượng đánh giá
    try:
        reviews_elem = driver.find_element(By.CSS_SELECTOR, "div.F7nice span[aria-label*='reviews']")
        reviews_text = reviews_elem.get_attribute("aria-label").split()[0].replace(",", "")
        data["Num_of_reviews"] = int(reviews_text)
    except (NoSuchElementException, ValueError):
        logger.warning(f"Lỗi khi lấy số lượt đánh giá")

    # Số điện thoại
    try:
        phone_elem = driver.find_element(By.CSS_SELECTOR, 'button[data-item-id^="phone:tel"]')
        data["Phone"] = phone_elem.get_attribute('data-item-id').replace("phone:tel:", "")
    except (NoSuchElementException, TimeoutException):
        logger.warning(f"Lỗi khi lấy số điện thoại")
        
    # Loại nhà hàng
    type_xpaths = [
        '//*[@id="QA0Szd"]/div/div/div[1]/div[2]/div/div[1]/div/div/div[2]/div/div[1]/div[2]/div/div[2]/span[1]/span/button',
        '//*[@id="QA0Szd"]/div/div/div[1]/div[2]/div/div[1]/div/div/div[2]/div/div[1]/h2/span'
    ]
    for xpath in type_xpaths:
        try:
            type_elems = wait.until(EC.presence_of_all_elements_located((By.XPATH, xpath)))
            if type_elems and any(elem.text.strip() for elem in type_elems):
                data["Restaurant_type"] = ', '.join([elem.text.strip() for elem in type_elems if elem.text.strip()])
                break
        except (TimeoutException, NoSuchElementException):
            continue
    if not data["Restaurant_type"]:
        logger.warning("Lỗi khi lấy loại nhà hàng")

    # Địa chỉ
    address_xpaths = [
            '//*[@id="QA0Szd"]/div/div/div[1]/div[2]/div/div[1]/div/div/div[9]/div[3]/button/div/div[2]/div[1]',
            '//*[@id="QA0Szd"]/div/div/div[1]/div[2]/div/div[1]/div/div/div[11]/div[3]/button/div/div[2]/div[1]',
            '//*[@id="QA0Szd"]/div/div/div[1]/div[2]/div/div[1]/div/div/div[13]/div[3]/button/div/div[2]/div[1]',
            '//*[@id="QA0Szd"]/div/div/div[1]/div[2]/div/div[1]/div/div/div[7]/div[3]/button/div/div[2]/div[1]'
    ]
    for xpath in address_xpaths:
        try:
            addr_elem = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
            if addr_elem.text.strip():
                data["Address"] = addr_elem.text.strip()
                break
        except (TimeoutException, NoSuchElementException):
            continue
    if not data["Address"]:
        logger.warning("Lỗi khi lấy địa chỉ")   
    
    # Plus Code -> Lat/Long
    try:
        plus_code_elem = driver.find_element(
            By.XPATH, "//button[contains(@aria-label, 'Plus code') and @class='CsEnBe']"
        )
        aria_label = plus_code_elem.get_attribute("aria-label")
        if aria_label:
            plus_code = aria_label.replace("Plus code: ", "").strip()
            code = plus_code.split()[0]
            if olc.isValid(code):
                reference_latitude, reference_longitude = 16.067, 108.220
                full_code = olc.recoverNearest(code, reference_latitude, reference_longitude)
                decoded = olc.decode(full_code)
                data["Latitude"], data["Longitude"] = decoded.latitudeCenter, decoded.longitudeCenter
    except (NoSuchElementException, ValueError):
        logger.warning(f"Lỗi khi lấy tọa độ từ Plus Code")

    return data

def update_details(driver, output_file="restaurants.csv", batch_size=10):
    """Đọc file CSV, crawl lại từng link và cập nhật nếu có thay đổi.
       Ghi file một lần sau khi xử lý toàn bộ danh sách để tránh xung đột.
       Trả về số lượng nhà hàng được cập nhật.

    Args:
        driver: WebDriver instance.
        output_file: Đường dẫn file CSV (mặc định: restaurants.csv).
        batch_size: Số lượng nhà hàng mỗi lần log tiến độ (mặc định: 10).

    Returns:
        int: Số lượng nhà hàng được cập nhật.
    """
    wait = WebDriverWait(driver, 10)
    
    # Đọc file csv
    rows = []
    try:
        with open(output_file, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        logger.error(f"Lỗi khi đọc file CSV {output_file}: {e}")
        return 0

    updated = 0
    total = len(rows)
    updated_rows = rows.copy() 

    for i, row in enumerate(updated_rows):
        url = row.get("Url", "")
        if not url:
            logger.warning(f"Bỏ qua dòng {i+1}: Không có URL")
            continue
        logger.info(f"Scraping {i+1}/{total}: {row.get('Restaurant_name', 'Unknown')}")
        try:
            driver.get(url)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "h1.DUwDvf")))
            
            data = scrape_restaurant(driver)
            if data:
                has_change = False
                for k in data.keys():
                    if k == "Crawl_date":
                        continue
                    new_val = str(data.get(k, ""))
                    old_val = str(row.get(k, ""))
                    if new_val.strip() == "" and old_val.strip() != "":
                        data[k] = old_val
                    elif new_val != old_val:
                        has_change = True
                
                if has_change:
                    row.update({k: data.get(k, row.get(k, "")) for k in data.keys() if k != "Crawl_date"})
                    row["Crawl_date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    updated += 1
                    logger.info(f"Cập nhật thay đổi cho nhà hàng: {row.get('Restaurant_name', url)}")
                else:
                    logger.info(f"Không có thay đổi cho nhà hàng: {row.get('Restaurant_name', url)}")
        except (TimeoutException, NoSuchElementException) as e:
            logger.error(f"Lỗi scrape {url}: {e}")
            continue

        if (i + 1) % batch_size == 0:
            logger.info(f"Đã xử lý {i+1}/{total} nhà hàng...")

    # Ghi file CSV
    try:
        with open(output_file, mode="a", encoding="utf-8-sig") as f:
            pass 
        with open(output_file, mode="w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(updated_rows)
        logger.info(f"Hoàn thành! Đã cập nhật {updated} nhà hàng có thay đổi trong {output_file}")
    except PermissionError as e:
        logger.error(f"Lỗi khi ghi file CSV {output_file}: {e}. Vui lòng kiểm tra xem file có đang được mở bởi chương trình khác không.")
        return updated
    except Exception as e:
        logger.error(f"Lỗi không xác định khi ghi file CSV {output_file}: {e}")
        return updated

    return updated
  
def main(search_url="https://www.google.com/maps/search/Restaurants+in+Da+Nang", output_file="restaurants.csv", batch_size=10, headless=False):
    """Chạy chương trình crawl Google Review.

    Args:
        search_url: URL tìm kiếm Google Review (mặc định: nhà hàng ở Đà Nẵng).
        output_file: Đường dẫn file CSV (mặc định: restaurants.csv).
        batch_size: Số lượng nhà hàng mỗi lần log tiến độ (mặc định: 10).
        headless: Chạy trình duyệt ở chế độ không giao diện nếu True (mặc định: False).
    """
    start_time = datetime.now()
    logger.info(f"Bắt đầu crawl: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    driver = None
    try:
        logger.info("Khởi tạo trình duyệt...")
        driver = setup_driver(headless=headless)

        logger.info(f"Mở URL: {search_url}")
        driver.get(search_url)

        # B1: Tạo file CSV
        logger.info(f"Khởi tạo file CSV: {output_file}")
        init_csv(output_file)

        # B2: Crawl danh sách link
        try:
            wait = WebDriverWait(driver, 10)
            scrollable_div = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='feed']"))
            )
            logger.info("Bắt đầu cuộn để tải thêm nhà hàng...")
            scroll_until_end(driver, scrollable_div)
            logger.info("Lưu danh sách link vào CSV...")
            save_links(driver, output_file)
        except TimeoutException as e:
            logger.error(f"Không thể tìm thấy danh sách nhà hàng: {e}")
            raise

        # B3: Cập nhật chi tiết nhà hàng
        logger.info("Bắt đầu cập nhật chi tiết nhà hàng...")
        updated = update_details(driver, output_file, batch_size)
        logger.info(f"Hoàn thành cập nhật dữ liệu! Đã cập nhật {updated} nhà hàng.")

    except (TimeoutException, WebDriverException) as e:
        logger.error(f"Lỗi trong quá trình thực thi: {e}")
        raise
    finally:
        if driver:
            driver.quit()
            logger.info("Đã đóng trình duyệt.")
        end_time = datetime.now()
        logger.info(f"Kết thúc crawl: {end_time.strftime('%Y-%m-%d %H:%M:%S')}, thời gian chạy: {end_time - start_time}, tổng số nhà hàng cập nhật: {updated}")

if __name__ == "__main__":
    main()