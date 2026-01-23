#!/usr/bin/env python3
"""
Test script to validate Country filtering and model name extraction.
Filters by Country China and extracts top 10 model names.
"""
from playwright.sync_api import sync_playwright
import time

def test_china_filter():
    with sync_playwright() as p:
        print("Launching browser...")
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        
        print("Navigating to leaderboard...")
        page.goto("https://llm-stats.com/leaderboards/llm-leaderboard", timeout=60000)
        # Wait for DOM to be ready instead of networkidle
        page.wait_for_load_state("domcontentloaded")
        time.sleep(3)  # Give JS time to initialize
        
        print("Looking for Country filter...")
        # Try multiple selectors for the Country filter
        selectors = [
            "button:has-text('Country')",
            "[aria-label*='Country']",
            "div.filter-button:has-text('Country')",
            "button[class*='filter']:has-text('Country')",
            ".filter:has-text('Country')"
        ]
        
        country_button = None
        for selector in selectors:
            try:
                country_button = page.wait_for_selector(selector, timeout=5000)
                if country_button:
                    print(f"Found Country filter using selector: {selector}")
                    break
            except:
                continue
        
        if not country_button:
            print("ERROR: Could not find Country filter button")
            print("Page content preview:")
            print(page.content()[:2000])
            browser.close()
            return
        
        print("Clicking Country filter...")
        country_button.click()
        time.sleep(1)
        
        print("Looking for China option...")
        # Try to find China option
        china_selectors = [
            "text='China'",
            "text='🇨🇳 China'",
            "[role='option']:has-text('China')",
            "div:has-text('China')",
            "li:has-text('China')"
        ]
        
        china_option = None
        for selector in china_selectors:
            try:
                china_option = page.wait_for_selector(selector, timeout=5000)
                if china_option:
                    print(f"Found China option using selector: {selector}")
                    break
            except:
                continue
        
        if not china_option:
            print("ERROR: Could not find China option")
            print("Available options:")
            print(page.content()[:2000])
            browser.close()
            return
        
        print("Clicking China option...")
        china_option.click()
        time.sleep(2)  # Wait for table to update
        
        print("Extracting model names from table...")
        # Get table rows
        rows = page.query_selector_all("tbody tr")
        
        if not rows:
            print("ERROR: No table rows found")
            browser.close()
            return
        
        print(f"Found {len(rows)} rows")
        models = []
        
        for i, row in enumerate(rows[:10]):  # Top 10
            # Try multiple selectors for model name
            name = None
            
            # Try getting link text (model names are usually links)
            link = row.query_selector("a")
            if link:
                name = link.inner_text().strip()
            
            # If no link, try first cell
            if not name:
                name_cell = row.query_selector("td:first-child")
                if name_cell:
                    name = name_cell.inner_text().strip()
            
            if name:
                models.append(name)
                print(f"{i+1}. {name}")
            else:
                print(f"{i+1}. (empty)")
        
        print(f"\nSuccessfully extracted {len(models)} model names")
        browser.close()

if __name__ == "__main__":
    test_china_filter()
