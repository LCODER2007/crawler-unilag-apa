"""
Faculty Directory Spider — crawls UNILAG staff pages and extracts
name + faculty + department for each staff member.
Saves to data/unilag_staff_detailed.json for accurate classification.
"""

import os
import json
import scrapy
from scrapy.http import Request

STAFF_CACHE = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "data", "unilag_staff.json"
)
DETAILED_CACHE = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "data", "unilag_staff_detailed.json"
)

# Known UNILAG faculty URLs — direct seeds so we don't rely on the homepage nav
FACULTY_SEEDS = [
    ("College of Medicine", "https://medicine.unilag.edu.ng/academic-staff/"),
    ("Faculty of Engineering", "https://engineering.unilag.edu.ng/staff/"),
    ("Faculty of Science", "https://science.unilag.edu.ng/staff/"),
    ("Faculty of Arts", "https://arts.unilag.edu.ng/staff/"),
    ("Faculty of Social Sciences", "https://socialsciences.unilag.edu.ng/staff/"),
    ("Faculty of Law", "https://law.unilag.edu.ng/staff/"),
    ("Faculty of Education", "https://education.unilag.edu.ng/staff/"),
    (
        "Faculty of Environmental Sciences",
        "https://environmentalsciences.unilag.edu.ng/staff/",
    ),
    ("Faculty of Management Sciences", "https://management.unilag.edu.ng/staff/"),
    ("Faculty of Pharmacy", "https://pharmacy.unilag.edu.ng/staff/"),
    ("Faculty of Dental Sciences", "https://dentistry.unilag.edu.ng/staff/"),
    ("Faculty of Basic Medical Sciences", "https://basicmedical.unilag.edu.ng/staff/"),
]

NOISE = {
    "click",
    "view",
    "department",
    "faculty",
    "university",
    "college",
    "profile",
    "contact",
    "email",
    "phone",
    "office",
    "research",
    "publications",
    "more",
    "read",
    "about",
    "staff",
    "list",
    "home",
    "menu",
    "search",
    "login",
    "logout",
}


class FacultyDirectorySpider(scrapy.Spider):
    name = "unilag_faculty_directory"
    custom_settings = {
        "DOWNLOAD_DELAY": 1.5,
        "ROBOTSTXT_OBEY": False,
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 2,
        "LOG_LEVEL": "WARNING",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.staff_records = []  # list of {name, faculty, department}
        self.staff_names = []  # flat list for backwards compat

    def start_requests(self):
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; URAAS/1.0; mailto:library@unilag.edu.ng)"
        }
        for faculty_name, url in FACULTY_SEEDS:
            yield Request(
                url,
                headers=headers,
                callback=self.parse_staff_page,
                errback=self.handle_error,
                meta={"faculty": faculty_name, "department": None},
            )

    def handle_error(self, failure):
        self.logger.warning(f"Failed: {failure.request.url}")

    def parse_staff_page(self, response):
        faculty = response.meta.get("faculty", "Unknown")
        department = response.meta.get("department")

        # Try to detect department from page heading
        heading = (
            response.css("h1::text, h2::text, .page-title::text").get(default="") or ""
        ).strip()
        if heading and len(heading) < 80 and "staff" not in heading.lower():
            department = heading

        found = 0

        # Strategy 1: Elementor headings
        for name in response.css(
            "h2.elementor-cta__title::text, h3.elementor-heading-title::text, h4.elementor-heading-title::text"
        ).getall():
            if self._add(name, faculty, department):
                found += 1

        # Strategy 2: Bold text in content blocks
        for name in response.css(
            "div.kc_text_block strong::text, div.entry-content strong::text, .wp-block-column strong::text"
        ).getall():
            if self._add(name, faculty, department):
                found += 1

        # Strategy 3: Table first column
        for name in response.css(
            "table td:first-child::text, table td:nth-child(2)::text"
        ).getall():
            if self._add(name, faculty, department):
                found += 1

        # Strategy 4: List items
        for name in response.css(
            "li strong::text, .staff-name::text, .member-name::text, .team-member-name::text"
        ).getall():
            if self._add(name, faculty, department):
                found += 1

        # Strategy 5: Generic headings (h3/h4/h5)
        for name in response.css("h3::text, h4::text, h5::text").getall():
            if self._add(name, faculty, department):
                found += 1

        self.logger.info(f"[{faculty}] {found} names from {response.url}")

        # Follow department sub-pages
        for link in response.css("a"):
            text = (link.css("::text").get(default="")).strip()
            href = link.attrib.get("href", "")
            if any(
                kw in text.lower() for kw in ["department", "dept", "staff", "academic"]
            ):
                yield response.follow(
                    href,
                    callback=self.parse_staff_page,
                    errback=self.handle_error,
                    meta={"faculty": faculty, "department": text},
                )

    def _add(self, name: str, faculty: str, department) -> bool:
        name = name.strip()
        if not name or len(name) < 4:
            return False
        words = name.split()
        if not (2 <= len(words) <= 6):
            return False
        if not any(c.isalpha() for c in name):
            return False
        if any(kw in name.lower() for kw in NOISE):
            return False
        # Avoid duplicates
        if any(r["name"] == name for r in self.staff_records):
            return False
        self.staff_records.append(
            {"name": name, "faculty": faculty, "department": department or faculty}
        )
        self.staff_names.append(name)
        return True

    def closed(self, reason):
        if not self.staff_records:
            self.logger.warning(
                "No staff found — UNILAG site structure may have changed."
            )
            return

        os.makedirs(os.path.dirname(STAFF_CACHE), exist_ok=True)

        # Save flat name list (backwards compat)
        unique_names = sorted(set(self.staff_names))
        with open(STAFF_CACHE, "w", encoding="utf-8") as f:
            json.dump(unique_names, f, indent=2, ensure_ascii=False)

        # Save detailed records
        with open(DETAILED_CACHE, "w", encoding="utf-8") as f:
            json.dump(self.staff_records, f, indent=2, ensure_ascii=False)

        self.logger.warning(
            f"Saved {len(unique_names)} staff names + {len(self.staff_records)} detailed records"
        )
