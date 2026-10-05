# Most suites test features behind sign-up, not the email confirmation itself, so they skip it (development only;
# production ignores the switch). tests/test_signup_security.py turns it back on and tests confirmation end to end.
import os
os.environ.setdefault("SKIP_EMAIL_VERIFICATION", "1")
