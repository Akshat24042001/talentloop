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
