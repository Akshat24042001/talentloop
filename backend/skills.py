"""Skill dictionary for free (non-AI) resume parsing and matching.

canonical skill -> spellings and synonyms seen in resumes and JDs. Matching works on canonical names, so "k8s",
"ReactJS" and "MS Excel" line up with "Kubernetes", "React" and "Excel". Anything not in the dictionary still counts
through the keyword relevance score; HR-entered skills are always matched literally as well.
"""
import re

SKILLS: dict[str, list[str]] = {
    # --- programming languages
    "Python": ["python", "python3", "py"], "Java": ["java", "core java", "j2ee", "java ee"], "JavaScript": ["javascript", "js", "es6", "ecmascript"],
    "TypeScript": ["typescript", "ts"], "C": ["c language", "ansi c"], "C++": ["c++", "cpp"], "C#": ["c#", "c sharp", "csharp"],
    "Go": ["golang", "go lang"], "Rust": ["rust"], "Kotlin": ["kotlin"], "Swift": ["swift"], "PHP": ["php"], "Ruby": ["ruby"],
    "Scala": ["scala"], "R": ["r programming", "r language", "rstudio"], "MATLAB": ["matlab"], "Dart": ["dart"], "Perl": ["perl"],
    "Bash": ["bash", "shell scripting", "shell script", "unix shell"], "PowerShell": ["powershell"], "SQL": ["sql", "t-sql", "tsql", "pl/sql", "plsql"],
    # --- web / frameworks
    "React": ["react", "reactjs", "react.js"], "Next.js": ["next.js", "nextjs"], "Angular": ["angular", "angularjs"], "Vue": ["vue", "vuejs", "vue.js"],
    "Svelte": ["svelte"], "Redux": ["redux", "redux toolkit"], "HTML": ["html", "html5"], "CSS": ["css", "css3", "scss", "sass"],
    "Tailwind CSS": ["tailwind", "tailwindcss", "tailwind css"], "Node.js": ["node.js", "nodejs", "node"], "Express": ["express", "expressjs", "express.js"],
    "NestJS": ["nestjs", "nest.js"], "Django": ["django"], "Flask": ["flask"], "FastAPI": ["fastapi"], "Spring Boot": ["spring boot", "springboot"],
    "Spring": ["spring", "spring framework", "spring mvc"], "Hibernate": ["hibernate", "jpa"], ".NET": [".net", "dotnet", "asp.net", ".net core"],
    "Laravel": ["laravel"], "Ruby on Rails": ["rails", "ruby on rails", "ror"], "GraphQL": ["graphql"], "REST APIs": ["rest", "rest api", "rest apis", "restful", "restful apis"],
    "gRPC": ["grpc"], "Microservices": ["microservices", "microservice", "micro services"], "React Native": ["react native"], "Flutter": ["flutter"],
    "Android": ["android"], "iOS": ["ios"], "jQuery": ["jquery"], "Webpack": ["webpack"], "Vite": ["vite"], "Storybook": ["storybook"],
    # --- data / ML
    "Pandas": ["pandas"], "NumPy": ["numpy"], "scikit-learn": ["scikit-learn", "sklearn", "scikit learn"], "TensorFlow": ["tensorflow"],
    "PyTorch": ["pytorch", "torch"], "Machine Learning": ["machine learning", "ml"], "Deep Learning": ["deep learning"], "NLP": ["nlp", "natural language processing"],
    "Computer Vision": ["computer vision", "opencv"], "LLMs": ["llm", "llms", "large language models", "generative ai", "genai", "gen ai"],
    "Statistics": ["statistics", "statistical analysis", "hypothesis testing"], "A/B Testing": ["a/b testing", "ab testing", "experimentation"],
    "Data Analysis": ["data analysis", "data analytics", "analytics"], "Data Visualization": ["data visualization", "data visualisation", "dashboards", "dashboarding"],
    "Power BI": ["power bi", "powerbi", "dax"], "Tableau": ["tableau"], "Looker": ["looker", "looker studio", "google data studio"], "Excel": ["excel", "ms excel", "microsoft excel", "advanced excel", "vlookup", "pivot tables"],
    "Google Sheets": ["google sheets"], "Spark": ["spark", "pyspark", "apache spark"], "Hadoop": ["hadoop", "hive"], "Airflow": ["airflow", "apache airflow"],
    "dbt": ["dbt"], "ETL": ["etl", "elt", "data pipelines", "data pipeline"], "Snowflake": ["snowflake"], "BigQuery": ["bigquery", "big query"], "Redshift": ["redshift"],
    "Databricks": ["databricks"], "Kafka": ["kafka", "apache kafka"], "RabbitMQ": ["rabbitmq"],
    # --- databases
    "PostgreSQL": ["postgresql", "postgres", "psql"], "MySQL": ["mysql"], "MongoDB": ["mongodb", "mongo"], "Redis": ["redis"], "Oracle": ["oracle db", "oracle database"],
    "SQL Server": ["sql server", "mssql", "ms sql"], "Elasticsearch": ["elasticsearch", "elastic search", "elk"], "DynamoDB": ["dynamodb"], "Cassandra": ["cassandra"],
    "Firebase": ["firebase"], "Supabase": ["supabase"],
    # --- cloud / devops
    "AWS": ["aws", "amazon web services", "ec2", "s3", "lambda", "rds"], "Azure": ["azure", "microsoft azure"], "GCP": ["gcp", "google cloud", "google cloud platform"],
    "Docker": ["docker", "containers", "containerization"], "Kubernetes": ["kubernetes", "k8s", "eks", "aks", "gke"], "Terraform": ["terraform"], "Ansible": ["ansible"],
    "Helm": ["helm"], "ArgoCD": ["argocd", "argo cd"], "CI/CD": ["ci/cd", "cicd", "continuous integration", "continuous delivery", "continuous deployment"],
    "Jenkins": ["jenkins"], "GitHub Actions": ["github actions"], "GitLab CI": ["gitlab ci", "gitlab"], "Linux": ["linux", "unix", "ubuntu", "centos"],
    "Prometheus": ["prometheus"], "Grafana": ["grafana"], "Nginx": ["nginx"], "Git": ["git", "github", "bitbucket", "version control"],
    "Site Reliability": ["sre", "site reliability"], "Networking": ["networking", "tcp/ip", "dns", "vpn"], "Security": ["cybersecurity", "infosec", "owasp", "application security", "network security"],
    # --- testing
    "Unit Testing": ["unit testing", "unit tests", "junit", "pytest", "jest", "mocha"], "Selenium": ["selenium"], "Cypress": ["cypress"], "Playwright": ["playwright"],
    "Test Automation": ["test automation", "automation testing", "automated testing"], "Manual Testing": ["manual testing", "qa testing"], "Mockito": ["mockito"],
    "Performance Testing": ["performance testing", "load testing", "jmeter"],
    # --- design / product
    "Figma": ["figma"], "Sketch": ["sketch"], "Adobe XD": ["adobe xd"], "Photoshop": ["photoshop"], "Illustrator": ["illustrator"], "UI Design": ["ui design", "ui"],
    "UX Research": ["ux research", "user research", "usability testing"], "Wireframing": ["wireframing", "wireframes", "prototyping"],
    "Product Management": ["product management", "product manager", "roadmap", "roadmapping"], "Agile": ["agile", "scrum", "kanban", "sprint planning"],
    "Jira": ["jira", "confluence"], "Accessibility": ["accessibility", "wcag", "a11y"],
    # --- sales / marketing / business
    "B2B Sales": ["b2b sales", "b2b", "enterprise sales"], "Inside Sales": ["inside sales", "telesales", "tele sales"], "Lead Generation": ["lead generation", "lead gen", "prospecting", "cold calling", "cold calls"],
    "Account Management": ["account management", "key account management", "kam", "client relationship"], "Negotiation": ["negotiation", "negotiating"],
    "CRM": ["crm"], "Salesforce": ["salesforce", "sfdc"], "HubSpot": ["hubspot"], "Zoho CRM": ["zoho crm", "zoho"], "Business Development": ["business development", "bd", "bde"],
    "Product Demos": ["product demos", "product demo", "demos"], "Pipeline Management": ["pipeline management", "sales pipeline", "forecasting"],
    "SaaS": ["saas", "software as a service"], "Digital Marketing": ["digital marketing", "online marketing"], "SEO": ["seo", "search engine optimization"],
    "SEM": ["sem", "google ads", "ppc", "adwords"], "Social Media Marketing": ["social media marketing", "smm", "social media"], "Content Writing": ["content writing", "copywriting", "content creation"],
    "Email Marketing": ["email marketing", "mailchimp"], "Google Analytics": ["google analytics", "ga4"], "Performance Marketing": ["performance marketing", "meta ads", "facebook ads"],
    "Brand Management": ["brand management", "branding"], "Market Research": ["market research", "competitive analysis"], "Public Speaking": ["public speaking", "presentations", "presentation skills"],
    # --- customer support / operations
    "Customer Service": ["customer service", "customer support", "customer care", "client service"], "Voice Process": ["voice process", "inbound calls", "outbound calls", "call center", "call centre", "bpo"],
    "Chat Support": ["chat support", "chat process", "non-voice"], "Ticketing": ["ticketing", "zendesk", "freshdesk", "service now", "servicenow"],
    "De-escalation": ["de-escalation", "escalation handling", "complaint handling"], "CSAT": ["csat", "nps", "customer satisfaction"],
    "Operations Management": ["operations management", "operations"], "Supply Chain": ["supply chain", "supply chain management", "procurement", "inventory management"],
    "Project Management": ["project management", "pmp", "prince2"], "Six Sigma": ["six sigma", "lean"],
    # --- HR / recruiting
    "Recruitment": ["recruitment", "recruiting", "talent acquisition", "hiring", "end to end recruitment", "end-to-end recruitment"],
    "Sourcing": ["sourcing", "boolean search", "headhunting"], "LinkedIn Recruiter": ["linkedin recruiter"], "Naukri": ["naukri", "naukri rms"],
    "ATS": ["ats", "applicant tracking", "greenhouse", "lever", "zoho recruit", "workday"], "Onboarding": ["onboarding", "induction"],
    "Payroll": ["payroll"], "HR Operations": ["hr operations", "hr ops", "hris"], "Employee Engagement": ["employee engagement", "employee relations"],
    "Performance Management": ["performance management", "appraisals", "okrs", "kpis"], "Campus Hiring": ["campus hiring", "campus recruitment"],
    "Offer Negotiation": ["offer negotiation", "salary negotiation"], "Labour Law": ["labour law", "labor law", "statutory compliance"],
    # --- finance / accounting
    "Accounting": ["accounting", "bookkeeping"], "Tally": ["tally", "tally erp", "tally prime"], "GST": ["gst", "taxation", "income tax", "tds"],
    "Financial Analysis": ["financial analysis", "financial modelling", "financial modeling", "fp&a"], "Audit": ["audit", "auditing", "internal audit"],
    "SAP": ["sap", "sap fico", "sap mm", "sap sd"], "QuickBooks": ["quickbooks"], "Reconciliation": ["reconciliation", "bank reconciliation"],
    # --- IT hardware, infrastructure and support
    "IT Hardware": ["it hardware", "computer hardware", "hardware components", "hardware sales"],
    "Hardware Troubleshooting": ["hardware troubleshooting", "troubleshooting hardware", "laptop repair", "desktop repair", "chip level"],
    "Desktop Support": ["desktop support", "desktop engineer", "it support", "helpdesk", "help desk", "service desk", "l1 support", "l2 support"],
    "System Administration": ["system administration", "system administrator", "sysadmin", "windows administration"],
    "Windows Server": ["windows server", "windows server 2019", "windows server 2022"], "Active Directory": ["active directory", "ad ds", "group policy"],
    "Server Hardware": ["server installation", "rack servers", "blade servers", "dell poweredge", "hpe proliant"],
    "Storage": ["san storage", "nas storage", "storage systems", "netapp", "raid"], "Firewall": ["firewall", "fortinet", "fortigate", "sophos firewall", "palo alto"],
    "CCNA": ["ccna", "ccnp"], "Printers": ["printers", "printer installation", "printer troubleshooting"],
    "Network Troubleshooting": ["lan", "wan", "lan/wan", "switches", "routers", "structured cabling"],
    "Data Centre": ["data center", "data centre", "datacenter"], "Virtualization": ["virtualization", "vmware", "vsphere", "hyper-v", "esxi"],
    "Microsoft 365": ["microsoft 365", "office 365", "o365", "exchange online"],
    # --- sales, pre-sales and channel (IT and B2B)
    "Field Sales": ["field sales", "on-field sales", "outside sales"], "Channel Sales": ["channel sales", "channel partners", "distributor management", "dealer network"],
    "Pre-sales": ["pre-sales", "presales", "pre sales", "solution consulting"], "Cold Calling": ["cold calling", "cold calls", "tele calling", "telecalling"],
    "Tenders": ["tender", "tenders", "gem portal", "rfp", "rfq", "bid management"], "Key Account Management": ["key account management", "key accounts", "kam"],
    # --- administration and office
    "MS Office": ["ms office", "microsoft office", "ms word", "ms powerpoint", "ms-office"],
    "Data Entry": ["data entry", "typing speed"], "Office Administration": ["office administration", "office admin", "front office", "admin executive"],
    "Inventory Management": ["inventory management", "inventory control", "stock management"], "Procurement": ["procurement", "purchase orders", "purchasing"],
    "Vendor Management": ["vendor management", "vendor coordination", "supplier management"], "MIS Reporting": ["mis", "mis reporting", "mis reports"],
    # --- soft skills (matched loosely)
    "Communication": ["communication", "communication skills", "verbal communication", "written communication"], "Leadership": ["leadership", "team lead", "team leadership", "people management"],
    "Mentoring": ["mentoring", "mentored", "coaching"], "Stakeholder Management": ["stakeholder management", "stakeholders"], "Problem Solving": ["problem solving", "problem-solving"],
    "Time Management": ["time management"], "Teamwork": ["teamwork", "collaboration"],
    # --- languages
    "English": ["english"], "Hindi": ["hindi"], "Gujarati": ["gujarati"], "Marathi": ["marathi"], "Tamil": ["tamil"], "Telugu": ["telugu"], "Kannada": ["kannada"],
    "Bengali": ["bengali"], "Malayalam": ["malayalam"], "Arabic": ["arabic"], "French": ["french"], "German": ["german"], "Spanish": ["spanish"],
}

_ALIAS: dict[str, str] = {}
for canon, alts in SKILLS.items():
    for a in [canon.lower(), *alts]:
        _ALIAS.setdefault(a.lower(), canon)
# Short or ambiguous aliases need word boundaries and are only trusted when written as-is (e.g. "go", "r", "c").
_AMBIGUOUS = {"go", "r", "c", "ts", "py", "ml", "bd", "ui", "node", "rest", "spring", "sketch", "lean", "sap", "s3", "lambda", "ats",
              "dns", "vpn", "sre", "kam", "sem", "smm", "elk", "rds", "ec2", "zoho", "gitlab", "operations", "analytics", "hiring", "demos"}
_PATTERN = re.compile(r"(?<![a-z0-9+#.])(" + "|".join(sorted((re.escape(a) for a in _ALIAS if a not in _AMBIGUOUS), key=len, reverse=True)) + r")(?![a-z0-9+#])")


# Families of skills where knowing one is good evidence for another ("semantic" partial credit in matching:
# a Kubernetes job and an OpenShift resume, a Tableau job and a Power BI analyst). Never full credit.
RELATED_GROUPS = [
    ["React", "Angular", "Vue", "Svelte", "Next.js"], ["JavaScript", "TypeScript"], ["Java", "Spring", "Spring Boot", "Hibernate", "Kotlin"],
    ["Django", "Flask", "FastAPI"], ["Pandas", "NumPy", "scikit-learn"],
    ["Machine Learning", "Deep Learning", "PyTorch", "TensorFlow", "NLP", "Computer Vision", "LLMs"], ["AWS", "Azure", "GCP"],
    ["Docker", "Kubernetes", "Helm"], ["CI/CD", "Jenkins", "GitHub Actions", "GitLab CI", "ArgoCD"], ["Terraform", "Ansible"],
    ["PostgreSQL", "MySQL", "SQL Server", "Oracle", "SQL"], ["MongoDB", "Cassandra", "DynamoDB"], ["Snowflake", "BigQuery", "Redshift", "Databricks"],
    ["Power BI", "Tableau", "Looker", "Data Visualization"], ["Excel", "Google Sheets", "MS Office"], ["Selenium", "Playwright", "Cypress", "Test Automation"],
    ["Android", "iOS", "Flutter", "React Native"], ["Kafka", "RabbitMQ"], ["Prometheus", "Grafana"], ["Salesforce", "HubSpot", "Zoho CRM", "CRM"],
    ["B2B Sales", "Inside Sales", "Field Sales", "Business Development", "Lead Generation", "Cold Calling", "Channel Sales"],
    ["Account Management", "Key Account Management", "Pipeline Management"], ["Customer Service", "Chat Support", "Voice Process", "Ticketing"],
    ["Recruitment", "Sourcing", "Campus Hiring", "LinkedIn Recruiter", "Naukri", "ATS"],
    ["HR Operations", "Payroll", "Onboarding", "Employee Engagement", "Performance Management"],
    ["Accounting", "Tally", "QuickBooks", "GST", "Reconciliation"], ["Digital Marketing", "SEO", "SEM", "Social Media Marketing", "Performance Marketing", "Email Marketing"],
    ["Figma", "Sketch", "Adobe XD", "UI Design", "Wireframing"],
    ["IT Hardware", "Hardware Troubleshooting", "Desktop Support", "Printers", "Server Hardware"], ["System Administration", "Windows Server", "Active Directory", "Microsoft 365", "Linux"],
    ["Networking", "Network Troubleshooting", "CCNA", "Firewall"], ["Server Hardware", "Storage", "Data Centre", "Virtualization"],
    ["Office Administration", "Data Entry", "MS Office", "MIS Reporting"], ["Procurement", "Vendor Management", "Inventory Management", "Supply Chain"],
]
_RELATED: dict[str, set[str]] = {}
for _g in RELATED_GROUPS:
    for _k in _g:
        _RELATED.setdefault(_k, set()).update(x for x in _g if x != _k)


def related(skill: str) -> set[str]:
    return _RELATED.get(canonical(skill), set())


def canonical(skill: str) -> str:
    """Canonical name for an HR-entered skill; unknown skills keep their own (trimmed) spelling."""
    s = (skill or "").strip()
    return _ALIAS.get(s.lower(), s)


def extract(text: str) -> set[str]:
    """Canonical skills mentioned in free text."""
    t = " " + (text or "").lower().replace("\n", " ") + " "
    found = {_ALIAS[m.group(1)] for m in _PATTERN.finditer(t)}
    # ambiguous short names only when clearly used as a skill list item: "Go," / "R," / "(Go)" etc.
    for a in ("go", "r", "c"):
        if re.search(rf"(?:^|[,(/|•·])\s*{re.escape(a)}\s*(?=[,)/|•·]|$)", text or "", re.I | re.M):
            found.add(_ALIAS[a])
    if re.search(r"\bnode\b(?!\s*(?:of|in|is))", t) and ("javascript" in t or "express" in t or "npm" in t):
        found.add("Node.js")
    if re.search(r"\brest\b", t) and "api" in t:
        found.add("REST APIs")
    if re.search(r"\bspring\b", t) and "java" in t:
        found.add("Spring")
    return found


def all_names() -> list[str]:
    return sorted(SKILLS)


# --- skills written in a "Skills" section that the dictionary does not know ---------------------------------------------
_HEAD = re.compile(r"^\s*(?:(?:technical|key|core|primary|professional|it|soft|functional|top)\s+)?(?:skills?(?:\s*(?:set|summary|&\s*tools|and\s+tools))?|"
                   r"competenc(?:y|ies)|core competencies|tech(?:nical)? stack|technologies|tools(?:\s*(?:&|and)\s*technologies)?|tools|expertise|areas of expertise|"
                   r"proficienc(?:y|ies)|languages\s*(?:&|and)\s*frameworks|programming languages)\s*[:\-–—]?\s*$", re.I)
_INLINE = re.compile(r"^\s*(?:(?:technical|key|core|primary|professional|it|soft|functional)\s+)?(?:skills?|competenc(?:y|ies)|tech(?:nical)? stack|technologies|tools|expertise)"
                     r"(?:\s*(?:set|summary))?\s*[:\-–—]\s*(.+)$", re.I)
_OTHER_HEAD = re.compile(r"^\s*(?:work\s+|professional\s+)?(?:experience|employment|education|academics?|projects?|certifications?|achievements?|awards?|"
                         r"summary|profile|objective|references?|declaration|personal|interests|hobbies|responsibilities|requirements|qualifications|"
                         r"about|languages?|publications|training|internships?|contact)\b[^,.]{0,30}[:\-–—]?\s*$", re.I)
_JUNK = {"and", "or", "etc", "others", "other", "more", "good", "basic", "advanced", "intermediate", "beginner", "expert", "proficient", "knowledge",
         "experience", "skills", "skill", "tools", "technologies", "familiar", "working", "strong", "excellent", "years", "year", "of", "in", "with", "the"}


def _items(line: str) -> list[str]:
    line = re.sub(r"^[\s•●▪◦*·\-–—>]+", "", line)
    if ":" in line and len(line.split(":", 1)[0].split()) <= 4:        # "Languages: Python, Java" -> the part after the label
        line = line.split(":", 1)[1]
    out = []
    for part in re.split(r"[,;|•●▪◦·/]\s*|\s{3,}|\t", line):
        part = re.sub(r"\s*[\(\[].*?[\)\]]", "", part).strip(" .-–—:")            # drop "(2 years)" / "[Advanced]"
        if re.search(r"\s[-–—]\s", part) and not re.search(r"[-–—]\s*(?:basic|advanced|intermediate|expert|beginner|proficient)$", part, re.I):
            part = re.split(r"\s[-–—]\s", part)[-1].strip()                          # "Vector databases - Pinecone" -> "Pinecone"
        part = re.sub(r"\s*[-–]\s*(?:basic|advanced|intermediate|expert|beginner|proficient)$", "", part, flags=re.I)
        if 2 <= len(part) <= 40 and len(part.split()) <= 4 and not re.fullmatch(r"[\d\W]+", part) and part.lower() not in _JUNK \
                and not re.search(r"\b(?:years?|yrs?)\b|@|https?:", part, re.I):
            out.append(part)
    return out


def extract_listed(text: str, limit: int = 60) -> list[str]:
    """Skills the person wrote in a Skills / Tools / Tech stack section, canonical when known, else as written.
    Order of appearance is kept."""
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    found: list[str] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = _INLINE.match(ln)
        if m:
            found += _items(m.group(1))
        elif _HEAD.match(ln):
            j, blanks = i + 1, 0
            while j < len(lines) and j - i <= 25:
                nxt = lines[j].strip()
                if not nxt:
                    blanks += 1
                    if blanks >= 2:
                        break
                    j += 1
                    continue
                if _OTHER_HEAD.match(nxt) or (_HEAD.match(nxt) and j > i + 0):
                    break
                if len(nxt) > 140:
                    break
                found += _items(nxt)
                j += 1
            i = j - 1
        i += 1
    out: list[str] = []
    seen: set[str] = set()
    for x in found:
        c = canonical(x)
        if c.lower() not in seen:
            seen.add(c.lower())
            out.append(c)
    return out[:limit]


def extract_all(text: str) -> list[str]:
    """Dictionary matches plus everything listed in a skills section, in order of first appearance in the text."""
    base = extract(text)
    low = (text or "").lower()
    ordered = sorted(base, key=lambda s: (min((low.find(a) for a in {s.lower(), *SKILLS.get(s, [])} if low.find(a) >= 0), default=10**9), s))
    seen = {s.lower() for s in ordered}
    return ordered + [x for x in extract_listed(text) if x.lower() not in seen]


# --- non-technical skills shown by what the person did, not only by the words "communication skills" ---------------------------
SOFT_EVIDENCE: dict[str, str] = {
    "Leadership": r"\b(?:led|leading|headed|managed|manage[sd]?)\s+(?:a\s+)?(?:team|group|squad|unit|crew)\b|\bteam\s+(?:lead|leader|of\s+\d+)\b|\breporting\s+to\s+me\b|\bpeople\s+manag",
    "Communication": r"\b(?:presented|presentations?\s+to|communicat\w+\s+with|liais\w+|client[- ]facing|customer[- ]facing|wrote\s+(?:documentation|reports?|proposals?)|"
                     r"documented|explained|briefed|public\s+speaking|spokesperson|anchored|hosted)\b",
    "Public Speaking": r"\b(?:spoke\s+at|speaker\s+at|talk\s+at|presented\s+at|conference\s+talk|webinar|keynote|workshop\s+(?:for|on)|conducted\s+(?:training|workshops?))\b",
    "Teamwork": r"\b(?:cross[- ]functional|collaborat\w+|worked\s+(?:closely\s+)?with\s+(?:the\s+)?(?:\w+\s+)?teams?|team\s+player|coordinat\w+\s+with)\b",
    "Stakeholder Management": r"\b(?:stakeholders?|senior\s+management|leadership\s+team|cxo|c-suite|business\s+owners?|clients?\s+and\s+partners)\b",
    "Mentoring": r"\b(?:mentor\w*|coached|trained\s+(?:\d+\s+)?(?:new\s+)?(?:hires|juniors?|interns|team\s+members|freshers)|onboarded\s+(?:new\s+)?(?:hires|engineers|members))\b",
    "Time Management": r"\b(?:deadlines?|on[- ]time|ahead\s+of\s+schedule|time[- ]bound|tight\s+timelines?|multiple\s+projects|prioriti[sz]\w+|delivered\s+within)\b",
    "Problem Solving": r"\b(?:troubleshoot\w*|root[- ]cause|resolved|debugg\w+|diagnos\w+|fixed\s+(?:critical|production)|problem[- ]solv\w+|solved)\b",
    "Negotiation": r"\b(?:negotiat\w+|closed\s+deals?|vendor\s+contracts?|pricing\s+discussions?)\b",
    "Customer Service": r"\b(?:customer\s+(?:queries|complaints|issues|support)|client\s+(?:queries|issues)|resolved\s+(?:customer|client)|csat|nps)\b",
    "Adaptability": r"\b(?:adapt\w+|quick(?:ly)?\s+learn\w*|picked\s+up|self[- ]taught|wore\s+many\s+hats|fast[- ]paced)\b",
    "Ownership": r"\b(?:owned|end[- ]to[- ]end|single[- ]handedly|took\s+ownership|drove|spearheaded|initiated)\b",
    "Analytical Thinking": r"\b(?:analy[sz]ed|insights?|data[- ]driven|metrics|kpis?|forecast\w*|identified\s+trends?)\b",
    "Attention to Detail": r"\b(?:accuracy|error[- ]free|audit\w*|quality\s+checks?|reconcil\w+|zero\s+defects?|detail[- ]oriented)\b",
    "Creativity": r"\b(?:designed|conceptuali[sz]ed|innovat\w+|brainstorm\w*|creative)\b",
    "Conflict Resolution": r"\b(?:conflict\s+resolution|resolved\s+conflicts?|de-?escalat\w+|mediat\w+|escalations?)\b",
}
_SOFT_RX = {k: re.compile(v, re.I) for k, v in SOFT_EVIDENCE.items()}


def infer_soft(text: str) -> list[str]:
    """Soft skills the text shows through actions ("led a team of 6" -> Leadership), in a fixed order."""
    return [k for k, rx in _SOFT_RX.items() if rx.search(text or "")]


def soft_evidence(text: str) -> dict[str, str]:
    """Each inferred soft skill with the words that show it, for HR to check."""
    out = {}
    for k, rx in _SOFT_RX.items():
        m = rx.search(text or "")
        if m:
            a = text.rfind("\n", 0, m.start()) + 1
            b = text.find("\n", m.end())
            out[k] = " ".join(text[a:b if b >= 0 else len(text)].split()).lstrip("-•*▪● ")[:160]
    return out
