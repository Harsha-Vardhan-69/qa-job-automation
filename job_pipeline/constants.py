import re

JOB_COLUMNS = [
    "Job Title",
    "Company",
    "Location",
    "Salary",
    "Source",
    "Direct Apply Link",
    "Posted Date",
    "Experience Required",
    "Required Skills",
    "Job Type (Remote / Hybrid / Onsite)",
    "Job ID",
    "Application Deadline",
    "Confidence Score",
    "Match Quality",
]

KEYWORDS = [
    "QA Tester",
    "Quality Assurance Engineer",
    "Software Test Engineer",
    "SDET",
    "QA Analyst",
    "Test Automation Engineer",
    "Selenium Automation Engineer",
]

KEYWORD_REGEX_PATTERNS = [
    re.compile(r"\bqa\b"),
    re.compile(r"quality assurance"),
    re.compile(r"\bsdet\b"),
    re.compile(r"software test"),
    re.compile(r"test automation"),
    re.compile(r"selenium"),
    re.compile(r"engineer in test"),
    re.compile(r"test engineer"),
    re.compile(r"testing engineer"),
    re.compile(r"qa engineer"),
    re.compile(r"qa analyst"),
]

RELAXED_KEYWORD_REGEX_PATTERNS = [
    re.compile(r"\bqa\b"),
    re.compile(r"quality assurance"),
    re.compile(r"\bsdet\b"),
    re.compile(r"software test"),
    re.compile(r"test automation"),
    re.compile(r"selenium"),
    re.compile(r"engineer in test"),
    re.compile(r"test engineer"),
    re.compile(r"testing engineer"),
    re.compile(r"qa engineer"),
    re.compile(r"qa analyst"),
    re.compile(r"\bqe\b"),
    re.compile(r"quality engineer"),
    re.compile(r"automation qa"),
    re.compile(r"test lead"),
    re.compile(r"manual test"),
    re.compile(r"quality specialist"),
    re.compile(r"software quality"),
]

LOCATION_QUERIES = [
    "Hyderabad",
    "Bangalore",
    "Remote India",
    "Global remote",
]

TARGET_SOURCES = {
    "LinkedIn",
    "Naukri",
    "Indeed",
    "Glassdoor",
    "Company career pages",
    "Wellfound",
    "Instahyre",
    "Cutshort",
    "Hirist",
    "YC Work at a Startup",
    "RemoteOK",
}

JSEARCH_MAPPED_SOURCES = [
    "LinkedIn",
    "Naukri",
    "Indeed",
    "Glassdoor",
    "Wellfound",
    "Instahyre",
    "Cutshort",
    "Hirist",
]

DEFAULT_GREENHOUSE_BOARDS = [
    "airbnb",
    "stripe",
    "coinbase",
    "figma",
    "datadog",
    "duolingo",
    "discord",
    "robinhood",
]

DEFAULT_ASHBY_ORGS: list[str] = []
DEFAULT_SMARTRECRUITERS_COMPANIES: list[str] = []
DEFAULT_WORKDAY_API_URLS: list[str] = []

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

REQUEST_TIMEOUT_SECONDS = 25
HTTP_MAX_ATTEMPTS = 3
HTTP_BACKOFF_SECONDS = 1.25
