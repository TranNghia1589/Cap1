import time
import logging
import csv
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
import json

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException, NoSuchElementException, TimeoutException, ElementClickInterceptedException, StaleElementReferenceException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from openlocationcode import openlocationcode as olc
import pandas as pd

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler('scraper_restaurant.log', maxBytes=5*1024*1024, backupCount=2, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Blacklist
blacklist_res = ["Anna Restaurant", "Suzu home", "Manvar rasoi", "Quán Cây Đa", "Embers & Leaves Restaurant",
                 "Da Nang Restaurant", "Le Bambino", "Cloves Restaurant (Bay Capital Da Nang Hotel)",
                 "Bê Thui Cô Vân", "Breakfast buffet at Lotus Wine & Dine Restaurant of Royal Lotus Hotel Da Nang",
                 "Danang local food restaurant","Shilla Noodle"]  

# Định nghĩa các cột trong file CSV
BASE_FIELDNAMES = [
    "Restaurant_id", "Url", "Restaurant_name", "Restaurant_type", "Rating_average",
    "Num_of_reviews", "Phone", "Price_level", "Address",
    "Latitude", "Longitude", "Crawl_date"
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

def scroll_until_end(driver, scrollable_div, max_attempts=5):
    """Cuộn tìm div chứa danh sách nhà hàng đến khi không còn dữ liệu mới.

    Args:
        driver: WebDriver instance.
        scrollable_div: Phần tử div có thể cuộn.
        max_attempts: Số lần tối đa kiểm tra nếu không có dữ liệu mới (5 lần).
    """
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

def safe_click(driver, element, wait_time=2, retries=3):
    """Click phần tử bằng JavaScript với cơ chế thử lại.

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
  
def init_csv(output_file="restaurants.csv"):
    """Tạo file CSV nếu chưa tồn tại, với các cột đã được định nghĩa.

    Args:
        output_file: Đường dẫn file CSV.
    """
    if not os.path.isfile(output_file):
        try:
            with open(output_file, mode="w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=BASE_FIELDNAMES)
                writer.writeheader()
            logger.info(f"Tạo file CSV mới: {output_file}")
        except Exception as e:
            logger.error(f"Lỗi khi tạo file CSV {output_file}: {e}")
            raise
    else:
        logger.info(f"File CSV {output_file} đã tồn tại.")

def save_links(driver, output_file="restaurants.csv"):
    """Crawl danh sách link và tên nhà hàng.
    Thêm các nhà hàng mới vào CSV dựa trên tên nhà hàng để tránh trùng lặp.
    Bỏ qua các nhà hàng trong blacklist_res.

    Args:
        driver: WebDriver instance.
        output_file: Đường dẫn file CSV.
    """
    wait = WebDriverWait(driver, 10)
    try:
        element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='feed']")))
        divs = element.find_elements(By.XPATH, "./div[position() > 2 and not(@class='TFQHme')]")
        restaurants = []
        for div in divs:
            a_tags = div.find_elements(By.CSS_SELECTOR, "a.hfpxzc")
            if a_tags:
                url = a_tags[0].get_attribute("href")
                name = a_tags[0].get_attribute("aria-label")
                if url and "google.com/maps/place" in url and name:
                    # Chuẩn hóa tên nhà hàng để kiểm tra blacklist
                    normalized_name = name.strip().lower()
                    # Kiểm tra xem tên nhà hàng có trong blacklist không
                    if normalized_name not in [black_name.lower() for black_name in blacklist_res]:
                        restaurants.append({"Url": url, "Restaurant_name": name})
                    else:
                        logger.info(f"Bỏ qua nhà hàng trong blacklist: {name}")
        logger.info(f"Tìm thấy {len(restaurants)} nhà hàng (sau khi lọc blacklist).")
    except TimeoutException as e:
        logger.error(f"Không thể tìm thấy danh sách nhà hàng: {e}")
        return

    existing_names = set()
    next_id = 1
    try:
        with open(output_file, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["Restaurant_name"]:
                    existing_names.add(row["Restaurant_name"].strip().lower())
                if row["Restaurant_id"]:
                    try:
                        current_id = int(row["Restaurant_id"])
                        next_id = max(next_id, current_id + 1)
                    except ValueError:
                        logger.warning(f"Restaurant_id không hợp lệ: {row['Restaurant_id']}")
    except Exception as e:
        logger.error(f"Lỗi khi đọc file CSV {output_file}: {e}")
        return

    try:
        with open(output_file, mode="a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=BASE_FIELDNAMES)
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


def extract_features(driver, wait):
    """Crawl feature types từ tab 'About'.

    Args:
        driver: WebDriver instance.
        wait: WebDriverWait instance.

    Returns:
        list: Danh sách các feature types (titles).
    """
    feature_dict = {}
    try:
        about_tabs = wait.until(
            EC.presence_of_all_elements_located((By.XPATH, "//div[text()='About']"))
        )
        if about_tabs and safe_click(driver, about_tabs[0]):
            wait.until(EC.presence_of_element_located((By.XPATH, "//h2[@class='iL3Qke fontTitleSmall']")))
            title_elements = driver.find_elements(By.XPATH, "//h2[@class='iL3Qke fontTitleSmall']")
            for title_elem in title_elements:
                title = title_elem.text.title()
                if title:
                    try:
                        items = title_elem.find_elements(By.XPATH, "./following-sibling::ul//span[@aria-label]")
                        items_list = [item.get_attribute('aria-label') for item in items if item.get_attribute('aria-label')]
                        feature_dict[title] = items_list
                    except Exception as e:
                        logger.warning(f"Lỗi khi lấy items cho {title}: {e}")
                        feature_dict[title] = []
        else:
            logger.warning("Không tìm thấy hoặc không click được tab 'About'")
    except (TimeoutException, NoSuchElementException) as e:
        logger.warning(f"Lỗi khi truy cập tab 'About': {e}")
    return feature_dict

def scrape_restaurant(driver, wait):
    """Thu thập thông tin cơ bản và feature types của một nhà hàng.

    Args:
        driver: WebDriver instance.
        wait: WebDriverWait instance.

    Returns:
        dict: Thông tin cơ bản và list feature types.
    """
    data = {
        "Restaurant_type": "",
        "Rating_average": "",
        "Num_of_reviews": "",
        "Phone": "",
        "Price_level": "",
        "Address": "",
        "Latitude": "",
        "Longitude": "",
        "Crawl_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "feature_type": {}
    }

    # Lấy thông tin
    try:
        data["Price_level"] = driver.find_element(
            By.XPATH,
            '//*[@id="QA0Szd"]/div/div/div[1]/div[2]/div/div[1]/div/div/div[2]/div/div[1]/div[2]/div/div[1]/span/span/span/span[2]/span/span'
        ).text
    except (NoSuchElementException, TimeoutException):
        logger.warning("Lỗi khi lấy mức giá")

    try:
        data["Rating_average"] = wait.until(
            EC.presence_of_element_located((By.XPATH,
                '//*[@id="QA0Szd"]/div/div/div[1]/div[2]/div/div[1]/div/div/div[2]/div/div[1]/div[2]/div/div[1]/div[2]/span[1]/span[1]'
            ))
        ).text
    except (TimeoutException, NoSuchElementException):
        logger.warning("Lỗi khi lấy rating")

    try:
        reviews_elem = driver.find_element(By.CSS_SELECTOR, "div.F7nice span[aria-label*='reviews']")
        reviews_text = reviews_elem.get_attribute("aria-label").split()[0].replace(",", "")
        data["Num_of_reviews"] = int(reviews_text)
    except (NoSuchElementException, ValueError):
        logger.warning("Lỗi khi lấy số lượt đánh giá")

    try:
        phone_elem = driver.find_element(By.CSS_SELECTOR, 'button[data-item-id^="phone:tel"]')
        data["Phone"] = phone_elem.get_attribute('data-item-id').replace("phone:tel:", "")
    except (NoSuchElementException, TimeoutException):
        logger.warning("Lỗi khi lấy số điện thoại")
        
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
        logger.warning("Lỗi khi lấy tọa độ từ Plus Code")

    # Lấy feature types
    data["feature_type"] = extract_features(driver, wait)

    return data

def update_details_and_save(driver, output_file="restaurants.csv", batch_size=10):
    """Cập nhật thông tin cơ bản và feature types cho từng nhà hàng.
    Sau đó lưu toàn bộ vào CSV với cột chứa JSON items cho từng cho feature types.

    Args:
        driver: WebDriver instance.
        output_file: Đường dẫn file CSV.
        batch_size: Số lượng mỗi batch log tiến độ.

    Returns:
        int: Số lượng nhà hàng được cập nhật.
    """
    wait = WebDriverWait(driver, 10)
    
    # Đọc tất cả rows từ CSV
    rows = []
    feature_cols = []
    try:
        with open(output_file, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            feature_cols = [col for col in reader.fieldnames if col not in BASE_FIELDNAMES]
            rows = list(reader)
    except Exception as e:
        logger.error(f"Lỗi khi đọc file CSV {output_file}: {e}")
        return 0

    updated = 0
    total = len(rows)
    data_list = []

    for i, row in enumerate(rows):
        url = row.get("Url", "")
        if not url:
            logger.warning(f"Bỏ qua dòng {i+1}: Không có URL")
            continue
        logger.info(f"Scraping {i+1}/{total}: {row.get('Restaurant_name', 'Unknown')}")
        try:
            driver.get(url)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "h1.DUwDvf")))
            
            # Reconstruct feature_type_old from row
            feature_type_old = {}
            for col in feature_cols:
                val = row.get(col, "")
                if val:
                    try:
                        feature_type_old[col] = json.loads(val)
                    except json.JSONDecodeError:
                        logger.warning(f"Lỗi parse JSON cho cột {col} ở row {i+1}")
                        feature_type_old[col] = []
                else:
                    feature_type_old[col] = []
            
            data = scrape_restaurant(driver, wait)
            if data:
                has_change = False
                current_data = {
                    "Restaurant_id": row.get("Restaurant_id", ""),
                    "Url": url,
                    "Restaurant_name": row.get("Restaurant_name", "Unknown")
                }
                for k in data.keys():
                    if k == "Crawl_date" or k == "feature_type":
                        continue
                    new_val = str(data.get(k, ""))
                    old_val = str(row.get(k, ""))
                    if new_val.strip() == "" and old_val.strip() != "":
                        data[k] = old_val
                    elif new_val != old_val:
                        has_change = True
                current_data.update({k: data.get(k, row.get(k, "")) for k in data.keys() if k != "feature_type" and k != "Crawl_date"})
                
                # Xử lý feature_type
                feature_new = data["feature_type"]
                if feature_new:  # Không rỗng
                    feature_merged = {**feature_type_old, **feature_new}
                    if feature_merged != feature_type_old:
                        has_change = True
                else:
                    feature_merged = feature_type_old
                    if feature_type_old:
                        logger.info(f"Giữ nguyên features cũ cho nhà hàng: {row.get('Restaurant_name', url)} vì scrape thất bại.")
                
                current_data["feature_type"] = feature_merged
                
                # Cập nhật Crawl_date nếu có thay đổi, giữ nguyên cũ nếu không
                if has_change:
                    current_data["Crawl_date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    updated += 1
                    logger.info(f"Cập nhật thay đổi cho nhà hàng: {row.get('Restaurant_name', url)}")
                else:
                    current_data["Crawl_date"] = row.get("Crawl_date", "")
                    logger.info(f"Không có thay đổi cho nhà hàng: {row.get('Restaurant_name', url)}")

                data_list.append(current_data)
        except (TimeoutException, NoSuchElementException) as e:
            logger.error(f"Lỗi scrape {url}: {e}")
            continue

        if (i + 1) % batch_size == 0:
            logger.info(f"Đã xử lý {i+1}/{total} nhà hàng...")

    # Lưu dữ liệu
    if data_list:
        unique_features = set()
        for data in data_list:
            if isinstance(data["feature_type"], dict):
                unique_features.update(data["feature_type"].keys())
        unique_features = sorted(unique_features)

        output_data = {field: [] for field in BASE_FIELDNAMES}
        for data in data_list:
            for field in BASE_FIELDNAMES:
                output_data[field].append(data.get(field, ""))

        for feature in unique_features:
            output_data[feature] = [
                json.dumps(data["feature_type"].get(feature, []), ensure_ascii=False) 
                if isinstance(data["feature_type"], dict) else "[]"
                for data in data_list
            ]

        output_df = pd.DataFrame(output_data)
        output_df.to_csv(output_file, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_NONNUMERIC)
        logger.info(f"Hoàn thành! Đã cập nhật {updated} nhà hàng và lưu vào {output_file}.")
    else:
        logger.warning("Không có dữ liệu để lưu.")

    return updated

def main(search_url="https://www.google.com/maps/search/Restaurants+in+Da+Nang", output_file="restaurants.csv", batch_size=10, headless=False):
    """Hàm chính để chạy chương trình crawl.

    Args:
        search_url: URL tìm kiếm Google Maps.
        output_file: Đường dẫn file CSV.
        batch_size: Số lượng mỗi batch log tiến độ.
        headless: Chạy headless nếu True.
    """
    start_time = datetime.now()
    logger.info(f"Bắt đầu crawl: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    driver = None
    try:
        driver = setup_driver(headless=headless)
        driver.get(search_url)

        init_csv(output_file)

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

        logger.info("Bắt đầu cập nhật chi tiết và đặc điểm nhà hàng...")
        updated = update_details_and_save(driver, output_file, batch_size)
        logger.info(f"Hoàn thành cập nhật dữ liệu! Đã cập nhật {updated} nhà hàng.")

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