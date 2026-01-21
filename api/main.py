from fastapi import FastAPI, Query, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
import os
from dotenv import load_dotenv
from supabase import create_client, Client
from pytrends.request import TrendReq
import pandas as pd
import requests
import json
from typing import Dict, Any

# Load environment variables
load_dotenv()

app = FastAPI(title="Wealth Trends Backend")

# Vercel serverless needs this explicit handler export
handler = app

# CORS - allow frontend (v0.dev) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change to your v0.dev domain later for security
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Supabase client
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
if not supabase_url or not supabase_key:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_KEY in environment variables")

supabase: Client = create_client(supabase_url, supabase_key)

# Simple API key verification (query param)
security = HTTPBearer()

def verify_api_key(api_key: str = Query(...)):
    expected_key = os.getenv("API_KEY")
    if not expected_key:
        raise RuntimeError("API_KEY not set in environment variables")
    if api_key != expected_key:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return api_key

# Root endpoint - health check
@app.get("/")
def root():
    return {
        "status": "live",
        "message": "Wealth Trends API - Ready",
        "docs": "/docs",
        "test_endpoint": "/api/google-trends?query=ai&api_key=YOUR_KEY"
    }

# Google Trends endpoint (no key needed)
@app.get("/api/google-trends")
def google_trends(query: str = Query(...), api_key: str = Depends(verify_api_key)):
    try:
        pytrend = TrendReq(hl='en-US', tz=360)
        pytrend.build_payload(kw_list=[query], timeframe='today 5-y')
        interest = pytrend.interest_over_time().to_dict()
        related = pytrend.related_queries()
        regions = pytrend.interest_by_region().to_dict()

        raw = {
            "interest_over_time": interest,
            "related_queries": related.get(query, {}),
            "interest_by_region": regions
        }

        # Simple analysis
        df = pd.DataFrame(interest)
        if not df.empty:
            rising = df.pct_change().mean().sort_values(ascending=False).head(5).to_dict()
        else:
            rising = {}

        analysis = {
            "rising_keywords": rising,
            "top_related": related.get(query, {}).get('top', [])[:5],
            "insights": f"Top rising: {list(rising.keys())[0] if rising else 'N/A'}"
        }

        # Store in Supabase
        supabase.table("trends").insert({
            "platform": "google",
            "query": query,
            "raw": raw,
            "analysis": analysis,
            "timestamp": pd.Timestamp.now().isoformat()
        }).execute()

        return {"platform": "google", "raw": raw, "analysis": analysis}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Google Trends error: {str(e)}")

# Reddit trends (public JSON, no API key needed)
@app.get("/api/reddit-trends")
def reddit_trends(query: str = Query(...), api_key: str = Depends(verify_api_key)):
    try:
        headers = {"User-Agent": "wealth-trends-app/1.0 (by /u/wealthuba)"}
        url = f"https://www.reddit.com/search.json?q={query}&sort=hot&limit=20"
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        data = response.json()
        posts = data.get("data", {}).get("children", [])
        raw = [post["data"] for post in posts]

        if not raw:
            return {"platform": "reddit", "raw": [], "analysis": {"insights": "No results found"}}

        df = pd.DataFrame(raw)
        top_posts = df[["title", "score", "num_comments", "created_utc"]].sort_values("score", ascending=False).head(5).to_dict("records")

        # Keyword frequency (simple)
        all_text = " ".join(df["title"].fillna("") + " " + df["selftext"].fillna(""))
        words = pd.Series(all_text.lower().split())
        top_keywords = words.value_counts().head(5).to_dict()

        analysis = {
            "top_posts": top_posts,
            "top_keywords": top_keywords,
            "insights": f"Top post: {top_posts[0]['title']} ({top_posts[0]['score']} points, {top_posts[0]['num_comments']} comments)" if top_posts else "No posts"
        }

        # Store in Supabase
        supabase.table("trends").insert({
            "platform": "reddit",
            "query": query,
            "raw": raw,
            "analysis": analysis,
            "timestamp": pd.Timestamp.now().isoformat()
        }).execute()

        return {"platform": "reddit", "raw": raw, "analysis": analysis}
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Reddit request failed: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reddit processing error: {str(e)}")

# Placeholder for future endpoints (YouTube, X, etc.)
@app.get("/api/health")
def health():
    return {"status": "healthy", "supabase_connected": bool(supabase_url and supabase_key)}
