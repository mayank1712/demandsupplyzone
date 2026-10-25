"""FastAPI server: run with  .venv\\Scripts\\python -m uvicorn app.main:app --reload"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import config, journal
from .data import TIMEFRAMES, read_watchlist
from .backtest import run_symbol
from .scanner import analyze, chart_payload

app = FastAPI(title="Demand Supply Zone Scanner")
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


def _fail(symbol: str, e: Exception):
    raise HTTPException(status_code=502, detail=f"{symbol}: {e}")


@app.get("/")
def index():
    return FileResponse(config.STATIC_DIR / "index.html")


@app.get("/api/settings")
def settings():
    return {
        "provider": config.DATA_PROVIDER,
        "capital": config.CAPITAL,
        "risk_pct": config.RISK_PCT,
        "reward_ratio": config.REWARD_RATIO,
        "watchlist": read_watchlist(),
    }


@app.get("/api/analyze/{symbol}")
def analyze_symbol(symbol: str, ltf: str = Query("2h", pattern="^(2h|1h)$"),
                   capital: float | None = None, risk_pct: float | None = None,
                   reward_ratio: float | None = None, refresh: bool = False):
    try:
        return analyze(symbol.upper(), ltf, capital, risk_pct, reward_ratio, refresh)
    except Exception as e:  # surface provider errors to the UI row
        _fail(symbol, e)


@app.get("/api/chart/{symbol}")
def chart(symbol: str, tf: str = "2h", refresh: bool = False):
    if tf not in TIMEFRAMES:
        raise HTTPException(400, f"tf must be one of {TIMEFRAMES}")
    try:
        return chart_payload(symbol.upper(), tf, refresh)
    except Exception as e:
        _fail(symbol, e)


@app.get("/api/backtest/{symbol}")
def backtest_symbol(symbol: str, ltf: str = Query("2h", pattern="^(2h|1h)$"),
                    reward_ratio: float | None = None, capital: float | None = None,
                    risk_pct: float | None = None, min_grade: str = Query("D", pattern="^[ABCD]$"),
                    sides: str = Query("both", pattern="^(both|long|short)$"),
                    aligned_only: bool = False, cost_pct: float = 0.0, refresh: bool = False):
    try:
        return run_symbol(symbol.upper(), ltf, reward_ratio, capital, risk_pct, min_grade, sides,
                          aligned_only, cost_pct, refresh)
    except Exception as e:
        _fail(symbol, e)


# ---------------- weekly journal ----------------
@app.get("/api/journal")
def journal_report():
    return journal.report()


@app.post("/api/journal/run")
def journal_run(weeks: int | None = Query(None, ge=1, le=26)):
    """Save missing weeks + check old zones in the background; poll /api/journal/status."""
    return {"started": journal.start_background(weeks), "job": journal.JOB}


@app.get("/api/journal/status")
def journal_status():
    return journal.JOB


@app.get("/api/journal/export")
def journal_export():
    return Response(journal.export_csv(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=zone_journal.csv"})
