"""
test_connection.py
Standalone diagnostic — run this directly to test your Supabase connection
without Streamlit in the mix at all. This isolates whether the problem is
your connection string itself, or something about how/when Streamlit is
loading secrets.toml.

Run with:
    python test_connection.py
"""

import sys

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # fallback for older Python; pip install tomli if needed

import psycopg2

SECRETS_PATH = ".streamlit/secrets.toml"

print(f"Reading connection string from {SECRETS_PATH} ...")
try:
    with open(SECRETS_PATH, "rb") as f:
        secrets = tomllib.load(f)
except FileNotFoundError:
    print(f"ERROR: could not find {SECRETS_PATH}. Run this script from your golf_app folder.")
    sys.exit(1)

conn_str = secrets.get("SUPABASE_DB_URL")
if not conn_str:
    print("ERROR: SUPABASE_DB_URL key not found in secrets.toml.")
    sys.exit(1)

# Print the host/project part only — never print the password.
# Format: postgresql://postgres.PROJECTREF:PASSWORD@HOST:PORT/postgres
safe_display = conn_str.split("@")[-1] if "@" in conn_str else "(could not parse)"
project_ref = "(could not parse)"
if "postgres." in conn_str:
    try:
        project_ref = conn_str.split("postgres.")[1].split(":")[0]
    except IndexError:
        pass

print(f"Project reference found in string: {project_ref}")
print(f"Connecting to host: {safe_display}")
print()

try:
    conn = psycopg2.connect(conn_str)
    print("SUCCESS: Connected to the database.")
except Exception as e:
    print("FAILED to connect. Full error below:")
    print(e)
    sys.exit(1)

cur = conn.cursor()

# Confirm which actual database/project we landed in.
cur.execute("SELECT current_database();")
print(f"Connected to database name: {cur.fetchone()[0]}")

# List existing tables in the public schema.
cur.execute(
    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';"
)
tables = [row[0] for row in cur.fetchall()]
print(f"Tables currently in 'public' schema: {tables if tables else '(none)'}")

# Try creating a harmless test table to confirm write permissions work.
print()
print("Attempting to create a test table...")
cur.execute("CREATE TABLE IF NOT EXISTS connection_test (id SERIAL PRIMARY KEY, note TEXT);")
cur.execute("INSERT INTO connection_test (note) VALUES ('it works');")
conn.commit()
print("SUCCESS: created 'connection_test' table and inserted a row.")
print()
print("Go check Supabase's Table Editor now — you should see a table called")
print("'connection_test' with one row in it. If you see it there, your")
print("connection string is correct and the issue is Streamlit-side")
print("(most likely: the app needs a full restart, not just a browser refresh).")
print("If you do NOT see it, you are looking at a different Supabase project")
print("than the one this connection string points to.")

cur.close()
conn.close()