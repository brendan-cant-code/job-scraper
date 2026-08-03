"""
Job Posting Scraper
Checks company job boards (Greenhouse + Lever) for internship / entry-level
postings, logs new ones to data/postings.csv, and sends a notification
(email and/or Slack) when new matches are found.
 
Configure the companies you want to track and your keyword filters below.
"""
 
import csv
import json
import os
import smtplib
from email.mime.text import MIMEText
from pathlib import Path
 
import requests
 
# ---------------------------------------------------------------------------
# CONFIG — edit this section to customize your search
# 
# Version 2.0 = slight code revamp to include new format for companies
# ---------------------------------------------------------------------------

# Greenhouse companies: find the slug in the URL, e.g.
# https://boards.greenhouse.io/airbnb -> "airbnb"

# GREENHOUSE_COMPANIES = [
#    "airbnb",
#    "stripe",
#    "doordash",
#    "doordashusa",
#    "robinhood",
# ]
 
# LEVER_COMPANIES = [
#    "netflix",
# ]
#
 
 
COMPANIES = [       # think of changing name: companies to tracked_companies
 
    {
        "name": "Airbnb",
        "platform": "greenhouse",
        "slug": "airbnb",
        "enabled": True,
    },
    {
        "name": "Stripe",
        "platform": "greenhouse",
        "slug": "stripe",
        "enabled": True,
    },
    {
        "name": "DoorDash",
        "platform": "greenhouse",
        "slug": "doordashusa",
        "enabled": True,
    },
    {
        "name": "Robinhood",
        "platform": "greenhouse",
        "slug": "robinhood",
        "enabled": True,
    },
    {
        "name": "Netflix",
        "platform": "lever",
        "slug": "netflix",
        "enabled": True,
    },
    {
        "name": "GE Vernova",
        "platform": "workday",
        "slug": "gevernova",
        "enabled": False,       # set to false for now
    } #,
]
 
# Keywords to match in job titles (case-insensitive). A posting matches if
# ANY of these appear in the title.
TITLE_KEYWORDS = [
    "intern",
    "internship",
    "entry level",
    "entry-level",
    "new grad",
    "graduate",
    "junior",
]
 
# Keywords that disqualify a match even if a title keyword matched
# (helps filter out "Senior Engineer - mentors interns" type false positives)
EXCLUDE_KEYWORDS = [
    "senior",
    "staff",
    "principal",
    "director",
    "lead",
]
 
DATA_FILE = Path(__file__).parent / "data" / "postings.csv"
 
# ---------------------------------------------------------------------------
# SCRAPING LOGIC
# ---------------------------------------------------------------------------
 
 
def fetch_greenhouse_jobs(company):     # replaced company_slug with company
    """Fetch all jobs for a company from Greenhouse's public API."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{company['slug']}/jobs"     # replaced {company_slug} to {company['slug']}
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        jobs = resp.json().get("jobs", [])
    except requests.RequestException as e:
        print(f"  [!] Failed to fetch Greenhouse jobs for {company['slug']}: {e}")
        return []
 
    results = []
    for job in jobs:
        results.append(
            {
                "company": company["name"], # changed company_slug to company["name"]
                "source": "greenhouse",
                "title": job.get("title", ""),
                "location": (job.get("location") or {}).get("name", ""),
                "url": job.get("absolute_url", ""),
                "job_id": str(job.get("id", "")),
            }
        )
    return results
 
 
def fetch_lever_jobs(company):     # repeated changes done to greenhouse companies
    """Fetch all jobs for a company from Lever's public API."""
    url = f"https://api.lever.co/v0/postings/{company['slug']}?mode=json"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        jobs = resp.json()
    except requests.RequestException as e:
        print(f"  [!] Failed to fetch Lever jobs for {company['slug']}: {e}")
        return []
 
    results = []
    for job in jobs:
        results.append(
            {
                "company": company["name"],
                "source": "lever",
                "title": job.get("text", ""),
                "location": (job.get("categories") or {}).get("location", ""),
                "url": job.get("hostedUrl", ""),
                "job_id": str(job.get("id", "")),
            }
        )
    return results
 
 
def matches_filters(title):
    title_lower = title.lower()
    has_keyword = any(k in title_lower for k in TITLE_KEYWORDS)
    has_exclusion = any(k in title_lower for k in EXCLUDE_KEYWORDS)
    return has_keyword and not has_exclusion
 
 
def load_existing_postings():
    """Load previously seen job IDs from the CSV log."""
    if not DATA_FILE.exists():
        return set()
    with open(DATA_FILE, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {row["job_id"] for row in reader}
 
 
def append_postings(postings):
    """Append new postings to the CSV log, creating it with headers if needed."""
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    file_exists = DATA_FILE.exists()
    with open(DATA_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["job_id", "company", "source", "title", "location", "url", "date_found"]
        )
        if not file_exists:
            writer.writeheader()
        for p in postings:
            writer.writerow(p)
 
 
# ---------------------------------------------------------------------------
# NOTIFICATIONS
# ---------------------------------------------------------------------------
 
 
def send_slack_notification(new_postings):
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return
    lines = [f"*{p['company']}* — {p['title']} ({p['location']})\n{p['url']}" for p in new_postings]
    text = f":briefcase: *{len(new_postings)} new posting(s) found:*\n\n" + "\n\n".join(lines)
    try:
        requests.post(webhook_url, json={"text": text}, timeout=10)
    except requests.RequestException as e:
        print(f"  [!] Slack notification failed: {e}")
 
 
def send_email_notification(new_postings):
    smtp_gmail_user = os.environ.get("SMTP_GMAIL_USER")
    smtp_gmail_pass = os.environ.get("SMTP_GMAIL_PASS")
    notify_to = os.environ.get("NOTIFY_GMAIL_EMAIL")
    
    if not (smtp_gmail_user and smtp_gmail_pass and notify_to):
        print("  [!] Missing email credentials in environment variables. Skipping email.")
        return
 
    lines = [f"{p['company']} — {p['title']} ({p['location']})\n{p['url']}" for p in new_postings]
    body = f"{len(new_postings)} new posting(s) found:\n\n" + "\n\n".join(lines)
 
    msg = MIMEText(body)
    msg["Subject"] = f"[Job Scraper] {len(new_postings)} new posting(s)"
    msg["From"] = smtp_gmail_user
    msg["To"] = notify_to
 
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(smtp_gmail_user, smtp_gmail_pass)
            server.sendmail(smtp_gmail_user, [notify_to], msg.as_string())
        print("  [+] Email notification sent successfully!")
    except Exception as e:
        print(f"  [!] Email notification failed: {e}")
 
 
# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
 
 
def main():
    from datetime import datetime, timezone
 
    print("Fetching postings...")
    all_jobs = []
# replaced with so below
 
#    for company in GREENHOUSE_COMPANIES:
#        print(f" - Greenhouse: {company}")
#        all_jobs.extend(fetch_greenhouse_jobs(company))
#    for company in LEVER_COMPANIES:
#        print(f" - Lever: {company}")
#        all_jobs.extend(fetch_lever_jobs(company))
 
    for company in COMPANIES:
        
        if not company["enabled"]:
            continue
        
        print(f"Searching {company['name']}...")
 
        if company["platform"] == "greenhouse":
            all_jobs.extend(fetch_greenhouse_jobs(company))
 
        elif company["platform"] == "lever":
            all_jobs.extend(fetch_lever_jobs(company))

        else:
            print(f"  [!] Unsupported platform '{company['platform']}' for {company['name']}, skipping.")

    matched = [j for j in all_jobs if matches_filters(j["title"])]
    print(f"Found {len(matched)} postings matching keyword filters.")
 
    existing_ids = load_existing_postings()
    new_postings = [j for j in matched if j["job_id"] not in existing_ids]
 
    if not new_postings:
        print("No new postings since last run.")
 
        # test email template
        # print("Sending test email to verify credentials...")
        # test_posting = [{
            # "company": "Test Company",
            # "title": "Software Engineer Intern (TEST)",
            # "location": "Remote",
            # "url": "https://example.com"
        # }]
        # send_email_notification(test_posting)
        
        return
 
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for p in new_postings:
        p["date_found"] = today
 
    append_postings(new_postings)
    print(f"Logged {len(new_postings)} new posting(s) to {DATA_FILE}")
 
    send_slack_notification(new_postings)
    send_email_notification(new_postings)
 
 
if __name__ == "__main__":
    main()