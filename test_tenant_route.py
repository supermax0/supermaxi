import sys
import os

# Add current directory to path
sys.path.append(os.getcwd())

print("Testing app routes as a logged-in tenant...")

try:
    from app import app
    app.testing = True
    client = app.test_client()
    
    with client.session_transaction() as sess:
        sess['user_id'] = 1  # Assuming admin ID is 1
        sess['tenant_slug'] = 'alnoor'
        sess['role'] = 'admin'
        sess['name'] = 'Test Admin'
    
    print("\n--- Testing /inventory/ as tenant 'alnoor' ---")
    try:
        response = client.get('/inventory/', follow_redirects=True)
        print(f"  Status Code: {response.status_code}")
        if response.status_code == 500:
            print("  [!] ERROR 500 found.")
            # Flask's debug output usually contains the error message in HTML
            html = response.get_data(as_text=True)
            if "Internal Server Error" in html:
                print("  Generic 500 error page received.")
            else:
                # Capture a few lines of the error if it's there
                print("  Error details snippet:")
                import re
                match = re.search(r"<pre class=\"errordata\">(.*?)</pre>", html, re.DOTALL)
                if match:
                    print(match.group(1))
                else:
                    print(html[:2000])
        elif response.status_code == 200:
            print("  Success! (200 OK)")
            
    except Exception as e:
        print(f"  [!!] CRITICAL EXCEPTION: {e}")
        import traceback
        traceback.print_exc()

except Exception as e:
    print(f"Could not initialize app for testing: {e}")
    import traceback
    traceback.print_exc()

print("\nTesting finished.")
