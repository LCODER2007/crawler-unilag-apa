import secrets
from werkzeug.security import generate_password_hash

secret_key = secrets.token_hex(32)
admin_pw = "uraas_admin_2026"
viewer_pw = "uraas_viewer_2026"

print("=== NEW URAAS CREDENTIALS ===")
print("DASHBOARD_SECRET_KEY=" + secret_key)
print("ADMIN_USERNAME=admin")
print("ADMIN_PASSWORD_HASH=" + generate_password_hash(admin_pw))
print("VIEWER_USERNAME=viewer")
print("VIEWER_PASSWORD_HASH=" + generate_password_hash(viewer_pw))
print()
print(f"Admin plain password: {admin_pw}")
print(f"Viewer plain password: {viewer_pw}")
print()
print("Store these safely in the server environment!")
