import sys
import os

# Add current directory to path
sys.path.append(os.getcwd())

print("Testing app routes for 500 errors with details...")

try:
    from app import app
    # Enable debug mode for the test client to propagate exceptions
    app.testing = True
    client = app.test_client()
    
    routes_to_test = [
        '/',
        '/pricing',
        '/login',
        '/superadmin/login',
        '/superadmin/',
        '/inventory/'
    ]
    
    for route in routes_to_test:
        print(f"\n--- Testing route: {route} ---")
        try:
            response = client.get(route, follow_redirects=True)
            print(f"  Status Code: {response.status_code}")
            if response.status_code == 500:
                print(f"  [!] ERROR 500 found on {route}")
                # Print response data to see if Flask's debugger caught it
                print("  Response (first 1000 chars):")
                print(response.get_data(as_text=True)[:1000])
        except Exception as e:
            print(f"  [!!] CRITICAL EXCEPTION on {route}: {e}")
            import traceback
            traceback.print_exc()

except Exception as e:
    print(f"Could not initialize app for testing: {e}")
    import traceback
    traceback.print_exc()

print("\nRoute testing finished.")
