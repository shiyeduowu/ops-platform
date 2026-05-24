from __future__ import annotations

import logging
import time
from typing import Any

from stress.base import BaseStressRunner

logger = logging.getLogger("stress.browser")


class BrowserStressRunner(BaseStressRunner):
    """浏览器自动化压测执行器（ChromeDriver 优先，Playwright 降级）"""

    def run(self) -> dict[str, Any]:
        self._start_time = time.monotonic()

        engine = self.config.get("browser_engine", "auto")
        iterations = min(self.config.get("iterations", 1), 50)
        steps = self.config.get("steps", [])
        timeout_ms = self.config.get("timeout_ms", 30000)
        results: list[dict[str, Any]] = []

        # 选择引擎
        use_engine = self._detect_engine(engine)
        logger.info("浏览器引擎: %s", use_engine)

        for i in range(iterations):
            if self._cancelled:
                break
            iter_result = self._run_single_iteration(i, steps, timeout_ms, use_engine)
            results.append(iter_result)
            self.report_progress({
                "completed_iterations": i + 1,
                "total_iterations": iterations,
                "current": iter_result,
                "engine": use_engine,
            })

        return {
            "iterations": results,
            "summary": self._compute_summary(results),
            "engine": use_engine,
        }

    def _detect_engine(self, preference: str) -> str:
        """检测可用的浏览器引擎"""
        if preference in ("chromedriver", "auto"):
            try:
                from selenium import webdriver
                from selenium.webdriver.chrome.options import Options
                # 尝试创建 driver 来验证可用性
                options = Options()
                options.add_argument("--headless")
                options.add_argument("--no-sandbox")
                options.add_argument("--disable-gpu")
                driver_path = self.config.get("chromedriver_path")
                if driver_path:
                    from selenium.webdriver.chrome.service import Service
                    service = Service(executable_path=driver_path)
                    driver = webdriver.Chrome(service=service, options=options)
                else:
                    driver = webdriver.Chrome(options=options)
                driver.quit()
                return "chromedriver"
            except Exception as e:
                if preference == "chromedriver":
                    raise RuntimeError(f"ChromeDriver 不可用: {e}")
                logger.warning("ChromeDriver 不可用，尝试 Playwright: %s", e)

        if preference in ("playwright", "auto"):
            try:
                from playwright.sync_api import sync_playwright
                return "playwright"
            except ImportError:
                if preference == "playwright":
                    raise RuntimeError(
                        "Playwright 未安装。请执行: pip install playwright && playwright install chromium"
                    )

        raise RuntimeError("无可用的浏览器引擎。请安装 ChromeDriver 或 Playwright")

    def _run_single_iteration(
        self, idx: int, steps: list[dict], timeout_ms: int, engine: str,
    ) -> dict[str, Any]:
        if engine == "chromedriver":
            return self._run_with_selenium(idx, steps, timeout_ms)
        return self._run_with_playwright(idx, steps, timeout_ms)

    # ──────────────── Selenium 实现 ────────────────

    def _run_with_selenium(self, idx: int, steps: list[dict], timeout_ms: int) -> dict[str, Any]:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        timings: dict[str, float] = {}
        step_results: list[dict[str, Any]] = []
        success = True
        error_msg: str | None = None

        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-dev-shm-usage")
        chrome_binary = self.config.get("chrome_binary_path")
        if chrome_binary:
            options.binary_location = chrome_binary

        driver_path = self.config.get("chromedriver_path")
        try:
            if driver_path:
                from selenium.webdriver.chrome.service import Service
                service = Service(executable_path=driver_path)
                driver = webdriver.Chrome(service=service, options=options)
            else:
                driver = webdriver.Chrome(options=options)

            driver.set_page_load_timeout(timeout_ms // 1000)
            driver.implicitly_wait(5)

            for step in steps:
                if self._cancelled:
                    break
                action = step.get("action", "")
                start = time.monotonic()
                step_ok = True
                step_error: str | None = None
                try:
                    self._execute_selenium_step(driver, step, timeout_ms)
                except Exception as e:
                    step_ok = False
                    step_error = str(e)[:500]
                    success = False
                elapsed_ms = round((time.monotonic() - start) * 1000, 1)

                key = f"{action}_{step.get('xpath', step.get('url', ''))}"
                timings[key] = elapsed_ms
                step_results.append({
                    "action": action,
                    "target": step.get("xpath") or step.get("url", ""),
                    "elapsed_ms": elapsed_ms,
                    "success": step_ok,
                    "error": step_error,
                })

                if not step_ok:
                    error_msg = step_error
                    break

            driver.quit()
        except Exception as e:
            success = False
            error_msg = str(e)[:500]

        return {
            "iteration": idx,
            "timings_ms": timings,
            "steps": step_results,
            "success": success,
            "error": error_msg,
            "total_ms": round(sum(timings.values()), 1),
        }

    def _execute_selenium_step(self, driver, step: dict, timeout_ms: int) -> None:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        action = step.get("action", "")
        xpath = step.get("xpath")
        url = step.get("url")
        value = step.get("value")
        timeout_s = (step.get("timeout_ms", timeout_ms)) / 1000

        if action == "navigate":
            if not url:
                raise ValueError("navigate 步骤需要 url")
            driver.get(url)

        elif action == "click":
            if not xpath:
                raise ValueError("click 步骤需要 xpath")
            elem = WebDriverWait(driver, timeout_s).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            elem.click()

        elif action == "input":
            if not xpath:
                raise ValueError("input 步骤需要 xpath")
            elem = WebDriverWait(driver, timeout_s).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
            elem.clear()
            elem.send_keys(value or "")

        elif action == "wait":
            if xpath:
                WebDriverWait(driver, timeout_s).until(
                    EC.presence_of_element_located((By.XPATH, xpath))
                )
            else:
                time.sleep(min(timeout_s, 5))

        elif action == "assert_text":
            if not xpath:
                raise ValueError("assert_text 步骤需要 xpath")
            elem = WebDriverWait(driver, timeout_s).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
            actual = elem.text
            if value and value not in actual:
                raise AssertionError(f"文本断言失败: 期望包含 '{value}', 实际 '{actual}'")

        elif action == "screenshot":
            driver.get_screenshot_as_png()

        else:
            raise ValueError(f"未知步骤操作: {action}")

    # ──────────────── Playwright 实现 ────────────────

    def _run_with_playwright(self, idx: int, steps: list[dict], timeout_ms: int) -> dict[str, Any]:
        from playwright.sync_api import sync_playwright

        timings: dict[str, float] = {}
        step_results: list[dict[str, Any]] = []
        success = True
        error_msg: str | None = None

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
                )
                context = browser.new_context()
                context.set_default_timeout(timeout_ms)
                page = context.new_page()

                for step in steps:
                    if self._cancelled:
                        break
                    action = step.get("action", "")
                    start = time.monotonic()
                    step_ok = True
                    step_error: str | None = None
                    try:
                        self._execute_playwright_step(page, step)
                    except Exception as e:
                        step_ok = False
                        step_error = str(e)[:500]
                        success = False
                    elapsed_ms = round((time.monotonic() - start) * 1000, 1)

                    key = f"{action}_{step.get('xpath', step.get('url', ''))}"
                    timings[key] = elapsed_ms
                    step_results.append({
                        "action": action,
                        "target": step.get("xpath") or step.get("url", ""),
                        "elapsed_ms": elapsed_ms,
                        "success": step_ok,
                        "error": step_error,
                    })

                    if not step_ok:
                        error_msg = step_error
                        break

                context.close()
                browser.close()
        except Exception as e:
            success = False
            error_msg = str(e)[:500]

        return {
            "iteration": idx,
            "timings_ms": timings,
            "steps": step_results,
            "success": success,
            "error": error_msg,
            "total_ms": round(sum(timings.values()), 1),
        }

    def _execute_playwright_step(self, page, step: dict) -> None:
        action = step.get("action", "")
        xpath = step.get("xpath")
        url = step.get("url")
        value = step.get("value")
        timeout_ms = step.get("timeout_ms", 10000)

        if action == "navigate":
            if not url:
                raise ValueError("navigate 步骤需要 url")
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

        elif action == "click":
            if not xpath:
                raise ValueError("click 步骤需要 xpath")
            page.locator(f"xpath={xpath}").click(timeout=timeout_ms)

        elif action == "input":
            if not xpath:
                raise ValueError("input 步骤需要 xpath")
            page.locator(f"xpath={xpath}").fill(value or "", timeout=timeout_ms)

        elif action == "wait":
            if xpath:
                page.locator(f"xpath={xpath}").wait_for(state="visible", timeout=timeout_ms)
            else:
                page.wait_for_timeout(min(timeout_ms, 5000))

        elif action == "assert_text":
            if not xpath:
                raise ValueError("assert_text 步骤需要 xpath")
            locator = page.locator(f"xpath={xpath}")
            actual = locator.inner_text(timeout=timeout_ms)
            if value and value not in actual:
                raise AssertionError(f"文本断言失败: 期望包含 '{value}', 实际 '{actual}'")

        elif action == "screenshot":
            page.screenshot()

        else:
            raise ValueError(f"未知步骤操作: {action}")

    # ──────────────── 工具方法 ────────────────

    def _compute_summary(self, iterations: list[dict]) -> dict[str, Any]:
        if not iterations:
            return {"total_iterations": 0, "success_rate": 0, "avg_page_load_ms": 0}

        success_count = sum(1 for it in iterations if it.get("success"))
        total_times = [it.get("total_ms", 0) for it in iterations]

        return {
            "total_iterations": len(iterations),
            "success_count": success_count,
            "success_rate": round(success_count / len(iterations) * 100, 1),
            "avg_page_load_ms": round(sum(total_times) / len(total_times), 1) if total_times else 0,
            "min_page_load_ms": round(min(total_times), 1) if total_times else 0,
            "max_page_load_ms": round(max(total_times), 1) if total_times else 0,
        }
