from langchain.tools import tool
from playwright.sync_api import sync_playwright
import threading

_thread_local = threading.local()

def _get_page():
    if not hasattr(_thread_local, 'playwright'):
        _thread_local.playwright = sync_playwright().start()
        _thread_local.browser = _thread_local.playwright.chromium.launch(headless=False)
        _thread_local.page = _thread_local.browser.new_page()
    return _thread_local.page

@tool
def navigate_to_url(url: str) -> str:
    """Navigates the browser to the specified URL. Use this for browsing the web natively."""
    try:
        page = _get_page()
        page.goto(url, wait_until="domcontentloaded")
        return f"Successfully navigated to {url}."
    except Exception as e:
        return f"Failed to navigate: {e}"

@tool
def extract_page_content() -> str:
    """Extracts the visible text content from the current webpage."""
    try:
        page = _get_page()
        content = page.evaluate('document.body.innerText')
        return content[:4000] + "\n...(truncated)" if len(content) > 4000 else content
    except Exception as e:
        return f"Failed to extract content: {e}"

@tool
def browser_click_element(text: str) -> str:
    """Clicks a button, link, or element on the webpage that matches the provided text."""
    try:
        page = _get_page()
        page.get_by_text(text, exact=False).first.click(timeout=3000)
        return f"Successfully clicked element containing '{text}'."
    except Exception as e:
        return f"Failed to click element: {e}"

@tool
def browser_type_text(placeholder: str, text: str) -> str:
    """Types text into an input field on the webpage that matches the provided placeholder or label text."""
    try:
        page = _get_page()
        page.get_by_placeholder(placeholder, exact=False).first.fill(text, timeout=3000)
        return f"Successfully typed into field '{placeholder}'."
    except Exception as e:
        try:
            page.get_by_label(placeholder, exact=False).first.fill(text, timeout=3000)
            return f"Successfully typed into field labeled '{placeholder}'."
        except Exception as e2:
            return f"Failed to type text: {e2}"

get_playwright_tools = lambda: [navigate_to_url, extract_page_content, browser_click_element, browser_type_text]
