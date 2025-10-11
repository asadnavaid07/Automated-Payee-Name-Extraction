from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from datetime import datetime
import os
import time
import argparse
from typing import Optional
import pandas as pd
from urllib.parse import urlparse
from extract_payee import extract_check_info
from concurrent.futures import ThreadPoolExecutor, as_completed


def _infer_bank_from_url(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        parts = [p for p in host.split('.') if p]
        if len(parts) >= 2:
            return parts[-2]
        if parts:
            return parts[-1]
    except Exception:
        pass
    return "unknown"


def run_ocr(front_path: str, check_number: str) -> Optional[dict]:
    """Run OCR on the front image and return the result."""
    if not os.path.exists(front_path):
        print(f"⚠️ Front image not found at {front_path}. Skipping OCR.")
        return None
    try:
        return extract_check_info(front_path)
    except Exception as e:
        print(f"⚠️ OCR failed for {front_path}: {e}")
        return None


def initialize_session(p, user_data_dir: str, account_name_contains: str) -> tuple:
    """Initialize or reinitialize a browser session with login and account selection."""
    context = None
    page = None
    try:
        context = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            channel="chrome",
            headless=False,
        )
        page = context.new_page()

        print("🌐 Opening Chase Login Page...")
        page.goto(
            "https://secure.chase.com/web/auth/#/logon/logon/chaseOnline",
            timeout=120000,
        )

        print("⏳ Waiting for manual login and 2FA completion...")
        try:
            page.wait_for_url(
                "https://secure.chase.com/web/auth/dashboard#/dashboard/*")
            print("✅ Login and 2FA completed successfully!")
            page.wait_for_load_state("networkidle")
        except PlaywrightTimeoutError:
            print("⚠️ Timeout waiting for login and 2FA. Please ensure login is completed within 5 minutes.")
            return None, None
        except Exception as e:
            print(f"⚠️ Error during login: {e}")
            return None, None

        # Detect bank from current URL
        current_url = page.url
        bank_name = _infer_bank_from_url(current_url)
        print(f"🏦 Detected bank: {bank_name} (from {current_url})")

        # Dynamic account selection
        try:
            account_button = page.get_by_role("button").filter(has_text=account_name_contains)
            account_button.wait_for(state="visible", timeout=10000)
            account_button.click()
            page.wait_for_load_state("networkidle")
        except PlaywrightTimeoutError:
            print(f"⚠️ Could not find account button containing '{account_name_contains}' — please verify login.")
            return None, None
        except Exception as e:
            print(f"⚠️ Error selecting account: {e}")
            return None, None

        # Open search activity panel
        try:
            page.get_by_test_id("quick-action-search-activity-tooltip-button").wait_for(state="visible", timeout=10000)
            page.get_by_test_id("quick-action-search-activity-tooltip-button").click()
            page.wait_for_timeout(2000)
            return context, page
        except Exception as e:
            print(f"⚠️ Could not open search activity panel: {e}")
            return None, None

    except Exception as e:
        print(f"⚠️ Failed to initialize session: {e}")
        if context:
            try:
                context.close()
            except Exception:
                pass
        return None, None


def main(account_name_contains: str = "CHECKING", parsed_csv_path: str = None):
    print(f"🚀 Starting image fetch for checks in CSV '{parsed_csv_path}' (account filter: '{account_name_contains}')")

    # Save under current project data/images/YYYY-MM/
    base_dir = os.getcwd()
    base_images_dir = os.path.join("data", "images")
    month_folder = datetime.now().strftime("%Y-%m")
    image_dir = os.path.join(base_images_dir, month_folder)
    os.makedirs(image_dir, exist_ok=True)

    # Load CSV
    df = None
    if not parsed_csv_path:
        print("⚠️ CSV path is required. Exiting.")
        return
    try:
        # Use the parsed_csv_path as-is if it's absolute, otherwise make it relative to current directory
        if not os.path.isabs(parsed_csv_path):
            parsed_csv_path = os.path.join(os.getcwd(), parsed_csv_path)
        df = pd.read_csv(parsed_csv_path)
        # Ensure columns exist and remove duplicates
        required_columns = {
            'bank': '',
            'img_front_path': '',
            'img_back_path': '',
            'payee_name': '',
            'confidence': '',
            'source': ''
        }
        # Remove duplicate columns by keeping only the first occurrence
        df = df.loc[:, ~df.columns.duplicated()]
        # Add missing columns
        for col_name, default_value in required_columns.items():
            if col_name not in df.columns:
                df[col_name] = default_value
        # Verify Check Number column exists
        if 'Check Number' not in df.columns:
            print("⚠️ 'Check Number' column not found in CSV. Exiting.")
            return
    except Exception as e:
        print(f"⚠️ Could not load parsed CSV '{parsed_csv_path}': {e}")
        return

    def save_df_safely():
        try:
            if df is not None and parsed_csv_path:
                df.to_csv(parsed_csv_path, index=False)
        except Exception as se:
            print(f"⚠️ Failed to save CSV: {se}")

    with sync_playwright() as p:
        user_data_dir = os.path.expanduser(
            r"~\AppData\Local\Google\Chrome\User Data\Default"
        )
        context, page = initialize_session(p, user_data_dir, account_name_contains)
        if not context or not page:
            print("⚠️ Initial session setup failed. Exiting.")
            return

        session_start_time = time.time()  # Track session start time for time-based relogin

        # List to store OCR tasks for parallel execution
        ocr_tasks = []

        try:
            # Iterate over Check Number column
            for idx, row in df.iterrows():
                # Check for time-based relogin
                if time.time() - session_start_time > 1800:  # 30 minutes = 1800 seconds
                    print("⚠️ 30 minutes elapsed. Triggering relogin to refresh session...")
                    save_df_safely()
                    # Process pending OCR tasks
                    if ocr_tasks and df is not None:
                        print("\n📸 Running OCR in parallel for current images...")
                        with ThreadPoolExecutor() as executor:
                            future_to_path = {executor.submit(run_ocr, path, check_num): (path, check_num) for path, check_num in ocr_tasks}
                            for future in as_completed(future_to_path):
                                front_path, check_number_str = future_to_path[future]
                                try:
                                    ocr_result = future.result()
                                    if ocr_result:
                                        ocr_payee = ocr_result.get('payee_name', '')
                                        ocr_conf = ocr_result.get('confidence')
                                        ocr_check = ocr_result.get('check_number', check_number_str)
                                        # Normalize numeric for match
                                        def to_int_safe(v):
                                            try:
                                                return int(str(v).strip().lstrip('0') or '0')
                                            except Exception:
                                                return None
                                        target_num = to_int_safe(ocr_check)
                                        row_idx = None
                                        if 'Check Number' in df.columns:
                                            numeric_series = df['Check Number'].apply(to_int_safe)
                                            if target_num is not None:
                                                idx_list = df.index[numeric_series == target_num].tolist()
                                            else:
                                                idx_list = []
                                            if not idx_list:
                                                # Fallback exact string match
                                                idx_list = df.index[df['Check Number'].astype(str) == str(check_number_str)].tolist()
                                            if idx_list:
                                                row_idx = idx_list[0]
                                        if row_idx is not None and ocr_payee:
                                            df.at[row_idx, 'payee_name'] = ocr_payee
                                            if ocr_conf is not None:
                                                df.at[row_idx, 'confidence'] = ocr_conf
                                            df.at[row_idx, 'source'] = 'ocr'
                                            df.to_csv(parsed_csv_path, index=False)
                                            print(f"📝 OCR updated CSV for check {check_number_str}: payee='{ocr_payee}'")
                                except Exception as e:
                                    print(f"⚠️ OCR processing failed for {front_path}: {e}")
                        ocr_tasks = []  # Clear tasks after processing

                    # Close current context and reinitialize
                    try:
                        context.close()
                    except Exception as e:
                        print(f"⚠️ Error closing context: {e}")
                    context, page = initialize_session(p, user_data_dir, account_name_contains)
                    if not context or not page:
                        print("⚠️ Failed to reinitialize session. Exiting.")
                        return
                    session_start_time = time.time()  # Reset session start time

                check_number = str(row['Check Number']).strip()
                if not check_number or check_number.lower() in ('nan', ''):
                    print(f"⚠️ Invalid or missing check number at CSV row {idx+1}. Skipping...")
                    continue
                try:
                    check_number_int = int(check_number.lstrip('0') or '0')  # Normalize for display
                except ValueError:
                    print(f"⚠️ Invalid check number '{check_number}' at CSV row {idx+1}. Skipping...")
                    continue

                print(f"\n🔍 Processing Check #{check_number} (CSV row {idx+1})...")

                try:
                    for attempt in range(1, 3):  # Try up to 2 times
                        print(f"🔄 Attempt {attempt} for check #{check_number}")
                        # Ensure search panel is open and input fields are visible
                        if not page.locator('[data-test-id="check-from"]').is_visible(timeout=10000):
                            print("↻ Re-opening search activity panel...")
                            try:
                                page.get_by_test_id("quick-action-search-activity-tooltip-button").wait_for(state="visible", timeout=10000)
                                page.get_by_test_id("quick-action-search-activity-tooltip-button").click()
                                page.wait_for_timeout(2000)
                            except Exception as e:
                                print(f"⚠️ Could not open search activity panel: {e}")
                                continue

                        # Wait for input fields explicitly
                        from_input = page.get_by_test_id("check-from").get_by_role("textbox", name="From")
                        to_input = page.get_by_test_id("check-to").get_by_role("textbox", name="To")

                        try:
                            from_input.wait_for(state="visible", timeout=15000)
                            to_input.wait_for(state="visible", timeout=15000)
                        except PlaywrightTimeoutError:
                            print("⚠️ Input fields not visible.")
                            continue

                        # Clear and fill inputs
                        from_input.fill("")
                        to_input.fill("")
                        from_input.fill(check_number)
                        to_input.fill(check_number)

                        try:
                            page.get_by_test_id("submit").click()
                            page.wait_for_load_state("networkidle", timeout=30000)
                            page.wait_for_timeout(2000)  # Increased delay for table loading
                        except PlaywrightTimeoutError:
                            print("⚠️ Submit button or page load failed.")
                            continue

                        # Check for check record in table
                        found = False
                        try:
                            # Locate all table rows and iterate to find the check number
                            rows = page.locator("tr").all()
                            print(f"🔎 Found {len(rows)} table rows to search for check #{check_number}")
                            for row in rows:
                                try:
                                    # Check if row contains the check number (e.g., "CHECK # 3515" or "CHECK #3515 01/17")
                                    row_text = row.text_content().lower()
                                    if f"check #{check_number}" in row_text.lower() or f"check # {check_number}" in row_text.lower():
                                        # Find the link within the row
                                        check_link = row.locator("a")
                                        check_link.wait_for(state="visible", timeout=5000)
                                        check_link.click()
                                        found = True
                                        print(f"✅ Found check #{check_number} in table row via text search")
                                        break
                                except PlaywrightTimeoutError:
                                    continue
                                except Exception as e:
                                    print(f"⚠️ Error checking row for check #{check_number}: {e}")
                                    continue
                            if found:
                                break
                        except PlaywrightTimeoutError:
                            print(f"⚠️ No table rows found for check #{check_number}. Trying alternative test IDs...")
                            # Fallback to original test_id-based approach
                            for suffix in range(0, 5):
                                test_id = f"mds-rich-text-link-CHECK-#-{check_number}_id_{suffix}"
                                try:
                                    check_link = page.get_by_test_id(test_id)
                                    check_link.wait_for(state="visible", timeout=5000)
                                    check_link.click()
                                    found = True
                                    print(f"✅ Found check #{check_number} with test ID {test_id}")
                                    break
                                except PlaywrightTimeoutError:
                                    continue
                                except Exception:
                                    continue

                        if found:
                            break
                        else:
                            print(f"⚠️ Check #{check_number} not found on attempt {attempt}. Retrying..." if attempt < 2 else f"⚠️ Check #{check_number} not found after {attempt} attempts.")

                    if not found:
                        print(f"⚠️ No record found for check #{check_number}. Skipping...")
                        continue

                    page.wait_for_load_state("networkidle")
                    time.sleep(2)

                    # Filenames: check_<number>_front.png and check_<number>_back.png
                    front_path = os.path.join(image_dir, f"check_{check_number}_front.png")
                    back_path = os.path.join(image_dir, f"check_{check_number}_back.png")

                    # Capture front image
                    try:
                        page.wait_for_selector("img[alt='Front of check']", timeout=15000)
                        page.locator("img[alt='Front of check']").screenshot(path=front_path)
                        print(f"✅ Saved front image: {front_path}")
                    except PlaywrightTimeoutError:
                        print("⚠️ Could not find front image — skipping front capture.")
                        front_path = None  # Set to None to skip OCR
                    else:
                        # Submit OCR task for parallel execution
                        ocr_tasks.append((front_path, str(check_number)))

                    # Capture back image
                    try:
                        page.get_by_role("tab", name="Back").click()
                        page.wait_for_selector("img[alt='Back of check']", timeout=15000)
                        page.locator("img[alt='Back of check']").screenshot(path=back_path)
                        print(f"✅ Saved back image: {back_path}")
                    except PlaywrightTimeoutError:
                        print("⚠️ Could not find back image — skipping back capture.")
                        back_path = None

                    # Update parsed CSV for this check
                    if df is not None and (front_path or back_path):
                        try:
                            df.at[idx, 'bank'] = _infer_bank_from_url(page.url)
                            if front_path:
                                df.at[idx, 'img_front_path'] = front_path
                            if back_path:
                                df.at[idx, 'img_back_path'] = back_path
                            df.to_csv(parsed_csv_path, index=False)
                            print(f"📝 Updated CSV for check {check_number} (row {idx+1})")
                        except Exception as e:
                            print(f"⚠️ Failed to update CSV for check {check_number} (row {idx+1}): {e}")

                    # Go back to previous page
                    try:
                        page.get_by_role("button", name="Back to previous page").click()
                        page.wait_for_load_state("networkidle")
                        page.wait_for_timeout(1000)
                    except Exception as e:
                        print(f"⚠️ Could not return to previous page: {e}")
                        continue

                except Exception as e:
                    print(f"⚠️ Error processing check #{check_number} (row {idx+1}): {e}")
                    continue

            # Run OCR tasks in parallel
            if ocr_tasks and df is not None:
                print("\n📸 Running OCR in parallel for captured images...")
                with ThreadPoolExecutor() as executor:
                    future_to_path = {executor.submit(run_ocr, path, check_num): (path, check_num) for path, check_num in ocr_tasks}
                    for future in as_completed(future_to_path):
                        front_path, check_number = future_to_path[future]
                        try:
                            ocr_result = future.result()
                            if ocr_result:
                                ocr_payee = ocr_result.get('payee_name', '')
                                ocr_conf = ocr_result.get('confidence')
                                ocr_check = ocr_result.get('check_number', check_number)
                                # Normalize numeric for match
                                def to_int_safe(v):
                                    try:
                                        return int(str(v).strip().lstrip('0') or '0')
                                    except Exception:
                                        return None
                                target_num = to_int_safe(ocr_check)
                                row_idx = None
                                if 'Check Number' in df.columns:
                                    numeric_series = df['Check Number'].apply(to_int_safe)
                                    if target_num is not None:
                                        idx_list = df.index[numeric_series == target_num].tolist()
                                    else:
                                        idx_list = []
                                    if not idx_list:
                                        # Fallback exact string match
                                        idx_list = df.index[df['Check Number'].astype(str) == str(check_number)].tolist()
                                    if idx_list:
                                        row_idx = idx_list[0]
                                if row_idx is not None and ocr_payee:
                                    df.at[row_idx, 'payee_name'] = ocr_payee
                                    if ocr_conf is not None:
                                        df.at[row_idx, 'confidence'] = ocr_conf
                                    df.at[row_idx, 'source'] = 'ocr'
                                    df.to_csv(parsed_csv_path, index=False)
                                    print(f"📝 OCR updated CSV for check {check_number}: payee='{ocr_payee}'")
                        except Exception as e:
                            print(f"⚠️ OCR processing failed for {front_path}: {e}")

        except KeyboardInterrupt:
            print("\n⏹️ Interrupted by user. Partial results saved.")
        except Exception as e:
            print(f"\n❌ Aborting due to unexpected error: {e}")
        finally:
            # Always attempt a final save of CSV before closing context
            save_df_safely()
            try:
                context.close()
            except Exception as e:
                print(f"⚠️ Error closing context: {e}")

        print("\n🎉 All checks processed successfully!")
        # Final save after successful completion
        save_df_safely()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch check images from CSV")
    parser.add_argument("--account", type=str, default="CHECKING", help="Substring of account name to select")
    parser.add_argument("--csv", type=str, required=True, help="Path to parsed CSV containing Check Number column")
    args = parser.parse_args()

    main(account_name_contains=args.account, parsed_csv_path=args.csv)

    