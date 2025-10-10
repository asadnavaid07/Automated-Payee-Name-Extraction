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


def main(start_check: int, end_check: int, account_name_contains: str = "CHECKING", parsed_csv_path: Optional[str] = None):
    print(f"🚀 Starting image fetch for checks {start_check} → {end_check} (account filter: '{account_name_contains}')")

    # Save under current project data/images/YYYY-MM/
    base_dir = os.getcwd()
    base_images_dir = os.path.join("data", "images")
    month_folder = datetime.now().strftime("%Y-%m")
    image_dir = os.path.join(base_images_dir, month_folder)
    os.makedirs(image_dir, exist_ok=True)

    df = None
    if parsed_csv_path:
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
        except Exception as e:
            print(f"⚠️ Could not load parsed CSV '{parsed_csv_path}': {e}")
            df = None

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

        # Wait for manual login and 2FA
        print("⏳ Waiting for manual login and 2FA completion...")
        try:
            # Wait until the dashboard URL is reached, indicating successful login
            page.wait_for_url(
                "https://secure.chase.com/web/auth/dashboard#/dashboard/*",
                timeout=300000  # 5 minutes for manual login and 2FA
            )
            print("✅ Login and 2FA completed successfully!")
            page.wait_for_load_state("networkidle")
        except PlaywrightTimeoutError:
            print("⚠️ Timeout waiting for login and 2FA. Please ensure login is completed within 5 minutes.")
            context.close()
            return
        except Exception as e:
            print(f"⚠️ Error during login: {e}")
            context.close()
            return

        # Detect bank from current URL
        current_url = page.url
        bank_name = _infer_bank_from_url(current_url)
        print(f"🏦 Detected bank: {bank_name} (from {current_url})")

        # Dynamic account selection
        try:
            # Find a button containing the specified account_name_contains text
            account_button = page.get_by_role("button").filter(has_text=account_name_contains)
            account_button.wait_for(state="visible", timeout=10000)
            account_button.click()
            page.wait_for_load_state("networkidle")
        except PlaywrightTimeoutError:
            print(f"⚠️ Could not find account button containing '{account_name_contains}' — please verify login.")
            context.close()
            return
        except Exception as e:
            print(f"⚠️ Error selecting account: {e}")
            context.close()
            return

        # Open search activity panel
        def open_search_panel():
            try:
                page.get_by_test_id("quick-action-search-activity-tooltip-button").wait_for(state="visible", timeout=10000)
                page.get_by_test_id("quick-action-search-activity-tooltip-button").click()
                page.wait_for_timeout(2000)
                return True
            except Exception as e:
                print(f"⚠️ Could not open search activity panel: {e}")
                return False

        if not open_search_panel():
            context.close()
            return

        # List to store OCR tasks for parallel execution
        ocr_tasks = []

        try:
            for check_number in range(start_check, end_check + 1):
                print(f"\n🔍 Processing Check #{check_number}...")

                try:
                    for attempt in range(1, 3):  # Try up to 2 times
                        print(f"🔄 Attempt {attempt} for check #{check_number}")
                        # Ensure search panel is open and input fields are visible
                        if not page.locator('[data-test-id="check-from"]').is_visible(timeout=10000):
                            print("↻ Re-opening search activity panel...")
                            if not open_search_panel():
                                print(f"⚠️ Skipping check #{check_number} due to search panel failure.")
                                continue

                        # Wait for input fields explicitly
                        from_input = page.get_by_test_id("check-from").get_by_role("textbox", name="From")
                        to_input = page.get_by_test_id("check-to").get_by_role("textbox", name="To")

                        from_input.wait_for(state="visible", timeout=15000)
                        to_input.wait_for(state="visible", timeout=15000)

                        # Clear and fill inputs
                        from_input.fill("")
                        to_input.fill("")
                        from_input.fill(str(check_number))
                        to_input.fill(str(check_number))

                        page.get_by_test_id("submit").click()
                        page.wait_for_load_state("networkidle", timeout=30000)
                        page.wait_for_timeout(2000)  # Increased delay for table loading

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
                            # Match by numeric check number if possible
                            def to_int_safe(v):
                                try:
                                    return int(str(v).strip().lstrip('0') or '0')
                                except Exception:
                                    return None

                            if 'Check Number' in df.columns:
                                numeric_series = df['Check Number'].apply(to_int_safe)
                                idx_list = df.index[numeric_series == check_number].tolist()
                                if not idx_list and str(check_number) in df['Check Number'].astype(str).values:
                                    # Fallback to string exact match
                                    idx_list = df.index[df['Check Number'].astype(str) == str(check_number)].tolist()
                                if idx_list:
                                    row_idx = idx_list[0]
                                    df.at[row_idx, 'bank'] = bank_name
                                    if front_path:
                                        df.at[row_idx, 'img_front_path'] = front_path
                                    if back_path:
                                        df.at[row_idx, 'img_back_path'] = back_path
                                    df.to_csv(parsed_csv_path, index=False)
                                    print(f"📝 Updated CSV for check {check_number}")
                                else:
                                    print(f"⚠️ No CSV row matched check {check_number}")
                            else:
                                print("⚠️ 'Check Number' column not found in parsed CSV")
                        except Exception as e:
                            print(f"⚠️ Failed to update CSV for check {check_number}: {e}")

                    # Go back to previous page
                    try:
                        page.get_by_role("button", name="Back to previous page").click()
                        page.wait_for_load_state("networkidle")
                        page.wait_for_timeout(1000)
                    except Exception as e:
                        print(f"⚠️ Could not return to previous page: {e}")
                        continue

                except Exception as e:
                    print(f"⚠️ Error processing check #{check_number}: {e}")
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

        print("\n🎉 All checks processed successfully!")
        # Final save after successful completion
        save_df_safely()
        context.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch check images by range")
    parser.add_argument("--start", type=int, required=True, help="Start check number (inclusive)")
    parser.add_argument("--end", type=int, required=True, help="End check number (inclusive)")
    parser.add_argument("--account", type=str, default="CHECKING", help="Substring of account name to select")
    parser.add_argument("--csv", type=str, default=None, help="Path to parsed CSV to update with image paths")
    args = parser.parse_args()

    main(start_check=args.start, end_check=args.end, account_name_contains=args.account, parsed_csv_path=args.csv)