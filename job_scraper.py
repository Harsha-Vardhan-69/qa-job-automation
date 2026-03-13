import requests
import pandas as pd
from datetime import datetime
from bs4 import BeautifulSoup

KEYWORDS = [
    "QA Tester",
    "Quality Assurance Engineer",
    "Software Test Engineer",
    "SDET",
    "QA Analyst",
    "Test Automation Engineer",
    "Selenium Automation Engineer"
]

LOCATIONS = [
    "Hyderabad",
    "Bangalore",
    "Remote",
    "India",
]

def search_indeed(keyword):
    url = f"https://in.indeed.com/jobs?q={keyword}&fromage=1"
    r = requests.get(url, headers={"User-Agent":"Mozilla/5.0"})
    soup = BeautifulSoup(r.text, "html.parser")

    jobs = []

    for card in soup.select(".job_seen_beacon"):
        title = card.select_one("h2").text.strip()
        company = card.select_one(".companyName").text.strip()

        loc_el = card.select_one(".companyLocation")
        location = loc_el.text.strip() if loc_el else "Not listed"

        link_el = card.select_one("a")
        link = "https://in.indeed.com" + link_el["href"]

        jobs.append({
            "Job Title": title,
            "Company": company,
            "Location": location,
            "Salary": "Not listed",
            "Source": "Indeed",
            "Direct Apply Link": link,
            "Posted Date": datetime.utcnow().isoformat(),
            "Experience Required": "Not listed",
            "Required Skills": "QA / Automation",
            "Job Type": "Not listed",
            "Job ID": link.split("jk=")[-1] if "jk=" in link else "",
            "Application Deadline": "Not listed"
        })

    return jobs


def run():
    all_jobs = []

    for keyword in KEYWORDS:
        try:
            results = search_indeed(keyword)
            all_jobs.extend(results)
        except Exception as e:
            print("Error:", e)

    df = pd.DataFrame(all_jobs)

    df = df.sort_values(by="Posted Date", ascending=False)

    df.to_excel("jobs.xlsx", index=False)

    print("Generated jobs.xlsx")


if __name__ == "__main__":
    run()