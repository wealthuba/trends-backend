from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv
from supabase import create_client, Client
from pytrends.request import TrendReq
import pandas as pd
import requests
import json

load_dotenv()

app = FastAPI(title="Wealth Trends Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Supabase
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

# Simple API key check
def verify_api_key(api_key: str = Query(...)):
    if api_key != os.getenv("API_KEY"):
        raise HTTPException(status_code=403, detail="Invalid API key")
    return api_key

@app.get("/")
def root():
    return {"status": "live", "message": "Wealth Trends API - Ready"}

@app.get("/api/google-trends")
def google_trends(query: str = Query(...), api_key: str = Depends(verify_api_key)):
    try:
        pytrend = TrendReq()
        pytrend.build_payload(kw_list=[query])
        interest = pytrend.interest_over_time().to_dict()
        related = pytrend.related_queries()
        analysis = {
            "interest_over_time": interest,
            "related_queries": related.get(query, {}),
            "insights": f"Top related: {related.get(query, {}).get('top', [{}])[0].get('query', 'N/A')}"
        }
        # Store in Supabase
        supabase.table("trends").insert({
            "platform": "google",
            "query": query,
            "raw": interest,
            "analysis": analysis
        }).execute()
        return {"platform": "google", "raw": interest, "analysis": analysis}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/reddit-trends")
def reddit_trends(query: str = Query(...), api_key: str = Depends(verify_api_key)):
    try:
        headers = {"User-Agent": "wealth-trends-app/1.0"}
        url = f"https://www.reddit.com/search.json?q={query}&sort=hot&limit=20"
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        posts = data["data"]["children"]
        raw = [p["data"] for p in posts]
        df = pd.DataFrame(raw)
        top = df[["title", "score", "num_comments"]].sort_values("score", ascending=False).head(5).to_dict("records")
        analysis = {"top_posts": top, "insights": f"Top post: {top[0]['title']} ({top[0]['score']} points)"}
        supabase.table("trends").insert({
            "platform": "reddit",
            "query": query,
            "raw": raw,
            "analysis": analysis
        }).execute()
        return {"platform": "reddit", "raw": raw, "analysis": analysis}
    except Exception as e:
        raise HTTPException(500, str(e))

# Add more endpoints later (YouTube, X, etc.)
