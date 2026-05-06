"""
Day 3 test suite — Paper trades, price alerts, price monitor logic.

Run from the backend directory:
  C:\\Users\\fadhm\\Desktop\\zentryx\\backend\\.venv\\Scripts\\python.exe test_day3.py
"""
from __future__ import annotations

import asyncio
import sys
import os
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

PASS = "[PASS]"
FAIL = "[FAIL]"
results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    results.append((name, condition, detail))
    status = PASS if condition else FAIL
    print(f"{status}  {name}" + (f"  — {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# Test 1-2: DB table imports
# ---------------------------------------------------------------------------

def test_imports() -> None:
    print("\n--- Table imports ---")
    try:
        from db import paper_trade_table, price_alert_table
        check("paper_trade_table importable", True)
        check("price_alert_table importable", True)
        cols_pt = {c.name for c in paper_trade_table.c}
        required_pt = {
            "id", "telegram_user_id", "token_address", "symbol", "side",
            "entry_price", "entry_time", "tp_pct", "sl_pct", "position_size_usd",
            "status", "exit_price", "exit_time", "pnl_pct", "close_reason", "created_at"
        }
        check("paper_trade_table has all columns", required_pt.issubset(cols_pt), str(required_pt - cols_pt) or "ok")
        cols_pa = {c.name for c in price_alert_table.c}
        required_pa = {
            "id", "telegram_user_id", "token_address", "symbol", "target_price",
            "direction", "created_at", "triggered_at", "status"
        }
        check("price_alert_table has all columns", required_pa.issubset(cols_pa), str(required_pa - cols_pa) or "ok")
    except Exception as exc:
        check("DB table imports", False, str(exc))


# ---------------------------------------------------------------------------
# Test 3-5: Router imports
# ---------------------------------------------------------------------------

def test_router_imports() -> None:
    print("\n--- Router imports ---")
    try:
        from routers.trades import router
        check("trades router importable", True)
        routes = {r.path for r in router.routes}
        check("POST /api/trades route exists", "/api/trades" in routes, str(routes))
        check("GET /api/alerts route exists", "/api/alerts" in routes, str(routes))
    except Exception as exc:
        check("routers.trades import", False, str(exc))


# ---------------------------------------------------------------------------
# Test 6: Price monitor imports
# ---------------------------------------------------------------------------

def test_price_monitor_import() -> None:
    print("\n--- Price monitor ---")
    try:
        from services.price_monitor import run_price_monitor, _check_paper_trades, _check_price_alerts
        check("price_monitor importable", True)
        import inspect
        check("run_price_monitor is coroutine function", inspect.iscoroutinefunction(run_price_monitor))
        check("_check_paper_trades is coroutine function", inspect.iscoroutinefunction(_check_paper_trades))
        check("_check_price_alerts is coroutine function", inspect.iscoroutinefunction(_check_price_alerts))
    except Exception as exc:
        check("price_monitor import", False, str(exc))


# ---------------------------------------------------------------------------
# Test 7: TP/SL threshold logic (unit)
# ---------------------------------------------------------------------------

def test_tp_sl_logic() -> None:
    print("\n--- TP/SL threshold logic ---")

    def should_close(entry: float, current: float, side: str, tp_pct: float | None, sl_pct: float | None) -> str | None:
        pnl_pct = ((current - entry) / entry) * 100
        if side == "SELL":
            pnl_pct = -pnl_pct
        if tp_pct is not None and pnl_pct >= tp_pct:
            return "tp"
        if sl_pct is not None and pnl_pct <= sl_pct:
            return "sl"
        return None

    check("BUY +50%  vs tp=40: hits TP", should_close(1.0, 1.5, "BUY", 40.0, -15.0) == "tp")
    check("BUY +20%  vs tp=40: no hit", should_close(1.0, 1.2, "BUY", 40.0, -15.0) is None)
    check("BUY -20%  vs sl=-15: hits SL", should_close(1.0, 0.8, "BUY", 40.0, -15.0) == "sl")
    check("BUY -10%  vs sl=-15: no hit", should_close(1.0, 0.9, "BUY", 40.0, -15.0) is None)
    check("SELL price up vs sl: hits SL", should_close(1.0, 1.3, "SELL", 40.0, -15.0) == "sl")
    check("SELL price down vs tp: hits TP", should_close(1.0, 0.5, "SELL", 40.0, -15.0) == "tp")


# ---------------------------------------------------------------------------
# Test 8: Direction logic for price alerts (unit)
# ---------------------------------------------------------------------------

def test_alert_direction_logic() -> None:
    print("\n--- Price alert direction logic ---")

    def triggered(current: float, target: float, direction: str) -> bool:
        if direction == "above":
            return current >= target
        if direction == "below":
            return current <= target
        return False

    check("above: current > target = triggered", triggered(0.00005, 0.000045, "above") is True)
    check("above: current < target = not triggered", triggered(0.000040, 0.000045, "above") is False)
    check("below: current < target = triggered", triggered(0.000040, 0.000045, "below") is True)
    check("below: current > target = not triggered", triggered(0.00005, 0.000045, "below") is False)


# ---------------------------------------------------------------------------
# Test 9: Pydantic request models validate correctly
# ---------------------------------------------------------------------------

def test_request_models() -> None:
    print("\n--- Request model validation ---")
    try:
        from routers.trades import OpenTradeRequest, CreateAlertRequest

        t = OpenTradeRequest(
            telegram_user_id=12345,
            token_address="DezXAZ8z7PnrdmdaQ4khTMaGZBV6k2GZMQqQqmPc8Jf",
            symbol="BONK",
            tp_pct=40.0,
            sl_pct=-15.0,
            position_size_usd=100.0,
        )
        check("OpenTradeRequest defaults side=BUY", t.side == "BUY")
        check("OpenTradeRequest tp_pct set", t.tp_pct == 40.0)

        a = CreateAlertRequest(
            telegram_user_id=12345,
            token_address="DezXAZ8z7PnrdmdaQ4khTMaGZBV6k2GZMQqQqmPc8Jf",
            symbol="BONK",
            target_price=0.000045,
            direction="above",
        )
        check("CreateAlertRequest direction=above", a.direction == "above")
        check("CreateAlertRequest target_price", a.target_price == 0.000045)
    except Exception as exc:
        check("Request model validation", False, str(exc))


# ---------------------------------------------------------------------------
# Test 10: main.py wires trades router
# ---------------------------------------------------------------------------

def test_main_wiring() -> None:
    print("\n--- main.py wiring ---")
    try:
        import importlib, types
        # Just read the source to verify imports, not fully load the app
        with open(os.path.join(os.path.dirname(__file__), "main.py")) as f:
            src = f.read()
        check("main.py imports trades_router", "from routers.trades import router as trades_router" in src)
        check("main.py includes trades_router", "app.include_router(trades_router)" in src)
        check("main.py imports run_price_monitor", "from services.price_monitor import run_price_monitor" in src)
        check("main.py starts price monitor task", "asyncio.create_task(run_price_monitor())" in src)
        check("main.py allows PATCH method", '"PATCH"' in src or "'PATCH'" in src)
        check("main.py allows DELETE method", '"DELETE"' in src or "'DELETE'" in src)
    except Exception as exc:
        check("main.py wiring check", False, str(exc))


# ---------------------------------------------------------------------------
# Test 11: Telegram new handlers present
# ---------------------------------------------------------------------------

def test_telegram_handlers() -> None:
    print("\n--- Telegram handlers ---")
    try:
        with open(os.path.join(os.path.dirname(__file__), "services", "telegram.py"), encoding="utf-8") as f:
            src = f.read()
        for handler in ["_handle_track", "_handle_my_trades", "_handle_alert", "_handle_my_alerts", "_handle_cancel_alert"]:
            check(f"telegram.py defines {handler}", f"async def {handler}" in src)
        for cmd in ["/track", "/my-trades", "/alert", "/my-alerts", "/cancel-alert"]:
            check(f"telegram.py dispatches {cmd}", cmd in src)
    except Exception as exc:
        check("Telegram handler check", False, str(exc))


# ---------------------------------------------------------------------------
# Test 12: Live Birdeye price fetch (end-to-end, requires network)
# ---------------------------------------------------------------------------

async def test_live_price_fetch() -> None:
    print("\n--- Live price fetch (Birdeye) ---")
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
        from services.birdeye import get_token_price

        # Use SOL — always liquid on Birdeye
        SOL = "So11111111111111111111111111111111111111112"
        raw = await get_token_price(SOL)
        data = raw.get("data") or {}
        price = float(data.get("value") or 0)
        check("Birdeye returns SOL price > 0", price > 0, f"price={price}")
    except Exception as exc:
        check("Live price fetch", False, str(exc))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print("=" * 60)
    print("  Zentryx — Day 3 Test Suite")
    print("  Paper trades | Price alerts | Price monitor")
    print("=" * 60)

    test_imports()
    test_router_imports()
    test_price_monitor_import()
    test_tp_sl_logic()
    test_alert_direction_logic()
    test_request_models()
    test_main_wiring()
    test_telegram_handlers()
    await test_live_price_fetch()

    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"  Results: {passed}/{total} passed")
    print("=" * 60)
    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
