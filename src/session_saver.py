from playwright.sync_api import sync_playwright
import os
import sys
from datetime import datetime

def main():
    # Path to Chrome user data directory (Windows)
    user_data_dir = os.path.expanduser(r"C:\Users\PMLS\AppData\Local\Google\Chrome\User Data\Default")  # Adjust for client’s username
    post_login_url = ""
    output_file = "recorded_flow.py"
    screenshot_dir = os.path.expanduser(r"C:\Users\PMLS\Desktop\bank-automation")  # Adjust to your preferred screenshot directory

    if not os.path.exists(screenshot_dir):
        os.makedirs(screenshot_dir)

    print("Starting browser to confirm login session...")
    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                channel="chrome"
            )
            page = context.new_page()
            page.goto(post_login_url)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            page.screenshot(path=os.path.join(screenshot_dir, f"initial_page_{timestamp}.png"))

            if page.is_visible('input[name="email"]') or page.is_visible('input[name="approvals_code"]'):
                print("Login or 2FA required. Enter your Bank credentials/2FA code, then click 'Resume' in the browser overlay.")
                page.pause()

            print("Browser is open. Confirm you see your Bank Dashboard.")
            print("Press Enter to close this browser and start recording instructions.")
            input("Press Enter when ready...")

            context.close()


        recorded_code = [
            "from playwright.sync_api import sync_playwright",
            "import os",
            "from datetime import datetime",
            "",
            "def main():",
            f"    user_data_dir = os.path.expanduser(r\"{user_data_dir}\")",
            f"    post_login_url = \"{post_login_url}\"",
            f"    screenshot_dir = os.path.expanduser(r\"{screenshot_dir}\")",
            "    # Create screenshot directory if it doesn't exist",
            "    if not os.path.exists(screenshot_dir):",
            "        os.makedirs(screenshot_dir)",
            "    with sync_playwright() as p:",
            "        context = p.chromium.launch_persistent_context(",
            "            user_data_dir=user_data_dir,",
            "            headless=False,",
            "            channel=\"chrome\"",
            "        )",
            "        page = context.new_page()",
            f"        page.goto(\"{post_login_url}\")",
            "        timestamp = datetime.now().strftime(\"%Y%m%d_%H%M%S\")",
            "        page.screenshot(path=os.path.join(screenshot_dir, f\"initial_page_{timestamp}.png\"))",
            "",
            "        # Add your recorded actions here (e.g., from 'playwright codegen')",
            "        # Example: page.click('a[href*=\"/reels/\"]')",
            "        # page.wait_for_load_state('load')",
            "        # timestamp = datetime.now().strftime(\"%Y%m%d_%H%M%S\")",
            "        # page.screenshot(path=os.path.join(screenshot_dir, f\"check_ss_{timestamp}.png\"))",
            "",
            "        context.close()",
            "",
            "if __name__ == \"__main__\":",
            "    main()"
        ]

        with open(output_file, "w") as f:
            f.write("\n".join(recorded_code))

        print(f"\nPlaceholder code saved to '{output_file}'.")
        print("Screenshots will be saved to: ", screenshot_dir)
        print("To record your actions for navigate:")
        print("1. Open Command Prompt and run: playwright codegen https://www.example.com/ --output temp.py")
        print("2. If prompted, log in and complete 2FA (this updates your session).")
        print("3. Complete your navigation to the desired page")
        print("4. Close the browser to save actions to 'temp.py'.")
        print("5. Open 'temp.py', copy the actions (e.g., page.click, page.wait_for_load_state) into 'recorded_flow.py' under '# Recorded actions'.")
        print("6. Add the following lines after the navigation to take a screenshot:")
        print("   timestamp = datetime.now().strftime(\"%Y%m%d_%H%M%S\")")
        print("   page.screenshot(path=os.path.join(screenshot_dir, f\"reels_page_{timestamp}.png\"))")
        print("7. Run: python recorded_flow.py to test (it should not ask for login).")
        print("If you can’t copy actions, describe your steps (e.g., 'Clicked Reels icon in sidebar') and send to the developer.")

    except Exception as e:
        print(f"Error: {e}")
        print("Check if Chrome is installed, the user_data_dir is correct, or contact the developer.")

if __name__ == "__main__":
    main()