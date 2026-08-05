"""
Job Posting Scraper
Checks company job boards (Greenhouse + Lever) for internship / entry-level
postings, logs new ones to data/postings.csv, and sends a notification
(email and/or Slack) when new matches are found.
 
Configure the companies you want to track and your keyword filters below.
"""
 
import csv
import os
import smtplib
from email.mime.text import MIMEText
from pathlib import Path
 
import requests
 
# ---------------------------------------------------------------------------
# CONFIG — edit this section to customize your search
# 
# Version 2.2.0 = configurable job-match scoring
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
    "tenant": "gevernova",
    "wd_server": "wd5",
    "site": "Vernova_ExternalSite",
    "enabled": True,
    },
]
 
# A role-level keyword is required before a job can be considered. Scores then
# distinguish a relevant engineering opportunity from a generic internship.
ROLE_KEYWORDS = {
    "internship": 10,
    "intern": 10,
    "entry level": 10,
    "entry-level": 10,
    "new grad": 10,
    "graduate": 5,
    "junior": 5,
}

# Adjust these weights as your search evolves. Phrases are scored only once,
# even when a title contains the same phrase more than once.
INTEREST_KEYWORDS = {
    "electrical": 20,
    "power systems": 25,
    "power electronics": 25,
    "protection": 25,
    "relay": 25,
    "hardware": 15,
    "embedded": 15,
    "semiconductor": 15,
    "data center": 15,
    "utility": 15,
    "utilities": 15,
    "defense": 15,
}

# A generic "Intern" scores 10 and is ignored. "Electrical Intern" scores
# 30 and is included. Tune this threshold without changing filtering logic.
MIN_MATCH_SCORE = 25
 
# Keywords that disqualify a match even if a title keyword matched
# (helps filter out "Senior Engineer - mentors interns" type false positives)
EXCLUDE_KEYWORDS = [
    "senior",
    "staff",
    "principal",
    "director",
    "lead",
    #"hr",      -- risky, some words may contain the "hr" string (rare). only include for hard blacklist
    "human resources",
    "recruiting",
    "recruiter",
    "talent acquisition",
    "marketing",
    "communications",
    "sales",
    "finance",
    "accounting",
    "legal",
    "supply chain",
    "human resource",
]
 
DATA_FILE = Path(__file__).parent / "data" / "postings.csv"
POSTING_FIELDS = [
    "job_id",
    "company",
    "source",
    "title",
    "location",
    "url",
    "match_score",
    "date_found",
]
 
# ---------------------------------------------------------------------------
# SCRAPING LOGIC - Greenhouse + Lever Jobs
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

# ---------------------------------------------------------------------------
# SCRAPING LOGIC - Workday Jobs
# ---------------------------------------------------------------------------

def fetch_workday_jobs(company):
    """Fetch all jobs for a company from Workday's CxS API."""
    tenant = company["tenant"]
    wd_server = company["wd_server"]
    site = company["site"]
    base_url = f"https://{tenant}.{wd_server}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    results = []
    offset = 0
    limit = 20

    while True:
        payload = {"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": ""}
        try:
            resp = requests.post(f"{base_url}/jobs", json=payload, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            print(f"  [!] Failed to fetch Workday jobs for {company['name']}: {e}")
            break

        postings = data.get("jobPostings", [])
        if not postings:
            break

        for job in postings:
            results.append(
                {
                    "company": company["name"],
                    "source": "workday",
                    "title": job.get("title", ""),
                    "location": job.get("locationsText", ""),
                    "url": f"https://{tenant}.{wd_server}.myworkdayjobs.com/en-US/{site}{job.get('externalPath', '')}",
                    "job_id": job.get("bulletFields", [job.get("externalPath", "")])[0]
                    if job.get("bulletFields")
                    else job.get("externalPath", ""),
                }
            )

        offset += limit
        if offset >= data.get("total", 0):
            break

    return results 
 
def score_job(title):
    """Return a job's score, or ``None`` when it is not eligible to alert."""
    title_lower = title.casefold()

    if any(keyword in title_lower for keyword in EXCLUDE_KEYWORDS):
        return None

    role_score = max(
        (score for keyword, score in ROLE_KEYWORDS.items() if keyword in title_lower),
        default=0,
    )
    if not role_score:
        return None

    interest_score = sum(
        score for keyword, score in INTEREST_KEYWORDS.items() if keyword in title_lower
    )
    return role_score + interest_score


def matches_filters(title):
    """Maintain the filtering interface while enforcing the score threshold."""
    score = score_job(title)
    return score is not None and score >= MIN_MATCH_SCORE


def posting_key(posting):
    """Return an ID that remains unique across companies and ATS platforms."""
    return f"{posting['source']}:{posting['company']}:{posting['job_id']}"
 
 
def load_existing_postings():
    """Load previously seen postings using a company-and-source-aware key."""
    if not DATA_FILE.exists():
        return set()
    with open(DATA_FILE, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {
            f"{row.get('source', '')}:{row.get('company', '')}:{row['job_id']}"
            for row in reader
        }


def ensure_posting_schema():
    """Add newly introduced CSV columns without discarding posting history."""
    if not DATA_FILE.exists():
        return

    with open(DATA_FILE, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames == POSTING_FIELDS:
            return
        rows = list(reader)

    with open(DATA_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=POSTING_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in POSTING_FIELDS})
 
 
def append_postings(postings):
    """Append new postings to the CSV log, creating it with headers if needed."""
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    ensure_posting_schema()
    file_exists = DATA_FILE.exists()
    with open(DATA_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=POSTING_FIELDS)
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

    from datetime import datetime, timezone
    run_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if new_postings:
        lines = [f"{p['company']} — {p['title']} ({p['location']})\n{p['url']}" for p in new_postings]
        body = (
            f"Run completed: {run_time}\n\n"
            f"{len(new_postings)} new posting(s) found:\n\n" + "\n\n".join(lines)
        )
        subject = f"[Job Scraper] {len(new_postings)} new posting(s) — {run_time}"
    else:
        body = f"Run completed: {run_time}\n\nNo new postings found this run."
        subject = f"[Job Scraper] No new postings — {run_time}"
 
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

        elif company["platform"] == "workday":
            all_jobs.extend(fetch_workday_jobs(company))

        else:
            print(f"  [!] Unsupported platform '{company['platform']}' for {company['name']}, skipping.")

    matched = []
    for job in all_jobs:
        score = score_job(job["title"])
        if score is not None and score >= MIN_MATCH_SCORE:
            job["match_score"] = score
            matched.append(job)
    print(f"Found {len(matched)} postings matching keyword filters.")
 
    existing_ids = load_existing_postings()
    new_postings = [j for j in matched if posting_key(j) not in existing_ids]
 
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
        
        send_email_notification([])
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
